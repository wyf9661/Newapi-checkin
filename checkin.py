#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NewAPI 自动签到脚本
支持多账号签到，通过 GitHub Actions 定时执行
"""

import os
import sys
import json
import base64
import requests
from datetime import datetime
from typing import Optional

try:
    from cf_bypass import detect_cloudflare_block, CloudflareBypasser
    CF_BYPASS_AVAILABLE = True
except ImportError:
    CF_BYPASS_AVAILABLE = False
    detect_cloudflare_block = None
    CloudflareBypasser = None

try:
    from dingtalk_notifier import send_checkin_notification
except ImportError:
    send_checkin_notification = None


class NewAPICheckin:
    """NewAPI 签到类"""

    @staticmethod
    def _mask_url(url: str) -> str:
        """
        脱敏 URL，隐藏域名细节
        例如: https://api.example.com -> https://api.***.**
        """
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain_parts = parsed.netloc.split('.')
            if len(domain_parts) >= 2:
                # 保留第一部分和最后一部分，中间用 *** 代替
                masked_domain = f"{domain_parts[0]}.***." + '.'.join(domain_parts[-1:])
            else:
                masked_domain = '***'
            return f"{parsed.scheme}://{masked_domain}"
        except Exception:
            return 'https://***'

    @staticmethod
    def _mask_user_id(user_id: str) -> str:
        """
        脱敏用户ID
        例如: 1429 -> ****
        """
        return '****'

    def __init__(self, base_url: str, session_cookie: str, user_id: str = None, cf_clearance: str = None):
        self.base_url = base_url.rstrip('/')
        self.session_cookie = session_cookie
        self.original_cf_clearance = cf_clearance
        self.cf_bypassed = False
        self.session = requests.Session()
        self.session.cookies.set('session', session_cookie)

        if cf_clearance:
            self.session.cookies.set('cf_clearance', cf_clearance)

        self.session.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Cache-Control': 'no-store',
            'Pragma': 'no-cache',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        })

        if user_id:
            self.user_id = user_id
            self.session.headers.update({'new-api-user': str(user_id)})
        else:
            self.user_id = self._extract_user_id_from_session(session_cookie)
            if self.user_id:
                self.session.headers.update({'new-api-user': str(self.user_id)})

    def _extract_user_id_from_session(self, session_cookie: str) -> Optional[str]:
        """
        从 Session Cookie 中提取用户ID

        Session Cookie 格式通常是 Base64 编码的数据
        """
        try:
            # 尝试解码 Session Cookie
            # Session 格式类似：MTc2NzQxMzYzM3xE...
            # 解码后可能包含用户信息
            decoded = base64.b64decode(session_cookie + '==')  # 添加 padding
            decoded_str = decoded.decode('utf-8', errors='ignore')

            # 查找可能的用户ID模式
            # 例如：linuxdo_988 中的 988
            import re
            # 查找 "linuxdo_数字" 或 "id"=数字 等模式
            patterns = [
                r'linuxdo[_-](\d+)',  # linuxdo_988
                r'"id"[:\s]+(\d+)',    # "id": 988
                r'user[_-](\d+)',      # user_988
                r'userid[:\s]+(\d+)',  # userid: 988
            ]

            for pattern in patterns:
                match = re.search(pattern, decoded_str, re.IGNORECASE)
                if match:
                    return match.group(1)

        except Exception:
            pass

        return None

    def get_user_info(self, verbose: bool = False) -> Optional[dict]:
        """
        获取用户信息

        自动设置 new-api-user 请求头

        Args:
            verbose: 是否显示详细调试信息
        """
        try:
            resp = self.session.get(f'{self.base_url}/api/user/self', timeout=30)

            if verbose:
                print(f'  [调试] HTTP 状态码: {resp.status_code}')
                print(f'  [调试] 响应内容预览: {resp.text[:200]}...')

            # 检查认证失败
            if resp.status_code == 401:
                print(f'[错误] 认证失败 (401): Session 可能已过期')
                if verbose:
                    print(f'  [调试] 完整响应: {resp.text[:500]}')
                return None

            # 尝试解析 JSON
            try:
                data = resp.json()
            except json.JSONDecodeError as e:
                # 检测是否是 Cloudflare 拦截
                if detect_cloudflare_block:
                    is_blocked, reason = detect_cloudflare_block(resp.status_code, resp.text)
                    if is_blocked:
                        print(f'[CF] 获取用户信息时检测到 Cloudflare 拦截: {reason}')
                        print(f'[CF] 该站点需要 CF 绕过才能访问')
                        return None
                print(f'[错误] 响应格式错误 (HTTP {resp.status_code}): 无法解析 JSON')
                if verbose:
                    print(f'  [调试] 原始响应: {resp.text[:500]}')
                return None

            if verbose:
                print(f'  [调试] success 字段: {data.get("success")}')
                print(f'  [调试] message 字段: {data.get("message")}')

            if resp.status_code == 200:
                if data.get('success'):
                    user_data = data.get('data')
                    # 保存用户ID并设置到请求头
                    if user_data and 'id' in user_data:
                        self.user_id = user_data['id']
                        self.session.headers.update({
                            'new-api-user': str(self.user_id)
                        })
                    return user_data
                else:
                    if verbose:
                        print(f'  [调试] API 返回失败: {data.get("message", "未知错误")}')
            else:
                print(f'[错误] HTTP {resp.status_code}: {data.get("message", "未知错误")}')

            return None

        except requests.exceptions.Timeout:
            print(f'[错误] 请求超时')
            return None
        except requests.exceptions.RequestException as e:
            print(f'[错误] 网络请求失败: {e}')
            return None
        except Exception as e:
            print(f'[错误] 未知错误: {e}')
            if verbose:
                import traceback
                traceback.print_exc()
            return None

    def checkin(self) -> dict:
        """
        执行签到

        流程（借鉴 Chrome 扩展 background.js:115-248）：
        1. requests 直连签到（快速模式）
        2. CF 拦截检测 → Playwright 获取 cookie 后重新签到
        3. 仍然失败 → Playwright 浏览器内直接签到（终极回退）

        Returns:
            签到结果字典
        """
        result = {
            'success': False,
            'message': '',
            'checkin_date': None,
            'quota_awarded': None,
            'already_checked': False
        }

        try:
            resp = self.session.post(f'{self.base_url}/api/user/checkin', timeout=30)

            if resp.status_code == 401:
                result['message'] = '认证失败: Session 可能已过期，请重新获取'
                return result

            try:
                data = resp.json()
            except json.JSONDecodeError:
                if detect_cloudflare_block:
                    is_blocked, reason = detect_cloudflare_block(resp.status_code, resp.text)
                    if is_blocked:
                        print(f'[CF] 检测到 Cloudflare 拦截: {reason}')
                        return self._cf_bypass_checkin()
                content_preview = resp.text[:200] if resp.text else '(空响应)'
                result['message'] = f'响应格式错误 (HTTP {resp.status_code}): {content_preview}'
                return result

            if detect_cloudflare_block and resp.status_code in (403, 503):
                is_blocked, reason = detect_cloudflare_block(resp.status_code, json.dumps(data))
                if is_blocked:
                    print(f'[CF] 检测到 Cloudflare 拦截: {reason}')
                    return self._cf_bypass_checkin()

            if resp.status_code == 200:
                if data.get('success'):
                    result['success'] = True
                    result['message'] = data.get('message', '签到成功')
                    result['already_checked'] = False

                    checkin_data = data.get('data', {})
                    result['checkin_date'] = checkin_data.get('checkin_date')
                    result['quota_awarded'] = checkin_data.get('quota_awarded')
                else:
                    message = data.get('message', '签到失败')
                    already_keywords = ['已签到', '已经签到', '今日已签', 'already', '重复签到']
                    if any(keyword in str(message) for keyword in already_keywords):
                        result['success'] = True
                        result['message'] = message
                        result['already_checked'] = True
                    else:
                        result['message'] = message
            else:
                result['message'] = f'HTTP {resp.status_code}: {data.get("message", "未知错误")}'

        except requests.exceptions.Timeout:
            result['message'] = '请求超时'
        except requests.exceptions.RequestException as e:
            result['message'] = f'网络请求失败: {e}'
        except Exception as e:
            result['message'] = f'未知错误: {e}'

        return result

    def _cf_bypass_checkin(self) -> dict:
        """
        CF 绕过签到流程

        在同一个 Playwright 会话中完成 CF 绕过 + 签到，
        不拆分 cookie 提取和 requests 重试（因为 cf_clearance 绑定浏览器指纹）
        """
        result = {
            'success': False,
            'message': '',
            'checkin_date': None,
            'quota_awarded': None,
            'already_checked': False
        }

        if not CF_BYPASS_AVAILABLE or not CloudflareBypasser:
            result['message'] = 'Cloudflare 拦截: 需安装 Playwright 才能自动绕过 (pip install playwright && playwright install chromium)'
            return result

        bypasser = CloudflareBypasser(self.base_url, self.session_cookie, self.user_id)

        if not bypasser.is_available():
            result['message'] = 'Cloudflare 拦截: Playwright 未正确安装'
            return result

        print('[CF] 开始 Playwright 绕过流程...')
        browser_result = bypasser.bypass_and_checkin()

        if not browser_result:
            result['message'] = 'Cloudflare 绕过失败: 无法通过 CF 验证'
            return result

        self.cf_bypassed = True

        if browser_result.get('error'):
            result['message'] = f'CF 绕过后签到失败: {browser_result["error"]}'
            return result

        if browser_result.get('alreadyCheckedIn'):
            result['success'] = True
            result['message'] = browser_result.get('message', '今日已签到 (CF绕过)')
            result['already_checked'] = True
        elif browser_result.get('success'):
            result['success'] = True
            result['message'] = browser_result.get('message', '签到成功 (CF绕过)')
            result['already_checked'] = False
            data = browser_result.get('data', {})
            if isinstance(data, dict):
                checkin_data = data.get('data', data)
                result['checkin_date'] = checkin_data.get('checkin_date')
                result['quota_awarded'] = checkin_data.get('quota_awarded')
        else:
            result['message'] = browser_result.get('message', 'CF 绕过后签到失败')

        return result

    def get_checkin_history(self, month: str = None) -> Optional[dict]:
        """
        获取签到历史

        Args:
            month: 月份，格式 YYYY-MM，默认当前月
        """
        if month is None:
            month = datetime.now().strftime('%Y-%m')

        try:
            resp = self.session.get(
                f'{self.base_url}/api/user/checkin',
                params={'month': month},
                timeout=30
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get('success'):
                    return data.get('data')
            return None
        except Exception as e:
            print(f'[错误] 获取签到历史失败: {e}')
            return None



class Sub2APICheckin:
    """Sub2API 签到类（自动探测不同站点的签到 API 实现）"""

    def __init__(self, base_url: str, auth_token: str, refresh_token: str = None, checkin_api: str = 'auto'):
        self.base_url = base_url.rstrip('/')
        self.auth_token = auth_token
        self.refresh_token = refresh_token
        self.checkin_api = checkin_api or 'auto'
        self.session = requests.Session()
        self.device_fingerprint = self._device_fingerprint(auth_token)
        self.session.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Authorization': f'Bearer {auth_token}',
        })

    @staticmethod
    def _device_fingerprint(seed: str) -> str:
        import hashlib
        return hashlib.sha256((seed or 'sub2api-checkin').encode('utf-8')).hexdigest()

    def _request(self, method: str, path: str, *, json_body=None, extra_headers=None, retry_auth=True):
        import uuid
        headers = {
            'X-Request-Id': str(uuid.uuid4()),
        }
        if method.upper() != 'GET':
            headers.update({
                'Idempotency-Key': str(uuid.uuid4()),
                'X-Requested-With': 'XMLHttpRequest',
                'X-Device-Fingerprint': self.device_fingerprint,
                'Origin': self.base_url,
                'Referer': f'{self.base_url}/extensions/checkin/index.html',
            })
        if extra_headers:
            headers.update(extra_headers)

        resp = self.session.request(method, f'{self.base_url}{path}', headers=headers, json=json_body, timeout=30)
        if resp.status_code == 401 and retry_auth and self.refresh_token and self._refresh_token():
            return self._request(method, path, json_body=json_body, extra_headers=extra_headers, retry_auth=False)
        return resp

    def _refresh_token(self) -> bool:
        try:
            resp = self.session.post(
                f'{self.base_url}/api/v1/auth/refresh',
                json={'refresh_token': self.refresh_token},
                timeout=30,
            )
            if resp.status_code != 200:
                return False
            data = resp.json()
            payload = data.get('data') if data.get('code') == 0 else data
            if not isinstance(payload, dict) or not payload.get('access_token'):
                return False
            self.auth_token = payload['access_token']
            self.session.headers.update({'Authorization': f'Bearer {self.auth_token}'})
            if payload.get('refresh_token'):
                self.refresh_token = payload['refresh_token']
            print('  [Sub2API] access token 已刷新')
            return True
        except Exception:
            return False

    def _parse_json(self, resp):
        try:
            return resp.json()
        except json.JSONDecodeError:
            return None

    def _unwrap(self, data):
        if isinstance(data, dict) and data.get('code') == 0 and 'data' in data:
            return data.get('data')
        return data

    def detect_checkin_api(self):
        """返回 (api_name, status_data)；api_name: v1 或 extension"""
        candidates = []
        if self.checkin_api in ('auto', 'v1'):
            candidates.append(('v1', '/api/v1/check-in/status'))
        if self.checkin_api in ('auto', 'extension'):
            candidates.append(('extension', '/api/checkin-sidebar/status'))

        last_error = ''
        for api_name, path in candidates:
            resp = self._request('GET', path)
            data = self._parse_json(resp)
            if resp.status_code == 200 and data is not None:
                payload = self._unwrap(data)
                return api_name, payload
            if resp.status_code not in (404, 405):
                last_error = f'{api_name}: HTTP {resp.status_code} {resp.text[:120]}'
        return None, {'error': last_error or '未发现支持的 Sub2API 签到接口'}

    def get_user_info(self):
        try:
            resp = self._request('GET', '/api/v1/auth/me')
            data = self._parse_json(resp)
            if resp.status_code == 200 and data is not None:
                return self._unwrap(data)
            return None
        except Exception:
            return None

    def checkin(self) -> dict:
        result = {
            'success': False,
            'message': '',
            'checkin_date': None,
            'quota_awarded': None,
            'checkin_count': 0,
            'total_quota': 0,
            'already_checked': False,
        }

        api_name, status = self.detect_checkin_api()
        if not api_name:
            result['message'] = status.get('error', '未发现支持的 Sub2API 签到接口') if isinstance(status, dict) else '未发现支持的 Sub2API 签到接口'
            return result

        status_checkin = status.get('checkin', status) if isinstance(status, dict) else {}
        checked_today = bool(status_checkin.get('checked_in_today') or status_checkin.get('checkedToday') or status_checkin.get('already_checked_in'))

        if checked_today:
            result.update(self._success_from_status(api_name, status_checkin, already=True))
            return result

        if api_name == 'v1':
            resp = self._request('POST', '/api/v1/check-in', json_body={'turnstile_token': None})
        else:
            resp = self._request('POST', '/api/checkin-sidebar/checkin', json_body={})

        data = self._parse_json(resp)
        if resp.status_code != 200 or data is None:
            result['message'] = f'HTTP {resp.status_code}: {resp.text[:200]}'
            return result

        payload = self._unwrap(data)
        if isinstance(payload, dict) and payload.get('checkin'):
            status_checkin = payload['checkin']
        elif isinstance(payload, dict):
            status_checkin = payload
        else:
            result['message'] = '签到响应格式错误'
            return result

        result.update(self._success_from_status(api_name, status_checkin, already=bool(status_checkin.get('already_checked_in'))))
        return result

    def _success_from_status(self, api_name: str, data: dict, already: bool = False) -> dict:
        reward = data.get('quota_awarded')
        if reward is None:
            reward = data.get('reward_amount')
        if reward is None:
            reward = data.get('reward')
        if reward is None:
            reward = data.get('today_reward')

        checkin_date = data.get('checkin_date') or data.get('check_in_date')
        if not checkin_date and data.get('lastCheckedAt'):
            checkin_date = str(data.get('lastCheckedAt'))[:10]

        checkin_count = data.get('monthCount') or data.get('total_check_in_days') or data.get('totalCount') or 0
        total_quota = data.get('totalReward') or data.get('total_reward') or 0
        if isinstance(data.get('calendar'), dict):
            summary = data['calendar'].get('summary', {})
            checkin_count = summary.get('checkedDays', checkin_count)
            total_quota = summary.get('totalReward', total_quota)

        message = data.get('message')
        if not message:
            message = '今日已签到' if already else '签到成功'

        return {
            'success': True,
            'message': message,
            'checkin_date': checkin_date,
            'quota_awarded': None if already else reward,
            'checkin_count': checkin_count,
            'total_quota': total_quota,
            'already_checked': already,
        }

    def get_checkin_history(self):
        api_name, status = self.detect_checkin_api()
        if not api_name or not isinstance(status, dict):
            return None
        checkin = status.get('checkin', status)
        stats = {
            'checkin_count': checkin.get('monthCount') or checkin.get('total_check_in_days') or checkin.get('totalCount') or 0,
            'total_quota': checkin.get('totalReward') or checkin.get('total_reward') or 0,
            'checked_in_today': bool(checkin.get('checked_in_today') or checkin.get('checkedToday')),
        }
        if isinstance(checkin.get('calendar'), dict):
            summary = checkin['calendar'].get('summary', {})
            stats['checkin_count'] = summary.get('checkedDays', stats['checkin_count'])
            stats['total_quota'] = summary.get('totalReward', stats['total_quota'])
        return {'stats': stats}

def parse_accounts(accounts_str: str) -> list:
    """
    解析账号配置

    支持格式:
    1. 单账号: BASE_URL#SESSION_COOKIE
    2. 多账号: BASE_URL1#SESSION1,BASE_URL2#SESSION2
    3. JSON格式: [{"url": "...", "session": "..."}]
    """
    accounts = []

    if not accounts_str:
        return accounts

    # 尝试 JSON 格式
    try:
        data = json.loads(accounts_str)
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict) or 'url' not in item:
                    continue

                account_type = item.get('type', 'newapi')
                if account_type == 'sub2api' and 'auth_token' in item:
                    account = {
                        'type': 'sub2api',
                        'url': item['url'],
                        'auth_token': item['auth_token'],
                        'refresh_token': item.get('refresh_token', ''),
                        'checkin_api': item.get('checkin_api', 'auto'),
                        'name': item.get('name', '')
                    }
                    accounts.append(account)
                    continue

                if 'session' in item:
                    account = {
                        'type': account_type,
                        'url': item['url'],
                        'session': item['session'],
                        'name': item.get('name', '')
                    }
                    # 如果提供了 user_id，添加到账号信息中
                    if 'user_id' in item:
                        account['user_id'] = item['user_id']
                    # 如果提供了 cf_clearance，添加到账号信息中
                    if 'cf_clearance' in item:
                        account['cf_clearance'] = item['cf_clearance']
                    accounts.append(account)
            return accounts
    except json.JSONDecodeError:
        pass

    # 简单格式: URL#SESSION,URL#SESSION
    for part in accounts_str.split(','):
        part = part.strip()
        if '#' in part:
            url, session = part.split('#', 1)
            accounts.append({
                'type': 'newapi',
                'url': url.strip(),
                'session': session.strip(),
                'name': ''
            })

    return accounts


def load_config_from_cloud(config_url: str, config_auth: str = None) -> Optional[str]:
    """
    从云端（WebDAV）加载配置

    支持:
    - 坚果云 WebDAV
    - 群晖 NAS WebDAV
    - NextCloud WebDAV
    - 任何支持 WebDAV/直接链接的云存储

    Args:
        config_url: 配置文件 URL (WebDAV 或直接下载链接)
        config_auth: 认证信息，格式:
            - Basic Auth: "username:password"
            - Token Auth: "token:your_token"
    """
    try:
        headers = {}

        if config_auth:
            if config_auth.startswith('token:'):
                headers['Authorization'] = 'Bearer ' + config_auth[6:]
            elif ':' in config_auth:
                import base64 as b64mod
                credentials = b64mod.b64encode(config_auth.encode('utf-8')).decode('utf-8')
                headers['Authorization'] = 'Basic ' + credentials

        print(f'[云端] 正在从云端加载配置: {NewAPICheckin._mask_url(config_url)}')

        resp = requests.get(config_url, headers=headers, timeout=30)

        if resp.status_code == 401:
            print('[云端] 认证失败: 请检查 CONFIG_AUTH 配置')
            return None
        elif resp.status_code == 404:
            print('[云端] 配置文件不存在: 请先通过配置生成器保存到云端')
            return None
        elif resp.status_code != 200:
            print(f'[云端] 加载失败: HTTP {resp.status_code}')
            return None

        data = resp.json()

        if isinstance(data, list):
            accounts_str = json.dumps(data)
            print(f'[云端] 成功加载 {len(data)} 个账号配置')
            return accounts_str
        elif isinstance(data, dict) and 'accounts' in data:
            accounts = data['accounts']
            accounts_str = json.dumps(accounts)
            print(f'[云端] 成功加载 {len(accounts)} 个账号配置')

            if data.get('dingtalk'):
                dt = data['dingtalk']
                if dt.get('webhook') and not os.environ.get('DINGTALK_WEBHOOK'):
                    os.environ['DINGTALK_WEBHOOK'] = dt['webhook']
                if dt.get('secret') and not os.environ.get('DINGTALK_SECRET'):
                    os.environ['DINGTALK_SECRET'] = dt['secret']
                if dt.get('webhook'):
                    print('[云端] 已从云端加载钉钉通知配置')

            return accounts_str
        else:
            print('[云端] 配置格式错误: 无法解析账号列表')
            return None

    except json.JSONDecodeError:
        print('[云端] 配置文件不是有效的 JSON 格式')
        return None
    except requests.exceptions.Timeout:
        print('[云端] 请求超时')
        return None
    except requests.exceptions.RequestException as e:
        print(f'[云端] 网络请求失败: {e}')
        return None
    except Exception as e:
        print(f'[云端] 加载失败: {e}')
        return None


def main():
    """主函数"""
    import pytz
    beijing_tz = pytz.timezone('Asia/Shanghai')
    execution_time = datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
    print('=' * 50)
    print('NewAPI 自动签到')
    print(f'执行时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 50)

    config_url = os.environ.get('CONFIG_URL', '')
    config_auth = os.environ.get('CONFIG_AUTH', '')

    accounts_str = ''

    if config_url:
        accounts_str = load_config_from_cloud(config_url, config_auth) or ''

    if not accounts_str:
        accounts_str = os.environ.get('NEWAPI_ACCOUNTS', '')

    if not accounts_str:
        print('[错误] 未配置账号信息')
        print('请设置 CONFIG_URL（云端配置）或 NEWAPI_ACCOUNTS（本地配置）环境变量')
        sys.exit(1)

    accounts = parse_accounts(accounts_str)

    if not accounts:
        print('[错误] 账号配置解析失败')
        sys.exit(1)

    print(f'共 {len(accounts)} 个账号待签到\n')

    success_count = 0
    fail_count = 0
    checkin_results = []

    for i, account in enumerate(accounts, 1):
        url = account['url']
        account_type = account.get('type', 'newapi')
        user_id = account.get('user_id')  # 获取用户ID（如果提供）
        name = account.get('name') or f'账号{i}'

        print(f'[{i}/{len(accounts)}] {name}')
        print(f'  站点: {NewAPICheckin._mask_url(url)}')
        if user_id:
            print(f'  用户ID: {NewAPICheckin._mask_user_id(user_id)}')

        if account_type == 'sub2api':
            client = Sub2APICheckin(
                url,
                account['auth_token'],
                account.get('refresh_token'),
                account.get('checkin_api', 'auto')
            )
        else:
            session_cookie = account['session']
            cf_clearance = account.get('cf_clearance')  # 获取 CF clearance（如果提供）
            client = NewAPICheckin(url, session_cookie, user_id, cf_clearance)

        # 获取用户信息
        user_info = client.get_user_info()
        if user_info:
            username = user_info.get('username', '未知')
            # 用户名也脱敏，只显示前3个字符
            masked_username = username[:3] + '***' if len(username) > 3 else '***'
            print(f'  用户: {masked_username}')
        else:
            print('  用户: 获取失败（可能 session 已过期）')

        # 执行签到
        result = client.checkin()
        checkin_count = 0  # 默认值，避免历史接口失败时未定义

        if result['success']:
            success_count += 1
            print(f'  结果: ✅ {result["message"]}')

            # 显示签到日期
            if result['checkin_date']:
                print(f'  日期: {result["checkin_date"]}')

            # 显示获得的额度（格式化显示）
            if result['quota_awarded']:
                quota = result['quota_awarded']
                # 格式化额度显示
                if quota >= 1000000:
                    quota_str = f'{quota / 1000000:.2f}M'
                elif quota >= 1000:
                    quota_str = f'{quota / 1000:.2f}K'
                else:
                    quota_str = str(quota)
                print(f'  奖励: +{quota_str} 额度 ({quota:,} tokens)')

            # 获取本月签到统计
            history = client.get_checkin_history()
            if history and history.get('stats'):
                stats = history['stats']
                checkin_count = result.get('checkin_count') or stats.get('checkin_count', 0)
                total_quota = result.get('total_quota') or stats.get('total_quota', 0)
                if total_quota >= 1000000:
                    total_str = f'{total_quota / 1000000:.2f}M'
                elif total_quota >= 1000:
                    total_str = f'{total_quota / 1000:.2f}K'
                else:
                    total_str = str(total_quota)
                print(f'  统计: 本月已签 {checkin_count} 天，累计 {total_str} 额度')

            # 收集结果用于钉钉通知
            account_result = {
                'name': name,
                'success': True,
                'message': result['message'],
                'quota_awarded': result.get('quota_awarded'),
                'already_checked': result.get('already_checked', False),
                'checkin_count': checkin_count
            }
            checkin_results.append(account_result)
        else:
            fail_count += 1
            print(f'  结果: ❌ {result["message"]}')

            # 收集结果用于钉钉通知
            message = result.get('message', '')
            account_result = {
                'name': name,
                'success': False,
                'message': message,
                'session_expired': 'session' in message.lower() or '认证' in message
            }
            checkin_results.append(account_result)

        print()

    # 汇总
    print('=' * 50)
    print(f'签到完成: 成功 {success_count}, 失败 {fail_count}')
    print('=' * 50)
    
    # 发送钉钉通知
    if send_checkin_notification:
        print('正在发送钉钉通知...')
        send_checkin_notification(checkin_results, execution_time)
    elif os.environ.get('DINGTALK_WEBHOOK'):
        print('[警告] 已配置 DINGTALK_WEBHOOK 但无法导入通知模块')

    # 如果全部失败则返回错误码
    if fail_count == len(accounts):
        sys.exit(1)


if __name__ == '__main__':
    main()

# === DINGTALK NOTIFICATION PATCH ===
# This section was added to send DingTalk notifications
