#!/usr/bin/env python3
"""
网易邮箱大师 (MailMaster) - 自动签到 & 任务自动完成脚本
========================================================
通过抓包获取认证信息，自动完成签到和各类任务获取积分。

⚠️ 重要: 必须配置环境变量才能运行，否则脚本会报错退出！

青龙面板环境变量配置:
  MASTER_MASTERSESS = 从HAR请求头mastersess中提取的值
  MASTER_MASTERFP    = 从HAR请求头masterfp中提取的值
  MASTER_TOKENS      = 从HAR请求体tokenList中提取,多个用&分隔
  MASTER_EMAILS      = 邮箱列表,多个用&分隔

  (可选)
  MASTER_M_INFO      = 从HAR Cookie中M_INFO的值,不填则自动生成

本地运行:
  export MASTER_MASTERSESS="你的值"
  export MASTER_MASTERFP="你的值"
  export MASTER_TOKENS="token1&token2"
  export MASTER_EMAILS="user1@163.com&user2@163.com"
  python3 netease_mail_daily.py
"""

import requests
import json
import time
import sys
import os
import base64
import uuid
from datetime import datetime


# ═══════════════════════════════════════════════════════════
# 环境变量配置 (必填)
# ═══════════════════════════════════════════════════════════

def load_config():
    """从环境变量加载配置，缺失必填项则直接报错退出"""
    mastersess = os.environ.get("MASTER_MASTERSESS", "").strip()
    masterfp = os.environ.get("MASTER_MASTERFP", "").strip()
    tokens_str = os.environ.get("MASTER_TOKENS", "").strip()
    emails_str = os.environ.get("MASTER_EMAILS", "").strip()
    m_info = os.environ.get("MASTER_M_INFO", "").strip()

    # === 必填项校验 ===
    errors = []
    if not mastersess:
        errors.append("MASTER_MASTERSESS")
    if not masterfp:
        errors.append("MASTER_MASTERFP")
    if not tokens_str:
        errors.append("MASTER_TOKENS")
    if not emails_str:
        errors.append("MASTER_EMAILS")

    if errors:
        print(f"\n[配置错误] 以下环境变量未设置: {', '.join(errors)}")
        print("\n请先配置环境变量:")
        print("  MASTER_MASTERSESS = mastersess 请求头值 (从HAR抓包获取)")
        print("  MASTER_MASTERFP    = masterfp 请求头值 (从HAR抓包获取)")
        print("  MASTER_TOKENS      = 邮箱token列表 (从HAR请求体tokenList提取, 多个用&分隔)")
        print("  MASTER_EMAILS      = 邮箱列表 (多个用&分隔)")
        print("  (可选) MASTER_M_INFO = 设备ID Cookie (不填自动生成)")
        sys.exit(1)

    token_list = [t.strip() for t in tokens_str.split("&") if t.strip()]
    email_list = [e.strip() for e in emails_str.split("&") if e.strip()]

    if not token_list or not email_list:
        print("[配置错误] MASTER_TOKENS 或 MASTER_EMAILS 解析后为空")
        sys.exit(1)

    if not m_info:
        did = str(uuid.uuid4()).upper()
        m_info = base64.b64encode(json.dumps({"did": did}).encode()).decode()

    return {
        "mastersess": mastersess,
        "masterfp": masterfp,
        "m_info": m_info,
        "token_list": token_list,
        "email_list": email_list,
    }


# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════

BASE_URL = "https://dashi.163.com"
TASK_LIST_URL = f"{BASE_URL}/task-center-api/fapi/task/list"
TASK_CLAIM_URL = f"{BASE_URL}/task-center-api/fapi/task/claim"
TASK_CONFIRM_URL = f"{BASE_URL}/task-center-api/fapi/task/confirm"
TASK_DETAIL_URL = f"{BASE_URL}/task-center-api/fapi/task/detail"
SCORE_URL = f"{BASE_URL}/mailsrv-score/fapi/score"
GIFT_LIST_URL = f"{BASE_URL}/mailsrv-score/fapi/gift/list"


# ═══════════════════════════════════════════════════════════
# 网络请求
# ═══════════════════════════════════════════════════════════

def build_session(auth):
    sess = requests.Session()
    sess.headers.update({
        "Host": "dashi.163.com",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "masterweb://static.dashi.163.com",
        "mastersess": auth["mastersess"],
        "masterfp": auth["masterfp"],
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
                      "Safari/603.2.4 MailMaster/7.25.17.2266",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Cookie": f"M_INFO={auth['m_info']}",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    })
    return sess


def api_call(sess, method, url, **kwargs):
    """统一 API 调用，失败返回 None 并打印错误"""
    try:
        resp = sess.request(method, url, timeout=15, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code
        body = e.response.text[:200] if e.response else ""
        print(f"    [HTTP {status}] {body}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"    [网络错误] {e}")
        return None
    except (json.JSONDecodeError, ValueError):
        print(f"    [解析错误] 响应不是有效JSON")
        return None


def build_env(auth):
    return {
        "emailList": auth["email_list"],
        "installedApps": ["xhs"],
        "widgetStatus": False,
        "tokenList": auth["token_list"],
        "calendarGranted": False,
        "industryTag": "",
        "systemNotiSwitchStatus": True,
    }


def get_score(sess):
    print("\n--- 积分查询 ---")
    result = api_call(sess, "GET", SCORE_URL)
    if result and result.get("code") == 200:
        data = result.get("result", {})
        score = data.get("score", 0)
        to_expire = data.get("toExpireScore", 0)
        gap_info = data.get("gapInfo", {})
        gift_name = gap_info.get("gift", {}).get("name", {}).get("cn", "")
        gap_score = gap_info.get("gapScore", 0)
        print(f"  当前积分: {score}")
        if to_expire:
            print(f"  即将过期: {to_expire}")
        if gift_name:
            print(f"  距「{gift_name}」还差: {gap_score} 分")
        return score
    print("  查询失败")
    return None


def get_task_list(sess, auth, entry="ScoreCenter", view_types=None, exclude_types=None, limit=None):
    body = {"entry": entry, "env": build_env(auth)}
    if view_types:
        body["includeViewTypes"] = view_types
    if exclude_types:
        body["excludeViewTypes"] = exclude_types
    if limit is not None:
        body["limit"] = limit
    result = api_call(sess, "POST", TASK_LIST_URL, json=body)
    if result and result.get("code") == 200:
        data = result.get("result", {})
        return data.get("list", []), data.get("taskExtendInfo", {})
    return [], {}


def get_task_detail(sess, task_type):
    result = api_call(sess, "GET", TASK_DETAIL_URL, params={"taskType": task_type})
    if result and result.get("code") == 200:
        return result.get("result", {})
    return None


def claim_task(sess, task_spe_type):
    print(f"    领取: {task_spe_type} ...", end=" ")
    result = api_call(sess, "POST", TASK_CLAIM_URL, json={"taskSpeType": task_spe_type})
    if result and result.get("code") == 200:
        print("成功")
        return True
    desc = result.get("desc", "") if result else "网络错误"
    print(f"失败 ({desc})")
    return False


def confirm_task(sess, task_spe_type, token):
    print(f"    确认: {task_spe_type} ...", end=" ")
    result = api_call(sess, "POST", TASK_CONFIRM_URL, json={
        "taskSpeType": task_spe_type, "token": token
    })
    if result and result.get("code") == 200:
        print("成功")
        return True
    desc = result.get("desc", "") if result else "网络错误"
    print(f"失败 ({desc})")
    return False


# ═══════════════════════════════════════════════════════════
# 任务处理逻辑
# ═══════════════════════════════════════════════════════════

def do_sign_in(sess):
    """签到"""
    print("\n--- 签到 ---")
    detail = get_task_detail(sess, "SIGN_IN")
    if not detail:
        print("  获取签到信息失败")
        return False

    brief = detail.get("brief", {})
    status = brief.get("status", "")
    title = brief.get("title", {}).get("cn", "")
    reward = brief.get("reward", {}).get("value", "?")
    info = detail.get("detail", {})
    history = info.get("history", [])
    continuous = info.get("continuousDuration", 0)
    re_sign = info.get("reSignInfo", {})

    print(f"  {title} | 状态: {status} | 奖励: {reward}积分")
    print(f"  连续签到: {continuous}天 | 已签: {history or '无'}")
    if re_sign.get("available"):
        print(f"  补签剩余: {re_sign.get('remainingTimes', 0)}次")

    if status == "Done":
        print("  今日已签到, 跳过")
        return False

    # 尝试签到
    spe_type = brief.get("taskSpeType", "")
    if spe_type:
        ok = claim_task(sess, spe_type)
        if ok:
            print("  签到成功!")
            return True
        else:
            print("  签到失败 (可能需要在App内操作)")
    return False


def do_collect_like(sess):
    """集赞墙"""
    print("\n--- 集赞墙 ---")
    detail = get_task_detail(sess, "COLLECT_LIKE")
    if not detail:
        print("  获取集赞信息失败")
        return

    brief = detail.get("brief", {})
    status = brief.get("status", "")
    title = brief.get("title", {}).get("cn", "")
    reward = brief.get("reward", {}).get("value", "?")
    info = detail.get("detail", {})
    total = info.get("total", 0)
    done = info.get("complete", 0)

    print(f"  {title} | {done}/{total} | 奖励: {reward}积分")
    if status == "Done":
        print("  已完成")
    else:
        print(f"  未完成, 还需 {total - done} 个赞 (需App操作)")


def do_tasks_by_view(sess, auth, label, view_key):
    """按 view_type 处理任务"""
    print(f"\n--- {label} ---")
    tasks, ext = get_task_list(sess, auth, include_view_types=[view_key])
    if not tasks:
        print("  无任务")
        return 0

    residual = ext.get("todayResidualScore", "?")
    print(f"  今日剩余可获积分: {residual}")

    claimed = 0
    confirmed = 0

    for task in tasks:
        status = task.get("status", "")
        title = task.get("title", {}).get("cn", "未知")
        spe = task.get("taskSpeType", "")
        pts = task.get("reward", {}).get("value", "?")
        button = task.get("button", {})
        op = button.get("operation", {})
        route = op.get("route", {})
        op_type = route.get("type", "")

        print(f"  [{status}] {title} ({pts}分) [{spe}]")

        if status == "Init" and op_type == "claim":
            claim_task(sess, spe)
            time.sleep(0.5)
            claimed += 1
        elif status == "NeedConfirm" and op_type == "confirm":
            token = task.get("token", "")
            confirm_task(sess, spe, token)
            time.sleep(0.5)
            confirmed += 1
        elif status == "Done":
            pass  # 已完成不打印
        elif status == "Todo":
            print(f"    (需App内操作, 无法自动完成)")

    print(f"  本类完成: 领取{claimed} 确认{confirmed}")
    return claimed + confirmed


def do_watch_ad(sess, auth):
    """观看广告 (每日3次)"""
    print("\n--- 观看广告 ---")
    tasks, _ = get_task_list(sess, auth, entry="TaskCenter", limit=1)
    found = False
    for task in tasks:
        if task.get("taskSpeType") == "reward_ad#1":
            found = True
            sub = task.get("subtitle", {}).get("cn", "")
            print(f"  {sub}")
            for i in range(3):
                print(f"  第{i+1}/3次:", end=" ")
                claim_task(sess, "reward_ad#1")
                time.sleep(1)
            break
    if not found:
        print("  未找到广告任务")


def do_gift_list(sess):
    """礼品列表"""
    print("\n--- 可兑换礼品 ---")
    result = api_call(sess, "GET", GIFT_LIST_URL, params={"limit": "20", "offset": ""})
    if result and result.get("code") == 200:
        gifts = result.get("result", [])
        if not gifts:
            print("  无礼品")
            return
        for g in gifts:
            name = g.get("name", {}).get("cn", "")
            score = g.get("score", 0)
            gid = g.get("giftId", "")
            print(f"  [{gid}] {name} - {score}积分")
    else:
        print("  获取失败")


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════

def run(auth):
    """执行全部任务"""
    sess = build_session(auth)

    # 先用积分接口验证认证是否有效
    print("\n[验证] 测试认证信息...")
    test = api_call(sess, "GET", SCORE_URL)
    if test is None:
        print("\n[致命错误] 认证信息无效或网络不通, 脚本退出")
        sys.exit(1)
    if test.get("code") != 200:
        print(f"\n[致命错误] 接口返回异常: code={test.get('code')}, desc={test.get('desc')}")
        print("请检查环境变量是否正确, mastersess/masterfp 是否过期")
        sys.exit(1)
    print("[验证] 认证有效")

    score_before = get_score(sess)

    # 签到
    do_sign_in(sess)

    # 集赞墙
    do_collect_like(sess)

    # 各类任务
    total_done = 0
    total_done += do_tasks_by_view(sess, auth, "互动任务", "interaction")
    total_done += do_tasks_by_view(sess, auth, "新用户功能体验", "onboarding")
    total_done += do_tasks_by_view(sess, auth, "AI功能体验", "ai_onboarding")
    total_done += do_tasks_by_view(sess, auth, "外贸功能体验", "industry_onboarding")
    total_done += do_tasks_by_view(sess, auth, "会员功能体验", "member_onboarding")
    total_done += do_tasks_by_view(sess, auth, "推荐设置", "setting")
    total_done += do_tasks_by_view(sess, auth, "每日任务", "daily")
    total_done += do_tasks_by_view(sess, auth, "产品合作", "cooperation")
    total_done += do_tasks_by_view(sess, auth, "会员任务", "open_member")

    # 广告
    do_watch_ad(sess, auth)

    # 最终积分
    score_after = get_score(sess)

    # 礼品
    do_gift_list(sess)

    # 总结
    print("\n" + "=" * 50)
    print("执行完毕")
    if score_before is not None and score_after is not None:
        earned = score_after - score_before
        print(f"  本次获得: {earned}积分")
        print(f"  当前总计: {score_after}积分")
    print("=" * 50)


def main():
    print("=" * 50)
    print("  网易邮箱大师 - 自动签到 & 任务完成")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    # 1. 加载并校验配置 (缺失必填项会 sys.exit(1))
    auth = load_config()

    print(f"\n[配置] 邮箱: {auth['email_list']}")
    print(f"[配置] Token数量: {len(auth['token_list'])}")

    # 2. 执行
    run(auth)


if __name__ == "__main__":
    main()
