#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GUI - 增强版主页列表（内嵌页面）
展示已保存用户的完整统计数据。
"""
import sys
import threading
try:
    from PyQt6 import QtWidgets, QtCore, QtGui
    from PyQt6.QtCore import Qt
except ImportError:
    print("[错误] PyQt6 未安装或无法导入: \n请安装 PyQt6 后重试（pip install PyQt6）。")
    sys.exit(1)

import requests
from douyin_downloader.gui import cfg
from douyin_downloader.utils.config import save_config
from douyin_downloader.core.api import extract_sec_user_id_from_url
from douyin_downloader.constants import USER_AGENT
from douyin_downloader.core.abogus import ABogus
from .widgets import NoFocusRectStyle, attach_header_checkbox
from .widget_extract_filters import ExtractFilterPanel


class _ProfileBatchWorker(QtCore.QObject):
    """后台批量拉取用户资料"""
    progress = QtCore.pyqtSignal(int, int, str)
    finished = QtCore.pyqtSignal(object)

    def run(self, sec_ids, cookie):
        results = []
        total = len(sec_ids)
        for i, sec in enumerate(sec_ids):
            self.progress.emit(i + 1, total, sec)
            profile, error = UserListWindow.fetch_profile_static(sec, cookie)
            results.append((sec, profile, error))
        self.finished.emit(results)


class UserListWindow(QtWidgets.QWidget):
    """增强版主页列表页面 — 展示用户完整统计（嵌入主窗口）"""

    # 列定义：(列名, 数据key, 对齐方式)
    COLS = [
        ('选择', None, 'center'),
        ('序号', '_idx', 'center'),
        ('分组', 'group', 'left'),
        ('作者', 'username', 'left'),
        ('关注数量', 'following_count', 'right'),
        ('粉丝数量', 'follower_count', 'right'),
        ('获赞数量', 'total_favorited', 'right'),
        ('喜欢数量', 'favoriting_count', 'right'),
        ('作品数量', 'aweme_count', 'right'),
        ('最后发布作品时间', 'last_publish_time', 'center'),
        ('监控', 'monitor', 'center'),
    ]
    COL_MONITOR = 10
    COL_GROUP = 2
    COL_AUTHOR = 3

    def __init__(self, parent=None, checkmark_svg_path=''):
        super().__init__(parent)
        self.checkmark_svg_path = checkmark_svg_path
        self._busy = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 工具栏
        toolbar = QtWidgets.QHBoxLayout()
        self.add_btn = QtWidgets.QPushButton('+ 添加主页')
        self.batch_import_btn = QtWidgets.QPushButton('批量导入')
        self.import_following_btn = QtWidgets.QPushButton('导入关注')
        self.refresh_stats_btn = QtWidgets.QPushButton('刷新数据')
        self.set_group_btn = QtWidgets.QPushButton('设置分组')
        self.fetch_works_btn = QtWidgets.QPushButton('提取作品')
        self.fetch_works_btn.setObjectName('primary_btn')
        self.select_all_btn = QtWidgets.QPushButton('全选')
        self.delete_btn = QtWidgets.QPushButton('删除')
        self.export_btn = QtWidgets.QPushButton('导出列表')

        toolbar.addWidget(self.add_btn)
        toolbar.addWidget(self.batch_import_btn)
        toolbar.addWidget(self.import_following_btn)
        toolbar.addWidget(self.refresh_stats_btn)
        toolbar.addWidget(self.set_group_btn)
        toolbar.addWidget(self.fetch_works_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.select_all_btn)
        toolbar.addWidget(self.export_btn)
        toolbar.addWidget(self.delete_btn)
        layout.addLayout(toolbar)

        # 表格
        self.user_tree = QtWidgets.QTreeWidget()
        self.user_tree.setStyle(NoFocusRectStyle())
        headers = ['' if i == 0 else c[0] for i, c in enumerate(self.COLS)]
        self.user_tree.setHeaderLabels(headers)
        self.user_tree.setRootIsDecorated(False)
        self.user_tree.setUniformRowHeights(True)
        self.user_tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.user_tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.user_tree.setAttribute(QtCore.Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.user_tree.setAlternatingRowColors(True)

        fm = self.user_tree.fontMetrics()
        width0 = fm.horizontalAdvance('选择') + 16
        width_mon = fm.horizontalAdvance('监控') + 16
        col_widths = [width0, 50, 70, 120, 80, 80, 80, 80, 80, 150, width_mon]
        for i, w in enumerate(col_widths):
            if i < self.user_tree.columnCount():
                self.user_tree.setColumnWidth(i, w)

        header = self.user_tree.header()
        if header:
            header.setSectionResizeMode(self.COL_AUTHOR, QtWidgets.QHeaderView.ResizeMode.Stretch)  # 作者列拉伸
            header.setSectionsMovable(False)
            header.setStretchLastSection(False)
            header.setSectionsClickable(True)
            header.setSortIndicatorShown(True)
            header.sectionClicked.connect(self.on_header_section_clicked)

        self._sort_column = -1
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._programmatic_change = False

        self.header_select_all, self._reposition_header_select_all = attach_header_checkbox(
            self.user_tree, self.checkmark_svg_path, tooltip='全选 / 取消全选'
        )
        self.header_select_all.clicked.connect(self.on_header_select_all_clicked)

        layout.addWidget(self.user_tree, 1)

        # 底部状态栏
        status_bar = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel('')
        status_bar.addWidget(self.status_label)
        status_bar.addStretch()
        layout.addLayout(status_bar)

        # 提取筛选条件（放在主页列表下方）
        self.filter_panel = ExtractFilterPanel(self)
        layout.addWidget(self.filter_panel)
        # 信号连接
        self.add_btn.clicked.connect(self.on_add_user)
        self.batch_import_btn.clicked.connect(self.on_batch_import)
        self.import_following_btn.clicked.connect(self.on_import_following)
        self.refresh_stats_btn.clicked.connect(self.on_refresh_stats)
        self.set_group_btn.clicked.connect(self.on_set_group)
        self.fetch_works_btn.clicked.connect(self.on_fetch_checked)
        self.delete_btn.clicked.connect(self.on_delete)
        self.export_btn.clicked.connect(self.on_export)
        self.select_all_btn.clicked.connect(self.on_select_all)
        self.user_tree.itemSelectionChanged.connect(self.on_selection_changed)
        self.user_tree.itemDoubleClicked.connect(self.on_double_click_item)
        self.user_tree.itemChanged.connect(self.on_item_changed)

        # 样式主体继承 app.py 全局 Apple 设计体系，这里只做页面级覆盖：
        # 页面浅灰底（与作品页一致）、主操作按钮、树行高
        self.setStyleSheet("""
            UserListWindow {
                background-color: #F2F2F7;
            }
            QTreeWidget {
                gridline-color: #F2F2F7;
                show-decoration-selected: 0;
            }
            QTreeWidget::item {
                height: 28px;
            }
            QPushButton#primary_btn {
                background-color: #007AFF;
                color: #FFFFFF;
                border-radius: 12px;
            }
            QPushButton#primary_btn:hover { background-color: #0064D6; }
            QPushButton#primary_btn:pressed { background-color: #004FAD; }
            QPushButton#primary_btn:disabled { background-color: #9FCBFF; color: #FFFFFF; }
            QLabel {
                background-color: transparent;
                color: #6E6E73;
                font-size: 12px;
            }
        """)

        self.load_users()

    def _set_busy(self, busy):
        self._busy = busy
        for btn in (
            self.add_btn, self.batch_import_btn, self.import_following_btn,
            self.refresh_stats_btn,
            self.set_group_btn, self.fetch_works_btn, self.delete_btn,
            self.export_btn, self.select_all_btn,
        ):
            btn.setEnabled(not busy)

    def _fmt_num(self, val):
        """格式化数字显示"""
        if val is None or val == '':
            return '-'
        try:
            n = int(val)
            if n >= 10000:
                return f'{n / 10000:.1f}万'
            return str(n)
        except (ValueError, TypeError):
            return str(val or '-')

    def load_users(self):
        """加载用户列表到表格"""
        self._programmatic_change = True
        try:
            self._load_users_impl()
        finally:
            self._programmatic_change = False

    def _load_users_impl(self):
        """加载用户列表到表格（实现）"""
        self.user_tree.clear()
        users = cfg.get('users', [])
        updated = False

        # 标准化 URL
        for user in users:
            original_url = user.get('url', '')
            if original_url and not original_url.startswith('https://www.douyin.com/user/'):
                sec_user_id = extract_sec_user_id_from_url(original_url)
                if sec_user_id:
                    normalized_url = f"https://www.douyin.com/user/{sec_user_id}"
                    if original_url != normalized_url:
                        user['url'] = normalized_url
                        updated = True

        if updated:
            cfg['users'] = users
            save_config(cfg)

        for idx, user in enumerate(users, start=1):
            user['_idx'] = idx
            values = []
            for col_idx, (col_name, key, align) in enumerate(self.COLS):
                if col_idx == 0 or col_idx == self.COL_MONITOR:
                    values.append(' ')
                elif key == '_idx':
                    values.append(str(idx))
                else:
                    val = user.get(key, '')
                    if key in ('following_count', 'follower_count', 'total_favorited',
                               'favoriting_count', 'aweme_count'):
                        values.append(self._fmt_num(val))
                    elif key == 'monitor':
                        values.append(' ')
                    else:
                        values.append(str(val or ''))

            item = QtWidgets.QTreeWidgetItem(values)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setCheckState(
                self.COL_MONITOR,
                Qt.CheckState.Checked if user.get('monitor') else Qt.CheckState.Unchecked,
            )
            item.setData(0, Qt.ItemDataRole.UserRole, user)
            self.user_tree.addTopLevelItem(item)

        total = len(users)
        monitored = sum(1 for u in users if u.get('monitor'))
        if monitored:
            self.status_label.setText(f'共 {total} 个主页，监控中 {monitored} 人')
        else:
            self.status_label.setText(f'共 {total} 个主页')
        self.sync_header_select_all()
        if hasattr(self, '_reposition_header_select_all'):
            self._reposition_header_select_all()

    def on_header_section_clicked(self, logical_index):
        """表头点击排序（选择列除外）；同列再次点击切换升/降序"""
        if logical_index == 0:
            return
        if self._sort_column == logical_index:
            if self._sort_order == Qt.SortOrder.AscendingOrder:
                self._sort_order = Qt.SortOrder.DescendingOrder
            else:
                self._sort_order = Qt.SortOrder.AscendingOrder
        else:
            self._sort_column = logical_index
            self._sort_order = Qt.SortOrder.AscendingOrder

        self.sort_users_by_column(self._sort_column, self._sort_order)
        header = self.user_tree.header()
        if header:
            header.setSortIndicator(self._sort_column, self._sort_order)

    def _user_sort_key(self, item, column):
        """按列计算排序键（数值列用原始数字，避免「1.2万」字符串误序）"""
        user = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if column >= len(self.COLS):
            return item.text(column) or ''
        _name, key, _align = self.COLS[column]
        if key == '_idx':
            try:
                return int(item.text(1))
            except (TypeError, ValueError):
                return 0
        if key in ('following_count', 'follower_count', 'total_favorited',
                   'favoriting_count', 'aweme_count'):
            val = user.get(key)
            if val is None or val == '':
                return -1
            try:
                return int(val)
            except (TypeError, ValueError):
                return -1
        if key == 'last_publish_time':
            return user.get(key) or ''
        if key == 'monitor':
            return 1 if user.get('monitor') else 0
        if key == 'group':
            return (user.get('group') or '').lower()
        if key == 'username':
            return (user.get('username') or '').lower()
        return str(user.get(key) or item.text(column) or '')

    def sort_users_by_column(self, column, order):
        """按指定列排序主页列表，并重写序号"""
        count = self.user_tree.topLevelItemCount()
        if count <= 1:
            return

        reverse = order == Qt.SortOrder.DescendingOrder
        self.user_tree.setUpdatesEnabled(False)
        try:
            items = [self.user_tree.takeTopLevelItem(0) for _ in range(count)]
            items.sort(key=lambda it: self._user_sort_key(it, column), reverse=reverse)
            for i, item in enumerate(items, start=1):
                item.setText(1, str(i))
                user = item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(user, dict):
                    user['_idx'] = i
            self.user_tree.addTopLevelItems(items)
        finally:
            self.user_tree.setUpdatesEnabled(True)

    @staticmethod
    def fetch_profile_static(sec_user_id, cookie):
        """独立 session 拉取用户资料（可在后台线程调用）"""
        if not cookie:
            return None, '未配置 Cookie，请先在设置中粘贴 Cookie'

        from douyin_downloader.core.api import (
            get_user_profile_info, build_aweme_post_url, api_request_with_retry,
        )
        from urllib.parse import quote, urlencode

        session = requests.Session()
        referer = f'https://www.douyin.com/user/{sec_user_id}'
        session.headers.update({
            'User-Agent': USER_AGENT,
            'Cookie': cookie,
            'Referer': referer,
        })

        try:
            profile, error = get_user_profile_info(session, sec_user_id)
            if not profile or error:
                return None, error or 'API 未返回有效数据'
        except Exception as e:
            return None, f'获取用户资料异常: {e}'

        try:
            abogus = ABogus()
            params, base_url = build_aweme_post_url(sec_user_id, 0, 10, True)
            a_bogus = quote(abogus.get_value(params), safe='')
            params['a_bogus'] = a_bogus
            req_url = base_url + '?' + urlencode(params)
            r = api_request_with_retry(session, req_url, max_retries=1)
            data = r.json()
            aweme_list = data.get('aweme_list', []) or []
            if aweme_list:
                timestamps = [a.get('create_time', 0) or 0 for a in aweme_list]
                max_ts = max(t for t in timestamps if t > 0) if any(t > 0 for t in timestamps) else 0
                if max_ts:
                    from datetime import datetime as dt
                    profile['last_publish_time'] = dt.fromtimestamp(max_ts).strftime('%Y-%m-%d %H:%M:%S')
                else:
                    profile['last_publish_time'] = ''
                if not profile.get('aweme_count'):
                    profile['aweme_count'] = len(aweme_list)
            else:
                profile['last_publish_time'] = ''
        except Exception as e:
            print(f'[警告] 获取最新作品时间失败: {e}')

        return profile, None

    def _fetch_profile_for_sec(self, sec_user_id):
        """兼容旧调用"""
        return self.fetch_profile_static(sec_user_id, cfg.get('cookie', ''))

    def _apply_profile_to_entry(self, entry, profile):
        for k in ('nickname', 'following_count', 'follower_count',
                  'total_favorited', 'favoriting_count', 'aweme_count',
                  'last_publish_time'):
            if k in profile:
                entry[k] = profile[k]
        if not entry.get('username') and profile.get('nickname'):
            entry['username'] = profile['nickname']

    def on_add_user(self):
        """手动添加主页链接（添加后自动获取资料数据）"""
        if self._busy:
            return
        url, ok = QtWidgets.QInputDialog.getText(
            self, '添加主页', '请输入抖音用户主页链接：',
            text='https://www.douyin.com/user/'
        )
        if not ok or not url.strip():
            return

        url = url.strip()
        sec_user_id = extract_sec_user_id_from_url(url)
        if not sec_user_id:
            QtWidgets.QMessageBox.warning(self, '错误', '无法从链接中提取用户ID，请检查链接是否正确。')
            return

        normalized_url = f"https://www.douyin.com/user/{sec_user_id}"

        users = cfg.get('users', [])
        for u in users:
            existing_sec = extract_sec_user_id_from_url(u.get('url', ''))
            if existing_sec == sec_user_id:
                QtWidgets.QMessageBox.information(self, '提示', '该主页已在列表中。')
                return

        cookie = cfg.get('cookie', '')
        entry = {
            'username': '', 'url': normalized_url, 'group': '',
            'sec_user_id': sec_user_id,
        }

        self._set_busy(True)
        self.status_label.setText('正在获取资料...')
        worker = _ProfileBatchWorker(self)

        def _done(results):
            self._set_busy(False)
            _sec, profile, error = results[0]
            if profile:
                self._apply_profile_to_entry(entry, profile)
            users_now = cfg.get('users', [])
            users_now.append(entry)
            cfg['users'] = users_now
            save_config(cfg)
            self.load_users()
            if profile:
                self.status_label.setText(f'已添加并获取资料: {entry.get("username") or sec_user_id}')
            else:
                self.status_label.setText(f'已添加主页（未获取到资料: {error}）')

        worker.finished.connect(_done)
        threading.Thread(
            target=worker.run, args=([sec_user_id], cookie), daemon=True
        ).start()

    def on_batch_import(self):
        """批量导入主页链接（每行一个链接，自动获取资料）"""
        if self._busy:
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('批量导入主页')
        dialog.resize(500, 300)
        dl = QtWidgets.QVBoxLayout(dialog)
        dl.addWidget(QtWidgets.QLabel('每行粘贴一个抖音主页链接：'))
        text_edit = QtWidgets.QPlainTextEdit()
        text_edit.setPlaceholderText(
            'https://www.douyin.com/user/MS4w...\n'
            'https://www.douyin.com/user/MS4w...'
        )
        dl.addWidget(text_edit)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QtWidgets.QPushButton('导入')
        cancel_btn = QtWidgets.QPushButton('取消')
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        dl.addLayout(btn_row)
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)

        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        lines = [l.strip() for l in text_edit.toPlainText().splitlines() if l.strip()]
        if not lines:
            return

        users = cfg.get('users', [])
        existing_secs = {extract_sec_user_id_from_url(u.get('url', '')) for u in users}
        new_secs = []
        for line in lines:
            sec = extract_sec_user_id_from_url(line)
            if sec and sec not in existing_secs:
                new_secs.append(sec)
                existing_secs.add(sec)

        if not new_secs:
            QtWidgets.QMessageBox.information(self, '提示', '没有新的主页需要导入（链接无效或已存在）')
            return

        cookie = cfg.get('cookie', '')
        self._set_busy(True)
        worker = _ProfileBatchWorker(self)

        def _on_progress(i, total, _sec):
            self.status_label.setText(f'正在获取 {i}/{total} ...')

        def _done(results):
            users_now = cfg.get('users', [])
            success = 0
            failed = 0
            for sec, profile, error in results:
                entry = {
                    'username': '', 'url': f'https://www.douyin.com/user/{sec}',
                    'group': '', 'sec_user_id': sec,
                }
                if profile:
                    self._apply_profile_to_entry(entry, profile)
                    success += 1
                else:
                    failed += 1
                users_now.append(entry)
            cfg['users'] = users_now
            save_config(cfg)
            self.load_users()
            self._set_busy(False)
            self.status_label.setText(f'批量导入完成: 成功 {success} 个, 失败 {failed} 个')

        worker.progress.connect(_on_progress)
        worker.finished.connect(_done)
        threading.Thread(
            target=worker.run, args=(new_secs, cookie), daemon=True
        ).start()

    def on_import_following(self):
        """打开关注列表导入窗口"""
        if self._busy:
            return
        from .dialog_following import FollowingImportWindow
        dlg = FollowingImportWindow(self)
        dlg.exec()

    def on_refresh_stats(self):
        """刷新选中行的统计数据"""
        if self._busy:
            return
        selected_items = [self.user_tree.topLevelItem(i)
                          for i in range(self.user_tree.topLevelItemCount())
                          if self.user_tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]
        if not selected_items:
            QtWidgets.QMessageBox.warning(self, '提示', '请先勾选要刷新的用户')
            return

        reply = QtWidgets.QMessageBox.question(
            self, '确认',
            f'确定要刷新 {len(selected_items)} 个用户的统计数据吗？\n需要有效的 Cookie。',
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        cookie = cfg.get('cookie', '')
        if not cookie:
            QtWidgets.QMessageBox.warning(self, '错误', '请先在设置中配置 Cookie')
            return

        sec_list = []
        for item in selected_items:
            user = item.data(0, Qt.ItemDataRole.UserRole)
            if not user:
                continue
            sec = extract_sec_user_id_from_url(user.get('url', ''))
            if sec:
                sec_list.append(sec)
        if not sec_list:
            return

        self._set_busy(True)
        worker = _ProfileBatchWorker(self)

        def _on_progress(i, total, _sec):
            self.status_label.setText(f'正在刷新 {i}/{total} ...')

        def _done(results):
            refreshed = 0
            users_now = cfg.get('users', [])
            for sec, profile, error in results:
                if not profile:
                    print(f'[警告] 刷新 {sec} 失败: {error}')
                    continue
                for u in users_now:
                    if extract_sec_user_id_from_url(u.get('url', '')) == sec:
                        u.update(profile)
                        if not u.get('username') and profile.get('nickname'):
                            u['username'] = profile['nickname']
                        break
                refreshed += 1
            cfg['users'] = users_now
            save_config(cfg)
            self.load_users()
            self._set_busy(False)
            QtWidgets.QMessageBox.information(self, '完成', f'已刷新 {refreshed} 个用户的数据')

        worker.progress.connect(_on_progress)
        worker.finished.connect(_done)
        threading.Thread(
            target=worker.run, args=(sec_list, cookie), daemon=True
        ).start()

    def on_fetch_checked(self):
        """提取勾选作者的作品 → 主窗口批量获取，作品累加到列表"""
        urls = []
        for i in range(self.user_tree.topLevelItemCount()):
            item = self.user_tree.topLevelItem(i)
            if item and item.checkState(0) == Qt.CheckState.Checked:
                user = item.data(0, Qt.ItemDataRole.UserRole)
                if user and user.get('url'):
                    urls.append(user['url'])
        if not urls:
            QtWidgets.QMessageBox.warning(self, '提示', '请先勾选要提取作品的作者')
            return

        main_window = self.window()
        if not main_window or not hasattr(main_window, 'start_batch_fetch'):
            return
        self.status_label.setText(f'开始批量提取 {len(urls)} 个主页的作品...')
        main_window.start_batch_fetch(urls)

    def on_delete(self):
        """删除选中的用户"""
        selected_items = []
        for i in range(self.user_tree.topLevelItemCount()):
            item = self.user_tree.topLevelItem(i)
            if item and item.checkState(0) == Qt.CheckState.Checked:
                selected_items.append(item)

        if not selected_items:
            QtWidgets.QMessageBox.warning(self, '提示', '请先选择要删除的用户')
            return

        msg_box = QtWidgets.QMessageBox(self)
        msg_box.setWindowTitle('确认')
        msg_box.setText(f'确定要删除选中的 {len(selected_items)} 个用户吗？')
        msg_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel)
        msg_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        button_ok = msg_box.button(QtWidgets.QMessageBox.StandardButton.Ok)
        button_cancel = msg_box.button(QtWidgets.QMessageBox.StandardButton.Cancel)
        if button_ok: button_ok.setText('确认')
        if button_cancel: button_cancel.setText('取消')

        if msg_box.exec() != QtWidgets.QMessageBox.StandardButton.Ok:
            return

        users_to_remove = [item.data(0, Qt.ItemDataRole.UserRole) for item in selected_items]
        remove_secs = set()
        remove_urls = set()
        for u in users_to_remove:
            if not isinstance(u, dict):
                continue
            sec = (u.get('sec_user_id') or '').strip() or extract_sec_user_id_from_url(u.get('url', '') or '')
            if sec:
                remove_secs.add(sec)
            url = (u.get('url') or '').strip()
            if url:
                remove_urls.add(url)

        new_users = []
        for u in cfg.get('users', []) or []:
            sec = (u.get('sec_user_id') or '').strip() or extract_sec_user_id_from_url(u.get('url', '') or '')
            url = (u.get('url') or '').strip()
            if sec and sec in remove_secs:
                continue
            if url and url in remove_urls:
                continue
            new_users.append(u)

        cfg['users'] = new_users
        save_config(cfg)
        self.load_users()
        self.status_label.setText(f'已删除 {len(users_to_remove)} 个主页，剩余 {len(new_users)} 个')

    def on_export(self):
        """导出用户列表为 CSV"""
        from datetime import datetime
        import csv
        import os

        users = cfg.get('users', [])
        if not users:
            QtWidgets.QMessageBox.warning(self, '提示', '没有可导出的数据')
            return

        default_name = f"主页列表_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, '导出列表', default_name, 'CSV 文件 (*.csv);;所有文件 (*)'
        )
        if not path:
            return

        fieldnames = ['序号', '分组', '作者', '关注数量', '粉丝数量', '获赞数量',
                       '喜欢数量', '作品数量', '最后发布作品时间', '主页链接']
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for idx, u in enumerate(users, start=1):
                    row = {'序号': idx, '主页链接': u.get('url', '')}
                    for fn in fieldnames[1:-1]:
                        key_map = {
                            '分组': 'group', '作者': 'username',
                            '关注数量': 'following_count', '粉丝数量': 'follower_count',
                            '获赞数量': 'total_favorited', '喜欢数量': 'favoriting_count',
                            '作品数量': 'aweme_count', '最后发布作品时间': 'last_publish_time',
                        }
                        row[fn] = u.get(key_map.get(fn, ''), '') or ''
                    writer.writerow(row)
            QtWidgets.QMessageBox.information(self, '导出成功', f'已导出到:\n{path}')
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, '导出失败', str(e))

    def on_header_select_all_clicked(self):
        """表头全选框：有未勾选则全选，否则取消全选"""
        self.on_select_all()

    def sync_header_select_all(self):
        """根据行勾选状态同步表头全选框"""
        cb = getattr(self, 'header_select_all', None)
        if not cb:
            return
        total = self.user_tree.topLevelItemCount()
        checked = sum(
            1 for i in range(total)
            if self.user_tree.topLevelItem(i)
            and self.user_tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked
        )
        cb.blockSignals(True)
        try:
            if total == 0 or checked == 0:
                cb.setCheckState(Qt.CheckState.Unchecked)
            elif checked == total:
                cb.setCheckState(Qt.CheckState.Checked)
            else:
                cb.setCheckState(Qt.CheckState.PartiallyChecked)
        finally:
            cb.blockSignals(False)

    def on_select_all(self):
        """全选/取消全选"""
        has_unchecked = any(
            self.user_tree.topLevelItem(i).checkState(0) != Qt.CheckState.Checked
            for i in range(self.user_tree.topLevelItemCount())
        )
        new_state = Qt.CheckState.Checked if has_unchecked else Qt.CheckState.Unchecked
        for i in range(self.user_tree.topLevelItemCount()):
            self.user_tree.topLevelItem(i).setCheckState(0, new_state)
        self.sync_header_select_all()

    def on_selection_changed(self):
        """行选中 → 同步复选框"""
        selected = self.user_tree.selectedItems()
        for i in range(self.user_tree.topLevelItemCount()):
            item = self.user_tree.topLevelItem(i)
            if item:
                item.setCheckState(0, Qt.CheckState.Checked if item in selected else Qt.CheckState.Unchecked)
        self.sync_header_select_all()

    def on_set_group(self):
        """为勾选用户设置分组名称"""
        if self._busy:
            return
        selected_items = [
            self.user_tree.topLevelItem(i)
            for i in range(self.user_tree.topLevelItemCount())
            if self.user_tree.topLevelItem(i)
            and self.user_tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked
        ]
        if not selected_items:
            QtWidgets.QMessageBox.warning(self, '提示', '请先勾选要设置分组的用户')
            return

        existing_groups = sorted({
            (u.get('group') or '').strip()
            for u in cfg.get('users', [])
            if (u.get('group') or '').strip()
        })
        default_group = ''
        first_user = selected_items[0].data(0, Qt.ItemDataRole.UserRole) or {}
        default_group = (first_user.get('group') or '').strip()

        group, ok = QtWidgets.QInputDialog.getText(
            self, '设置分组',
            f'为选中的 {len(selected_items)} 个用户设置分组名称：\n'
            f'（留空表示清除分组'
            + (f'；已有：{", ".join(existing_groups[:8])}' if existing_groups else '')
            + '）',
            text=default_group,
        )
        if not ok:
            return

        group = group.strip()
        users = cfg.get('users', [])
        changed = 0
        for item in selected_items:
            user = item.data(0, Qt.ItemDataRole.UserRole)
            if not user:
                continue
            user['group'] = group
            item.setText(self.COL_GROUP, group)
            sec = extract_sec_user_id_from_url(user.get('url', ''))
            for u in users:
                if extract_sec_user_id_from_url(u.get('url', '')) == sec:
                    u['group'] = group
                    changed += 1
                    break
        cfg['users'] = users
        save_config(cfg)
        self.status_label.setText(
            f'已为 {changed} 个用户设置分组' + (f'「{group}」' if group else '（已清除）')
        )

    def on_item_changed(self, item, column):
        """监控列勾选变化 → 开启/关闭监控；选择列变化 → 同步表头全选"""
        if getattr(self, '_programmatic_change', False):
            return
        if column == 0:
            self.sync_header_select_all()
            return
        if column != self.COL_MONITOR:
            return
        user = item.data(0, Qt.ItemDataRole.UserRole)
        if not user:
            return
        enabled = item.checkState(self.COL_MONITOR) == Qt.CheckState.Checked
        if enabled:
            self._enable_monitor_for_user(item, user)
        else:
            self._disable_monitor_for_user(item, user)

    def _disable_monitor_for_user(self, item, user):
        user['monitor'] = False
        sec = extract_sec_user_id_from_url(user.get('url', '')) or user.get('sec_user_id', '')
        users = cfg.get('users', [])
        for u in users:
            if extract_sec_user_id_from_url(u.get('url', '')) == sec or u.get('sec_user_id') == sec:
                u['monitor'] = False
                break
        cfg['users'] = users
        save_config(cfg)
        monitored = sum(1 for u in users if u.get('monitor'))
        self.status_label.setText(f'已关闭监控: {user.get("username") or sec}（当前监控 {monitored} 人）')
        main_window = self.window()
        if main_window and hasattr(main_window, 'reload_monitor_timer'):
            main_window.reload_monitor_timer()

    def _enable_monitor_for_user(self, item, user):
        """开启监控：后台取第一页设水位，不下载历史"""
        if self._busy:
            self._programmatic_change = True
            try:
                item.setCheckState(self.COL_MONITOR, Qt.CheckState.Unchecked)
            finally:
                self._programmatic_change = False
            return

        cookie = cfg.get('cookie', '')
        if not cookie:
            QtWidgets.QMessageBox.warning(self, '错误', '请先在设置中配置 Cookie')
            self._programmatic_change = True
            try:
                item.setCheckState(self.COL_MONITOR, Qt.CheckState.Unchecked)
            finally:
                self._programmatic_change = False
            return

        from douyin_downloader.core.monitor import (
            resolve_user_sec, fetch_user_aweme_page, compute_watermark,
        )
        sec = resolve_user_sec(user)
        if not sec:
            QtWidgets.QMessageBox.warning(self, '错误', '无法解析用户 ID')
            self._programmatic_change = True
            try:
                item.setCheckState(self.COL_MONITOR, Qt.CheckState.Unchecked)
            finally:
                self._programmatic_change = False
            return

        self._set_busy(True)
        self.status_label.setText(f'正在初始化监控水位: {user.get("username") or sec} ...')
        name = user.get('username') or sec

        class _InitWorker(QtCore.QObject):
            finished = QtCore.pyqtSignal(object, object, str)  # since, seen_ids, error

            def run(self, sec_id, cookie_str):
                awemes, err = fetch_user_aweme_page(sec_id, cookie_str)
                if err:
                    self.finished.emit(0, [], err)
                    return
                since, seen = compute_watermark(awemes)
                self.finished.emit(since, seen, '')

        worker = _InitWorker(self)

        def _done(since, seen_ids, error):
            self._set_busy(False)
            if error:
                self._programmatic_change = True
                try:
                    item.setCheckState(self.COL_MONITOR, Qt.CheckState.Unchecked)
                finally:
                    self._programmatic_change = False
                self.status_label.setText(f'开启监控失败: {error}')
                QtWidgets.QMessageBox.warning(self, '开启监控失败', error)
                return

            user['monitor'] = True
            user['monitor_since'] = int(since or 0)
            user['monitor_seen_ids'] = list(seen_ids or [])
            user['sec_user_id'] = sec
            users = cfg.get('users', [])
            for u in users:
                if extract_sec_user_id_from_url(u.get('url', '')) == sec or u.get('sec_user_id') == sec:
                    u['monitor'] = True
                    u['monitor_since'] = int(since or 0)
                    u['monitor_seen_ids'] = list(seen_ids or [])
                    u['sec_user_id'] = sec
                    break
            cfg['users'] = users
            save_config(cfg)
            monitored = sum(1 for u in users if u.get('monitor'))
            self.status_label.setText(
                f'已开启监控: {name}（水位已记录，不回溯下载；当前监控 {monitored} 人）'
            )
            main_window = self.window()
            if main_window and hasattr(main_window, 'reload_monitor_timer'):
                main_window.reload_monitor_timer()
            if main_window and hasattr(main_window, 'append_log'):
                main_window.append_log(f'[监控] 已开启: {name}')

        worker.finished.connect(_done)
        threading.Thread(target=worker.run, args=(sec, cookie), daemon=True).start()

    def on_double_click_item(self, item, column):
        """双击分组列编辑分组；双击其他列在浏览器打开主页"""
        user = item.data(0, Qt.ItemDataRole.UserRole)
        if not user:
            return

        if column == self.COL_GROUP:  # 分组列
            group, ok = QtWidgets.QInputDialog.getText(
                self, '设置分组',
                f'为「{user.get("username") or "该用户"}」设置分组：\n（留空表示清除分组）',
                text=(user.get('group') or ''),
            )
            if not ok:
                return
            group = group.strip()
            user['group'] = group
            item.setText(self.COL_GROUP, group)
            sec = extract_sec_user_id_from_url(user.get('url', ''))
            users = cfg.get('users', [])
            for u in users:
                if extract_sec_user_id_from_url(u.get('url', '')) == sec:
                    u['group'] = group
                    break
            cfg['users'] = users
            save_config(cfg)
            return

        if column == self.COL_MONITOR:
            return

        url = (user.get('url') or '').strip()
        if not url:
            sec = user.get('sec_user_id') or extract_sec_user_id_from_url(user.get('url', ''))
            if sec:
                url = f'https://www.douyin.com/user/{sec}'
        if not url:
            QtWidgets.QMessageBox.warning(self, '提示', '该用户没有可用的主页链接')
            return
        try:
            import webbrowser
            webbrowser.open(url)
            self.status_label.setText(f'已在浏览器打开主页: {user.get("username") or url}')
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, '提示', f'无法打开浏览器: {e}')
