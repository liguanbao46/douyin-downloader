# -*- coding: utf-8 -*-
"""
GUI - 关注列表导入对话框
获取当前登录账号的关注列表，勾选后导入主页列表。
"""
import sys
import threading
import time

import requests

try:
    from PyQt6 import QtWidgets, QtCore
    from PyQt6.QtCore import Qt
except ImportError:
    print("[错误] PyQt6 未安装或无法导入: \n请安装 PyQt6 后重试（pip install PyQt6）。")
    sys.exit(1)

from douyin_downloader.constants import USER_AGENT
from douyin_downloader.gui import cfg
from douyin_downloader.utils.config import save_config
from douyin_downloader.core.api import (
    get_self_user_info, build_following_url, parse_following_response,
    api_request_with_retry, extract_sec_user_id_from_url,
)
from douyin_downloader.core.abogus import ABogus


class _FollowingFetchWorker(QtCore.QObject):
    """后台线程分页拉取关注列表"""
    page_ready = QtCore.pyqtSignal(list)   # 一页精简用户 dict 列表
    finished = QtCore.pyqtSignal(str)      # '' 成功，否则错误信息

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self, cookie):
        session = requests.Session()
        session.headers.update({
            'User-Agent': USER_AGENT,
            'Cookie': cookie,
            'Referer': 'https://www.douyin.com/',
        })

        sec, uid, err = get_self_user_info(session, cookie)
        if err:
            self.finished.emit(err)
            return

        # 关注接口要求 Referer 指向用户主页
        session.headers['Referer'] = f'https://www.douyin.com/user/{sec}'

        ab = ABogus()
        offset = 0
        count = 20
        page = 0
        while not self._stop:
            params, base_url = build_following_url(sec, uid, offset, count)
            try:
                from urllib.parse import quote, urlencode
                a = quote(ab.get_value(params), safe='')
                params['a_bogus'] = a
                url = base_url + '?' + urlencode(params)
                r = api_request_with_retry(session, url, max_retries=2)
                data = r.json()
            except Exception as e:
                self.finished.emit(f'获取关注列表失败: {e}')
                return

            if data.get('status_code') != 0:
                msg = data.get('status_msg') or f'status_code={data.get("status_code")}'
                self.finished.emit(f'接口返回错误: {msg}')
                return

            users, has_more, new_offset, _total = parse_following_response(data)
            page += 1
            if users:
                self.page_ready.emit(users)
            if not has_more or not users:
                break
            offset = new_offset if new_offset is not None else (offset + len(users))
            time.sleep(0.3)

        self.finished.emit('')


class FollowingImportWindow(QtWidgets.QDialog):
    """关注列表导入窗口"""
    COLS = [
        ('选择', None, 'center'),
        ('昵称', 'nickname', 'left'),
        ('抖音号', 'unique_id', 'left'),
        ('粉丝数', 'follower_count', 'right'),
        ('作品数', 'aweme_count', 'right'),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('导入关注列表')
        self.setModal(True)
        self.resize(560, 520)
        self._users = []      # 已拉取的关注用户（按 sec_uid 去重）
        self._seen = set()
        self._worker = None
        self._thread = None
        self._fetching = False
        self.setup_ui()

    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        hint = QtWidgets.QLabel('获取你抖音账号的关注列表，勾选后导入到主页列表。')
        hint.setObjectName('FilterHint')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 顶部按钮
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)
        self.fetch_btn = QtWidgets.QPushButton('获取关注列表')
        self.fetch_btn.setObjectName('primary_btn')
        self.select_all_btn = QtWidgets.QPushButton('全选')
        self.invert_btn = QtWidgets.QPushButton('反选')
        toolbar.addWidget(self.fetch_btn)
        toolbar.addWidget(self.select_all_btn)
        toolbar.addWidget(self.invert_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # 列表
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels([c[0] for c in self.COLS])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.tree.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(0, 40)
        self.tree.setColumnWidth(3, 80)
        self.tree.setColumnWidth(4, 70)
        layout.addWidget(self.tree, 1)

        # 底部状态 + 导入
        self.status_label = QtWidgets.QLabel('尚未获取关注列表')
        self.status_label.setObjectName('FilterSummary')
        bottom = QtWidgets.QHBoxLayout()
        bottom.addWidget(self.status_label, 1)
        self.import_btn = QtWidgets.QPushButton('导入选中到主页列表')
        self.import_btn.setObjectName('primary_btn')
        self.import_btn.setEnabled(False)
        bottom.addWidget(self.import_btn)
        layout.addLayout(bottom)

        self.fetch_btn.clicked.connect(self.on_fetch)
        self.select_all_btn.clicked.connect(self.on_select_all)
        self.invert_btn.clicked.connect(self.on_invert)
        self.import_btn.clicked.connect(self.on_import)

        # 样式主体继承全局 Apple 体系，这里只定义主操作按钮
        self.setStyleSheet("""
            QPushButton#primary_btn {
                background-color: #007AFF;
                color: #FFFFFF;
                border-radius: 12px;
            }
            QPushButton#primary_btn:hover { background-color: #0064D6; }
            QPushButton#primary_btn:pressed { background-color: #004FAD; }
            QPushButton#primary_btn:disabled { background-color: #9FCBFF; color: #FFFFFF; }
        """)

    def _append_users(self, users):
        for u in users:
            sec = u.get('sec_uid') or ''
            if not sec or sec in self._seen:
                continue
            self._seen.add(sec)
            self._users.append(u)
            item = QtWidgets.QTreeWidgetItem()
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable |
                          Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setText(1, u.get('nickname') or '(未命名)')
            item.setText(2, u.get('unique_id') or '')
            item.setText(3, self._fmt_num(u.get('follower_count')))
            item.setText(4, self._fmt_num(u.get('aweme_count')))
            item.setData(0, Qt.ItemDataRole.UserRole, u)
            self.tree.addTopLevelItem(item)
        self.import_btn.setEnabled(bool(self._users))
        self.status_label.setText(f'已获取 {len(self._users)} 个关注')

    @staticmethod
    def _fmt_num(val):
        try:
            n = int(val)
        except (TypeError, ValueError):
            return str(val or '-')
        if n >= 10000:
            return f'{n / 10000:.1f}万'
        return str(n)

    def _set_fetching(self, fetching):
        self._fetching = fetching
        if fetching:
            self.fetch_btn.setText('停止获取')
            self.fetch_btn.setProperty('running', 'true')
        else:
            self.fetch_btn.setText('获取关注列表')
            self.fetch_btn.setProperty('running', 'false')
        self.fetch_btn.style().unpolish(self.fetch_btn)
        self.fetch_btn.style().polish(self.fetch_btn)

    def on_fetch(self):
        if self._fetching:
            if self._worker:
                self._worker.stop()
            return
        cookie = cfg.get('cookie', '').strip()
        if not cookie:
            QtWidgets.QMessageBox.warning(self, '错误', '请先在设置中配置 Cookie')
            return
        self._users.clear()
        self._seen.clear()
        self.tree.clear()
        self.import_btn.setEnabled(False)
        self._set_fetching(True)
        self.status_label.setText('正在获取关注列表...')

        self._worker = _FollowingFetchWorker(self)
        self._worker.page_ready.connect(self._append_users)
        self._worker.finished.connect(self._on_fetch_finished)
        self._thread = threading.Thread(
            target=self._worker.run, args=(cookie,), daemon=True
        )
        self._thread.start()

    def _on_fetch_finished(self, msg):
        self._set_fetching(False)
        if msg:
            self.status_label.setText(f'获取失败: {msg}')
            QtWidgets.QMessageBox.warning(self, '获取失败', msg)
        else:
            self.status_label.setText(f'获取完成，共 {len(self._users)} 个关注')

    def on_select_all(self):
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, Qt.CheckState.Checked)

    def on_invert(self):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            new = Qt.CheckState.Unchecked if item.checkState(0) == Qt.CheckState.Checked else Qt.CheckState.Checked
            item.setCheckState(0, new)

    def on_import(self):
        checked = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                u = item.data(0, Qt.ItemDataRole.UserRole)
                if u:
                    checked.append(u)
        if not checked:
            QtWidgets.QMessageBox.warning(self, '提示', '请先勾选要导入的关注博主')
            return

        users_now = cfg.get('users', [])
        existing = {extract_sec_user_id_from_url(x.get('url', '')) for x in users_now}
        added = 0
        for u in checked:
            sec = u.get('sec_uid') or ''
            if not sec or sec in existing:
                continue
            entry = {
                'username': u.get('nickname') or '',
                'url': f'https://www.douyin.com/user/{sec}',
                'group': '',
                'sec_user_id': sec,
            }
            for k in ('nickname', 'unique_id', 'following_count', 'follower_count',
                      'total_favorited', 'favoriting_count', 'aweme_count'):
                if k in u:
                    entry[k] = u[k]
            users_now.append(entry)
            existing.add(sec)
            added += 1

        if not added:
            QtWidgets.QMessageBox.information(self, '提示', '选中的博主都已在主页列表中')
            return

        cfg['users'] = users_now
        save_config(cfg)

        parent = self.parent()
        if parent and hasattr(parent, 'load_users'):
            try:
                parent.load_users()
            except Exception:
                pass

        QtWidgets.QMessageBox.information(self, '完成', f'已导入 {added} 个主页到主页列表')
        self.accept()

    def closeEvent(self, a0):
        if self._worker:
            self._worker.stop()
        super().closeEvent(a0)
