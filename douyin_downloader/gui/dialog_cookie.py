#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GUI - Cookie Auto Fetch Dialog
Playwright 在独立线程运行，避免阻塞 UI。
"""
import sys
import os
import queue
import threading
try:
    from PyQt6 import QtWidgets, QtCore
    from PyQt6.QtCore import Qt
except ImportError:
    print("[错误] PyQt6 未安装或无法导入: \n请安装 PyQt6 后重试（pip install PyQt6）。")
    sys.exit(1)

from douyin_downloader.utils.config import load_config, save_config


class _CookieBrowserSession(QtCore.QObject):
    """在后台线程持有 Playwright 浏览器会话"""
    launched = QtCore.pyqtSignal()
    launch_failed = QtCore.pyqtSignal(str)
    cookies_ready = QtCore.pyqtSignal(str)
    cookies_failed = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = queue.Queue()
        self._thread = None

    def start(self, chrome_path, edge_path):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, args=(chrome_path, edge_path), daemon=True
        )
        self._thread.start()

    def request_cookies(self):
        self._queue.put('cookies')

    def request_close(self):
        self._queue.put('close')

    def _run(self, chrome_path, edge_path):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.launch_failed.emit(
                '未安装Playwright库，请运行: pip install playwright\n'
                '然后运行: playwright install chromium'
            )
            return

        try:
            with sync_playwright() as p:
                if chrome_path and os.path.exists(chrome_path):
                    browser = p.chromium.launch(
                        headless=False, executable_path=chrome_path
                    )
                elif edge_path and os.path.exists(edge_path):
                    browser = p.chromium.launch(
                        headless=False, executable_path=edge_path
                    )
                else:
                    browser = p.chromium.launch(headless=False)

                context = browser.new_context()
                page = context.new_page()
                page.goto("https://www.douyin.com/?recommend=1")
                self.launched.emit()

                while True:
                    cmd = self._queue.get()
                    if cmd == 'cookies':
                        try:
                            cookies = context.cookies("https://www.douyin.com")
                            cookie_str = "; ".join(
                                f"{c.get('name', '')}={c.get('value', '')}" for c in cookies
                            )
                            self.cookies_ready.emit(cookie_str)
                        except Exception as e:
                            self.cookies_failed.emit(str(e))
                    elif cmd == 'close':
                        break

                try:
                    browser.close()
                except Exception:
                    pass
        except Exception as e:
            self.launch_failed.emit(str(e))


class CookieFetchWindow(QtWidgets.QDialog):
    """Cookie自动获取窗口"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Cookie自动获取')
        self.setModal(True)
        self.resize(400, 200)
        self._session = None
        self.setup_ui()

    def setup_ui(self):
        """设置界面"""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(15)

        info_text = (
            "请在点击【开始获取】按钮后弹出的浏览器登录账号\n"
            "\n"
            "【如果有二次验证请完成二次验证】\n"
            "\n"
            "建议扫码登录\n"
            "\n"
            "登录并验证成功后点击【确认】按钮"
        )
        info_label = QtWidgets.QLabel(info_text)
        info_label.setWordWrap(True)
        info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(info_label)

        layout.addStretch()

        button_layout = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton('开始获取')
        self.confirm_btn = QtWidgets.QPushButton('确认')
        self.confirm_btn.setObjectName('primary_btn')
        self.confirm_btn.setEnabled(False)

        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.confirm_btn)
        layout.addLayout(button_layout)

        self.start_btn.clicked.connect(self.on_start_fetch)
        self.confirm_btn.clicked.connect(self.on_confirm)

        # 基础控件样式继承 app.py 全局 Apple 设计体系，这里只定义主操作按钮
        self.setStyleSheet("""
        QLabel {
            color: #1D1D1F;
            font-size: 13px;
        }
        QPushButton#primary_btn {
            background-color: #007AFF;
            color: #FFFFFF;
            border-radius: 12px;
        }
        QPushButton#primary_btn:hover {
            background-color: #0064D6;
        }
        QPushButton#primary_btn:pressed {
            background-color: #004FAD;
        }
        QPushButton#primary_btn:disabled {
            background-color: #9FCBFF;
            color: #FFFFFF;
        }
        """)

    def validate_cookie(self, cookie_str):
        """验证Cookie是否有效"""
        try:
            if not cookie_str or len(cookie_str) < 50:
                return False
            if 'sessionid' not in cookie_str:
                return False
            return True
        except Exception:
            return False

    def _close_session(self):
        if self._session:
            try:
                self._session.request_close()
            except Exception:
                pass
            self._session = None

    def on_start_fetch(self):
        """开始获取Cookie（浏览器在后台线程启动）"""
        try:
            config = load_config()
            chrome_path = config.get('chrome_path', '').strip()
            edge_path = config.get('edge_path', '').strip()

            if not chrome_path and not edge_path:
                msg_box = QtWidgets.QMessageBox(self)
                msg_box.setWindowTitle('浏览器未配置')
                msg_box.setText('您尚未配置浏览器路径，是否现在配置浏览器？')
                confirm_button = msg_box.addButton('确认', QtWidgets.QMessageBox.ButtonRole.AcceptRole)
                cancel_button = msg_box.addButton('取消', QtWidgets.QMessageBox.ButtonRole.RejectRole)
                msg_box.setDefaultButton(confirm_button)
                msg_box.exec()

                if msg_box.clickedButton() == confirm_button:
                    from .dialog_browser import BrowserConfigWindow
                    browser_config_window = BrowserConfigWindow(self)
                    browser_config_window.exec()
                    config = load_config()
                    chrome_path = config.get('chrome_path', '').strip()
                    edge_path = config.get('edge_path', '').strip()
                    if chrome_path or edge_path:
                        self.start_btn.setEnabled(True)
                        self.confirm_btn.setEnabled(False)
                        QtWidgets.QMessageBox.information(
                            self, '提示', '浏览器已配置完成，请点击"开始获取"按钮启动浏览器'
                        )
                        return
                    self.start_btn.setEnabled(True)
                    self.confirm_btn.setEnabled(False)
                    return
                return

            self._close_session()
            self.start_btn.setEnabled(False)
            self.confirm_btn.setEnabled(False)
            self.start_btn.setText('正在启动...')

            self._session = _CookieBrowserSession(self)
            self._session.launched.connect(self._on_browser_launched)
            self._session.launch_failed.connect(self._on_browser_launch_failed)
            self._session.cookies_ready.connect(self._on_cookies_ready)
            self._session.cookies_failed.connect(self._on_cookies_failed)
            self._session.start(chrome_path, edge_path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, '错误', f'启动浏览器失败: {str(e)}')
            self.start_btn.setEnabled(True)
            self.start_btn.setText('开始获取')
            self.confirm_btn.setEnabled(False)

    def _on_browser_launched(self):
        self.start_btn.setText('开始获取')
        self.start_btn.setEnabled(False)
        self.confirm_btn.setEnabled(True)

    def _on_browser_launch_failed(self, message):
        QtWidgets.QMessageBox.warning(self, '错误', f'启动浏览器失败: {message}')
        self._session = None
        self.start_btn.setEnabled(True)
        self.start_btn.setText('开始获取')
        self.confirm_btn.setEnabled(False)

    def on_confirm(self):
        """确认并获取Cookie"""
        if not self._session:
            QtWidgets.QMessageBox.warning(
                self, '错误', '请先点击"开始获取"按钮，并等待浏览器启动完成'
            )
            return
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.setText('获取中...')
        self._session.request_cookies()

    def _on_cookies_ready(self, cookie_str):
        self.confirm_btn.setText('确认')
        if not self.validate_cookie(cookie_str):
            QtWidgets.QMessageBox.warning(self, '错误', '获取到的Cookie无效，请重新登录获取')
            self.confirm_btn.setEnabled(True)
            return

        from douyin_downloader.gui import cfg
        cfg['cookie'] = cookie_str
        save_config(cfg)

        parent = self.parent()
        if parent:
            settings_cookie = getattr(parent, 'settings_cookie', None)
            if settings_cookie:
                settings_cookie.setPlainText(cookie_str)

        self._close_session()
        QtWidgets.QMessageBox.information(self, '成功', 'Cookie已成功获取并填入设置中')
        self.accept()

    def _on_cookies_failed(self, message):
        self.confirm_btn.setText('确认')
        self.confirm_btn.setEnabled(True)
        QtWidgets.QMessageBox.warning(self, '错误', f'获取Cookie失败: {message}')

    def closeEvent(self, a0):
        """窗口关闭事件"""
        self._close_session()
        super().closeEvent(a0)
