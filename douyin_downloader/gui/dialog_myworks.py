# -*- coding: utf-8 -*-
"""
GUI - 我的主页提取页面
识别当前登录账号（Cookie 对应账号），展示账号统计信息，
四个一键提取入口：
  1. 我的关注主页网址（页内拉取，展示可复制的网址列表）
  2. 我的主页作品
  3. 我的主页喜欢作品（点赞）
  4. 我的主页收藏作品
作品类提取结果复用「作品列表」页的获取/下载/导出流程。
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
from douyin_downloader.gui.dialog_following import _FollowingFetchWorker


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
    """我的主页提取页面：当前登录账号相关内容一键提取"""
    extract_requested = QtCore.pyqtSignal(str, str, bool)  # url, mode('post'/'favorite'/'collect'), latest_only

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profile = None     # 当前账号资料（含 sec_user_id）
        self._loading = False
        self._worker = None
        self._thread = None
        self._ever_loaded = False
        # 关注网址提取
        self._fw_worker = None
        self._fw_thread = None
        self._fw_fetching = False
        self._following = []     # [(nickname, url)]
        self._fw_seen = set()
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
            '自动识别当前 Cookie 登录的抖音账号，一键提取你的关注主页网址、'
            '发布作品、喜欢作品与收藏作品。作品提取结果显示在「作品列表」页，可直接勾选下载、导出。'
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

        # 选项行（对作品/喜欢/收藏提取生效）
        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(16)
        self.latest_checkbox = QtWidgets.QCheckBox('仅最新一页')
        self.latest_checkbox.setToolTip('只获取第一页最新作品，不翻页拉取历史')
        self.latest_checkbox.setChecked(bool(cfg.get('fetch_latest_only', False)))
        row2.addWidget(self.latest_checkbox)
        row2.addStretch()
        layout.addLayout(row2)

        # 四个提取按钮（2x2）
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        self.following_btn = self._make_action_btn('开始提取我的关注主页网址')
        self.following_btn.setToolTip('拉取你关注的所有博主，生成主页网址列表，可一键复制')
        self.following_btn.clicked.connect(self.on_extract_following)

        self.post_btn = self._make_action_btn('开始提取我的主页作品')
        self.post_btn.setToolTip('提取你自己发布的作品到「作品列表」页')
        self.post_btn.clicked.connect(lambda: self.on_extract_works('post'))

        self.favorite_btn = self._make_action_btn('开始提取我的主页喜欢作品')
        self.favorite_btn.setToolTip('提取你点赞（喜欢）的作品到「作品列表」页')
        self.favorite_btn.clicked.connect(lambda: self.on_extract_works('favorite'))

        self.collect_btn = self._make_action_btn('开始提取我的主页收藏作品')
        self.collect_btn.setToolTip('提取你收藏的作品到「作品列表」页')
        self.collect_btn.clicked.connect(lambda: self.on_extract_works('collect'))

        grid.addWidget(self.following_btn, 0, 0)
        grid.addWidget(self.post_btn, 0, 1)
        grid.addWidget(self.favorite_btn, 1, 0)
        grid.addWidget(self.collect_btn, 1, 1)
        layout.addLayout(grid)

        layout.addStretch()

    def _make_action_btn(self, text):
        btn = QtWidgets.QPushButton(text)
        btn.setObjectName('fetch_btn')
        btn.setMinimumHeight(38)
        btn.setEnabled(False)
        return btn

    def _set_action_btns_enabled(self, enabled):
        for b in (self.following_btn, self.post_btn,
                  self.favorite_btn, self.collect_btn):
            b.setEnabled(enabled)

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
        self._set_action_btns_enabled(False)
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
            self._set_action_btns_enabled(False)
            QtWidgets.QMessageBox.warning(self, '提示', f'识别登录账号失败：{error}\n\n请确认 Cookie 有效且已登录。')
            return

        self._profile = profile
        self._set_action_btns_enabled(True)

        if error:
            self.info_status.setText('账号统计获取失败（仍可提取作品）')
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

    # ---------- 作品类提取（作品/喜欢/收藏） ----------

    def on_extract_works(self, mode):
        """点击提取：把我的主页链接+模式发给主窗口，走现有获取流程"""
        profile = self._profile or {}
        sec = profile.get('sec_user_id') or ''
        if not sec:
            QtWidgets.QMessageBox.warning(self, '提示', '尚未识别到登录账号，请先刷新账号信息')
            return

        url = f'https://www.douyin.com/user/{sec}'
        latest_only = bool(self.latest_checkbox.isChecked())
        names = {'post': '作品', 'favorite': '喜欢作品', 'collect': '收藏作品'}
        name = profile.get('nickname') or '我'
        self.info_status.setText(f'正在提取「{name}」的{names.get(mode, "作品")}，请到「作品列表」页查看…')
        self.extract_requested.emit(url, mode, latest_only)

    # ---------- 关注主页网址提取 ----------

    def on_extract_following(self):
        """拉取全部关注列表，生成主页网址列表"""
        if self._fw_fetching:
            return
        cookie = cfg.get('cookie', '').strip()
        if not cookie:
            QtWidgets.QMessageBox.warning(self, '提示', '请先在设置中配置 Cookie')
            return

        self._following = []
        self._fw_seen = set()
        self._fw_fetching = True
        self.following_btn.setEnabled(False)
        self.info_status.setText('正在拉取关注列表…')

        self._fw_worker = _FollowingFetchWorker()
        self._fw_worker.page_ready.connect(self._on_following_page)
        self._fw_worker.finished.connect(self._on_following_done)
        self._fw_thread = threading.Thread(target=self._fw_worker.run, args=(cookie,), daemon=True)
        self._fw_thread.start()

    def _on_following_page(self, users):
        """每页关注数据到达（主线程信号回调）"""
        for u in users:
            sec = u.get('sec_uid') or ''
            if not sec or sec in self._fw_seen:
                continue
            self._fw_seen.add(sec)
            self._following.append((u.get('nickname') or '(未命名)',
                                    f'https://www.douyin.com/user/{sec}'))
        self.info_status.setText(f'正在拉取关注列表…已获取 {len(self._following)} 个')

    def _on_following_done(self, msg):
        """关注列表拉取完成"""
        self._fw_fetching = False
        self.following_btn.setEnabled(True)
        if msg:
            self.info_status.setText('关注列表获取失败')
            QtWidgets.QMessageBox.warning(self, '提示', f'获取关注列表失败：{msg}')
            return
        if not self._following:
            self.info_status.setText('关注列表为空')
            return
        self.info_status.setText(f'关注列表获取完成，共 {len(self._following)} 个主页网址')
        self._show_following_urls()

    def _show_following_urls(self):
        """展示关注主页网址列表对话框"""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f'我的关注主页网址（共 {len(self._following)} 个）')
        dlg.resize(620, 480)
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        tip = QtWidgets.QLabel('每行「昵称 - 网址」。可复制全部网址，粘贴到「作品列表」页的链接框进行批量提取。')
        tip.setWordWrap(True)
        tip.setStyleSheet('color: #8E8E93;')
        lay.addWidget(tip)

        text = QtWidgets.QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText('\n'.join(f'{n} - {u}' for n, u in self._following))
        lay.addWidget(text, 1)

        btns = QtWidgets.QHBoxLayout()
        btns.addStretch()

        copy_btn = QtWidgets.QPushButton('复制全部网址')
        copy_btn.setObjectName('fetch_btn')

        def do_copy():
            urls = '\n'.join(u for _n, u in self._following)
            QtWidgets.QApplication.clipboard().setText(urls)
            copy_btn.setText('已复制')
            QtCore.QTimer.singleShot(1500, lambda: copy_btn.setText('复制全部网址'))

        copy_btn.clicked.connect(do_copy)
        btns.addWidget(copy_btn)

        close_btn = QtWidgets.QPushButton('关闭')
        close_btn.clicked.connect(dlg.accept)
        btns.addWidget(close_btn)
        lay.addLayout(btns)

        dlg.exec()
