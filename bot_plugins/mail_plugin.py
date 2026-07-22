# -*- coding: utf-8 -*-
"""
网易邮箱大师自动签到 - QQ机器人插件
==================================
QL-Bot 业务项目插件，提供 QQ 交互逻辑。

命令列表:
  大师菜单          - 帮助菜单
  大师登录          - 交互式设置 mastersess/masterfp/tokens/emails
  大师配置          - 直接设置 MASTER_COOKIE 字符串
  大师状态          - 查看配置状态
  大师查询          - 查看最近一次执行结果
  大师执行          - 执行全部自动化任务
  大师签到          - 仅执行签到
  大师开启/关闭 XX  - 开关功能
  签到              - 快捷命令
"""

import os
import re
import subprocess
import sys
import threading

from bot.plugins.base import Plugin
from bot.utils import Log
from bot.ql_api import ql
from bot.session import sessions

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _import_mail():
    sys.path.insert(0, _PROJECT_DIR)
    import mail_auto
    return mail_auto


MAIL_ENV_VARS = [
    ("MASTER_COOKIE", "大师号认证（格式: mastersess:::masterfp:::M_INFO:::token1&token2:::email1&email2）"),
    ("MASTER_MASTERSESS", "大师号会话令牌"),
    ("MASTER_MASTERFP", "设备指纹"),
    ("MASTER_M_INFO", "设备ID"),
    ("MASTER_TOKENS", "邮箱token列表"),
    ("MASTER_EMAILS", "邮箱列表"),
    ("MASTER_ENABLE_SIGNIN", "启用签到 (true/false)"),
    ("MASTER_ENABLE_TASKS", "启用任务领取 (true/false)"),
    ("MASTER_ENABLE_AD", "启用广告任务 (true/false)"),
]

MENU_TEXT = """📧 网易邮箱大师自动签到

🎯 快捷: 签到 | 积分

🔑 大师登录  - 交互式设置认证信息
📊 大师状态  - 查看配置和开关
📋 大师查询  - 查看最近一次结果
🚀 大师执行  - 执行全部任务
✅ 大师开启 XX
❌ 大师关闭 XX

可开关: 签到 | 任务 | 广告

获取方式: 抓包 MailMaster App 请求 dashi.163.com"""


class MailMasterPlugin(Plugin):
    name = "MailMaster"
    commands = ["大师", "邮箱", "签到", "积分"]

    def __init__(self):
        super().__init__()
        self.project_dir = _PROJECT_DIR
        self._env_path = None

    def match(self, text):
        return any(text.strip().startswith(cmd) for cmd in self.commands)

    def handle(self, text, sender_id, group_id=None):
        text = text.strip()

        if text == "签到":
            return self._cmd_signin(sender_id, group_id)
        if text in ("积分",):
            return self._cmd_status(sender_id, group_id)
        if text == "邮箱":
            return MENU_TEXT
        if not text.startswith("大师"):
            return MENU_TEXT

        rest = text[2:].strip()
        if not rest:
            return MENU_TEXT

        parts = rest.split(maxsplit=1)
        sub = parts[0]
        arg = parts[1] if len(parts) > 1 else ""

        if sub in ("菜单", "帮助", "help"):
            return MENU_TEXT
        if sub == "登录":
            return self._cmd_login(sender_id, group_id)
        if sub == "配置":
            return self._cmd_config(sender_id, group_id, arg)
        if sub == "状态":
            return self._cmd_status(sender_id, group_id)
        if sub == "查询":
            return self._cmd_query(sender_id, group_id)
        if sub == "执行":
            return self._cmd_run(sender_id, group_id)
        if sub == "签到":
            return self._cmd_signin(sender_id, group_id)
        if sub == "开启":
            return self._cmd_toggle(arg, True, sender_id, group_id)
        if sub == "关闭":
            return self._cmd_toggle(arg, False, sender_id, group_id)

        return MENU_TEXT

    # ---------- 环境文件 ----------
    def _get_env_path(self):
        if self._env_path:
            return self._env_path
        self._env_path = os.path.join(self.project_dir, ".env")
        return self._env_path

    def _read_env(self) -> dict:
        env = {}
        p = self._get_env_path()
        if not os.path.exists(p):
            self._init_env(p)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        env[k.strip()] = v.strip().strip("\"'")
        return env

    def _init_env(self, path: str):
        example = os.path.join(os.path.dirname(path), ".env.example")
        if os.path.exists(example):
            import shutil
            shutil.copy(example, path)
        else:
            self._write_env({})

    def _write_env(self, env: dict):
        p = self._get_env_path()
        lines = ["# 网易邮箱大师自动签到", ""]
        for key, desc in MAIL_ENV_VARS:
            val = env.get(key, "")
            lines.append(f"# {desc}")
            lines.append(f"{key}={val}")
            lines.append("")
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _parse_account(self, env: dict) -> tuple:
        raw = env.get("MASTER_COOKIE", "")
        if raw and ":::" in raw:
            parts = raw.split(":::")
            if len(parts) >= 5:
                return parts[0], parts[1], parts[3], parts[4]
        ms = env.get("MASTER_MASTERSESS", "")
        mf = env.get("MASTER_MASTERFP", "")
        tk = env.get("MASTER_TOKENS", "")
        em = env.get("MASTER_EMAILS", "")
        if ms and mf and tk and em:
            return ms, mf, tk, em
        return ("", "", "", "")

    # ---------- 命令实现 ----------

    def _cmd_login(self, sender_id, group_id=None):
        sessions.set(sender_id, group_id, "mail_login", {})
        return "🔑 请输入 mastersess 值：\n获取方式: 抓包 MailMaster App → dashi.163.com → 请求头 mastersess"

    def _login_session(self, sender_id, group_id, text, session):
        text = text.strip()
        data = session.get("data", {})

        if "mastersess" not in data:
            data["mastersess"] = text
            session["data"] = data
            return "📱 请输入 masterfp 值："

        if "masterfp" not in data:
            data["masterfp"] = text
            session["data"] = data
            return "📱 请输入 tokens 值（多个用逗号分隔）："

        if "tokens" not in data:
            data["tokens"] = text
            session["data"] = data
            return "📱 请输入 emails 值（多个用逗号分隔）："

        if "emails" not in data:
            data["emails"] = text
            ms = data["mastersess"]
            mf = data["masterfp"]
            tokens = "&".join(t.strip() for t in text.split(",") if t.strip())
            emails = "&".join(e.strip() for e in text.split(",") if e.strip())
            cookie = f"{ms}:::{mf}:::::{tokens}:::{emails}"

            env = self._read_env()
            env["MASTER_COOKIE"] = cookie
            self._write_env(env)
            sessions.clear(sender_id, group_id)

            submit = self._auto_submit(env)
            return (
                f"✅ 配置已保存！\n"
                f"📧 mastersess: {ms[:15]}...\n"
                f"📱 masterfp: {mf[:15]}...\n"
                f"🔗 tokens: {len(tokens.split('&'))} 个\n"
                f"📬 emails: {emails}\n\n"
                f"{submit}"
            )

        return "⚠️ 请先输入 mastersess"

    def _cmd_config(self, sender_id, group_id, arg):
        if not arg:
            return "用法: 大师配置 <MASTER_COOKIE>\n格式: mastersess:::masterfp:::M_INFO:::token1&token2:::email1@163.com"
        cookie = arg.strip()
        env = self._read_env()
        env["MASTER_COOKIE"] = cookie
        self._write_env(env)
        submit = self._auto_submit(env)
        return f"✅ 配置已保存！\n{submit}"

    def _auto_submit(self, env: dict) -> str:
        ql_url = env.get("QL_URL", "")
        ql_cid = env.get("QL_CLIENT_ID", "")
        ql_cs = env.get("QL_CLIENT_SECRET", "")

        if not ql_url or not ql_cid or not ql_cs:
            return "⚠️ 青龙未配置，请手动设置 QL_URL / QL_CLIENT_ID / QL_CLIENT_SECRET"

        try:
            ql.base_url = ql_url.rstrip("/")
            ql.client_id = ql_cid
            ql.client_secret = ql_cs
            ql.token = None

            ok = 0
            fail = 0
            for key, desc in MAIL_ENV_VARS:
                val = env.get(key, "")
                if not val:
                    continue
                try:
                    existing = ql.list_envs(search_value=key)
                    found = [e for e in existing if e.get("name") == key]
                    if found:
                        eid = found[0].get("id") or found[0].get("_id")
                        ql.update_env(eid, key, val, f"EMAIL: {desc}")
                    else:
                        ql.create_env(key, val, f"EMAIL: {desc}")
                    ok += 1
                except Exception:
                    fail += 1

            result = f"📤 青龙提交: ✅{ok}"
            if fail:
                result += f" ❌{fail}"
            result += (
                "\n定时任务:\n"
                "  任务名: QL-EMAIL\n"
                "  命令: task mail_auto.py\n"
                "  定时: 30 8 * * *"
            )
            return result
        except Exception as e:
            return f"⚠️ 青龙提交失败: {e}"

    def _cmd_status(self, sender_id, group_id=None):
        env = self._read_env()
        ms, mf, tk, em = self._parse_account(env)

        cookie = env.get("MASTER_COOKIE", "")
        cookie_s = "已配置" if cookie else "未配置"
        ms_s = f"{ms[:15]}..." if ms else "未设置"
        emails = em.split("&") if em else []
        em_s = f"{len(emails)} 个" if emails else "未设置"
        tokens = tk.split("&") if tk else []
        tk_s = f"{len(tokens)} 个" if tokens else "未设置"

        def on(key):
            return "✅" if env.get(key, "true").lower() in ("true", "1", "yes", "on") else "❌"

        return (
            f"📊 状态\n"
            f"COOKIE: {cookie_s}\n"
            f"sess: {ms_s}\n"
            f"邮箱: {em_s} | token: {tk_s}\n"
            f"签到{on('MASTER_ENABLE_SIGNIN')} 任务{on('MASTER_ENABLE_TASKS')} "
            f"广告{on('MASTER_ENABLE_AD')}"
        )

    def _cmd_query(self, sender_id, group_id=None):
        try:
            mail = _import_mail()
            return mail.query_results()
        except Exception as e:
            return f"❌ 查询失败: {e}"

    def _cmd_signin(self, sender_id, group_id=None):
        return self._run_script("签到", signin_only=True)

    def _cmd_run(self, sender_id, group_id=None):
        return self._run_script("全部任务", signin_only=False)

    def _cmd_toggle(self, arg, enable: bool, sender_id, group_id=None):
        toggle_map = {
            "签到": "MASTER_ENABLE_SIGNIN", "任务": "MASTER_ENABLE_TASKS",
            "广告": "MASTER_ENABLE_AD",
            "signin": "MASTER_ENABLE_SIGNIN", "tasks": "MASTER_ENABLE_TASKS",
            "ad": "MASTER_ENABLE_AD",
        }
        key = toggle_map.get(arg.strip())
        if not key:
            return f"❌ 未知: {arg}\n可用: 签到|任务|广告"

        env = self._read_env()
        env[key] = "true" if enable else "false"
        self._write_env(env)
        return f"{'开启✅' if enable else '关闭❌'} {arg}"

    def _run_script(self, task_name: str, signin_only: bool = False) -> str:
        env = self._read_env()
        ms, mf, tk, em = self._parse_account(env)
        if not ms or not mf:
            return "⚠️ 请先执行 大师登录 或 大师配置"

        script = os.path.join(self.project_dir, "mail_auto.py")
        if not os.path.exists(script):
            return "❌ 脚本未找到"

        args = [sys.executable, script]
        if signin_only:
            args.append("--signin-only")

        def _bg():
            try:
                ec = os.environ.copy()
                ec.update(env)
                proc = subprocess.run(args, cwd=self.project_dir, env=ec,
                                      capture_output=True, text=True, timeout=300)
                Log.ok(f"MailMaster {task_name} 完成")
            except Exception as e:
                Log.error(f"MailMaster {task_name} 异常: {e}")

        threading.Thread(target=_bg, daemon=True).start()
        return f"🚀 {task_name}已提交，完成后发送 大师查询 查看结果"


def register_session_handlers(handlers: dict):
    handlers["mail_login"] = lambda text, sid, gid, sess: MailMasterPlugin()._login_session(sid, gid, text, sess)
    Log.ok("MailMaster 已注册")
