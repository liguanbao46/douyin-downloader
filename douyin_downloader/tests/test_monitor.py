#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""水位过滤单元测试"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from douyin_downloader.core.monitor import (
    filter_new_awemes, compute_watermark, advance_watermark,
)


def test_filter_newer_than_since():
    awemes = [
        {'aweme_id': 'a', 'create_time': 100},
        {'aweme_id': 'b', 'create_time': 200},
        {'aweme_id': 'c', 'create_time': 300},
    ]
    new = filter_new_awemes(awemes, 200, ['b'])
    ids = [x['aweme_id'] for x in new]
    assert ids == ['c'], ids


def test_filter_same_second_unseen():
    awemes = [
        {'aweme_id': 'a', 'create_time': 100},
        {'aweme_id': 'b', 'create_time': 100},
    ]
    new = filter_new_awemes(awemes, 100, ['a'])
    ids = [x['aweme_id'] for x in new]
    assert ids == ['b'], ids


def test_compute_watermark():
    awemes = [
        {'aweme_id': 'a', 'create_time': 50},
        {'aweme_id': 'b', 'create_time': 90},
        {'aweme_id': 'c', 'create_time': 90},
    ]
    since, seen = compute_watermark(awemes)
    assert since == 90
    assert set(seen) == {'b', 'c'}


def test_advance_watermark():
    since, seen = advance_watermark(100, ['x'], [
        {'aweme_id': 'y', 'create_time': 150},
        {'aweme_id': 'z', 'create_time': 150},
    ])
    assert since == 150
    assert set(seen) == {'y', 'z'}


def test_enable_monitor_no_backfill():
    """开启监控时水位=当前最新，过滤结果应为空"""
    awemes = [
        {'aweme_id': 'a', 'create_time': 10},
        {'aweme_id': 'b', 'create_time': 20},
    ]
    since, seen = compute_watermark(awemes)
    new = filter_new_awemes(awemes, since, seen)
    assert new == []


if __name__ == '__main__':
    tests = [
        test_filter_newer_than_since,
        test_filter_same_second_unseen,
        test_compute_watermark,
        test_advance_watermark,
        test_enable_monitor_no_backfill,
    ]
    passed = 0
    for t in tests:
        t()
        print(f'  [PASS] {t.__name__}')
        passed += 1
    print(f'\n{passed}/{len(tests)} passed')
