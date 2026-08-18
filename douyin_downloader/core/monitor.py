#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
主页监控：水位过滤与单页作品拉取
"""
import time
from urllib.parse import quote, urlencode

import requests

from douyin_downloader.constants import USER_AGENT, MONITOR_CHECK_COUNT
from douyin_downloader.core.abogus import ABogus
from douyin_downloader.core.api import (
    extract_sec_user_id_from_url,
    build_aweme_post_url,
    api_request_with_retry,
)


def compute_watermark(awemes):
    """
    根据作品列表计算水位线。
    返回 (monitor_since, monitor_seen_ids)
    无作品时 since=当前时间，seen=[]。
    """
    if not awemes:
        return int(time.time()), []
    max_ct = 0
    for a in awemes:
        try:
            ct = int(a.get('create_time') or 0)
        except (TypeError, ValueError):
            ct = 0
        if ct > max_ct:
            max_ct = ct
    if max_ct <= 0:
        return int(time.time()), []
    seen_ids = []
    for a in awemes:
        try:
            ct = int(a.get('create_time') or 0)
        except (TypeError, ValueError):
            ct = 0
        if ct == max_ct:
            aid = str(a.get('aweme_id') or '')
            if aid and aid not in seen_ids:
                seen_ids.append(aid)
    return max_ct, seen_ids


def filter_new_awemes(awemes, monitor_since, seen_ids=None):
    """
    筛出新于水位线的作品。
    create_time > since，或 create_time == since 且 aweme_id 不在 seen_ids。
    结果按 create_time 升序（先旧后新）。
    """
    since = int(monitor_since or 0)
    seen = set(str(x) for x in (seen_ids or []) if x)
    new_list = []
    for a in awemes or []:
        try:
            ct = int(a.get('create_time') or 0)
        except (TypeError, ValueError):
            ct = 0
        aid = str(a.get('aweme_id') or '')
        if ct > since:
            new_list.append(a)
        elif ct == since and aid and aid not in seen:
            new_list.append(a)
    new_list.sort(key=lambda x: int(x.get('create_time') or 0))
    return new_list


def advance_watermark(monitor_since, seen_ids, awemes):
    """用一批作品推进水位，返回新的 (since, seen_ids)"""
    if not awemes:
        return int(monitor_since or 0), list(seen_ids or [])
    page_since, page_seen = compute_watermark(awemes)
    cur_since = int(monitor_since or 0)
    if page_since > cur_since:
        return page_since, page_seen
    if page_since == cur_since:
        merged = list(seen_ids or [])
        for aid in page_seen:
            if aid not in merged:
                merged.append(aid)
        return cur_since, merged
    return cur_since, list(seen_ids or [])


def fetch_user_aweme_page(sec_user_id, cookie, count=None):
    """
    拉取用户主页第一页作品。
    返回 (aweme_list, error_msg)；成功时 error_msg 为 None。
    """
    if not cookie:
        return [], '未配置 Cookie'
    sec = sec_user_id or ''
    if not sec:
        return [], '缺少 sec_user_id'
    if count is None:
        count = MONITOR_CHECK_COUNT

    session = requests.Session()
    session.headers.update({
        'User-Agent': USER_AGENT,
        'Cookie': cookie,
        'Referer': f'https://www.douyin.com/user/{sec}',
    })
    try:
        abogus = ABogus()
        params, base_url = build_aweme_post_url(sec, 0, count, True)
        a_bogus = quote(abogus.get_value(params), safe='')
        params['a_bogus'] = a_bogus
        req_url = base_url + '?' + urlencode(params)
        r = api_request_with_retry(session, req_url, max_retries=1)
        data = r.json()
        aweme_list = data.get('aweme_list', []) or []
        return aweme_list, None
    except Exception as e:
        return [], str(e)


def resolve_user_sec(user):
    """从用户条目解析 sec_user_id"""
    sec = (user or {}).get('sec_user_id') or ''
    if sec:
        return sec
    return extract_sec_user_id_from_url((user or {}).get('url', '') or '') or ''
