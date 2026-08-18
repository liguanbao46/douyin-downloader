# -*- coding: utf-8 -*-
import os
import tempfile
import time

from douyin_downloader.utils.file_utils import set_folder_mtime, update_author_folders_mtime


def test_set_folder_mtime_fresh_dir_uses_publish_time():
    with tempfile.TemporaryDirectory() as tmp:
        folder = os.path.join(tmp, 'author')
        os.makedirs(folder)
        publish = 1700000000
        assert set_folder_mtime(folder, publish) is True
        assert int(os.stat(folder).st_mtime) == publish


def test_set_folder_mtime_keeps_newer_existing():
    with tempfile.TemporaryDirectory() as tmp:
        folder = os.path.join(tmp, 'author')
        os.makedirs(folder)
        older = 1600000000
        newer = 1700000000
        # 先写成较旧时间，再假装目录不是「刚创建」：把 mtime 拨到较新但远早于 now
        os.utime(folder, (newer, newer))
        # 绕过「2 分钟内刚创建」分支：把 cur 设为 now-300，再调用时用更旧的 publish
        past = int(time.time()) - 300
        os.utime(folder, (past, past))
        assert set_folder_mtime(folder, older) is True
        assert int(os.stat(folder).st_mtime) == past


def test_update_author_folders_mtime_picks_latest_per_folder():
    with tempfile.TemporaryDirectory() as tmp:
        a = os.path.join(tmp, 'a')
        b = os.path.join(tmp, 'b')
        os.makedirs(a)
        os.makedirs(b)
        tasks = [
            {'base_folder': a, 'create_time': 100},
            {'base_folder': a, 'create_time': 300},
            {'base_folder': b, 'create_time': 200},
            {'base_folder': '', 'create_time': 999},  # 用 fallback
        ]
        n = update_author_folders_mtime(tasks, fallback_folder=b)
        assert n == 2
        assert int(os.stat(a).st_mtime) == 300
        assert int(os.stat(b).st_mtime) == 999
