#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
工具函数 - 文件名和路径处理
"""
import os
import re
import shutil
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


def set_folder_mtime(path, create_time):
    """
    将目录修改时间设为 create_time（Unix 时间戳）。
    若目录已有较新的「非刚刚创建」时间则保留较新值，避免被更旧作品批量下载回拨；
    若目录刚创建（约 2 分钟内），则强制写成作品时间。
    """
    if not path or not create_time:
        return False
    try:
        ts = int(create_time)
    except (TypeError, ValueError):
        return False
    if ts <= 0 or not os.path.isdir(path):
        return False
    try:
        cur = int(os.stat(path).st_mtime)
    except Exception:
        cur = 0
    now = int(time.time())
    # 刚 mkdir 的目录 mtime≈现在，应改成作品发布时间
    if cur >= now - 120:
        target = ts
    else:
        target = max(cur, ts)
    try:
        os.utime(path, (target, target))
        return True
    except Exception:
        return False


def update_author_folders_mtime(tasks, fallback_folder=''):
    """
    更新「作者名称」文件夹的修改时间（作品下载/{昵称-unique_id}/），
    取该作者本次任务中最大的 create_time；不改动其下的 视频/图集 子目录。
    tasks: 可迭代的 task dict（含 base_folder / create_time）
    """
    folder_latest = {}
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        folder = t.get('base_folder') or fallback_folder
        if not folder:
            continue
        try:
            ct = int(t.get('create_time') or 0)
        except (TypeError, ValueError):
            ct = 0
        if ct <= 0:
            continue
        prev = folder_latest.get(folder, 0)
        if ct > prev:
            folder_latest[folder] = ct
    updated = 0
    for folder, ct in folder_latest.items():
        if set_folder_mtime(folder, ct):
            updated += 1
    return updated


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
    desc 格式: 'some_title_p3'       → ('some_title', '3', 'normal')
                'some_title_live2'    → ('some_title', '2', 'live')
                'some_title_livecover2'→ ('some_title', '2', 'cover')
    无法匹配时返回 (desc, '', 'normal')
    """
    m = re.match(r'^(.+?)_p(\d+)$', desc)
    if m:
        return m.group(1), m.group(2), 'normal'
    m = re.match(r'^(.+?)_livecover(\d+)$', desc)
    if m:
        return m.group(1), m.group(2), 'cover'
    m = re.match(r'^(.+?)_live(\d+)$', desc)
    if m:
        return m.group(1), m.group(2), 'live'
    return desc, '', 'normal'


def compute_download_folder(base_folder, mix_name=None, is_image=False,
                            base_desc=None, date_str='', include_date=True,
                            flat_mode=False):
    """
    计算下载目录。
    - 视频: base_folder/[合集/]视频/
    - 图集（正常）: base_folder/[合集/]图集/{date}_{base_desc}/
    - 图集（扁平）: base_folder/图片/  （所有图片集中一个目录，不建逐个图集子目录）
    worker 预检和 downloader 实际下载共用此函数，确保路径一致。
    """
    folder = base_folder
    if flat_mode and is_image:
        # 扁平模式：博主文件夹下建一个「图片」子目录，所有图片集中存放
        # （命名为「图片」以区别于原有「图集」结构）
        return os.path.join(folder, '图片')
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


def build_expected_filename(desc, ext, is_image, mix_name=None, date_str='', include_date=True,
                            flat_mode=False):
    """
    构建预期的文件相对路径（用于去重检查）。
    与 download_single_file 共用 compute_download_folder / compute_base_filename，
    保证预检路径与实际下载路径一致（不含 hash/重名后缀）。

    正常模式（图集在各子文件夹内）:
      图片: {idx}{ext}  实况: live{idx}{ext}  封面: live{idx}_cover{ext}
    扁平模式（集中存放于博主文件夹下的「图片」目录，文件名带描述保证唯一）:
      图片: {date}_{desc}_{idx}{ext}  实况: {date}_{desc}_live{idx}{ext}  封面: {date}_{desc}_live{idx}_cover{ext}
    """
    if is_image:
        base_desc, idx, media_type = _extract_image_parts(desc)
        folder = compute_download_folder('', mix_name, is_image, base_desc, date_str, include_date, flat_mode)
        if flat_mode:
            # 扁平模式：文件名包含描述，避免不同图集同名冲突
            # 描述必须清洗（Windows 非法字符 < > ? : " | 等），否则复制/写盘报 WinError 123
            name_base = compute_base_filename(sanitize_filename(base_desc, 120), date_str, include_date)
            if media_type == 'live':
                filename = f"{name_base}_live{idx}{ext}" if idx else sanitize_filename(desc, 150) + ext
            elif media_type == 'cover':
                filename = f"{name_base}_live{idx}_cover{ext}" if idx else sanitize_filename(desc, 150) + ext
            else:
                filename = f"{name_base}_{idx}{ext}" if idx else sanitize_filename(desc, 150) + ext
        else:
            if media_type == 'live':
                filename = f"live{idx}{ext}" if idx else sanitize_filename(desc, 150) + ext
            elif media_type == 'cover':
                filename = f"live{idx}_cover{ext}" if idx else sanitize_filename(desc, 150) + ext
            else:
                filename = f"{idx}{ext}" if idx else sanitize_filename(desc, 150) + ext
    else:
        base_filename = compute_base_filename(desc, date_str, include_date)
        folder = compute_download_folder('', mix_name, is_image)
        filename = sanitize_filename(base_filename, 150) + ext
    return os.path.join(folder, filename) if folder else filename


def compute_flat_mirror_path(task, mirror_base):
    """计算图集任务在扁平镜像目录中的完整目标路径。

    结构: mirror_base/图片/{date}_{desc}_{idx}{ext}（扁平，不建逐个图集子目录）
    mirror_base 通常为博主文件夹（作品下载/{博主}/），即扁平图集以博主为父级。
    与 build_expected_filename(flat_mode=True) 共用逻辑，保证路径一致。
    """
    expected = build_expected_filename(
        task.get('desc', ''), task.get('ext', ''), True,
        None, task.get('date', ''), task.get('include_date_in_filename', True),
        flat_mode=True,
    )
    return os.path.join(mirror_base, expected)


def mirror_file_to_flat(src_path, task, mirror_base):
    """将已下载的图集文件复制到扁平镜像目录（与原有结构并存）。

    返回 (dst_path, copied)：
      - copied=True  本次实际复制
      - copied=False 目标已存在（跳过）或失败（dst_path=None）
    """
    dst_path = compute_flat_mirror_path(task, mirror_base)
    if os.path.exists(dst_path):
        return dst_path, False
    dst_folder = os.path.dirname(dst_path)
    if not safe_mkdir(dst_folder):
        return None, False
    try:
        shutil.copy2(src_path, dst_path)  # copy2 保留修改时间
        return dst_path, True
    except Exception as e:
        print(f"[警告] 镜像复制失败: {src_path} -> {dst_path}: {e}")
        return None, False