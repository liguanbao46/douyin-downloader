# -*- coding: utf-8 -*-
"""
GUI - 浏览器登录提取
在软件内启动 Playwright 浏览器（持久化配置目录，登录一次后免扫码），
用户登录抖音后自动打开「我的主页」对应标签页并自动滚动，
监听浏览器自身发出的接口响应来捕获作品——浏览器请求自带完整风控签名，
可绕过 Argus 403 拦截（喜欢/收藏等接口）。
"""
import os
import re
import sys
import time
import queue
import threading

try:
    from PyQt6 import QtWidgets, QtCore
except ImportError:
    print("[错误] PyQt6 未安装或无法导入: \n请安装 PyQt6 后重试（pip install PyQt6）。")
    sys.exit(1)

from douyin_downloader.constants import CONFIG_FILE
from douyin_downloader.utils.config import load_config, save_config
from douyin_downloader.gui import cfg


# 各模式对应的「我的主页」标签页
MODE_TAB = {
    'post': 'https://www.douyin.com/user/self?showTab=post',
    'favorite': 'https://www.douyin.com/user/self?showTab=favorite',
    'collect': 'https://www.douyin.com/user/self?showTab=favorite_collection',
}

# 各模式捕获的接口 URL 片段
MODE_PATTERN = {
    'post': '/aweme/v1/web/aweme/post',
    'favorite': '/aweme/v1/web/aweme/favorite',
    'collect': '/aweme/v1/web/aweme/listcollection',
}

PROFILE_PATTERNS = ('/aweme/v1/web/user/profile/self', '/aweme/v1/web/user/profile/other')

LOGIN_WAIT_SECONDS = 300     # 等待扫码登录最长 5 分钟
SCROLL_MAX_ROUNDS = 400      # 最多滚动轮数（每轮约 1.5s，足够翻完 2000+ 作品）
SCROLL_IDLE_ROUNDS = 6       # 连续 N 轮无新数据则认为到底
MAX_ITEMS = 3000             # 单次提取上限（防失控）

# 常见浏览器路径（未配置时自动探测，免下载 playwright chromium）
_COMMON_BROWSERS = (
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    '/usr/bin/google-chrome',
    '/usr/bin/microsoft-edge',
    '/usr/bin/chromium',
)


def _detect_browser_path():
    """配置的浏览器路径优先，否则探测本机常见 Chrome/Edge"""
    try:
        config = load_config()
        for key in ('chrome_path', 'edge_path'):
            p = (config.get(key) or '').strip()
            if p and os.path.exists(p):
                return p
    except Exception:
        pass
    for p in _COMMON_BROWSERS:
        if os.path.exists(p):
            return p
    return ''


class _BrowserExtractSession(QtCore.QObject):
    """后台线程持有 Playwright 持久化浏览器会话，监听接口响应捕获作品"""
    launched = QtCore.pyqtSignal()
    login_ok = QtCore.pyqtSignal(str)           # 登录成功，携带最新 Cookie
    log_msg = QtCore.pyqtSignal(str)
    self_ready = QtCore.pyqtSignal(str, str)    # (sec_user_id, "nickname|unique_id")
    tasks_page = QtCore.pyqtSignal(list, str)   # (aweme_list, user_info)
    done = QtCore.pyqtSignal(int)               # 捕获总数
    failed = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = queue.Queue()
        self._thread = None
        self._stopped = False

    def start(self, mode):
        if self._thread and self._thread.is_alive():
            return
        self._stopped = False
        self._thread = threading.Thread(target=self._run, args=(mode,), daemon=True)
        self._thread.start()

    def request_stop(self):
        self._stopped = True

    def _pop_stop(self):
        try:
            while True:
                cmd = self._queue.get_nowait()
                if cmd == 'stop':
                    self._stopped = True
        except queue.Empty:
            pass
        return self._stopped

    def _run(self, mode):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.failed.emit(
                '未安装 Playwright 库，请运行:\npip install playwright\nplaywright install chromium'
            )
            return

        pattern = MODE_PATTERN.get(mode)
        tab_url = MODE_TAB.get(mode)
        if not pattern or not tab_url:
            self.failed.emit(f'不支持的提取模式: {mode}')
            return

        profile_dir = os.path.join(os.path.dirname(CONFIG_FILE) or '.', 'browser_profile')
        try:
            os.makedirs(profile_dir, exist_ok=True)
        except Exception:
            pass

        items = []          # 已捕获的全部 aweme（去重后）
        seen = set()
        pending = []        # 待发送批次
        self_profile = {}   # profile/self 接口返回的本人资料

        def _handle_response(resp):
            try:
                url = resp.url
                is_target = pattern in url
                is_profile = any(p in url for p in PROFILE_PATTERNS)
                if not (is_target or is_profile):
                    return
                data = resp.json()
            except Exception:
                return
            try:
                if is_profile:
                    user = data.get('user') or {}
                    if user.get('sec_uid') or user.get('nickname'):
                        self_profile.clear()
                        self_profile.update(user)
                    return
                for aweme in data.get('aweme_list') or []:
                    aid = aweme.get('aweme_id')
                    if not aid or aid in seen:
                        continue
                    seen.add(aid)
                    items.append(aweme)
                    pending.append(aweme)
            except Exception:
                pass

        try:
            with sync_playwright() as p:
                kwargs = {'headless': False}
                browser_path = _detect_browser_path()
                if browser_path:
                    kwargs['executable_path'] = browser_path
                try:
                    context = p.chromium.launch_persistent_context(profile_dir, **kwargs)
                except Exception as e:
                    self.failed.emit(
                        f'启动浏览器失败: {e}\n\n'
                        '若提示缺少浏览器，请运行: playwright install chromium\n'
                        '或在「设置 - 浏览器配置」中指定本机 Chrome/Edge 路径'
                    )
                    return

                page = context.pages[0] if context.pages else context.new_page()
                page.on('response', _handle_response)

                try:
                    page.goto('https://www.douyin.com/', timeout=60000)
                except Exception:
                    pass
                self.launched.emit()

                # ---------- 等待登录（已登录则立即通过） ----------
                self.log_msg.emit('请在浏览器中登录抖音（建议扫码），登录后自动开始提取…')
                deadline = time.time() + LOGIN_WAIT_SECONDS
                logged_in = False
                while time.time() < deadline:
                    if self._pop_stop():
                        break
                    try:
                        cookies = context.cookies('https://www.douyin.com')
                        if any(c.get('name') == 'sessionid' for c in cookies):
                            logged_in = True
                            cookie_str = '; '.join(
                                f"{c.get('name', '')}={c.get('value', '')}" for c in cookies
                            )
                            self.login_ok.emit(cookie_str)
                            break
                    except Exception:
                        pass
                    try:
                        page.wait_for_timeout(2000)
                    except Exception:
                        break

                if not logged_in:
                    self.failed.emit('等待登录超时或已停止，未完成登录')
                    try:
                        context.close()
                    except Exception:
                        pass
                    return

                # ---------- 打开对应标签页 ----------
                self.log_msg.emit('登录成功，正在打开「我的主页」对应标签页…')
                try:
                    page.goto(tab_url, timeout=60000)
                except Exception:
                    pass
                try:
                    page.wait_for_timeout(4000)
                except Exception:
                    pass

                # 从页面 URL 提取本人 sec_uid（/user/self 会跳转到 /user/<sec_uid>）
                sec = ''
                try:
                    m = re.search(r'/user/(MS4wLjABAAAA[\w-]+)', page.url or '')
                    if m:
                        sec = m.group(1)
                except Exception:
                    pass

                nickname = (self_profile.get('nickname') or '').strip() or '我'
                unique_id = (self_profile.get('unique_id') or self_profile.get('short_id') or '').strip()
                user_info = f"{nickname}|{unique_id}" if unique_id else nickname
                if sec:
                    self.self_ready.emit(sec, user_info)

                # ---------- 自动滚动，捕获接口响应 ----------
                mode_name = {'post': '作品', 'favorite': '喜欢作品', 'collect': '收藏作品'}[mode]
                self.log_msg.emit(f'正在自动滚动提取{mode_name}…可随时点击「停止」')
                idle_rounds = 0
                for _round in range(SCROLL_MAX_ROUNDS):
                    if self._pop_stop() or len(items) >= MAX_ITEMS:
                        break
                    try:
                        page.mouse.wheel(0, 4000)
                        page.wait_for_timeout(1500)
                    except Exception as e:
                        # 浏览器被手动关闭等
                        if pending:
                            self.tasks_page.emit(list(pending), user_info)
                            pending.clear()
                        self.failed.emit(f'浏览器会话中断: {e}')
                        try:
                            context.close()
                        except Exception:
                            pass
                        return

                    if pending:
                        self.tasks_page.emit(list(pending), user_info)
                        pending.clear()
                        idle_rounds = 0
                        self.log_msg.emit(f'已捕获 {len(items)} 个{mode_name}…')
                    else:
                        idle_rounds += 1
                        if idle_rounds >= SCROLL_IDLE_ROUNDS:
                            break

                if pending:
                    self.tasks_page.emit(list(pending), user_info)
                    pending.clear()

                try:
                    context.close()
                except Exception:
                    pass
                self.done.emit(len(items))
        except Exception as e:
            self.failed.emit(f'浏览器提取失败: {e}')


class BrowserExtractDialog(QtWidgets.QDialog):
    """浏览器登录提取对话框：登录抖音 → 自动滚动捕获 → 结果送入作品列表"""
    self_ready = QtCore.pyqtSignal(str, str)     # (sec_user_id, user_info)
    tasks_ready = QtCore.pyqtSignal(list, str)   # (aweme_list, user_info)
    done_ready = QtCore.pyqtSignal(int)          # 总数
    cookie_saved = QtCore.pyqtSignal(str)

    def __init__(self, mode='post', parent=None):
        super().__init__(parent)
        self.setWindowTitle('浏览器登录提取')
        self.resize(460, 320)
        self._mode = mode
        self._session = None
        self._running = False
        self.setup_ui()

    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        info = QtWidgets.QLabel(
            '点击「开始」后会打开浏览器：\n'
            '1. 若未登录，请扫码登录抖音（登录状态会被记住，下次免扫码）\n'
            '2. 登录后自动打开对应页面并滚动，自动捕获全部作品\n'
            '3. 捕获完成后浏览器自动关闭，作品进入「作品列表」页\n\n'
            '提示：浏览器内请求自带抖音风控签名，喜欢/收藏等被接口直连'
            '拦截（403）的内容也可正常提取。'
        )
        info.setWordWrap(True)
        info.setStyleSheet('color: #1D1D1F; font-size: 13px;')
        layout.addWidget(info)

        mode_row = QtWidgets.QHBoxLayout()
        self._mode_group = QtWidgets.QButtonGroup(self)
        self._radios = {}
        for key, name in (('post', '我的作品'), ('favorite', '喜欢作品'), ('collect', '收藏作品')):
            radio = QtWidgets.QRadioButton(name)
            if key == self._mode:
                radio.setChecked(True)
            self._mode_group.addButton(radio)
            mode_row.addWidget(radio)
            self._radios[key] = radio
        mode_row.addStretch()
        layout.addLayout(mode_row)

        self.status_label = QtWidgets.QLabel('')
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet('color: #8E8E93;')
        layout.addWidget(self.status_label)

        layout.addStretch()

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        self.stop_btn = QtWidgets.QPushButton('停止')
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.on_stop)
        self.start_btn = QtWidgets.QPushButton('打开浏览器并开始')
        self.start_btn.setObjectName('primary_btn')
        self.start_btn.clicked.connect(self.on_start)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.start_btn)
        layout.addLayout(btn_row)

        self.setStyleSheet("""
        QLabel { color: #1D1D1F; font-size: 13px; }
        QPushButton#primary_btn {
            background-color: #007AFF; color: #FFFFFF;
            border-radius: 12px; padding: 6px 18px;
        }
        QPushButton#primary_btn:hover { background-color: #0064D6; }
        QPushButton#primary_btn:pressed { background-color: #004FAD; }
        QPushButton#primary_btn:disabled { background-color: #9FCBFF; color: #FFFFFF; }
        """)

    def _selected_mode(self):
        for key, radio in self._radios.items():
            if radio.isChecked():
                return key
        return 'post'

    def on_start(self):
        if self._running:
            return
        self._mode = self._selected_mode()
        self._running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        for radio in self._radios.values():
            radio.setEnabled(False)
        self.status_label.setText('正在启动浏览器…')

        self._session = _BrowserExtractSession(self)
        self._session.launched.connect(lambda: self.status_label.setText('浏览器已打开，等待登录…'))
        self._session.login_ok.connect(self._on_login_ok)
        self._session.log_msg.connect(self.status_label.setText)
        self._session.self_ready.connect(self.self_ready)
        self._session.tasks_page.connect(self._on_tasks)
        self._session.done.connect(self._on_done)
        self._session.failed.connect(self._on_failed)
        self._session.start(self._mode)

    def on_stop(self):
        if self._session:
            self._session.request_stop()
        self.status_label.setText('正在停止…')
        self.stop_btn.setEnabled(False)

    def _on_login_ok(self, cookie_str):
        """登录成功：保存最新 Cookie 到配置（含 msToken 等风控相关字段）"""
        try:
            cfg['cookie'] = cookie_str
            save_config(cfg)
            self.cookie_saved.emit(cookie_str)
        except Exception:
            pass

    def _on_tasks(self, aweme_list, user_info):
        self.tasks_ready.emit(aweme_list, user_info)

    def _on_done(self, total):
        self._running = False
        self._session = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        for radio in self._radios.values():
            radio.setEnabled(True)
        if total > 0:
            self.status_label.setText(f'提取完成，共捕获 {total} 个作品，已加入「作品列表」')
            QtWidgets.QMessageBox.information(
                self, '提取完成', f'共捕获 {total} 个作品，已加入「作品列表」页。'
            )
            self.accept()
        else:
            self.status_label.setText('未捕获到作品：请确认账号在该分类下有内容')
            QtWidgets.QMessageBox.warning(
                self, '提示', '未捕获到作品。请确认账号在该分类下有内容，或稍后重试。'
            )

    def _on_failed(self, message):
        self._running = False
        self._session = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        for radio in self._radios.values():
            radio.setEnabled(True)
        self.status_label.setText('提取失败')
        QtWidgets.QMessageBox.warning(self, '错误', message)

    def closeEvent(self, event):
        if self._session:
            self._session.request_stop()
        super().closeEvent(event)
