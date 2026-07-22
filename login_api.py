#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网易邮箱大师 - 登录API模块
==========================
实现手机号 + 短信验证码登录，自动提取所有配置。

核心流程:
  1. 发送短信验证码 → 用户输入验证码
  2. 验证码登录 → 获取 mastersess / masterfp / M_INFO
  3. 调用任务列表API → 自动提取 tokenList / emailList
  4. 组装 MASTER_COOKIE → 返回完整配置

API端点说明:
  - 端点需要从 MailMaster App 登录抓包中获取
  - 以下默认使用网易通行证 Web 登录接口
  - 若端点不对，请根据抓包结果通过环境变量覆盖:
    MASTER_SEND_SMS_URL    发送验证码端点
    MASTER_VERIFY_LOGIN_URL  验证码登录端点
    MASTER_LOGIN_PRODUCT   登录产品标识 (默认: mailmaster)
"""

import base64
import json
import os
import time
import uuid
from typing import Dict, Optional, Tuple

import certifi
import requests


# ==================== 登录API端点 ====================
# 发送短信验证码（需从抓包确认）
SEND_SMS_URL = os.environ.get(
    "MASTER_SEND_SMS_URL",
    "https://reg.163.com/interfaces/yd/getSmsCode.do"
)

# 验证码登录（需从抓包确认）
VERIFY_LOGIN_URL = os.environ.get(
    "MASTER_VERIFY_LOGIN_URL",
    "https://reg.163.com/interfaces/yd/web/login.do"
)

# 登录产品标识
LOGIN_PRODUCT = os.environ.get("MASTER_LOGIN_PRODUCT", "mailmaster")

# 登录后获取大师号信息的端点（需从抓包确认）
MASTER_INFO_URL = os.environ.get(
    "MASTER_INFO_URL",
    "https://appconf.mail.163.com/mailmaster/api/user/info.do"
)

# 任务中心（用于获取 tokenList / emailList）
TASK_CENTER_URL = "https://dashi.163.com/task-center-api/fapi/task/list"


# ==================== HTTP 会话 ====================

def _create_session() -> requests.Session:
    s = requests.Session()
    s.verify = certifi.where()
    s.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) '
            'AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 '
            'Safari/603.2.4 MailMaster/7.25.17.2266'
        ),
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh-Hans;q=0.9',
        'Content-Type': 'application/x-www-form-urlencoded',
    })
    return s


# ==================== 登录流程 ====================

def send_sms_code(phone: str) -> Dict:
    """
    发送短信验证码
    返回: {"ok": True/False, "msg": "..."}
    """
    session = _create_session()
    try:
        # 方式1: 网易通行证 Web 登录
        params = {
            "mobile": phone,
            "product": LOGIN_PRODUCT,
            "type": "login",
        }
        r = session.get(SEND_SMS_URL, params=params, timeout=15)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}

        # 尝试解析多种响应格式
        code = data.get("code") if isinstance(data, dict) else None
        if code is None:
            # 可能返回的是文本
            try:
                text = r.text
                if "200" in str(code) or "success" in text.lower() or "true" in text.lower():
                    return {"ok": True, "msg": "验证码已发送"}
            except Exception:
                pass

        if code == 200 or code == "200":
            return {"ok": True, "msg": "验证码已发送"}
        elif code == 460 or code == "460":
            return {"ok": False, "msg": "发送过于频繁，请稍后再试"}
        else:
            msg = data.get("msg", data.get("desc", r.text[:200]))
            return {"ok": False, "msg": f"发送失败: {msg}", "raw": data}

    except requests.exceptions.Timeout:
        return {"ok": False, "msg": "请求超时，请检查网络"}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "msg": "连接失败，请检查端点配置"}
    except Exception as e:
        return {"ok": False, "msg": f"发送异常: {e}"}


def verify_login(phone: str, sms_code: str) -> Dict:
    """
    验证码登录，获取 mastersess / masterfp / M_INFO
    返回: {"ok": True/False, "msg": "...", "mastersess": "...", "masterfp": "...", "m_info": "..."}
    """
    session = _create_session()
    try:
        # 方式1: 网易通行证 Web 登录
        params = {
            "mobile": phone,
            "smsCode": sms_code,
            "product": LOGIN_PRODUCT,
        }
        r = session.post(VERIFY_LOGIN_URL, data=params, timeout=15)

        # 尝试解析响应
        data = {}
        try:
            data = r.json()
        except Exception:
            pass

        code = data.get("code") if isinstance(data, dict) else None

        if code == 200 or code == "200":
            # ---- 从响应中提取 mastersess / masterfp / M_INFO ----
            mastersess = ""
            masterfp = ""
            m_info = ""

            # 1. 从响应 JSON 提取
            result = data.get("result", data.get("data", {}))
            if isinstance(result, dict):
                mastersess = result.get("mastersess", result.get("masterSess", result.get("session", "")))
                masterfp = result.get("masterfp", result.get("masterFp", result.get("fingerprint", "")))
                m_info = result.get("mInfo", result.get("M_INFO", result.get("deviceId", "")))

            # 2. 从响应 Cookie 提取
            if not mastersess:
                for cookie in session.cookies:
                    if cookie.name.lower() in ("mastersess", "ntes_yd_sess", "master_sess"):
                        mastersess = cookie.value
                    if cookie.name.lower() in ("masterfp", "master_fp", "device_fp"):
                        masterfp = cookie.value
                    if cookie.name.lower() in ("m_info", "device_id"):
                        m_info = cookie.value

            # 3. 从响应头提取
            if not mastersess:
                mastersess = r.headers.get("mastersess", r.headers.get("MasterSess", ""))
            if not masterfp:
                masterfp = r.headers.get("masterfp", r.headers.get("MasterFp", ""))

            # 4. 生成 M_INFO（如果未获取到）
            if not m_info:
                did = str(uuid.uuid4()).upper()
                m_info = base64.b64encode(
                    json.dumps({"did": did}).encode()
                ).decode()

            if mastersess:
                return {
                    "ok": True,
                    "msg": "登录成功",
                    "mastersess": mastersess,
                    "masterfp": masterfp,
                    "m_info": m_info,
                    "phone": phone,
                }
            else:
                # 登录成功但未提取到 mastersess，返回原始数据供调试
                return {
                    "ok": True,
                    "msg": "登录成功但未提取到 mastersess，请检查端点配置",
                    "mastersess": "",
                    "masterfp": "",
                    "m_info": m_info,
                    "phone": phone,
                    "raw": data,
                    "cookies": {c.name: c.value for c in session.cookies},
                    "headers": dict(r.headers),
                }

        elif code == 461 or code == "461":
            return {"ok": False, "msg": "验证码错误"}
        elif code == 462 or code == "462":
            return {"ok": False, "msg": "验证码已过期"}
        else:
            msg = data.get("msg", data.get("desc", ""))
            return {
                "ok": False,
                "msg": f"登录失败: {msg or '未知错误'}",
                "raw": data,
            }

    except requests.exceptions.Timeout:
        return {"ok": False, "msg": "请求超时，请检查网络"}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "msg": "连接失败，请检查端点配置"}
    except Exception as e:
        return {"ok": False, "msg": f"登录异常: {e}"}


def extract_task_config(mastersess: str, masterfp: str, m_info: str = "") -> Dict:
    """
    登录成功后，调用任务列表API自动提取 tokenList / emailList
    返回: {"ok": True/False, "tokens": [...], "emails": [...], "master_cookie": "..."}
    """
    session = requests.Session()
    session.verify = certifi.where()
    session.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) '
            'AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 '
            'Safari/603.2.4 MailMaster/7.25.17.2266'
        ),
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh-Hans;q=0.9',
        'Content-Type': 'application/json',
        'Origin': 'masterweb://static.dashi.163.com',
        'mastersess': mastersess,
        'masterfp': masterfp,
        'Cookie': f'M_INFO={m_info}' if m_info else '',
    })

    try:
        # 调用任务列表 API 获取 emailList 和 tokenList
        body = {
            "entry": "ScoreCenter",
            "env": {
                "emailList": [],
                "installedApps": ["xhs"],
                "widgetStatus": False,
                "tokenList": [],
                "calendarGranted": False,
                "industryTag": "",
                "systemNotiSwitchStatus": True,
            },
        }
        r = session.post(TASK_CENTER_URL, json=body, timeout=15)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}

        if data.get("code") == 200:
            # 从响应中提取 emailList 和 tokenList
            env = data.get("result", {}).get("env", {})
            token_list = env.get("tokenList", [])
            email_list = env.get("emailList", [])

            if not email_list:
                # 尝试从其他字段提取
                task_ext = data.get("result", {}).get("taskExtendInfo", {})
                email_list = task_ext.get("emailList", [])
                token_list = task_ext.get("tokenList", token_list)

            if email_list or token_list:
                tokens_str = "&".join(token_list) if token_list else ""
                emails_str = "&".join(email_list) if email_list else ""

                master_cookie = f"{mastersess}:::{masterfp}:::{m_info}:::{tokens_str}:::{emails_str}"

                return {
                    "ok": True,
                    "tokens": token_list,
                    "emails": email_list,
                    "master_cookie": master_cookie,
                    "mastersess": mastersess,
                    "masterfp": masterfp,
                    "m_info": m_info,
                }
            else:
                return {
                    "ok": False,
                    "msg": "未获取到邮箱列表，请确认大师号已绑定邮箱",
                    "raw": data,
                }
        else:
            return {
                "ok": False,
                "msg": f"认证失败: {data.get('desc', '未知错误')}",
                "code": data.get("code"),
            }

    except Exception as e:
        return {"ok": False, "msg": f"提取配置异常: {e}"}


def full_login(phone: str, sms_code: str) -> Dict:
    """
    完整登录流程: 验证码登录 → 自动提取配置
    返回: {"ok": True/False, "master_cookie": "...", "emails": [...], ...}
    """
    # Step 1: 验证码登录
    login_result = verify_login(phone, sms_code)
    if not login_result.get("ok"):
        return login_result

    mastersess = login_result.get("mastersess", "")
    masterfp = login_result.get("masterfp", "")
    m_info = login_result.get("m_info", "")

    if not mastersess:
        # 登录成功但未获取到 mastersess
        return {
            "ok": False,
            "msg": "登录成功但未提取到 mastersess。请检查:\n"
                   "1. 端点配置是否正确（MASTER_VERIFY_LOGIN_URL）\n"
                   "2. 响应格式是否匹配\n"
                   "3. 建议抓包登录流程后更新端点",
            "debug": login_result,
        }

    # Step 2: 提取任务配置
    time.sleep(1)
    config_result = extract_task_config(mastersess, masterfp, m_info)

    if config_result.get("ok"):
        return {
            "ok": True,
            "msg": "登录成功，配置已自动获取",
            "master_cookie": config_result["master_cookie"],
            "mastersess": mastersess,
            "masterfp": masterfp,
            "m_info": m_info,
            "tokens": config_result.get("tokens", []),
            "emails": config_result.get("emails", []),
            "phone": phone,
        }
    else:
        # 提取配置失败，但登录成功，返回基础信息
        tokens_str = ""
        emails_str = ""
        master_cookie = f"{mastersess}:::{masterfp}:::{m_info}:::{tokens_str}:::{emails_str}"
        return {
            "ok": True,
            "msg": f"登录成功，但自动提取配置失败: {config_result.get('msg', '')}",
            "master_cookie": master_cookie,
            "mastersess": mastersess,
            "masterfp": masterfp,
            "m_info": m_info,
            "tokens": [],
            "emails": [],
            "phone": phone,
            "extract_error": config_result.get("msg", ""),
        }


# ==================== 配置验证 ====================

def validate_config(master_cookie: str) -> bool:
    """验证 MASTER_COOKIE 是否有效"""
    if not master_cookie or ":::" not in master_cookie:
        return False

    parts = master_cookie.split(":::")
    if len(parts) < 5:
        return False

    mastersess = parts[0].strip()
    if not mastersess:
        return False

    # 尝试调用积分 API 验证
    session = requests.Session()
    session.verify = certifi.where()
    session.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) '
            'AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 '
            'Safari/603.2.4 MailMaster/7.25.17.2266'
        ),
        'Accept': 'application/json, text/plain, */*',
        'mastersess': mastersess,
        'masterfp': parts[1].strip() if len(parts) > 1 else "",
        'Cookie': f'M_INFO={parts[2].strip()}' if len(parts) > 2 and parts[2].strip() else "",
    })

    try:
        r = session.get("https://dashi.163.com/mailsrv-score/fapi/score", timeout=10)
        data = r.json()
        return data.get("code") == 200
    except Exception:
        return False
