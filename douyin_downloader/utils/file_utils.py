#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
工具函数 - 文件名和路径处理
"""
import os
import re
import time
import hashlib
from datetime import datetime
from urllib.parse import unquote, urlparse

# 预编译正则，避免每次调用 sanitize_filename 时重新编译
_ILLEGAL_CHARS_RE = re.compile(r'[\\/*?:"<>|#]')
_WHITESPACE_RE = re.compile(r'\s+')

def sanitize_filename(filename, max_length=100):
    """清理文件名，移除非法字符"""
    if not filename:
        filename = "unknown"
    filename = unquote(str(filename))
    filename = _ILLEGAL_CHARS_RE.sub("_", filename)
    filename = _WHITESPACE_RE.sub(' ', filename).strip()
    if len(filename) > max_length:
        prefix = filename[:max_length // 2 - 2]
        suffix = filename[-(max_length // 2 - 1):]
        filename = f"{prefix}...{suffix}"
    # Windows 不允许目录/文件名以点或空格结尾（如标题截断后的 "......"）
    filename = filename.rstrip(' .')
    return filename or "unknown"


def safe_mkdir(path):
    """安全创建目录（支持多级目录），成功返回 True，失败返回 False"""
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except Exception as e:
        print(f"[错误] 创建目录失败: {path} -> {e}")
        return False


def get_extension_from_url(url, default_ext='.mp4'):
    """从URL提取文件扩展名"""
    try:
        parsed = urlparse(url)
        root, ext = os.path.splitext(parsed.path)
        # 确保扩展名有效
        if ext and 1 < len(ext) <= 6:
            return ext
    except Exception:
        pass
    return default_ext


def generate_unique_filename(base, ext, folder, url, url_hash=None):
    """
    生成唯一的文件路径，避免覆盖。
    """
    base_clean = sanitize_filename(base, max_length=150)
    filename = base_clean + ext
    path = os.path.join(folder, filename)

    if len(path) > 240 or os.path.exists(path):
        ts = datetime.now().strftime('%Y%m%d%H%M%S')
        h = url_hash or hashlib.md5(url.encode('utf-8')).hexdigest()[:8]
        filename = f"{base_clean[:80]}_{ts}_{h}{ext}"
        path = os.path.join(folder, filename)

    counter = 1
    original_path_prefix = path[:-len(ext)]
    while os.path.exists(path):
        filename = f"{original_path_prefix}_{counter}{ext}"
        path = os.path.join(folder, filename)
        counter += 1
        if counter > 200:
            h = url_hash or hashlib.md5(url.encode('utf-8')).hexdigest()[:8]
            filename = f"file_{int(time.time())}_{h}{ext}"
            path = os.path.join(folder, filename)
            break

    return path


def _extract_image_parts(desc):
    """从图片任务 desc 中提取 base_desc 和序号。
    desc 格式: 'some_title_p3' → ('some_title', '3', False)
                'some_title_live2' → ('some_title', '2', True)
    无法匹配时返回 (desc, '', False)
    """
    m = re.match(r'^(.+?)_p(\d+)$', desc)
    if m:
        return m.group(1), m.group(2), False
    m = re.match(r'^(.+?)_live(\d+)$', desc)
    if m:
        return m.group(1), m.group(2), True
    return desc, '', False


def compute_download_folder(base_folder, mix_name=None, is_image=False,
                            base_desc=None, date_str='', include_date=True):
    """
    计算下载目录。
    - 视频: base_folder/[合集/]视频/
    - 图集: base_folder/[合集/]图集/{date}_{base_desc}/
    worker 预检和 downloader 实际下载共用此函数，确保路径一致。
    """
    folder = base_folder
    if mix_name:
        mix_clean = sanitize_filename(mix_name, max_length=100)
        folder = os.path.join(folder, mix_clean)
    if is_image:
        folder = os.path.join(folder, '图集')
        if base_desc:
            if include_date and date_str:
                set_name = f"{date_str}_{base_desc}"
            else:
                set_name = base_desc
            folder = os.path.join(folder, sanitize_filename(set_name, max_length=100))
    else:
        folder = os.path.join(folder, '视频')
    return folder


def compute_base_filename(desc, date_str='', include_date=True):
    """构建基础文件名（日期前缀 + 描述）"""
    if include_date and date_str:
        return f"{date_str}_{desc}"
    return desc


def build_expected_filename(desc, ext, is_image, mix_name=None, date_str='', include_date=True):
    """
    构建预期的文件相对路径（用于去重检查）。
    与 download_single_file 共用 compute_download_folder / compute_base_filename，
    保证预检路径与实际下载路径一致（不含 hash/重名后缀）。
    图片文件名简化为序号: '3.jpg', 'live2.mp4'
    """
    if is_image:
        base_desc, idx, is_live = _extract_image_parts(desc)
        folder = compute_download_folder('', mix_name, is_image, base_desc, date_str, include_date)
        if is_live:
            filename = f"live{idx}{ext}" if idx else sanitize_filename(desc, 150) + ext
        else:
            filename = f"{idx}{ext}" if idx else sanitize_filename(desc, 150) + ext
    else:
        base_filename = compute_base_filename(desc, date_str, include_date)
        folder = compute_download_folder('', mix_name, is_image)
        filename = sanitize_filename(base_filename, 150) + ext
    return os.path.join(folder, filename) if folder else filename