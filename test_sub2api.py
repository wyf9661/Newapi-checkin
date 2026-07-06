#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sub2API 签到测试脚本
"""

import sys
from checkin import Sub2APICheckin


def test_sub2api_checkin(base_url: str, auth_token: str, refresh_token: str = '', checkin_api: str = 'auto'):
    print('=' * 50)
    print('Sub2API 签到测试')
    print('=' * 50)
    print(f'站点: {base_url}')
    print(f'Access Token 长度: {len(auth_token)} 字符')
    print(f'签到 API: {checkin_api}')
    print()

    client = Sub2APICheckin(base_url, auth_token, refresh_token, checkin_api)

    print('[1/3] 测试获取用户信息...')
    user_info = client.get_user_info()
    if user_info:
        print('✅ 成功')
        print(f'  用户名: {user_info.get("username")}')
        print(f'  用户ID: {user_info.get("id")}')
        print(f'  余额: {user_info.get("balance")}')
    else:
        print('⚠️  获取失败，将继续探测签到接口')

    print('\n[2/3] 探测签到接口...')
    api_name, status = client.detect_checkin_api()
    if not api_name:
        print(f'❌ {status.get("error") if isinstance(status, dict) else status}')
        return False
    print(f'✅ 命中: {api_name}')

    print('\n[3/3] 测试签到...')
    result = client.checkin()
    if result['success']:
        print(f'✅ {result["message"]}')
        if result.get('checkin_date'):
            print(f'  日期: {result["checkin_date"]}')
        if result.get('quota_awarded') is not None:
            print(f'  奖励: {result["quota_awarded"]}')
        if result.get('checkin_count'):
            print(f'  本月签到: {result["checkin_count"]} 天')
        if result.get('total_quota'):
            print(f'  累计奖励: {result["total_quota"]}')
        return True

    print(f'❌ {result["message"]}')
    return False


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('使用方法：')
        print('  python test_sub2api.py <BASE_URL> <AUTH_TOKEN> [REFRESH_TOKEN] [--api auto|v1|extension]')
        print('')
        print('示例：')
        print('  python test_sub2api.py https://example.com eyJ... rt_xxx')
        sys.exit(1)

    base_url = sys.argv[1]
    auth_token = sys.argv[2]
    refresh_token = ''
    checkin_api = 'auto'

    i = 3
    while i < len(sys.argv):
        if sys.argv[i] == '--api' and i + 1 < len(sys.argv):
            checkin_api = sys.argv[i + 1]
            i += 2
        else:
            refresh_token = sys.argv[i]
            i += 1

    success = test_sub2api_checkin(base_url, auth_token, refresh_token, checkin_api)
    sys.exit(0 if success else 1)
