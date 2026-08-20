#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
配置管理 - INI配置文件读写
"""
import os
import json
import tempfile
import configparser
from douyin_downloader.constants import CONFIG_FILE, DEFAULT_THREAD_COUNT, DEFAULT_MONITOR_INTERVAL_MINUTES
from douyin_downloader.core.work_filters import DEFAULT_EXTRACT_FILTERS, normalize_filters


def _safe_get(cp, section, key, getter='get', default=None, **kwargs):
    """安全读取配置值，任何异常时返回默认值"""
    try:
        if section not in cp:
            return default
        method = getattr(cp[section], getter)
        # Py3.13 SectionProxy 对缺失项可能返回 None 而不抛错；显式传 fallback
        if 'fallback' not in kwargs:
            kwargs['fallback'] = default
        val = method(key, **kwargs)
        if val is None and default is not None:
            return default
        return val
    except Exception:
        return default


def _parse_bool_flag(raw, default=False):
    if raw is None:
        return default
    s = str(raw).strip().lower()
    if s in ('1', 'true', 'yes', 'on'):
        return True
    if s in ('0', 'false', 'no', 'off', ''):
        return False
    return default


def _parse_int_field(raw, default=0):
    if raw is None or str(raw).strip() == '':
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def load_config():
    """加载应用配置"""
    cfg = {}

    # 1. 尝试从旧版 config.txt (json) 迁移
    old_json = os.path.join(os.path.dirname(CONFIG_FILE) or '.', 'config.txt')
    if os.path.exists(old_json):
        try:
            with open(old_json, 'r', encoding='utf-8') as f:
                j = json.load(f) or {}
            if isinstance(j, dict):
                cfg.update(j)
        except Exception:
            pass

    # 2. 从 config.ini 加载/覆盖
    if os.path.exists(CONFIG_FILE):
        try:
            cp = configparser.ConfigParser(interpolation=None)
            cp.read(CONFIG_FILE, encoding='utf-8')

            if 'main' in cp:
                cfg['path'] = _safe_get(cp, 'main', 'path', default='')
                cfg['cookie'] = _safe_get(cp, 'main', 'cookie', default='')
                cfg['chrome_path'] = _safe_get(cp, 'main', 'chrome_path', default='')
                cfg['edge_path'] = _safe_get(cp, 'main', 'edge_path', default='')
                cfg['use_mix_folder'] = _safe_get(cp, 'main', 'use_mix_folder', 'getboolean', True)
                cfg['include_date_in_filename'] = _safe_get(cp, 'main', 'include_date_in_filename', 'getboolean', True)
                cfg['auto_select_after_fetch'] = _safe_get(cp, 'main', 'auto_select_after_fetch', 'getboolean', True)
                cfg['fetch_latest_only'] = _safe_get(cp, 'main', 'fetch_latest_only', 'getboolean', False)
                cfg['add_title_when_export_urls'] = _safe_get(cp, 'main', 'add_title_when_export_urls', 'getboolean', False)
                cfg['set_file_time_to_publish_time'] = _safe_get(
                    cp, 'main', 'set_file_time_to_publish_time', 'getboolean', False
                )
                cfg['download_live_cover'] = _safe_get(
                    cp, 'main', 'download_live_cover', 'getboolean', False
                )
                cfg['flat_image_enabled'] = _safe_get(
                    cp, 'main', 'flat_image_enabled', 'getboolean', False
                )
                cfg['threads'] = _safe_get(cp, 'main', 'threads', 'getint', DEFAULT_THREAD_COUNT)
                cfg['icon_choice'] = _safe_get(cp, 'main', 'icon_choice', default='default')
                cfg['monitor_enabled'] = _safe_get(cp, 'main', 'monitor_enabled', 'getboolean', False)
                cfg['monitor_interval_minutes'] = _safe_get(
                    cp, 'main', 'monitor_interval_minutes', 'getint', DEFAULT_MONITOR_INTERVAL_MINUTES
                )

            # 提取筛选条件（JSON）
            if 'extract_filters' in cp:
                raw = {}
                for k, v in cp['extract_filters'].items():
                    raw[k] = v
                # bool/int 还原
                parsed = {}
                for k, default in DEFAULT_EXTRACT_FILTERS.items():
                    if k not in raw:
                        continue
                    if isinstance(default, bool):
                        parsed[k] = _parse_bool_flag(raw[k], default)
                    elif isinstance(default, int):
                        parsed[k] = _parse_int_field(raw[k], default)
                    else:
                        parsed[k] = raw[k]
                cfg['extract_filters'] = normalize_filters(parsed)

            # 加载用户列表（兼容旧格式 username,url 和新格式多字段）
            cfg['users'] = []
            if 'users' in cp:
                for key in cp['users']:
                    if key.startswith('user'):
                        try:
                            value = cp['users'][key]
                            parts = value.split('|')
                            if len(parts) >= 2:
                                seen_raw = parts[12].strip() if len(parts) > 12 else ''
                                seen_ids = [x for x in seen_raw.split(',') if x] if seen_raw else []
                                user_entry = {
                                    'username': parts[0].strip(),
                                    'url': parts[1].strip(),
                                    'group': parts[2].strip() if len(parts) > 2 else '',
                                    'following_count': int(parts[3]) if len(parts) > 3 and parts[3].strip().isdigit() else None,
                                    'follower_count': int(parts[4]) if len(parts) > 4 and parts[4].strip().isdigit() else None,
                                    'total_favorited': int(parts[5]) if len(parts) > 5 and parts[5].strip().isdigit() else None,
                                    'favoriting_count': int(parts[6]) if len(parts) > 6 and parts[6].strip().isdigit() else None,
                                    'aweme_count': int(parts[7]) if len(parts) > 7 and parts[7].strip().isdigit() else None,
                                    'last_publish_time': parts[8].strip() if len(parts) > 8 else '',
                                    'sec_user_id': parts[9].strip() if len(parts) > 9 else '',
                                    'monitor': _parse_bool_flag(parts[10] if len(parts) > 10 else '0', False),
                                    'monitor_since': _parse_int_field(parts[11] if len(parts) > 11 else '', 0),
                                    'monitor_seen_ids': seen_ids,
                                }
                                cfg['users'].append(user_entry)
                        except Exception:
                            pass
        except Exception:
            pass

    # 确保关键默认值存在
    cfg.setdefault('path', '')
    cfg.setdefault('cookie', '')
    cfg.setdefault('chrome_path', '')
    cfg.setdefault('edge_path', '')
    cfg.setdefault('use_mix_folder', True)
    cfg.setdefault('include_date_in_filename', True)
    cfg.setdefault('auto_select_after_fetch', True)
    cfg.setdefault('fetch_latest_only', False)
    cfg.setdefault('add_title_when_export_urls', False)
    cfg.setdefault('set_file_time_to_publish_time', False)
    cfg.setdefault('download_live_cover', False)
    cfg.setdefault('flat_image_enabled', False)
    cfg.setdefault('threads', DEFAULT_THREAD_COUNT)
    cfg.setdefault('icon_choice', 'default')
    cfg.setdefault('monitor_enabled', False)
    cfg.setdefault('monitor_interval_minutes', DEFAULT_MONITOR_INTERVAL_MINUTES)
    cfg.setdefault('users', [])
    cfg['extract_filters'] = normalize_filters(cfg.get('extract_filters'))

    return cfg


def save_config(cfg):
    """保存配置到INI文件（原子写入）。

    安全策略：若内存中 users/cookie/path 为空，则尽量保留磁盘上已有值，
    避免筛选面板等局部保存把主页列表或 Cookie 整文件冲掉。
    """
    try:
        # 先读盘上的现有配置，用于填补空字段 / 防止误清空 users
        disk = {}
        if os.path.exists(CONFIG_FILE):
            try:
                disk = load_config()
            except Exception:
                disk = {}

        merged = dict(disk)
        if isinstance(cfg, dict):
            for k, v in cfg.items():
                if k == 'users':
                    # 内存里显式带了 users（含空列表=用户主动删光）则以内存为准；
                    # 若根本没有该键（异常空 cfg），则保留磁盘，避免误冲掉主页列表。
                    merged['users'] = list(v) if isinstance(v, list) else []
                elif k == 'extract_filters':
                    merged[k] = v
                elif k in ('cookie', 'path', 'chrome_path', 'edge_path'):
                    # 空字符串不覆盖磁盘已有非空值
                    if v or not merged.get(k):
                        merged[k] = v
                else:
                    merged[k] = v

        cp = configparser.ConfigParser(interpolation=None)

        # [main] section
        cp['main'] = {
            'path': merged.get('path', ''),
            'use_mix_folder': str(bool(merged.get('use_mix_folder', True))),
            'include_date_in_filename': str(bool(merged.get('include_date_in_filename', True))),
            'auto_select_after_fetch': str(bool(merged.get('auto_select_after_fetch', True))),
            'fetch_latest_only': str(bool(merged.get('fetch_latest_only', False))),
            'add_title_when_export_urls': str(bool(merged.get('add_title_when_export_urls', False))),
            'set_file_time_to_publish_time': str(bool(merged.get('set_file_time_to_publish_time', False))),
            'download_live_cover': str(bool(merged.get('download_live_cover', False))),
            'flat_image_enabled': str(bool(merged.get('flat_image_enabled', False))),
            'threads': str(int(merged.get('threads', DEFAULT_THREAD_COUNT))),
            'icon_choice': merged.get('icon_choice', 'default'),
            'chrome_path': merged.get('chrome_path', ''),
            'edge_path': merged.get('edge_path', ''),
            'cookie': merged.get('cookie', ''),
            'monitor_enabled': str(bool(merged.get('monitor_enabled', False))),
            'monitor_interval_minutes': str(int(
                merged.get('monitor_interval_minutes', DEFAULT_MONITOR_INTERVAL_MINUTES)
            )),
        }

        filters = normalize_filters(merged.get('extract_filters'))
        cp['extract_filters'] = {k: str(v) for k, v in filters.items()}

        # [users] 始终写出（可为空，但优先用 merged 中的列表）
        users = merged.get('users') or []
        cp['users'] = {}
        for idx, user in enumerate(users, start=1):
            def _field(key, _u=user):
                v = _u.get(key)
                return '' if v is None else str(v)

            seen_ids = user.get('monitor_seen_ids') or []
            if isinstance(seen_ids, str):
                seen_str = seen_ids
            else:
                seen_str = ','.join(str(x) for x in seen_ids if x)

            fields = [
                user.get('username', ''),
                user.get('url', ''),
                user.get('group', ''),
                _field('following_count'),
                _field('follower_count'),
                _field('total_favorited'),
                _field('favoriting_count'),
                _field('aweme_count'),
                user.get('last_publish_time', ''),
                user.get('sec_user_id', ''),
                '1' if user.get('monitor') else '0',
                str(int(user.get('monitor_since') or 0)),
                seen_str,
            ]
            cp['users'][f'user{idx}'] = '|'.join(fields)

        # 原子写入：先写临时文件，再替换
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(CONFIG_FILE) or '.',
            prefix='.config_', suffix='.tmp'
        )
        try:
            with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
                cp.write(f)
            os.replace(tmp_path, CONFIG_FILE)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

        # 写回内存 cfg，避免界面仍持有空 users
        if isinstance(cfg, dict):
            cfg['users'] = list(users)
            if merged.get('cookie') and not cfg.get('cookie'):
                cfg['cookie'] = merged.get('cookie')
            if merged.get('path') and not cfg.get('path'):
                cfg['path'] = merged.get('path')
    except Exception as e:
        print(f"[警告] 保存 {CONFIG_FILE} 失败: {e}")
