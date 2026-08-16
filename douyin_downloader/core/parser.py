#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
作品解析与任务构建区块 （解析 Aweme → 视频/图片任务）
"""
import hashlib
from datetime import datetime
from douyin_downloader.constants import MAX_DESC_LENGTH
from douyin_downloader.utils.file_utils import get_extension_from_url

def extract_media_links_from_aweme(aweme):
    """
    从单个 aweme JSON 对象中提取媒体链接。
    
    互斥提取逻辑：
      - 如果 image 项包含 'video' 字段 -> 视为实况图（只提取实况图视频 .mp4）
      - 否则 -> 视为普通图片（提取最高分辨率 url_list[-1] .jpg/.png）
      
    返回： desc, videos[], images[], live_images[], date_str, mix_name, create_time
      create_time 为原始 Unix 时间戳（整数），用于设置文件修改时间。
    """
    videos, images, live_images = [], [], []
    aweme_id = aweme.get('aweme_id') or ''
    desc = aweme.get('desc', '') or aweme_id or 'no_desc'
    
    # 提取合集名称
    mix_name = None
    mix_info = aweme.get('mix_info', {})
    if isinstance(mix_info, dict):
        mix_name = mix_info.get('mix_name') or mix_info.get('mix_name_str') or None
    if not mix_name:
        mix_name = aweme.get('mix_name') or aweme.get('mix_name_str') or None

    # 转换时间戳 -> YYYY-MM-DD，并保留原始时间戳
    ts = aweme.get('create_time')
    date_str = ''
    create_time = 0
    if ts:
        try:
            create_time = int(ts)
            date_str = datetime.fromtimestamp(create_time).strftime("%Y-%m-%d")
        except Exception:
            pass # 时间戳转换失败

    # 自动截断过长描述
    if len(desc) > MAX_DESC_LENGTH:
        desc = desc[:MAX_DESC_LENGTH] + "......"

    # 1. 提取普通视频作品 (aweme.video)
    video_info = aweme.get('video', {})
    bit_rate_list = video_info.get('bit_rate', [])
    if bit_rate_list:
        try:
            # 选择最高码率
            best = max(bit_rate_list, key=lambda x: x.get('bit_rate', 0))
            url_list = best.get('play_addr', {}).get('url_list', [])
            if url_list:
                videos.append(url_list[0]) # 通常第一个链接最稳定
        except Exception:
            pass # 码率列表格式异常

    # 2. 提取图集作品 (aweme.images)
    if 'images' in aweme and isinstance(aweme['images'], list):
        for img in aweme['images']:
            if not isinstance(img, dict):
                continue

            # 2a. 检查是否为实况图（包含 video 字段）
            vinfo = img.get('video')
            if vinfo and isinstance(vinfo, dict) and 'bit_rate' in vinfo:
                try:
                    rates = vinfo.get('bit_rate') or []
                    if rates:
                        best = max(rates, key=lambda x: x.get('bit_rate', 0))
                        vurl_list = best.get('play_addr', {}).get('url_list', [])
                        if vurl_list:
                            live_images.append(vurl_list[0])
                    # 互斥：提取了实况图，就跳过该项的普通图片提取
                    continue
                except Exception:
                    pass # 码率列表格式异常

            # 2b. 按普通图片处理
            url_list = img.get('url_list', [])
            if url_list and isinstance(url_list, list) and url_list:
                # 默认最后一个是最高分辨率
                images.append(url_list[-1])

    return desc, videos, images, live_images, date_str, mix_name, create_time


def parse_awemes_to_works(all_awemes):
    """
    将 aweme 列表解析为作品级（work）分组数据。
    每个作品一行，聚合其视频/图片/实况图信息。

    返回: list[dict], 每个 dict 包含:
      aweme, desc, date_str, mix_name,
      work_type (视频|图集|实况图集|视频+图集),
      video_count, image_count, live_count,
      duration_ms, resolution, author_nickname,
      video_tasks, image_tasks
    """
    works = []
    for aweme in all_awemes:
        desc, videos, images, live_images, date_str, mix_name, create_time = extract_media_links_from_aweme(aweme)

        # ---- 聚合元信息 ----
        author_nickname = ''
        author = aweme.get('author')
        if isinstance(author, dict):
            author_nickname = author.get('nickname', '') or ''

        # 视频时长（毫秒）
        duration_ms = 0
        video_info = aweme.get('video', {})
        if isinstance(video_info, dict):
            duration_ms = video_info.get('duration', 0) or 0

        # 分辨率：优先取 video 顶层 width/height，其次 bit_rate 子项
        resolution = ''
        if videos and isinstance(video_info, dict):
            w = video_info.get('width', 0) or 0
            h = video_info.get('height', 0) or 0
            if w and h:
                resolution = f'{w}×{h}'
            else:
                try:
                    rates = video_info.get('bit_rate') or []
                    best_rate = max(rates, key=lambda x: x.get('bit_rate', 0)) if rates else None
                    if best_rate:
                        bw = best_rate.get('width', 0) or 0
                        bh = best_rate.get('height', 0) or 0
                        if bw and bh:
                            resolution = f'{bw}×{bh}'
                except Exception:
                    pass

        # ---- 构建子任务（与 parse_all_awemes_to_tasks 相同逻辑）----
        video_tasks = []
        for vurl in videos:
            ext = get_extension_from_url(vurl, '.mp4')
            video_tasks.append({
                'url': vurl, 'desc': desc, 'ext': ext,
                'date': date_str, 'mix_name': mix_name,
                'aweme': aweme, 'aweme_id': aweme.get('aweme_id', ''),
                'create_time': create_time,
                'url_hash': hashlib.md5(vurl.encode('utf-8')).hexdigest()[:8],
            })

        image_tasks = []
        for idx, iurl in enumerate(images, start=1):
            ext = get_extension_from_url(iurl, '.jpg')
            image_tasks.append({
                'url': iurl, 'desc': f"{desc}_p{idx}", 'ext': ext,
                'date': date_str, 'mix_name': mix_name,
                'aweme_id': aweme.get('aweme_id', ''),
                'create_time': create_time,
                'url_hash': hashlib.md5(iurl.encode('utf-8')).hexdigest()[:8],
            })
        for idx, lvurl in enumerate(live_images, start=1):
            ext = get_extension_from_url(lvurl, '.mp4')
            image_tasks.append({
                'url': lvurl, 'desc': f"{desc}_live{idx}", 'ext': ext,
                'date': date_str, 'mix_name': mix_name,
                'aweme_id': aweme.get('aweme_id', ''),
                'create_time': create_time,
                'url_hash': hashlib.md5(lvurl.encode('utf-8')).hexdigest()[:8],
            })

        # ---- 判断作品类型 ----
        has_video = len(videos) > 0
        has_image = len(images) > 0
        has_live = len(live_images) > 0

        if has_video and (has_image or has_live):
            work_type = '视频+图集'
        elif has_video:
            work_type = '视频'
        elif has_live and has_image:
            work_type = '图集+实况'
        elif has_live:
            work_type = '实况图集'
        else:
            work_type = '图集'

        works.append({
            'aweme_id': aweme.get('aweme_id', ''),
            'aweme': aweme,
            'desc': desc,
            'date_str': date_str,
            'mix_name': mix_name or '',
            'work_type': work_type,
            'video_count': len(videos),
            'image_count': len(images),
            'live_count': len(live_images),
            'duration_ms': duration_ms,
            'resolution': resolution,
            'author_nickname': author_nickname,
            'video_tasks': video_tasks,
            'image_tasks': image_tasks,
            'create_time': create_time,
        })

    return works


def parse_all_awemes_to_tasks(all_awemes):
    """将所有aweme解析为下载任务列表"""
    video_tasks, image_tasks = [], []
    album_count = 0
    image_count = 0
    live_count = 0

    for aweme in all_awemes:
        desc, videos, images, live_images, date_str, mix_name, create_time = extract_media_links_from_aweme(aweme)

        # 视频任务
        for vurl in videos:
            ext = get_extension_from_url(vurl, '.mp4')
            task = {
                'url': vurl,
                'desc': desc,
                'ext': ext,
                'date': date_str,
                'mix_name': mix_name,
                'aweme': aweme,
                'create_time': create_time,
                'url_hash': hashlib.md5(vurl.encode('utf-8')).hexdigest()[:8],
            }
            video_tasks.append(task)

        # 如果这个 aweme 有普通图片或实况图，则视为一个图集作品
        if images or live_images:
            album_count += 1

        # 普通图片（按张）
        for idx, iurl in enumerate(images, start=1):
            ext = get_extension_from_url(iurl, '.jpg')
            image_tasks.append({
                'url': iurl, 'desc': f"{desc}_p{idx}", 'ext': ext,
                'date': date_str, 'mix_name': mix_name,
                'create_time': create_time,
                'url_hash': hashlib.md5(iurl.encode('utf-8')).hexdigest()[:8],
            })
        image_count += len(images)

        # 实况图（按张）
        for idx, lvurl in enumerate(live_images, start=1):
            ext = get_extension_from_url(lvurl, '.mp4')
            image_tasks.append({
                'url': lvurl, 'desc': f"{desc}_live{idx}", 'ext': ext,
                'date': date_str, 'mix_name': mix_name,
                'create_time': create_time,
                'url_hash': hashlib.md5(lvurl.encode('utf-8')).hexdigest()[:8],
            })
        live_count += len(live_images)

    return video_tasks, image_tasks, album_count, image_count, live_count