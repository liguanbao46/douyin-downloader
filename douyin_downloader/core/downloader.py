#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
下载引擎 - 单文件下载（支持断点续传）
"""
import os

import requests

from douyin_downloader.constants import DOWNLOAD_CHUNK_SIZE
from douyin_downloader.utils.file_utils import (
    safe_mkdir, generate_unique_filename, sanitize_filename,
    compute_download_folder, compute_base_filename, _extract_image_parts,
    mirror_file_to_flat,
)
from douyin_downloader.gui import cfg


def _set_file_mtime(path, create_time):
    """将文件的访问时间和修改时间设为 create_time（Unix 时间戳）"""
    if not create_time or create_time <= 0:
        return
    try:
        os.utime(path, (create_time, create_time))
    except Exception:
        pass  # 设置时间失败不影响下载结果


def _mirror_if_needed(task, path, worker=None):
    """图集扁平镜像：下载成功后复制一份到独立扁平目录（与原有结构并存）"""
    mirror_base = task.get('flat_mirror_folder')
    if not mirror_base:
        return
    dst, copied = mirror_file_to_flat(path, task, mirror_base)
    if copied and dst and worker:
        try:
            worker.log_signal.emit(f"[镜像] 已同步到扁平目录: {os.path.basename(dst)}")
        except Exception:
            pass


def download_single_file(task, base_folder, is_image=False, worker=None, session=None):
    """
    下载单个文件（视频或图片/实况图），支持断点续传。
    由 `Worker.download_tasks` 在线程池中调用。
    """
    url = task['url']
    desc = task['desc']
    ext = task['ext']
    mix_name = task.get('mix_name') or None
    create_time = task.get('create_time', 0)
    set_mtime = bool(cfg.get('set_file_time_to_publish_time', False))

    include_date = task.get('include_date_in_filename', True)
    date_str = task.get('date', '')

    # 1. 确定目标文件夹和文件名（与 build_expected_filename 共用逻辑）
    if is_image:
        base_desc, idx, media_type = _extract_image_parts(desc)
        folder = compute_download_folder(base_folder, mix_name, is_image, base_desc, date_str, include_date)
        if media_type == 'live':
            base_filename = f"live{idx}" if idx else desc
        elif media_type == 'cover':
            base_filename = f"live{idx}_cover" if idx else desc
        else:
            base_filename = str(idx) if idx else desc
    else:
        folder = compute_download_folder(base_folder, mix_name, is_image)
        base_filename = compute_base_filename(desc, date_str, include_date)

    if not safe_mkdir(folder):
        task['_error'] = f'创建目录失败: {folder}'
        return None

    # 2. 生成唯一文件名
    path = generate_unique_filename(base_filename, ext, folder, url, task.get('url_hash'))
    tmp_path = path + '.tmp'

    # 3. 获取 session
    s = session or requests.Session()
    headers = {}

    # 4. 检查是否有未完成的下载（断点续传）
    existing_size = 0
    if os.path.exists(tmp_path):
        existing_size = os.path.getsize(tmp_path)
        if existing_size > 0:
            headers['Range'] = f'bytes={existing_size}-'

    try:
        with s.get(url, headers=headers, stream=True, timeout=30) as r:
            if r.status_code == 416:  # Range Not Satisfiable — 文件已完整
                os.replace(tmp_path, path)
                if set_mtime:
                    _set_file_mtime(path, create_time)
                _mirror_if_needed(task, path, worker)
                return os.path.relpath(path, base_folder)

            if r.status_code not in (200, 206):
                r.raise_for_status()

            # 206 = 服务器支持断点续传，200 = 从头开始
            mode = 'ab' if r.status_code == 206 else 'wb'
            if mode == 'wb' and existing_size > 0:
                existing_size = 0  # 服务器不支持续传，重置

            with open(tmp_path, mode) as f:
                for chunk in r.iter_content(DOWNLOAD_CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
                        if worker and worker.should_stop_download():
                            raise SystemExit("下载被用户终止")

        # 下载完成，原子替换
        os.replace(tmp_path, path)
        if set_mtime:
            _set_file_mtime(path, create_time)
        _mirror_if_needed(task, path, worker)
        return os.path.relpath(path, base_folder)

    except SystemExit:
        # 用户取消 —— 保留 .tmp 以便下次续传
        return None
    except Exception as e:
        # 其他错误 —— 保留 .tmp 以便下次续传，记录原因供 worker 日志使用
        task['_error'] = str(e)
        return None
