#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QL-EMAIL - 网易邮箱大师自动签到脚本
=========================================
基于 HAR 抓包分析，模拟 MailMaster App API 请求。

环境变量:
  MASTER_COOKIE=mastersess:::masterfp:::M_INFO:::token1&token2:::email1&email2
  多账号换行分隔（每行一个 MASTER_COOKIE）

  兼容分开配置: MASTER_MASTERSESS / MASTER_MASTERFP / MASTER_TOKENS / MASTER_EMAILS

青龙定时任务:
  命令: task mail_auto.py
  定时: 30 8 * * *

依赖安装:
  pip install requests certifi --break-system-packages
"""

import base64
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Union

import certifi
import requests

# 登录API模块（可选，用于 --login 模式）
try:
    from login_api import validate_config as _login_validate
except ImportError:
    _login_validate = None

# ==================== 环境变量加载 ====================
_PROJECT_DIR = Path(__file__).resolve().parent
_ENV_FILE = _PROJECT_DIR / ".env"
if _ENV_FILE.exists():
    with open(str(_ENV_FILE), "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                if _key.strip() not in os.environ:
                    os.environ.setdefault(_key.strip(), _val.strip().strip("\"'"))

# ==================== 配置 ====================

PROJECT_DIR = Path(__file__).resolve().parent
RESULT_FILE = PROJECT_DIR / "result.json"
LOG_FILE = PROJECT_DIR / "mail_master.log"

# 功能开关
ENABLE_SIGNIN = os.environ.get("MASTER_ENABLE_SIGNIN", "true").lower() in ("true", "1", "yes", "on")
ENABLE_TASKS = os.environ.get("MASTER_ENABLE_TASKS", "true").lower() in ("true", "1", "yes", "on")
ENABLE_AD = os.environ.get("MASTER_ENABLE_AD", "true").lower() in ("true", "1", "yes", "on")

BASE_URL = "https://dashi.163.com"

# ==================== 日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("QL-EMAIL")

# ==================== 工具函数 ====================

_global_logs = []


def log(msg: str):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    full_msg = f"[{timestamp}] {msg}"
    _global_logs.append(full_msg)
    logger.info(msg)


def mask(s: str) -> str:
    if not s or len(s) < 7:
        return s
    return f"{s[:3]}****{s[-4:]}"


# ==================== HTTP 会话 ====================

_session = requests.Session()
_session.verify = certifi.where()
_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) '
                  'AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 '
                  'Safari/603.2.4 MailMaster/7.25.17.2266',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh-Hans;q=0.9',
    'Content-Type': 'application/json',
    'Origin': 'masterweb://static.dashi.163.com',
    'Sec-Fetch-Site': 'cross-site',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Dest': 'empty',
})


def _apply_auth(auth: dict):
    """将认证信息应用到会话头"""
    m_info = auth.get("m_info", "")
    if not m_info:
        did = str(uuid.uuid4()).upper()
        m_info = base64.b64encode(json.dumps({"did": did}).encode()).decode()
        auth["m_info"] = m_info
    _session.headers["mastersess"] = auth["mastersess"]
    _session.headers["masterfp"] = auth["masterfp"]
    _session.headers["Cookie"] = f"M_INFO={m_info}"


def _build_env(auth: dict) -> dict:
    """构建请求体中的 env 字段"""
    return {
        "emailList": auth.get("email_list", []),
        "installedApps": ["xhs"],
        "widgetStatus": False,
        "tokenList": auth.get("token_list", []),
        "calendarGranted": False,
        "industryTag": "",
        "systemNotiSwitchStatus": True,
    }


def api_req(url: str, method: str = "GET", **kwargs) -> Union[Dict[str, Any], str]:
    try:
        r = _session.request(method, url, timeout=15, **kwargs)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log(f"[网络异常] {e}")
        return {}


# ==================== API 接口 ====================

def api_get_score() -> dict:
    return api_req(f"{BASE_URL}/mailsrv-score/fapi/score")


def api_get_task_list(auth: dict, entry="ScoreCenter", view_types=None, exclude_types=None, limit=None):
    body = {"entry": entry, "env": _build_env(auth)}
    if view_types:
        body["includeViewTypes"] = view_types
    if exclude_types:
        body["excludeViewTypes"] = exclude_types
    if limit is not None:
        body["limit"] = limit
    return api_req(f"{BASE_URL}/task-center-api/fapi/task/list", "POST", json=body)


def api_get_task_detail(task_type: str) -> dict:
    return api_req(f"{BASE_URL}/task-center-api/fapi/task/detail", params={"taskType": task_type})


def api_claim_task(task_spe_type: str) -> dict:
    return api_req(f"{BASE_URL}/task-center-api/fapi/task/claim", "POST",
                  json={"taskSpeType": task_spe_type})


def api_confirm_task(task_spe_type: str, token: str) -> dict:
    return api_req(f"{BASE_URL}/task-center-api/fapi/task/confirm", "POST",
                  json={"taskSpeType": task_spe_type, "token": token})


def api_get_gift_list() -> dict:
    return api_req(f"{BASE_URL}/mailsrv-score/fapi/gift/list", params={"limit": "20", "offset": ""})


# ==================== 任务执行 ====================

def sign_tasks(auth: dict, signin_only: bool = False):
    """执行签到及所有任务"""
    emails = auth.get("email_list", [])
    email_str = ", ".join(emails) if emails else "未知"
    log(f"[任务开始] {mask(email_str[:20])}")

    _apply_auth(auth)

    result = {
        "email": email_str,
        "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "items": [],
        "login": True,
        "signin": {},
        "tasks_done": 0,
        "score_before": 0,
        "score_after": 0,
        "today_earned": 0,
        "gifts": [],
    }

    # 认证预检
    score_data = api_get_score()
    if not isinstance(score_data, dict) or score_data.get("code") != 200:
        log(f"[认证失败] 接口返回异常: {score_data}")
        result["login"] = False
        result["error"] = "认证无效"
        _save_result(result)
        return result
    log("[认证] 有效")

    score_before = score_data.get("result", {}).get("score", 0)
    result["score_before"] = score_before
    log(f"[积分] 当前: {score_before}")

    # 签到
    if ENABLE_SIGNIN:
        log("[签到] 开始")
        detail = api_get_task_detail("SIGN_IN")
        if isinstance(detail, dict) and detail.get("code") == 200:
            brief = detail.get("result", {}).get("brief", {})
            status = brief.get("status", "")
            title = brief.get("title", {}).get("cn", "")
            reward = brief.get("reward", {}).get("value", "?")
            info = detail.get("result", {}).get("detail", {})
            history = info.get("history", [])
            continuous = info.get("continuousDuration", 0)

            log(f"[签到] {title} | 状态: {status} | 奖励: {reward}积分")
            log(f"[签到] 连续签到: {continuous}天 | 已签: {history or '无'}")

            if status != "Done":
                spe_type = brief.get("taskSpeType", "")
                if spe_type:
                    r = api_claim_task(spe_type)
                    if r.get("code") == 200:
                        msg = f"签到成功, +{reward}积分"
                        log(f"[签到成功] {msg}")
                        result["signin"] = {"ok": True, "msg": msg}
                        result["items"].append({"type": "签到", "value": msg})
                    else:
                        msg = r.get("desc", "签到失败")
                        log(f"[签到失败] {msg}")
                        result["signin"] = {"ok": False, "msg": msg}
                else:
                    log("[签到] 无 taskSpeType, 可能需要App内操作")
            else:
                log("[签到] 今日已签到")
                result["signin"] = {"ok": True, "msg": "今日已签到"}
        else:
            log("[签到] 获取签到信息失败")
            result["signin"] = {"ok": False, "msg": "获取信息失败"}
    else:
        log("[签到] 已禁用")

    if signin_only:
        log("[仅签到模式] 跳过其他任务")
    else:
        # 集赞墙
        log("[集赞墙] 查询")
        cl = api_get_task_detail("COLLECT_LIKE")
        if isinstance(cl, dict) and cl.get("code") == 200:
            b = cl.get("result", {}).get("brief", {})
            info = cl.get("result", {}).get("detail", {})
            total = info.get("total", 0)
            done = info.get("complete", 0)
            status = b.get("status", "")
            log(f"[集赞墙] {done}/{total} | 状态: {status}")
            if status == "Done":
                result["items"].append({"type": "集赞墙", "value": "已完成"})

        # 各类任务
        if ENABLE_TASKS:
            views = [
                ("互动任务", "interaction"),
                ("新用户功能体验", "onboarding"),
                ("AI功能体验", "ai_onboarding"),
                ("外贸功能体验", "industry_onboarding"),
                ("会员功能体验", "member_onboarding"),
                ("推荐设置", "setting"),
                ("每日任务", "daily"),
                ("产品合作", "cooperation"),
                ("会员任务", "open_member"),
            ]

            total_claimed = 0
            for label, key in views:
                tasks_res = api_get_task_list(auth, view_types=[key])
                if not isinstance(tasks_res, dict) or tasks_res.get("code") != 200:
                    log(f"[{label}] 无任务")
                    continue

                tasks = tasks_res.get("result", {}).get("list", [])
                if not tasks:
                    continue

                ext = tasks_res.get("result", {}).get("taskExtendInfo", {})
                residual = ext.get("todayResidualScore", "?")
                log(f"[{label}] 剩余可获积分: {residual}, 任务数: {len(tasks)}")

                for task in tasks:
                    status = task.get("status", "")
                    title = task.get("title", {}).get("cn", "未知")
                    spe = task.get("taskSpeType", "")
                    pts = task.get("reward", {}).get("value", "?")
                    button = task.get("button", {})
                    op = button.get("operation", {}).get("route", {}).get("type", "")

                    if status == "Init" and op == "claim":
                        log(f"[{label}] 领取: {title} ({pts}分)")
                        r = api_claim_task(spe)
                        if r.get("code") == 200:
                            log(f"[{label}]   -> 成功")
                            total_claimed += 1
                            result["items"].append({"type": label, "value": f"{title} +{pts}分"})
                        else:
                            log(f"[{label}]   -> 失败: {r.get('desc', r)}")
                        time.sleep(0.5)
                    elif status == "NeedConfirm" and op == "confirm":
                        token = task.get("token", "")
                        log(f"[{label}] 确认: {title} ({pts}分)")
                        r = api_confirm_task(spe, token)
                        if r.get("code") == 200:
                            log(f"[{label}]   -> 成功")
                            total_claimed += 1
                            result["items"].append({"type": label, "value": f"{title} +{pts}分"})
                        else:
                            log(f"[{label}]   -> 失败: {r.get('desc', r)}")
                        time.sleep(0.5)
                    elif status == "Done":
                        pass
                    elif status == "Todo":
                        log(f"[{label}] 需App操作: {title}")

            result["tasks_done"] = total_claimed
            log(f"[任务] 共完成 {total_claimed} 个任务")
        else:
            log("[任务] 已禁用")

        # 广告
        if ENABLE_AD:
            log("[广告] 开始 (最多3次)")
            ad_res = api_get_task_list(auth, entry="TaskCenter", limit=1)
            ad_found = False
            if isinstance(ad_res, dict):
                for task in ad_res.get("result", {}).get("list", []):
                    if task.get("taskSpeType") == "reward_ad#1":
                        ad_found = True
                        for i in range(3):
                            log(f"[广告] 第{i+1}/3次")
                            r = api_claim_task("reward_ad#1")
                            if r.get("code") == 200:
                                log(f"[广告]   -> 成功")
                                result["items"].append({"type": "广告", "value": f"第{i+1}次"})
                            else:
                                log(f"[广告]   -> 失败: {r.get('desc', r)}")
                            time.sleep(1)
                        break
            if not ad_found:
                log("[广告] 未找到广告任务")
        else:
            log("[广告] 已禁用")

        # 礼品
        gifts = api_get_gift_list()
        if isinstance(gifts, dict) and gifts.get("code") == 200:
            for g in gifts.get("result", [])[:5]:
                name = g.get("name", {}).get("cn", "")
                score = g.get("score", 0)
                result["gifts"].append({"name": name, "score": score})
            log(f"[礼品] 已查询")

    # 最终积分
    final = api_get_score()
    if isinstance(final, dict) and final.get("code") == 200:
        score_after = final.get("result", {}).get("score", 0)
        result["score_after"] = score_after
        result["today_earned"] = score_after - score_before
        log(f"[积分] {score_before} -> {score_after} (本次+{result['today_earned']})")

    log(f"[任务全部完成] {mask(email_str[:20])}")
    _save_result(result)
    return result


# ==================== 产物记录 ====================

def _load_results() -> dict:
    if RESULT_FILE.exists():
        try:
            return json.loads(RESULT_FILE.read_text())
        except Exception:
            pass
    return {"total": {}, "history": []}


def _save_result(run_result: dict):
    records = _load_results()
    records["history"].append(run_result)
    for item in run_result.get("items", []):
        key = item.get("type", "其他")
        val = item.get("value", "")
        if key not in records["total"]:
            records["total"][key] = []
        records["total"][key].append({"time": run_result["time"], "value": val})
    RESULT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2))


def format_wxpusher_summary(result: dict) -> str:
    email = result.get("email", "未知")
    signin = result.get("signin", {})
    score_before = result.get("score_before", 0)
    score_after = result.get("score_after", 0)
    today = result.get("today_earned", 0)
    tasks_done = result.get("tasks_done", 0)

    lines = [
        f"邮箱大师签到 {'✅' if signin.get('ok') else '❌'}",
        f"积分 {score_before} -> {score_after} (本次+{today})",
        f"任务完成 {tasks_done} 个",
    ]
    if result.get("error"):
        lines.append(f"异常: {result['error']}")
    return "\n".join(lines)


def query_results() -> str:
    records = _load_results()
    history = records.get("history", [])
    if not history:
        return "暂无任务执行记录，请先执行 大师执行"
    last = history[-1]
    return format_wxpusher_summary(last)


# ==================== 账号解析 ====================

def _parse_cookie(cookie_str: str) -> list:
    """解析 MASTER_COOKIE: mastersess:::masterfp:::M_INFO:::token1&token2:::email1&email2"""
    if not cookie_str:
        return []
    parts = cookie_str.strip().split(":::")
    if len(parts) < 5:
        return []
    token_list = [t.strip() for t in parts[3].split("&") if t.strip()]
    email_list = [e.strip() for e in parts[4].split("&") if e.strip()]
    return [{
        "mastersess": parts[0].strip(),
        "masterfp": parts[1].strip(),
        "m_info": parts[2].strip(),
        "token_list": token_list,
        "email_list": email_list,
    }]


def _parse_individual() -> list:
    """从独立环境变量解析"""
    mastersess = os.environ.get("MASTER_MASTERSESS", "").strip()
    masterfp = os.environ.get("MASTER_MASTERFP", "").strip()
    m_info = os.environ.get("MASTER_M_INFO", "").strip()
    tokens = [t.strip() for t in os.environ.get("MASTER_TOKENS", "").split("&") if t.strip()]
    emails = [e.strip() for e in os.environ.get("MASTER_EMAILS", "").split("&") if e.strip()]
    if not mastersess or not masterfp or not tokens or not emails:
        return []
    return [{
        "mastersess": mastersess,
        "masterfp": masterfp,
        "m_info": m_info,
        "token_list": tokens,
        "email_list": emails,
    }]


# ==================== 主入口 ====================

def run_all(signin_only: bool = False) -> dict:
    global _global_logs
    _global_logs = []

    # 解析账号 (支持多账号换行)
    raw = os.environ.get('MASTER_COOKIE', '')
    accounts = []
    for line in raw.strip().split('\n'):
        line = line.strip()
        if line:
            parsed = _parse_cookie(line)
            if parsed:
                accounts.extend(parsed)

    if not accounts:
        accounts = _parse_individual()

    if not accounts:
        log("未找到环境变量 MASTER_COOKIE，请按格式设置：mastersess:::masterfp:::M_INFO:::token1&token2:::email1&email2")
        log("多账号换行分隔")
        return {"error": "账号未配置", "login": False}

    all_results = []
    for idx, auth in enumerate(accounts, 1):
        emails = auth.get("email_list", [])
        m = mask(emails[0] if emails else "未知")
        log(f"\n{'='*10} 账号[{idx}] {m} {'='*10}")

        if signin_only:
            # 仅签到模式
            _apply_auth(auth)
            detail = api_get_task_detail("SIGN_IN")
            if isinstance(detail, dict) and detail.get("code") == 200:
                brief = detail.get("result", {}).get("brief", {})
                status = brief.get("status", "")
                if status != "Done":
                    spe = brief.get("taskSpeType", "")
                    if spe:
                        r = api_claim_task(spe)
                        if r.get("code") == 200:
                            log(f"[签到成功] {m}")
                        else:
                            log(f"[签到] {m}: {r.get('desc', '失败')}")
                else:
                    log(f"[签到] {m} 今日已签到")
            time.sleep(2)
        else:
            result = sign_tasks(auth, signin_only=False)
            all_results.append(result)

        time.sleep(2)

    # 推送
    try:
        import notify
        if all_results:
            for r in all_results:
                summary = format_wxpusher_summary(r)
                notify.send('邮箱大师签到推送', summary)
            log("通知推送成功")
    except ImportError:
        pass

    return all_results[0] if all_results else {"error": "无执行结果", "login": False}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="QL-EMAIL 网易邮箱大师自动签到")
    parser.add_argument("--signin-only", action="store_true", help="仅执行签到")
    parser.add_argument("--login", action="store_true", help="手机号+验证码登录（交互式）")
    parser.add_argument("--validate", action="store_true", help="验证 MASTER_COOKIE 是否有效")
    args = parser.parse_args()

    if args.login:
        # 交互式登录
        try:
            from login_api import send_sms_code, full_login
        except ImportError:
            print("[FAIL] login_api.py 未找到，请确保文件存在")
            sys.exit(1)

        phone = input("请输入手机号: ").strip()
        if not phone:
            print("[FAIL] 手机号不能为空")
            sys.exit(1)

        result = send_sms_code(phone)
        if not result.get("ok"):
            print(f"[FAIL] 发送验证码失败: {result.get('msg')}")
            sys.exit(1)

        print(f"验证码已发送到 {phone}")
        code = input("请输入验证码: ").strip()
        if not code:
            print("[FAIL] 验证码不能为空")
            sys.exit(1)

        login_result = full_login(phone, code)
        if login_result.get("ok"):
            print(f"\n[OK] 登录成功!")
            print(f"MASTER_COOKIE={login_result.get('master_cookie', '')}")
            print(f"邮箱: {login_result.get('emails', [])}")
            print(f"\n请将以上 MASTER_COOKIE 设置到环境变量中")
        else:
            print(f"\n[FAIL] {login_result.get('msg', '')}")
        sys.exit(0)

    if args.validate:
        cookie = os.environ.get('MASTER_COOKIE', '')
        if not cookie:
            print("[FAIL] MASTER_COOKIE 未设置")
            sys.exit(1)

        if _login_validate:
            valid = _login_validate(cookie)
            print(f"[{'OK' if valid else 'FAIL'}] 配置{'有效' if valid else '无效'}")
        else:
            print("[FAIL] login_api.py 未找到")
        sys.exit(0)

    result = run_all(signin_only=args.signin_only)
    if result.get("error"):
        print(f"\n[FAIL] {result['error']}")
        sys.exit(1)
    else:
        print(f"\n[OK] 执行完成")
        sys.exit(0)
