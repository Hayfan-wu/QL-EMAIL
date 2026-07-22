# -*- coding: utf-8 -*-
"""
网易邮箱大师自动签到 - QQ机器人插件
==================================
QL-Bot 业务项目插件，提供 QQ 交互逻辑。

登录流程:
  大师登录 → 输入手机号 → 发送验证码 → 输入验证码 → 自动登录
  → 自动提取 tokenList / emailList → 自动保存配置 → 自动提交青龙

命令列表:
  大师菜单          - 帮助菜单
  大师登录          - 手机号+验证码登录，自动获取所有配置
  大师配置          - 手动设置 MASTER_COOKIE（备选方案）
  大师状态          - 查看配置状态
  大师查询          - 查看最近一次执行结果
  大师执行          - 执行全部自动化任务
  大师签到          - 仅执行签到
  大师开启/关闭 XX  - 开关功能
  签到 / 积分       - 快捷命令
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


def _import_login_api():
    sys.path.insert(0, _PROJECT_DIR)
    import login_api
    return login_api


MAIL_ENV_VARS = [
    ("MASTER_COOKIE", "大师号认证（自动生成，格式: mastersess:::masterfp:::M_INFO:::token1&token2:::email1&email2）"),
    ("MASTER_PHONE", "登录手机号"),
    ("MASTER_ENABLE_SIGNIN", "启用签到 (true/false)"),
    ("MASTER_ENABLE_TASKS", "启用任务领取 (true/false)"),
    ("MASTER_ENABLE_AD", "启用广告任务 (true/false)"),
    # 以下为手动配置时的备用端点
    ("MASTER_SEND_SMS_URL", "发送验证码端点（可选，默认使用网易通行证）"),
    ("MASTER_VERIFY_LOGIN_URL", "验证码登录端点（可选，默认使用网易通行证）"),
]

MENU_TEXT = """📧 网易邮箱大师自动签到

🔑 大师登录  - 手机号+验证码登录（自动获取所有配置）
📊 大师状态  - 查看配置和开关
📋 大师查询  - 查看最近一次结果
🚀 大师执行  - 执行全部任务
✅ 大师签到  - 仅执行签到
🛠 大师配置  - 手动设置 MASTER_COOKIE（备选）
✅ 大师开启 XX  /  ❌ 大师关闭 XX

可开关: 签到 | 任务 | 广告
快捷: 签到 | 积分

用户只需配置青龙面板的 QL_URL / QL_CLIENT_ID / QL_CLIENT_SECRET"""


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
        lines = ["# 网易邮箱大师自动签到 - 由QQ机器人自动管理", ""]
        lines.append("# 青龙面板（用户需手动配置这三项）")
        lines.append(f"QL_URL={env.get('QL_URL', 'http://127.0.0.1:5700')}")
        lines.append(f"QL_CLIENT_ID={env.get('QL_CLIENT_ID', '')}")
        lines.append(f"QL_CLIENT_SECRET={env.get('QL_CLIENT_SECRET', '')}")
        lines.append("")
        lines.append("# 大师号认证（由 大师登录 自动生成，无需手动填写）")
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
                return parts[0], parts[1], parts[2], parts[3], parts[4]
        return ("", "", "", "", "")

    # ---------- 命令实现 ----------

    # ---- 登录（手机号+验证码）----
    def _cmd_login(self, sender_id, group_id=None):
        sessions.set(sender_id, group_id, "mail_login", {"step": "phone"})
        return (
            "📱 请输入手机号（11位）：\n\n"
            "系统将发送短信验证码到该手机号，\n"
            "验证码登录后自动获取所有配置。\n"
            "发送 q 取消。"
        )

    def _login_session(self, sender_id, group_id, text, session):
        text = text.strip()

        if text.lower() == "q":
            sessions.clear(sender_id, group_id)
            return "已取消登录。"

        data = session.get("data", {})
        step = data.get("step", "phone")

        # ---- Step 1: 输入手机号 ----
        if step == "phone":
            phone = text.strip()
            if not re.match(r"^1[3-9]\d{9}$", phone):
                return "❌ 手机号格式不正确，请重新输入11位手机号："

            data["phone"] = phone
            data["step"] = "sending"
            session["data"] = data

            # 异步发送验证码
            def _send_sms():
                try:
                    api = _import_login_api()
                    result = api.send_sms_code(phone)
                    data["sms_result"] = result
                except Exception as e:
                    data["sms_result"] = {"ok": False, "msg": str(e)}

            threading.Thread(target=_send_sms, daemon=True).start()
            return f"📤 正在发送验证码到 {phone}...\n请稍候（约5-10秒），然后输入收到的短信验证码："

        # ---- Step 2: 等待验证码发送结果 + 输入验证码 ----
        if step == "sending":
            # 检查发送结果
            sms_result = data.get("sms_result", {})
            if sms_result and sms_result.get("ok"):
                # 验证码已发送，用户输入验证码
                code = text.strip()
                if not re.match(r"^\d{4,6}$", code):
                    return "❌ 验证码格式不正确，请输入4-6位数字验证码："

                data["code"] = code
                data["step"] = "verifying"
                session["data"] = data

                # 异步验证登录
                phone = data["phone"]

                def _verify():
                    try:
                        api = _import_login_api()
                        result = api.full_login(phone, code)
                        data["login_result"] = result
                    except Exception as e:
                        data["login_result"] = {"ok": False, "msg": str(e)}

                threading.Thread(target=_verify, daemon=True).start()
                return f"🔐 正在验证登录...\n手机号: {phone}\n请稍候..."

            elif sms_result and not sms_result.get("ok"):
                # 发送失败
                msg = sms_result.get("msg", "未知错误")
                sessions.clear(sender_id, group_id)
                return f"❌ 验证码发送失败: {msg}\n\n请稍后重试 大师登录"

            else:
                # 还没返回结果，稍等
                return "⏳ 验证码发送中，请稍候...\n收到验证码后直接输入即可。"

        # ---- Step 3: 等待验证结果 ----
        if step == "verifying":
            login_result = data.get("login_result", {})
            if login_result and login_result.get("ok"):
                # 登录成功！保存配置
                master_cookie = login_result.get("master_cookie", "")
                emails = login_result.get("emails", [])
                phone = login_result.get("phone", data.get("phone", ""))
                msg = login_result.get("msg", "")

                env = self._read_env()
                env["MASTER_COOKIE"] = master_cookie
                env["MASTER_PHONE"] = phone
                self._write_env(env)
                sessions.clear(sender_id, group_id)

                # 自动提交青龙
                submit = self._auto_submit(env)

                email_str = ", ".join(emails) if emails else "未提取到（请手动配置）"
                master_cookie_masked = (
                    master_cookie[:30] + "..." if len(master_cookie) > 30 else master_cookie
                )

                return (
                    f"✅ 登录成功！\n"
                    f"📱 手机号: {phone}\n"
                    f"📬 邮箱: {email_str}\n"
                    f"🔑 COOKIE: {master_cookie_masked}\n"
                    f"📝 {msg}\n\n"
                    f"{submit}"
                )

            elif login_result and not login_result.get("ok"):
                # 登录失败
                msg = login_result.get("msg", "未知错误")
                debug = login_result.get("debug", {})
                sessions.clear(sender_id, group_id)

                debug_info = ""
                if debug:
                    debug_info = "\n\n调试信息（可反馈给开发者）:\n"
                    if debug.get("raw"):
                        debug_info += f"响应: {json.dumps(debug['raw'], ensure_ascii=False)[:300]}"
                    if debug.get("cookies"):
                        debug_info += f"\nCookies: {list(debug['cookies'].keys())}"
                    if debug.get("headers"):
                        debug_info += f"\nHeaders: {json.dumps(debug['headers'], ensure_ascii=False)[:200]}"

                return f"❌ 登录失败: {msg}{debug_info}\n\n请确认:\n1. 验证码是否正确\n2. 手机号是否已注册大师号\n3. 端点配置是否正确"

            else:
                return "⏳ 正在验证登录，请稍候..."

        return "⚠️ 会话状态异常，请重新发送 大师登录"

    # ---- 手动配置（备选方案）----
    def _cmd_config(self, sender_id, group_id, arg):
        if not arg:
            return (
                "用法: 大师配置 <MASTER_COOKIE>\n\n"
                "格式: mastersess:::masterfp:::M_INFO:::token1&token2:::email1@163.com\n\n"
                "💡 推荐使用 大师登录 自动获取，无需手动填写。"
            )
        cookie = arg.strip()
        if ":::" not in cookie or len(cookie.split(":::")) < 5:
            return "❌ 格式错误，需要5段 ::: 分隔"

        env = self._read_env()
        env["MASTER_COOKIE"] = cookie
        self._write_env(env)

        # 验证配置
        try:
            api = _import_login_api()
            valid = api.validate_config(cookie)
            if valid:
                submit = self._auto_submit(env)
                return f"✅ 配置已保存并验证通过！\n{submit}"
            else:
                return "⚠️ 配置已保存，但验证失败，可能已过期或不正确。"
        except Exception as e:
            return f"⚠️ 配置已保存，但验证异常: {e}"

    # ---- 自动提交青龙 ----
    def _auto_submit(self, env: dict) -> str:
        ql_url = env.get("QL_URL", "")
        ql_cid = env.get("QL_CLIENT_ID", "")
        ql_cs = env.get("QL_CLIENT_SECRET", "")

        if not ql_url or not ql_cid or not ql_cs:
            return (
                "⚠️ 青龙未配置，请设置 QL_URL / QL_CLIENT_ID / QL_CLIENT_SECRET\n"
                "在 .env 文件中填写这三项即可。"
            )

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

            # 同时提交青龙面板配置
            for ql_key in ("QL_URL", "QL_CLIENT_ID", "QL_CLIENT_SECRET"):
                ql_val = env.get(ql_key, "")
                if ql_val:
                    try:
                        existing = ql.list_envs(search_value=ql_key)
                        found = [e for e in existing if e.get("name") == ql_key]
                        if found:
                            eid = found[0].get("id") or found[0].get("_id")
                            ql.update_env(eid, ql_key, ql_val, "青龙面板配置")
                        else:
                            ql.create_env(ql_key, ql_val, "青龙面板配置")
                        ok += 1
                    except Exception:
                        fail += 1

            result = f"📤 青龙提交: ✅{ok}"
            if fail:
                result += f" ❌{fail}"
            result += (
                "\n\n定时任务:\n"
                "  任务名: QL-EMAIL\n"
                "  命令: task mail_auto.py\n"
                "  定时: 30 8 * * *"
            )
            return result
        except Exception as e:
            return f"⚠️ 青龙提交失败: {e}"

    # ---- 状态 ----
    def _cmd_status(self, sender_id, group_id=None):
        env = self._read_env()
        ms, mf, mi, tk, em = self._parse_account(env)

        cookie = env.get("MASTER_COOKIE", "")
        cookie_s = "已配置" if cookie else "未配置"
        phone = env.get("MASTER_PHONE", "")
        phone_s = phone if phone else "未设置"
        emails = em.split("&") if em else []
        em_s = f"{len(emails)} 个" if emails else "未设置"
        tokens = tk.split("&") if tk else []
        tk_s = f"{len(tokens)} 个" if tokens else "未设置"

        # 验证配置有效性
        valid_s = ""
        if cookie:
            try:
                api = _import_login_api()
                valid = api.validate_config(cookie)
                valid_s = " ✅有效" if valid else " ❌已过期"
            except Exception:
                valid_s = " ⚠️未知"

        def on(key):
            return "✅" if env.get(key, "true").lower() in ("true", "1", "yes", "on") else "❌"

        ql_url = env.get("QL_URL", "")
        ql_cid = env.get("QL_CLIENT_ID", "")
        ql_cs = env.get("QL_CLIENT_SECRET", "")
        ql_s = "已配置" if ql_url and ql_cid and ql_cs else "未配置"

        return (
            f"📊 状态\n"
            f"登录: {cookie_s}{valid_s}\n"
            f"手机: {phone_s}\n"
            f"邮箱: {em_s} | token: {tk_s}\n"
            f"青龙: {ql_s}\n"
            f"签到{on('MASTER_ENABLE_SIGNIN')} 任务{on('MASTER_ENABLE_TASKS')} "
            f"广告{on('MASTER_ENABLE_AD')}"
        )

    # ---- 查询 ----
    def _cmd_query(self, sender_id, group_id=None):
        try:
            mail = _import_mail()
            return mail.query_results()
        except Exception as e:
            return f"❌ 查询失败: {e}"

    # ---- 签到 ----
    def _cmd_signin(self, sender_id, group_id=None):
        return self._run_script("签到", signin_only=True)

    # ---- 执行 ----
    def _cmd_run(self, sender_id, group_id=None):
        return self._run_script("全部任务", signin_only=False)

    # ---- 开关 ----
    def _cmd_toggle(self, arg, enable: bool, sender_id, group_id=None):
        toggle_map = {
            "签到": "MASTER_ENABLE_SIGNIN",
            "任务": "MASTER_ENABLE_TASKS",
            "广告": "MASTER_ENABLE_AD",
            "signin": "MASTER_ENABLE_SIGNIN",
            "tasks": "MASTER_ENABLE_TASKS",
            "ad": "MASTER_ENABLE_AD",
        }
        key = toggle_map.get(arg.strip())
        if not key:
            return f"❌ 未知: {arg}\n可用: 签到|任务|广告"

        env = self._read_env()
        env[key] = "true" if enable else "false"
        self._write_env(env)
        return f"{'开启✅' if enable else '关闭❌'} {arg}"

    # ---- 脚本执行 ----
    def _run_script(self, task_name: str, signin_only: bool = False) -> str:
        env = self._read_env()
        ms, mf, mi, tk, em = self._parse_account(env)
        if not ms:
            return "⚠️ 请先执行 大师登录 完成配置"

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
                subprocess.run(args, cwd=self.project_dir, env=ec,
                               capture_output=True, text=True, timeout=300)
                Log.ok(f"MailMaster {task_name} 完成")
            except Exception as e:
                Log.error(f"MailMaster {task_name} 异常: {e}")

        threading.Thread(target=_bg, daemon=True).start()
        return f"🚀 {task_name}已提交，完成后发送 大师查询 查看结果"


# ==================== 插件注册 ====================

import json  # noqa: E402 - 用于调试输出

def register_session_handlers(handlers: dict):
    handlers["mail_login"] = lambda text, sid, gid, sess: (
        MailMasterPlugin()._login_session(sid, gid, text, sess)
    )
    Log.ok("MailMaster 已注册")
