#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
后台工作线程（用于 Fetch 和 Download）
"""
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
try:
    from PyQt6 import QtCore
except ImportError:
    print("[错误] PyQt6 未安装或无法导入: \n请安装 PyQt6 后重试（pip install PyQt6）。")
    sys.exit(1)
from douyin_downloader.constants import (
    TEXT_INFO_FETCH_PAGE, PAGE_COUNT_PER_REQUEST, MAX_RETRY_DELAY, USER_AGENT
)
from douyin_downloader.utils.file_utils import (
    build_expected_filename, update_author_folders_mtime,
    compute_flat_mirror_path, mirror_file_to_flat,
)
from urllib.parse import quote, urlencode
from douyin_downloader.core.api import (
    resolve_short_url_and_extract, get_user_profile_info,
    build_aweme_post_url, build_aweme_favorite_url,
    build_aweme_collect_url, api_request_with_retry
)
from douyin_downloader.core.abogus import ABogus
from douyin_downloader.core.parser import parse_all_awemes_to_tasks
from douyin_downloader.core.downloader import download_single_file
from douyin_downloader.core.exporter import generate_excel_file


class Worker(QtCore.QObject):
    """
    后台工作线程（用于 Fetch 和 Download）
    """
    log_signal = QtCore.pyqtSignal(str)
    progress_signal = QtCore.pyqtSignal(int, int)
    tasks_signal = QtCore.pyqtSignal(object, object, object, object)
    fetch_finished = QtCore.pyqtSignal()
    download_finished = QtCore.pyqtSignal()
    export_finished_signal = QtCore.pyqtSignal(str)
    export_error_signal = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pause_requested = False
        self._fetch_stop_requested = False  # 用户主动停止
        self._fetch_no_more_pages = False   # 筛选达标，正常结束翻页（非取消）
        self._download_stop_requested = False
        self._fetch_generation = 0
        
        self._failed_tasks = []
        self._completed_tasks = []
        self._total_received = 0
        self.all_awemes = []
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': USER_AGENT,
            'Referer': 'https://www.douyin.com/',
        })
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=retry_strategy,
        )
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)
        self.abogus = ABogus()
        self._download_tls = threading.local()

    def _clone_session(self):
        """复制一份独立 Session，供下载线程使用（requests.Session 非线程安全）"""
        session = requests.Session()
        session.headers.update(dict(self.session.headers))
        try:
            session.cookies.update(self.session.cookies)
        except Exception:
            pass
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(
            pool_connections=4,
            pool_maxsize=8,
            max_retries=retry_strategy,
        )
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        return session

    def _session_for_download_thread(self):
        """每个下载工作线程持有自己的 Session"""
        session = getattr(self._download_tls, 'session', None)
        if session is None:
            session = self._clone_session()
            self._download_tls.session = session
        return session

        
    def should_stop_download(self):
        """检查是否应该停止下载"""
        return getattr(self, '_download_stop_requested', False)
    
    def is_download_stopped(self):
        """检查下载是否已被用户停止"""
        return getattr(self, '_download_stop_requested', False)

    @staticmethod
    def _trim_aweme_for_storage(aweme):
        """精简 aweme 数据，仅保留 Excel 导出需要的字段"""
        return {
            'desc': aweme.get('desc', ''),
            'create_time': aweme.get('create_time', 0),
            'aweme_id': aweme.get('aweme_id', ''),
            'statistics': aweme.get('statistics', {}),
            'mix_info': aweme.get('mix_info'),
            'mix_name': aweme.get('mix_name'),
            'images': aweme.get('images') is not None,
            'video': {'duration': (aweme.get('video') or {}).get('duration', 0)},
            'author': aweme.get('author'),
        }

    def _is_my_fetch(self, gen):
        """检查当前线程的 fetch 代际是否仍然有效"""
        return self._fetch_generation == gen

    def fetch_tasks(self, url, cookie, fetch_mode='post', latest_only=False):
        """
        获取用户作品列表（在单独线程中运行）。
        采用分页增量方式，每获取一页就通过 tasks_signal 发回 GUI。
        fetch_mode: 'post' 获取主页作品, 'favorite' 获取点赞作品, 'collect' 获取收藏作品
        latest_only: True 时只获取第一页最新作品，不翻历史分页
        """
        # 递增代际，使旧 fetch 线程失效
        self._fetch_generation += 1
        my_gen = self._fetch_generation

        try:
            # 在当前线程内清理共享状态（避免依赖主线程）
            self.all_awemes = []
            self._total_received = 0

            headers = {'Cookie': cookie, 'Referer': url}
            self.session.headers.update(headers)

            if not self._is_my_fetch(my_gen):
                return
            _mode_labels = {'favorite': '点赞作品', 'collect': '收藏作品', 'post': '主页作品'}
            mode_label = _mode_labels.get(fetch_mode, '主页作品')
            if latest_only:
                self.log_signal.emit(f'[信息] 开始获取{mode_label}（仅最新一页）')
            else:
                self.log_signal.emit(f'[信息] 开始获取{mode_label}')

            sec = resolve_short_url_and_extract(url, session=self.session)
            if not sec:
                if self._is_my_fetch(my_gen):
                    self.log_signal.emit('[错误] 无法解析 sec_user_id')
                    self.finished.emit()
                return

            profile, error = get_user_profile_info(self.session, sec)
            if error:
                if self._is_my_fetch(my_gen):
                    self.log_signal.emit(f'[错误] 获取用户信息失败: {error}')
                    self.finished.emit()
                return
            nickname = profile.get('nickname', '') or ''
            unique_id = profile.get('unique_id', '') or ''
            if self._is_my_fetch(my_gen):
                self.log_signal.emit(f"[信息] 抖音用户: {nickname}")

            page = 1
            max_cursor = 0

            while True:
                if getattr(self, '_fetch_stop_requested', False):
                    if self._is_my_fetch(my_gen):
                        self.log_signal.emit('[信息] 获取已停止')
                    break
                if getattr(self, '_fetch_no_more_pages', False):
                    if self._is_my_fetch(my_gen):
                        self.log_signal.emit('[信息] 已达筛选条件，结束翻页')
                    break

                if not self._is_my_fetch(my_gen):
                    return

                if fetch_mode == 'favorite':
                    params, base_url = build_aweme_favorite_url(sec, max_cursor, PAGE_COUNT_PER_REQUEST)
                elif fetch_mode == 'collect':
                    params, base_url = build_aweme_collect_url(max_cursor, PAGE_COUNT_PER_REQUEST)
                else:
                    params, base_url = build_aweme_post_url(sec, max_cursor, PAGE_COUNT_PER_REQUEST, page == 1)
                a_bogus = quote(self.abogus.get_value(params), safe='')
                params['a_bogus'] = a_bogus
                req_url = base_url + '?' + urlencode(params)

                try:
                    req_start = time.time()
                    r = api_request_with_retry(self.session, req_url)
                    if getattr(self, '_fetch_stop_requested', False):
                        if self._is_my_fetch(my_gen):
                            self.log_signal.emit('[信息] 获取已停止')
                        break
                    if getattr(self, '_fetch_no_more_pages', False):
                        if self._is_my_fetch(my_gen):
                            self.log_signal.emit('[信息] 已达筛选条件，结束翻页')
                        break
                    if not self._is_my_fetch(my_gen):
                        return
                    data = r.json()
                except requests.HTTPError as e:
                    status = getattr(getattr(e, 'response', None), 'status_code', None)
                    if status == 403:
                        # 抖音 Argus 风控：点赞/收藏等接口要求浏览器级设备签名
                        if self._is_my_fetch(my_gen):
                            self.log_signal.emit(
                                '[错误] 接口被抖音风控拦截（HTTP 403）：'
                                '该接口当前要求浏览器级设备签名，暂不可用。'
                                '可尝试更换网络环境或稍后重试；主页作品/关注列表不受影响。'
                            )
                        break
                    if self._is_my_fetch(my_gen):
                        self.log_signal.emit(f"[警告] 第 {page} 页请求异常: {e}")
                    break
                except Exception as e:
                    if self._is_my_fetch(my_gen):
                        self.log_signal.emit(f"[警告] 第 {page} 页请求异常: {e}")
                    break

                aweme_list = data.get('aweme_list', []) or []
                if not aweme_list:
                    break

                vtasks, itasks, _, _, _ = parse_all_awemes_to_tasks(aweme_list)

                if not self._is_my_fetch(my_gen):
                    return
                self.all_awemes.extend(aweme_list)

                if self._is_my_fetch(my_gen):
                    try:
                        user_info = f"{nickname}|{unique_id}"
                        self.tasks_signal.emit(vtasks, itasks, user_info, aweme_list)
                    except Exception as e:
                        self.log_signal.emit(f"[警告] tasks_signal.emit 失败: {e}")

                if self._is_my_fetch(my_gen):
                    self._total_received += len(aweme_list)
                    self.log_signal.emit(TEXT_INFO_FETCH_PAGE.format(page=page, count=len(aweme_list), total=self._total_received))

                new_cursor = data.get('max_cursor', 0)
                if new_cursor in (0, None, ''):
                    # 收藏接口用 cursor 字段（可能为字符串）
                    new_cursor = data.get('cursor', 0) or 0
                try:
                    new_cursor = int(new_cursor)
                except (TypeError, ValueError):
                    new_cursor = 0
                has_more = data.get('has_more', 0) == 1
                if fetch_mode == 'collect' and has_more and new_cursor <= max_cursor:
                    # 游标未推进，避免死循环
                    if self._is_my_fetch(my_gen):
                        self.log_signal.emit('[信息] 收藏列表游标未推进，结束翻页')
                    break
                max_cursor = new_cursor
                page += 1

                # 自适应延迟：根据响应时间调整等待
                elapsed = time.time() - req_start
                adaptive_delay = max(0.1, min(1.0, elapsed * 0.5))
                time.sleep(adaptive_delay)

                if latest_only:
                    if self._is_my_fetch(my_gen):
                        self.log_signal.emit('[信息] 仅最新模式：已获取第一页，停止翻页')
                    break

                if not has_more:
                    break
            
            # 精简 aweme 数据（仅当前代际有效）
            if self._is_my_fetch(my_gen):
                self.all_awemes = [self._trim_aweme_for_storage(a) for a in self.all_awemes]
                self.log_signal.emit('[完成] 获取完成')

        except Exception as e:
            if self._is_my_fetch(my_gen):
                self.log_signal.emit(f"[错误] 获取异常: {e}")
        finally:
            if self._is_my_fetch(my_gen):
                try:
                    self.fetch_finished.emit()
                except Exception:
                    pass
                self.finished.emit()

    def _download_with_retry(self, task, base_folder, is_image, max_retries, session=None):
        """
        带重试机制的下载函数，视频任务依次尝试不同码率。
        session 默认在当前线程内懒创建，保证线程池中各 worker 互不共享。
        """
        if session is None:
            session = self._session_for_download_thread()

        is_video_task = not is_image and 'aweme' in task

        bitrate_urls = []
        if is_video_task:
            aweme_data = task.get('aweme', {})
            video_info = aweme_data.get('video', {})
            rates = video_info.get('bit_rate', [])
            if rates:
                sorted_rates = sorted(rates, key=lambda x: x.get('bit_rate', 0), reverse=True)
                for rate_info in sorted_rates:
                    url_list = rate_info.get('play_addr', {}).get('url_list', [])
                    if url_list:
                        bitrate_urls.append(url_list[0])

        for attempt in range(max_retries + 1):
            if self.should_stop_download():
                return "__STOPPED__"

            if attempt > 0 and attempt <= len(bitrate_urls):
                task['url'] = bitrate_urls[attempt - 1]
                self.log_signal.emit(f"[信息] {task['desc']} 尝试第{attempt + 1}个码率")

            try:
                result = download_single_file(task, base_folder, is_image, self, session)
                if result:
                    if attempt > 0:
                        print(f"[重试成功] {task['desc']} (尝试 {attempt + 1} 次)")
                    return result

                if self.should_stop_download():
                    return "__STOPPED__"

                if attempt < max_retries:
                    delay = min(2 ** attempt, MAX_RETRY_DELAY)
                    time.sleep(delay)
                    if self.should_stop_download():
                        return "__STOPPED__"
            except Exception as e:
                if "下载被用户终止" in str(e):
                    return "__STOPPED__"

                if attempt < max_retries:
                    delay = min(2 ** attempt, MAX_RETRY_DELAY)
                    time.sleep(delay)
                    if self.should_stop_download():
                        return "__STOPPED__"
                else:
                    return None
        return None

    def download_tasks(self, vtasks, itasks, base_folder, threads):
        """
        执行下载任务（在单独线程中运行）。
        使用线程池并发下载。
        """
        try:
            self.log_signal.emit('[信息] 检查已存在文件...')
            self._failed_tasks = []
            self._completed_tasks = []
            # 新一轮下载重建线程局部 Session，带上最新 Cookie/Headers
            self._download_tls = threading.local()
            all_tasks = []
            results_success_files = set()
            
            for t in vtasks:
                if self.should_stop_download():
                    self.log_signal.emit('[信息] 下载任务已被用户终止')
                    return
                
                include_date = t.get('include_date_in_filename', True)
                date_str = t.get('date', '')
                expected = build_expected_filename(t['desc'], t['ext'], False, t.get('mix_name'), date_str, include_date)

                fullpath = os.path.join(t.get('base_folder', base_folder), expected)
                if os.path.exists(fullpath):
                    self.log_signal.emit(f"[跳过] 已存在: {expected}")
                    results_success_files.add(expected)
                    rec = {'task': t, 'is_image': False, 'path': expected}
                    self._completed_tasks.append(rec)
                else:
                    all_tasks.append((t, False)) # (task, is_image=False)
            
            for t in itasks:
                if self.should_stop_download():
                    self.log_signal.emit('[信息] 下载任务已被用户终止')
                    return
                
                include_date = t.get('include_date_in_filename', True)
                date_str = t.get('date', '')
                expected = build_expected_filename(t['desc'], t['ext'], True, t.get('mix_name'), date_str, include_date)

                fullpath = os.path.join(t.get('base_folder', base_folder), expected)
                if os.path.exists(fullpath):
                    # 原有结构已存在 → 检查扁平镜像是否需要补齐
                    mirror_base = t.get('flat_mirror_folder')
                    if mirror_base:
                        mp = compute_flat_mirror_path(t, mirror_base)
                        if not os.path.exists(mp):
                            dst, copied = mirror_file_to_flat(fullpath, t, mirror_base)
                            if copied and dst:
                                self.log_signal.emit(f"[镜像] 已复制到扁平目录: {os.path.basename(dst)}")
                    self.log_signal.emit(f"[跳过] 已存在: {expected}")
                    results_success_files.add(expected)
                    rec = {'task': t, 'is_image': True, 'path': expected}
                    self._completed_tasks.append(rec)
                else:
                    all_tasks.append((t, True)) # (task, is_image=True)

            total_files = len(vtasks) + len(itasks)
            total = len(all_tasks)
            done = max(0, total_files - total)  # 已存在跳过计入进度
            
            if total_files > 0:
                self.progress_signal.emit(done, total_files)

            if total == 0:
                self.log_signal.emit('[信息] 没有需要下载的新文件。')
                self.progress_signal.emit(max(1, total_files), max(1, total_files))
                n = update_author_folders_mtime(list(vtasks) + list(itasks), base_folder)
                if n:
                    self.log_signal.emit(f'[信息] 已更新 {n} 个作者文件夹的修改时间为最新作品时间')
                self.download_finished.emit()
                self.finished.emit()
                return

            MAX_RETRIES = 3
            
            with ThreadPoolExecutor(max_workers=threads) as ex:
                future_map = {}
                submitted_futures = []
                
                # 提交任务
                for t, is_img in all_tasks:
                    if self.should_stop_download():
                        self.log_signal.emit('[信息] 下载任务已被用户终止')
                        return

                    while getattr(self, '_pause_requested', False):
                        if self.should_stop_download():
                            self.log_signal.emit('[信息] 下载任务已被用户终止')
                            return
                        time.sleep(0.1)
                    
                    future = ex.submit(
                        self._download_with_retry,
                        t,
                        t.get('base_folder', base_folder),
                        is_img,
                        MAX_RETRIES,
                    )
                    future_map[future] = (t, is_img)
                    submitted_futures.append(future)
                
                completed_count = 0
                for future in as_completed(submitted_futures):
                    completed_count += 1
                    if completed_count % 5 == 0:
                        if self.should_stop_download():
                            self.log_signal.emit('[信息] 下载任务已被用户终止')
                            return

                    t, is_img = future_map[future]
                    try:
                        if self.should_stop_download():
                            self.log_signal.emit('[信息] 下载任务已被用户终止')
                            return
                        result = future.result()

                        if result == "__STOPPED__":
                            pass
                        elif result:
                            results_success_files.add(result)
                            rec = {'task': t, 'is_image': is_img, 'path': result}
                            self._completed_tasks.append(rec)
                            done += 1
                            self.log_signal.emit(f"[完成] {result}")

                            self.progress_signal.emit(done, max(1, total_files))
                        else:
                            err = t.get('_error', '')
                            self.log_signal.emit(f"[失败] {t['desc']} - URL: {t['url']}" + (f" ({err})" if err else ""))
                            self._failed_tasks.append(t)
                            done += 1
                            self.progress_signal.emit(done, max(1, total_files))
                    except Exception as e:
                        self.log_signal.emit(f"[失败] {t['desc']} - URL: {t['url']} ({e})")
                        self._failed_tasks.append(t)
                        done += 1
                        self.progress_signal.emit(done, max(1, total_files))
            
            self.progress_signal.emit(max(1, total_files), max(1, total_files))

            normalized_base_folder = base_folder.replace('\\', '/').replace('\\', '/')
            self.log_signal.emit(f"[日志] 本次成功下载文件 {len(results_success_files)} 个（目录: {normalized_base_folder}）")

            n = update_author_folders_mtime(list(vtasks) + list(itasks), base_folder)
            if n:
                self.log_signal.emit(f'[信息] 已更新 {n} 个作者文件夹的修改时间为最新作品时间')

            self.download_finished.emit()

            if self.should_stop_download():
                self.log_signal.emit('[信息] 下载任务已被用户终止')
                return

        except Exception as e:
            # 在处理异常时检查是否需要停止
            if self.should_stop_download():
                self.log_signal.emit('[信息] 下载任务已被用户终止')
                return
            self.log_signal.emit(f"[错误] 下载异常: {e}")
        finally:
            if self.should_stop_download():
                try:
                    self.download_finished.emit()
                except:
                    pass
            self.finished.emit()
    
    def export_excel(self, all_awemes, nickname, base_folder):
        """
        在后台线程中执行Excel导出 (包装器)。
        调用核心函数，并根据结果发出PyQt信号。
        """
        try:
            filepath = generate_excel_file(all_awemes, nickname, base_folder)

            self.export_finished_signal.emit(filepath)

        except Exception as e:
            self.export_error_signal.emit(str(e))