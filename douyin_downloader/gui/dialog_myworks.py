# -*- coding: utf-8 -*-
"""
GUI - 我的主页提取页面
识别当前登录账号（Cookie 对应账号），展示账号统计信息，
一键提取自己的作品/点赞作品到作品列表（复用现有获取/下载/导出流程）。
"""
import sys
import threading

import requests

try:
    from PyQt6 import QtWidgets, QtCore
    from PyQt6.QtCore import Qt
except ImportError:
    print("[错误] PyQt6 未安装或无法导入: \n请安装 PyQt6 后重试（pip install PyQt6）。")
    sys.exit(1)

from douyin_downloader.constants import USER_AGENT
from douyin_downloader.gui import cfg
from douyin_downloader.core.api import get_self_user_info, get_user_profile_info


class _SelfInfoWorker(QtCore.QObject):
    """后台线程获取当前登录账号的 sec_uid 与资料统计"""
    finished = QtCore.pyqtSignal(object, str)  # (profile dict or None, error)

    def run(self, cookie):
        session = requests.Session()
        session.headers.update({
            'User-Agent': USER_AGENT,
            'Cookie': cookie,
            'Referer': 'https://www.douyin.com/',
        })

        sec, _uid, err = get_self_user_info(session, cookie)
        if not sec:
            self.finished.emit(None, err or '未识别到登录账号')
            return

        profile, perr = get_user_profile_info(session, sec)
        if profile:
            self.finished.emit(profile, '')
        else:
            # 资料接口失败不影响提取作品，至少带上 sec_uid
            self.finished.emit({'sec_user_id': sec, 'nickname': ''}, perr or '')


class MyWorksWindow(QtWidgets.QWidget):
    """我的主页提取页面：当前登录账号的作品一键提取"""
    extract_requested = QtCore.pyqtSignal(str, bool, bool)  # url, favorite, latest_only

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profile = None     # 当前账号资料（含 sec_user_id）
        self._loading = False
        self._worker = None
        self._thread = None
        self._ever_loaded = False
        self.setup_ui()

    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QtWidgets.QLabel('我的主页提取')
        title_font = title.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        hint = QtWidgets.QLabel(
            '自动识别当前 Cookie 登录的抖音账号，一键提取你自己发布（或点赞）的作品。'
            '提取结果将显示在「作品列表」页，可直接勾选下载、导出。'
        )
        hint.setWordWrap(True)
        hint.setStyleSheet('color: #8E8E93;')
        layout.addWidget(hint)

        # 账号信息卡片
        card = QtWidgets.QFrame()
        card.setStyleSheet(
            'QFrame { background-color: #F7F7FA; border: 1px solid #E5E5EA; border-radius: 8px; }'
            'QLabel { background: transparent; border: none; }'
        )
        card_lay = QtWidgets.QGridLayout(card)
        card_lay.setContentsMargins(16, 14, 16, 14)
        card_lay.setHorizontalSpacing(24)
        card_lay.setVerticalSpacing(10)

        nickname_label = QtWidgets.QLabel('未获取')
        nickname_font = nickname_label.font()
        nickname_font.setPointSize(12)
        nickname_font.setBold(True)
        nickname_label.setFont(nickname_font)

        self._stat_labels = {}
        stats = [
            ('nickname', '昵称', nickname_label),
            ('unique_id', '抖音号', QtWidgets.QLabel('—')),
            ('following_count', '关注', QtWidgets.QLabel('—')),
            ('follower_count', '粉丝', QtWidgets.QLabel('—')),
            ('total_favorited', '获赞', QtWidgets.QLabel('—')),
            ('aweme_count', '作品数', QtWidgets.QLabel('—')),
        ]
        for col, (key, name, value_label) in enumerate(stats):
            name_label = QtWidgets.QLabel(name)
            name_label.setStyleSheet('color: #8E8E93;')
            value_label.setStyleSheet('font-weight: 600;')
            card_lay.addWidget(name_label, 0, col)
            card_lay.addWidget(value_label, 1, col)
            self._stat_labels[key] = value_label
        card_lay.setColumnStretch(6, 1)
        layout.addWidget(card)

        # 操作行：刷新账号信息 + 状态
        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(8)
        self.refresh_btn = QtWidgets.QPushButton('刷新账号信息')
        self.refresh_btn.clicked.connect(self.refresh_info)
        row1.addWidget(self.refresh_btn)
        self.info_status = QtWidgets.QLabel('')
        self.info_status.setStyleSheet('color: #8E8E93;')
        row1.addWidget(self.info_status, 1)
        layout.addLayout(row1)

        # 选项行
        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(16)
        self.like_checkbox = QtWidgets.QCheckBox('提取点赞作品（不勾选则提取我发布的作品）')
        self.like_checkbox.setToolTip('勾选后提取你的点赞列表，未勾选提取你自己发布的作品')
        self.latest_checkbox = QtWidgets.QCheckBox('仅最新一页')
        self.latest_checkbox.setToolTip('只获取第一页最新作品，不翻页拉取历史')
        self.latest_checkbox.setChecked(bool(cfg.get('fetch_latest_only', False)))
        row2.addWidget(self.like_checkbox)
        row2.addWidget(self.latest_checkbox)
        row2.addStretch()
        layout.addLayout(row2)

        # 提取按钮
        self.extract_btn = QtWidgets.QPushButton('提取我的作品')
        self.extract_btn.setObjectName('fetch_btn')
        self.extract_btn.setMinimumHeight(38)
        self.extract_btn.setEnabled(False)
        self.extract_btn.clicked.connect(self.on_extract)
        layout.addWidget(self.extract_btn)

        layout.addStretch()

    # ---------- 账号信息 ----------

    def refresh_info_if_needed(self):
        """切换到本页时自动加载一次（已有数据则跳过）"""
        if self._ever_loaded or self._loading:
            return
        self.refresh_info()

    def refresh_info(self):
        """后台获取当前登录账号信息"""
        if self._loading:
            return
        cookie = cfg.get('cookie', '')
        if not cookie:
            self.info_status.setText('未配置 Cookie，请先在「设置」中填写')
            QtWidgets.QMessageBox.warning(self, '提示', '请先在设置中配置 Cookie')
            return

        self._loading = True
        self._ever_loaded = True
        self.refresh_btn.setEnabled(False)
        self.extract_btn.setEnabled(False)
        self.info_status.setText('正在识别登录账号…')

        self._worker = _SelfInfoWorker()
        self._worker.finished.connect(self._on_info_finished)
        self._thread = threading.Thread(target=self._worker.run, args=(cookie,), daemon=True)
        self._thread.start()

    def _on_info_finished(self, profile, error):
        """后台获取账号信息完成（主线程信号回调）"""
        self._loading = False
        self.refresh_btn.setEnabled(True)

        if not profile:
            self._profile = None
            self.info_status.setText('识别失败')
            self.extract_btn.setEnabled(False)
            QtWidgets.QMessageBox.warning(self, '提示', f'识别登录账号失败：{error}\n\n请确认 Cookie 有效且已登录。')
            return

        self._profile = profile
        self.extract_btn.setEnabled(True)

        if error:
            self.info_status.setText(f'账号统计获取失败（仍可提取作品）: {error}')
        else:
            self.info_status.setText('账号识别成功')

        def fmt(v):
            try:
                n = int(v or 0)
            except (TypeError, ValueError):
                return '—'
            if n >= 10000_0000:
                return f'{n / 10000_0000:.1f}亿'
            if n >= 10000:
                return f'{n / 10000:.1f}万'
            return str(n)

        for key in ('nickname', 'unique_id', 'following_count', 'follower_count',
                    'total_favorited', 'aweme_count'):
            label = self._stat_labels.get(key)
            if not label:
                continue
            value = profile.get(key)
            if key in ('following_count', 'follower_count', 'total_favorited', 'aweme_count'):
                text = fmt(value)
            else:
                text = str(value) if value else '—'
            label.setText(text)

    # ---------- 提取 ----------

    def on_extract(self):
        """点击提取：把我的主页链接发给主窗口，走现有获取流程"""
        profile = self._profile or {}
        sec = profile.get('sec_user_id') or ''
        if not sec:
            QtWidgets.QMessageBox.warning(self, '提示', '尚未识别到登录账号，请先刷新账号信息')
            return

        url = f'https://www.douyin.com/user/{sec}'
        favorite = bool(self.like_checkbox.isChecked())
        latest_only = bool(self.latest_checkbox.isChecked())
        name = profile.get('nickname') or '我'
        self.info_status.setText(f'正在提取「{name}」的作品，请到「作品列表」页查看…')
        self.extract_requested.emit(url, favorite, latest_only)
