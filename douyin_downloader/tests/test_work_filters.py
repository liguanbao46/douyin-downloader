# -*- coding: utf-8 -*-
from douyin_downloader.core.work_filters import (
    normalize_filters, work_matches_filters, filter_works,
    aweme_has_goods, aweme_has_local_life, aweme_is_member,
)


def _work(aweme_id='1', create_time=1700000000, work_type='视频',
          duration_ms=15000, resolution='1920×1080',
          image_count=0, live_count=0, video_count=1, aweme=None):
    return {
        'aweme_id': aweme_id,
        'create_time': create_time,
        'work_type': work_type,
        'duration_ms': duration_ms,
        'resolution': resolution,
        'image_count': image_count,
        'live_count': live_count,
        'video_count': video_count,
        'author_nickname': 'u',
        'aweme': aweme or {},
    }


def test_disabled_passes_all():
    f = normalize_filters({'enabled': False})
    assert work_matches_filters(_work(), f) is True


def test_type_filter_video_only():
    f = normalize_filters({
        'enabled': True, 'type_video': True, 'type_image': False,
    })
    assert work_matches_filters(_work(work_type='视频'), f) is True
    assert work_matches_filters(
        _work(work_type='图集', video_count=0, image_count=3, duration_ms=0, resolution=''),
        f,
    ) is False


def test_duration_and_landscape():
    f = normalize_filters({
        'enabled': True,
        'duration_enabled': True,
        'duration_min': 10,
        'duration_max': 30,
        'want_landscape': True,
    })
    assert work_matches_filters(_work(duration_ms=15000, resolution='1920×1080'), f) is True
    assert work_matches_filters(_work(duration_ms=5000, resolution='1920×1080'), f) is False
    assert work_matches_filters(_work(duration_ms=15000, resolution='1080×1920'), f) is False


def test_image_count():
    f = normalize_filters({
        'enabled': True,
        'type_video': False,
        'type_image': True,
        'image_count_enabled': True,
        'image_count_min': 1,
        'image_count_max': 3,
    })
    w = _work(work_type='图集', video_count=0, image_count=2, duration_ms=0, resolution='')
    assert work_matches_filters(w, f) is True
    w2 = _work(work_type='图集', video_count=0, image_count=5, duration_ms=0, resolution='')
    assert work_matches_filters(w2, f) is False


def test_unrecorded_and_limit():
    f = normalize_filters({
        'enabled': True,
        'only_unrecorded_ids': True,
        'per_user_limit': 2,
    })
    works = [
        _work('a'), _work('b'), _work('c'), _work('a'),
    ]
    kept, rejected = filter_works(works, f, recorded_ids={'a'}, per_user_counts={})
    assert [w['aweme_id'] for w in kept] == ['b', 'c']
    assert rejected == 2  # a recorded + c would be 3rd but wait: a rejected, then b,c kept (limit 2), fourth a rejected
    # Actually: a recorded -> reject; b keep (1); c keep (2); a recorded -> reject. rejected=2. Good.


def test_goods_and_member_heuristics():
    assert aweme_has_goods({'with_goods': True}) is True
    assert aweme_has_local_life({'poi_info': {'id': 1}}) is True
    assert aweme_is_member({'is_charge_content': True}) is True
    assert aweme_has_goods({}) is False
