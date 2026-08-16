#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
parser.py 自检测试 — 无框架，assert + __main__。
覆盖：视频提取、图集提取、实况图提取、合集名、时间戳、空数据。
运行: python -m douyin_downloader.tests.test_parser
"""
import hashlib
import os
import sys

# 确保以包方式 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from douyin_downloader.core.parser import extract_media_links_from_aweme, parse_all_awemes_to_tasks


# ── fixtures ──────────────────────────────────────────────

VIDEO_AWEME = {
    "aweme_id": "7000001",
    "desc": "测试视频",
    "create_time": 1700000000,
    "mix_info": {"mix_name": "合集A"},
    "video": {
        "bit_rate": [
            {"bit_rate": 800000, "play_addr": {"url_list": ["https://v.douyin.com/low.mp4"]}},
            {"bit_rate": 1200000, "play_addr": {"url_list": ["https://v.douyin.com/high.mp4"]}},
        ]
    },
}

IMAGE_AWEME = {
    "aweme_id": "7000002",
    "desc": "图集作品",
    "create_time": 1700100000,
    "images": [
        {"url_list": ["https://i.douyin.com/img1_720.jpg", "https://i.douyin.com/img1_1080.jpg"]},
        {"url_list": ["https://i.douyin.com/img2_720.jpg"]},
    ],
}

LIVE_IMAGE_AWEME = {
    "aweme_id": "7000003",
    "desc": "实况图作品",
    "create_time": 1700200000,
    "mix_info": {"mix_name": "实况合集"},
    "images": [
        {
            "url_list": ["https://i.douyin.com/cover.jpg"],
            "video": {
                "bit_rate": [
                    {"bit_rate": 500000, "play_addr": {"url_list": ["https://v.douyin.com/live_low.mp4"]}},
                    {"bit_rate": 900000, "play_addr": {"url_list": ["https://v.douyin.com/live_high.mp4"]}},
                ]
            },
        },
        {"url_list": ["https://i.douyin.com/plain.jpg"]},
    ],
}

EMPTY_AWEME = {
    "aweme_id": "7000004",
    "desc": "",
    "create_time": None,
}


# ── tests ─────────────────────────────────────────────────

def test_video_extraction():
    """视频：提取最高码率 URL，并返回 create_time"""
    desc, videos, images, live, date_str, mix_name, create_time = extract_media_links_from_aweme(VIDEO_AWEME)
    assert len(videos) == 1, f"expected 1 video, got {len(videos)}"
    assert videos[0] == "https://v.douyin.com/high.mp4", f"wrong url: {videos[0]}"
    assert len(images) == 0
    assert len(live) == 0
    assert mix_name == "合集A"
    assert date_str == "2023-11-15"  # 1700000000 = 2023-11-15 06:13:20 GMT+8
    assert create_time == 1700000000
    assert desc == "测试视频"


def test_image_extraction():
    """图集：取 url_list[-1] 作为最高分辨率，并返回 create_time"""
    desc, videos, images, live, date_str, mix_name, create_time = extract_media_links_from_aweme(IMAGE_AWEME)
    assert len(videos) == 0
    assert len(images) == 2, f"expected 2 images, got {len(images)}"
    assert images[0] == "https://i.douyin.com/img1_1080.jpg"
    assert images[1] == "https://i.douyin.com/img2_720.jpg"
    assert len(live) == 0
    assert mix_name is None
    assert create_time == 1700100000


def test_live_image_extraction():
    """实况图：有 video 字段的 image 项提取实况视频，跳过普通图片；普通图片项正常提取"""
    desc, videos, images, live, date_str, mix_name, create_time = extract_media_links_from_aweme(LIVE_IMAGE_AWEME)
    assert len(videos) == 0
    assert len(live) == 1, f"expected 1 live image, got {len(live)}"
    assert live[0] == "https://v.douyin.com/live_high.mp4"
    assert len(images) == 1, f"expected 1 plain image, got {len(images)}"
    assert images[0] == "https://i.douyin.com/plain.jpg"
    assert mix_name == "实况合集"
    assert create_time == 1700200000


def test_empty_aweme():
    """空数据：desc 回退到 aweme_id，时间戳缺失不报错"""
    desc, videos, images, live, date_str, mix_name, create_time = extract_media_links_from_aweme(EMPTY_AWEME)
    assert desc == "7000004"
    assert len(videos) == 0
    assert len(images) == 0
    assert len(live) == 0
    assert date_str == ''
    assert mix_name is None
    assert create_time == 0


def test_parse_all_to_tasks():
    """parse_all_awemes_to_tasks: 视频/图片/实况图任务正确分类"""
    vtasks, itasks, album_count, image_count, live_count = parse_all_awemes_to_tasks(
        [VIDEO_AWEME, IMAGE_AWEME, LIVE_IMAGE_AWEME]
    )
    assert len(vtasks) == 1
    assert vtasks[0]['desc'] == "测试视频"
    assert vtasks[0]['ext'] == '.mp4'
    assert vtasks[0]['mix_name'] == "合集A"

    # 图集任务 = 2(IMAGE_AWEME) + 1 plain + 1 live(LIVE_IMAGE_AWEME) = 4
    assert len(itasks) == 4, f"expected 4 image tasks, got {len(itasks)}"
    # album_count = 有图片或实况图的 aweme 数 = 2
    assert album_count == 2, f"expected album_count=2, got {album_count}"
    assert image_count == 3  # 2 from IMAGE_AWEME + 1 plain from LIVE_IMAGE_AWEME
    assert live_count == 1

    # 验证 url_hash 正确生成
    expected_hash = hashlib.md5("https://v.douyin.com/high.mp4".encode('utf-8')).hexdigest()[:8]
    assert vtasks[0]['url_hash'] == expected_hash


def test_desc_truncation():
    """过长描述自动截断"""
    long_desc = "A" * 500
    aweme = {"aweme_id": "x", "desc": long_desc, "create_time": 1700000000, "video": {}}
    desc, *_ = extract_media_links_from_aweme(aweme)
    from douyin_downloader.constants import MAX_DESC_LENGTH
    assert len(desc) == MAX_DESC_LENGTH + len("......"), f"desc length {len(desc)}"


# ── runner ────────────────────────────────────────────────

def main():
    tests = [
        test_video_extraction,
        test_image_extraction,
        test_live_image_extraction,
        test_empty_aweme,
        test_parse_all_to_tasks,
        test_desc_truncation,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  [PASS] {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {t.__name__}: {e}")
        except Exception as e:
            print(f"  [ERR]  {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
