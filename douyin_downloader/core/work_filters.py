# -*- coding: utf-8 -*-
"""
提取作品筛选：根据配置过滤 work / aweme。
本地生活 / 商品 / 会员 依赖接口字段启发式识别，无字段时视为不匹配。
"""
import time
from datetime import datetime


DEFAULT_EXTRACT_FILTERS = {
    'enabled': False,
    'type_video': True,
    'type_image': True,
    'only_unrecorded_ids': False,
    'hours_enabled': False,
    'hours': 10,
    'per_user_limit': 0,
    'want_local_life': False,
    'want_no_local_life': False,
    'want_goods': False,
    'want_no_goods': False,
    'start_time_enabled': False,
    'start_time': '',
    'end_time_enabled': False,
    'end_time': '',
    'duration_enabled': False,
    'duration_min': 10,
    'duration_max': 30,
    'want_landscape': False,
    'want_no_landscape': False,
    'image_count_enabled': False,
    'image_count_min': 1,
    'image_count_max': 3,
    'want_member': False,
    'want_no_member': False,
}


def normalize_filters(raw):
    """合并默认值，保证类型正确"""
    out = dict(DEFAULT_EXTRACT_FILTERS)
    if isinstance(raw, dict):
        out.update(raw)
    for k in (
        'enabled', 'type_video', 'type_image', 'only_unrecorded_ids',
        'hours_enabled', 'want_local_life', 'want_no_local_life',
        'want_goods', 'want_no_goods', 'start_time_enabled', 'end_time_enabled',
        'duration_enabled', 'want_landscape', 'want_no_landscape',
        'image_count_enabled', 'want_member', 'want_no_member',
    ):
        out[k] = bool(out.get(k))
    for k in (
        'hours', 'per_user_limit', 'duration_min', 'duration_max',
        'image_count_min', 'image_count_max',
    ):
        try:
            out[k] = int(out.get(k) or 0)
        except (TypeError, ValueError):
            out[k] = DEFAULT_EXTRACT_FILTERS[k]
    out['start_time'] = str(out.get('start_time') or '')
    out['end_time'] = str(out.get('end_time') or '')
    return out


def _parse_dt(s):
    s = (s or '').strip()
    if not s:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _create_time(work):
    try:
        return int(work.get('create_time') or 0)
    except (TypeError, ValueError):
        return 0


def _is_video_work(work):
    wt = work.get('work_type') or ''
    return '视频' in wt or int(work.get('video_count') or 0) > 0


def _is_image_work(work):
    wt = work.get('work_type') or ''
    if '图集' in wt or '实况' in wt or '图文' in wt:
        return True
    return (int(work.get('image_count') or 0) + int(work.get('live_count') or 0)) > 0


def _video_size(work):
    aweme = work.get('aweme') if isinstance(work.get('aweme'), dict) else {}
    video = aweme.get('video') if isinstance(aweme.get('video'), dict) else {}
    w = int(video.get('width') or 0)
    h = int(video.get('height') or 0)
    if w and h:
        return w, h
    res = work.get('resolution') or ''
    for sep in ('×', 'x', 'X'):
        if sep in res:
            parts = res.split(sep, 1)
            try:
                return int(parts[0]), int(parts[1])
            except (TypeError, ValueError):
                break
    return 0, 0


def _is_landscape(work):
    w, h = _video_size(work)
    return bool(w and h and w > h)


def _image_pages(work):
    return int(work.get('image_count') or 0) + int(work.get('live_count') or 0)


def _duration_sec(work):
    ms = int(work.get('duration_ms') or 0)
    return ms // 1000 if ms > 0 else 0


def _anchor_text(anchor):
    if not isinstance(anchor, dict):
        return ''
    bits = []
    for k in ('type', 'type_tag', 'icon_tag', 'title', 'keyword', 'extra', 'name'):
        v = anchor.get(k)
        if v is not None:
            bits.append(str(v))
    return ' '.join(bits).lower()


def aweme_has_local_life(aweme):
    if not isinstance(aweme, dict):
        return False
    if aweme.get('poi_info') or aweme.get('poi_data') or aweme.get('poi'):
        return True
    if aweme.get('life_share_ext') or aweme.get('local_life'):
        return True
    for a in aweme.get('anchors') or []:
        t = _anchor_text(a)
        if any(x in t for x in ('life', 'poi', '本地', '团购', '门店', '生活')):
            return True
    return False


def aweme_has_goods(aweme):
    if not isinstance(aweme, dict):
        return False
    if aweme.get('with_goods') or aweme.get('promotions') or aweme.get('commerce_info'):
        return True
    if aweme.get('goods_info') or aweme.get('product_info'):
        return True
    for a in aweme.get('anchors') or []:
        t = _anchor_text(a)
        if any(x in t for x in ('goods', 'shop', 'cart', '商品', '小店', '购物', 'commerce')):
            return True
        try:
            if int(a.get('type') or 0) in (100, 1000, 10000):  # 常见电商锚点类型，容错
                if 'shop' in t or 'goods' in t or '商品' in t:
                    return True
        except (TypeError, ValueError):
            pass
    return False


def aweme_is_member(aweme):
    if not isinstance(aweme, dict):
        return False
    if aweme.get('is_charge_content') or aweme.get('is_paid_content'):
        return True
    charge = aweme.get('charge_info')
    if isinstance(charge, dict) and any(charge.values()):
        return True
    for key in ('series_paid_info', 'paid_series_info', 'entertainment_product_info'):
        info = aweme.get(key)
        if isinstance(info, dict) and (
            info.get('is_paid_content')
            or info.get('paid_type')
            or info.get('is_charge_content')
            or info.get('has_paid_content')
        ):
            return True
    return False


def work_matches_filters(work, filters, recorded_ids=None):
    """单条作品是否通过筛选。filters 需先 normalize。"""
    f = normalize_filters(filters)
    if not f.get('enabled'):
        return True

    is_video = _is_video_work(work)
    is_image = _is_image_work(work)
    if is_video and not f.get('type_video'):
        return False
    if is_image and not is_video and not f.get('type_image'):
        return False
    if is_video and is_image:
        # 视频+图集：任一类型开启即可
        if not (f.get('type_video') or f.get('type_image')):
            return False
    if not is_video and not is_image:
        return False

    ct = _create_time(work)
    now = int(time.time())

    if f.get('hours_enabled') and f.get('hours', 0) > 0:
        if ct <= 0 or ct < now - int(f['hours']) * 3600:
            return False

    if f.get('start_time_enabled'):
        dt = _parse_dt(f.get('start_time'))
        if dt and (ct <= 0 or ct < int(dt.timestamp())):
            return False

    if f.get('end_time_enabled'):
        dt = _parse_dt(f.get('end_time'))
        if dt and (ct <= 0 or ct > int(dt.timestamp())):
            return False

    if f.get('only_unrecorded_ids'):
        aid = str(work.get('aweme_id') or '')
        recorded = recorded_ids or set()
        if aid and aid in recorded:
            return False

    aweme = work.get('aweme') if isinstance(work.get('aweme'), dict) else {}

    has_life = aweme_has_local_life(aweme)
    if f.get('want_local_life') and not has_life:
        return False
    if f.get('want_no_local_life') and has_life:
        return False

    has_goods = aweme_has_goods(aweme)
    if f.get('want_goods') and not has_goods:
        return False
    if f.get('want_no_goods') and has_goods:
        return False

    is_member = aweme_is_member(aweme)
    if f.get('want_member') and not is_member:
        return False
    if f.get('want_no_member') and is_member:
        return False

    if f.get('duration_enabled') and is_video:
        sec = _duration_sec(work)
        if sec < int(f.get('duration_min') or 0) or sec > int(f.get('duration_max') or 0):
            return False

    if is_video:
        landscape = _is_landscape(work)
        if f.get('want_landscape') and not landscape:
            return False
        if f.get('want_no_landscape') and landscape:
            return False

    if f.get('image_count_enabled') and is_image and not is_video:
        pages = _image_pages(work)
        if pages < int(f.get('image_count_min') or 0) or pages > int(f.get('image_count_max') or 0):
            return False

    return True


def filter_works(works, filters, recorded_ids=None, per_user_counts=None):
    """
    过滤作品列表。
    per_user_counts: 可选 dict，作者 key -> 已通过数量（跨页累加）；
      若 filters.per_user_limit > 0，达到上限后丢弃后续。
    返回 (kept_works, rejected_count)
    """
    f = normalize_filters(filters)
    if not f.get('enabled'):
        return list(works or []), 0

    limit = int(f.get('per_user_limit') or 0)
    counts = per_user_counts if isinstance(per_user_counts, dict) else {}
    kept = []
    rejected = 0
    for w in works or []:
        if not work_matches_filters(w, f, recorded_ids=recorded_ids):
            rejected += 1
            continue
        author = ''
        aweme = w.get('aweme') if isinstance(w.get('aweme'), dict) else {}
        author_obj = aweme.get('author') if isinstance(aweme.get('author'), dict) else {}
        author = (
            w.get('author_nickname')
            or author_obj.get('unique_id')
            or author_obj.get('sec_uid')
            or author_obj.get('nickname')
            or ''
        )
        if limit > 0:
            n = counts.get(author, 0)
            if n >= limit:
                rejected += 1
                continue
            counts[author] = n + 1
        kept.append(w)
    return kept, rejected


def load_aweme_id_records(path):
    """读取 {sec_user_id: [aweme_id, ...]}"""
    import json
    import os
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
        if not isinstance(data, dict):
            return {}
        out = {}
        for k, v in data.items():
            if isinstance(v, list):
                out[str(k)] = [str(x) for x in v if x]
            elif isinstance(v, str):
                out[str(k)] = [x for x in v.split(',') if x]
        return out
    except Exception:
        return {}


def save_aweme_id_records(path, records):
    import json
    import os
    import tempfile
    records = records or {}
    directory = os.path.dirname(path) or '.'
    tmp_fd, tmp_path = tempfile.mkstemp(dir=directory, prefix='.aweme_ids_', suffix='.tmp')
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def recorded_ids_for_user(records, sec_user_id):
    if not sec_user_id:
        return set()
    return set(records.get(str(sec_user_id)) or [])


def add_recorded_ids(records, sec_user_id, aweme_ids, max_keep=5000):
    """追加作品 ID 到记录，并限制每个用户最多保留条数"""
    if not sec_user_id:
        return records
    key = str(sec_user_id)
    existing = list(records.get(key) or [])
    seen = set(existing)
    for aid in aweme_ids or []:
        aid = str(aid or '')
        if aid and aid not in seen:
            existing.append(aid)
            seen.add(aid)
    if len(existing) > max_keep:
        existing = existing[-max_keep:]
    records[key] = existing
    return records
