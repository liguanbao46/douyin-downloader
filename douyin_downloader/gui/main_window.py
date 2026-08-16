#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GUI界面 - 主窗口
"""
import os
import re
import sys
import threading
from datetime import datetime
try:
    from PyQt6 import QtWidgets, QtCore, QtGui
    from PyQt6.QtCore import Qt
except ImportError:
    print("[错误] PyQt6 未安装或无法导入: \n请安装 PyQt6 后重试（pip install PyQt6）。")
    sys.exit(1)

from douyin_downloader.constants import (
    TEXT_APP_NAME, OPENPYXL_AVAILABLE, DEFAULT_THREAD_COUNT, CONFIG_FILE, 
    ICON_BYTES_OPTIONS, CUSTOM_ICON_PATH
)
from douyin_downloader.utils.config import save_config
from douyin_downloader.utils.file_utils import sanitize_filename, safe_mkdir
from douyin_downloader.core.api import extract_sec_user_id_from_url
from douyin_downloader.core.parser import parse_awemes_to_works

from douyin_downloader.gui.worker import Worker
from douyin_downloader.gui import cfg
from douyin_downloader.gui.widgets import NoFocusRectStyle
from douyin_downloader.gui.dialog_log import LogWindow
from douyin_downloader.gui.dialog_userlist import UserListWindow
from douyin_downloader.gui.dialog_settings import SettingsWindow


def get_app_icon():
    """获取应用程序图标"""
    # 从配置中获取图标选择
    icon_choice = cfg.get('icon_choice', 'default')
    
    # 如果配置为使用自定义图标，且自定义图标文件存在，则加载自定义图标文件
    if icon_choice == 'custom' and os.path.exists(CUSTOM_ICON_PATH):
        try:
            with open(CUSTOM_ICON_PATH, 'rb') as f:
                custom_icon_bytes = f.read()
            return custom_icon_bytes
        except Exception as e:
            print(f"Warning: Failed to load custom icon: {e}")
    
    # 使用预设图标
    from douyin_downloader.constants import ICON_BYTES
    return ICON_BYTES_OPTIONS.get(icon_choice, ICON_BYTES)


class MainWindow(QtWidgets.QMainWindow):
    """主窗口"""
    def __init__(self, checkmark_svg_path=''):
        super().__init__()
        self.checkmark_svg_path = checkmark_svg_path
        self.setWindowTitle(TEXT_APP_NAME)
        self.resize(1200, 700)
        # 设置窗口图标，确保任务栏也显示正确的图标
        self._set_window_icon()
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        lay = QtWidgets.QVBoxLayout(central)

        form = QtWidgets.QGridLayout()
        lay.addLayout(form)
        # "主页链接" 标签做成按钮，点击可打开用户列表
        self.url_label_btn = QtWidgets.QPushButton('主页链接:')
        self.url_label_btn.setFlat(True)
        self.url_label_btn.setCursor(QtGui.QCursor(Qt.CursorShape.PointingHandCursor))
        form.addWidget(self.url_label_btn, 0, 0)
        self.url_edit = QtWidgets.QLineEdit()
        form.addWidget(self.url_edit, 0, 1, 1, 1)
        self.like_checkbox = QtWidgets.QCheckBox('点赞作品')
        form.addWidget(self.like_checkbox, 0, 2)
        self.fetch_btn = QtWidgets.QPushButton('获取作品')
        form.addWidget(self.fetch_btn, 0, 3)


        btns = QtWidgets.QHBoxLayout()
        lay.addLayout(btns)
        self.settings_btn = QtWidgets.QPushButton('设置')
        self.clear_btn = QtWidgets.QPushButton('清空列表')
        self.select_all_btn = QtWidgets.QPushButton('全选')
        self.invert_btn = QtWidgets.QPushButton('反选')
        self.export_urls_btn = QtWidgets.QPushButton('导出直链')
        self.export_excel_btn = QtWidgets.QPushButton('导出Excel')
        self.download_btn = QtWidgets.QPushButton('开始下载')
        self.open_folder_btn = QtWidgets.QPushButton('打开文件夹')

        btns.addWidget(self.settings_btn)
        btns.addWidget(self.export_urls_btn)
        btns.addWidget(self.export_excel_btn)
        btns.addStretch()
        btns.addWidget(self.clear_btn)
        btns.addWidget(self.select_all_btn)
        btns.addWidget(self.invert_btn)
        
        if not OPENPYXL_AVAILABLE:
            self.export_excel_btn.setEnabled(False)
            self.export_excel_btn.setToolTip("请先安装 'openpyxl' (pip install openpyxl) 以启用此功能")
        
        btns.addWidget(self.download_btn)
        btns.addWidget(self.open_folder_btn)

        # 搜索框
        search_layout = QtWidgets.QHBoxLayout()
        lay.addLayout(search_layout)
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText('搜索作品标题或作者...')
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMaximumWidth(300)
        search_layout.addWidget(self.search_edit)
        search_layout.addStretch()

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setStyle(NoFocusRectStyle())
        self.tree.setHeaderLabels(['选择', '序号', '作者', '提取方式', '作品类型', '作品标题', '时长/数量', '分辨率', '下载状态', '发布时间'])

        self.type_filter_menu = QtWidgets.QMenu(self)
        self.type_filter_menu.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.type_filter_menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.type_filter_menu.setStyleSheet("""
            QMenu {
                border: 1px solid #dcdfe6;
                background-color: #ffffff;
                border-radius: 0px;
            }
            QCheckBox {
                spacing: 5px;
                padding: 4px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #c0c4cc;
                border-radius: 0px;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                background-color: #409EFF;
                border: 1px solid #409EFF;
                image: url(""" + self.checkmark_svg_path + """);
            }
        """)
        filter_widget = QtWidgets.QWidget()
        filter_layout = QtWidgets.QVBoxLayout(filter_widget)
        filter_layout.setContentsMargins(5, 5, 5, 5)
        filter_layout.setSpacing(2)

        self.video_checkbox = QtWidgets.QCheckBox('视频')
        self.image_checkbox = QtWidgets.QCheckBox('图集')
        self.live_checkbox = QtWidgets.QCheckBox('实况')

        self.video_checkbox.setChecked(True)
        self.image_checkbox.setChecked(True)
        self.live_checkbox.setChecked(True)

        filter_layout.addWidget(self.video_checkbox)
        filter_layout.addWidget(self.image_checkbox)
        filter_layout.addWidget(self.live_checkbox)

        filter_action = QtWidgets.QWidgetAction(self.type_filter_menu)
        filter_action.setDefaultWidget(filter_widget)
        self.type_filter_menu.addAction(filter_action)

        self.video_checkbox.stateChanged.connect(self.on_type_filter_changed)
        self.image_checkbox.stateChanged.connect(self.on_type_filter_changed)
        self.live_checkbox.stateChanged.connect(self.on_type_filter_changed)

        fm = self.tree.fontMetrics()
        width0 = fm.horizontalAdvance('选择') + 16
        self.tree.setColumnWidth(0, width0)
        self.tree.setColumnWidth(1, 50)   # 序号
        self.tree.setColumnWidth(2, 80)   # 作者
        self.tree.setColumnWidth(3, 70)   # 提取方式
        self.tree.setColumnWidth(4, 80)   # 作品类型
        self.tree.setColumnWidth(5, 300)  # 作品标题 (stretch)
        self.tree.setColumnWidth(6, 80)   # 时长/数量
        self.tree.setColumnWidth(7, 90)   # 分辨率
        self.tree.setColumnWidth(8, 70)   # 下载状态
        self.tree.setColumnWidth(9, 100)  # 发布时间

        header = self.tree.header()
        hdr_h = fm.height() + 10
        if header:
            header.setFixedHeight(int(hdr_h))
            header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
            for col in range(1, 10):
                if col == 5:
                    header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeMode.Stretch)
                else:
                    header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeMode.Fixed)
            header.setSectionsMovable(False)
            header.setStretchLastSection(False)

        if header:
            header.sectionClicked.connect(self.on_header_section_clicked)
            header.setSectionsClickable(True)
            
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setAttribute(QtCore.Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.tree.setFrameShape(QtWidgets.QFrame.Shape.Box)
        self.tree.setAlternatingRowColors(True)
        self.tree.setStyleSheet(
            "QTreeWidget { background: #ffffff; border: 1px solid #e6eef8; show-decoration-selected: 0; }"
            "QTreeWidget::item { padding:6px 4px; color: #222222; outline: 0; }"
            "QTreeWidget::item:focus { outline: 0; border: 0; }"
            "QTreeWidget::item:selected { background: #e6f2ff; color: #000000; outline: 0; }"
            "QTreeWidget::item:selected:active { background: #e6f2ff; outline: 0; }"
            "QTreeWidget::item:selected:!active { background: #e6f2ff; outline: 0; }"
        )
        lay.addWidget(self.tree)

        bottom = QtWidgets.QHBoxLayout()
        lay.addLayout(bottom)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setFixedHeight(26)
        self.progress.setTextVisible(True)
        self.progress.setStyleSheet(
            "QProgressBar { border: none; border-radius: 0px; background: #f0f0f0; text-align: center; }"
            "QProgressBar::chunk { background-color: #5aa6ff; border-radius: 0px; }"
        )
        bottom.addWidget(self.progress)
        self.progress.hide()

        status_layout = QtWidgets.QHBoxLayout()
        lay.addLayout(status_layout)
        self.status = QtWidgets.QLabel('')
        # 长文本（如下载失败的 URL）自动换行，避免撑大窗口宽度
        self.status.setWordWrap(True)
        self.status.setMinimumWidth(0)
        self.status.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Minimum)
        self.status.setCursor(QtGui.QCursor(Qt.CursorShape.PointingHandCursor))
        self.status.setMouseTracking(True)
        status_layout.addWidget(self.status)
        status_layout.addStretch()
        status_layout.addWidget(QtWidgets.QLabel('当前用户:'))
        self.nickname_label = QtWidgets.QLabel('')
        font = self.nickname_label.font()
        font.setBold(True)
        self.nickname_label.setFont(font)
        status_layout.addWidget(self.nickname_label)

        self.vtasks_all = []
        self.itasks_all = []
        self.vtasks = []
        self.itasks = []
        self.all_awemes = []
        self.all_works = []  # 作品级分组数据
        self._download_status = {}  # aweme_id -> '' | '已下载' | '下载中' | '部分完成'
        self.current_nickname = ''

        self.log_window = LogWindow(self)
        self.log_window.hide()
        self.user_list_window = UserListWindow(self, self.checkmark_svg_path)
        self.user_list_window.hide()
        self.settings_window = SettingsWindow(self, self.checkmark_svg_path)
        self.settings_window.hide()

        self.worker = Worker()
        self._thread = None

        btn_font = QtGui.QFont()
        btn_font.setPointSize(11)
        self.like_checkbox.setFont(btn_font)
        for b in (self.fetch_btn, self.download_btn, self.settings_btn, self.clear_btn, self.select_all_btn, self.invert_btn, self.export_urls_btn):
            b.setFont(btn_font)
        button_width = 100
        self.fetch_btn.setFixedWidth(button_width)
        self.download_btn.setFixedWidth(button_width)

        self.clear_btn.setStyleSheet('''
            QPushButton {
                background: #d9534f; color: white; padding: 7px 14px;
                border: none; font-weight: 500; font-size: 13px;                 
            }
            QPushButton:hover { background: #fa8480; }
            QPushButton:disabled { background: #f0b3b3; color: #f8e6e6; }
        ''')

        self.url_label_btn.clicked.connect(self.on_show_user_list)
        self.fetch_btn.clicked.connect(self.on_fetch)
        self.download_btn.clicked.connect(self.on_download)
        self.settings_btn.clicked.connect(self.on_settings)
        self.select_all_btn.clicked.connect(self.on_select_all)
        self.export_excel_btn.clicked.connect(self.on_export_excel)
        self.export_urls_btn.clicked.connect(self.on_export_urls)
        self.invert_btn.clicked.connect(self.on_invert)
        self.clear_btn.clicked.connect(self.on_clear_list)
        self.open_folder_btn.clicked.connect(self.on_open_folder)
        self.search_edit.textChanged.connect(self.on_search_changed)
        self.status.mousePressEvent = lambda ev: self.on_status_click(ev)

        self.worker.log_signal.connect(self.append_log)
        self.worker.tasks_signal.connect(lambda vtasks, itasks, nickname, aweme_list: self.on_tasks_received(vtasks, itasks, nickname, aweme_list))
        self.worker.progress_signal.connect(self.on_progress)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.fetch_finished.connect(self.on_fetch_finished)
        self.worker.download_finished.connect(self.on_download_finished)
        self.worker.export_finished_signal.connect(self._on_export_finished)
        self.worker.export_error_signal.connect(self._on_export_error)

        self.tree.itemSelectionChanged.connect(self.on_tree_selection_changed)
        self.tree.itemChanged.connect(self.on_tree_item_changed)

        self._programmatic_change = False  # 防止联动循环
        self._last_status_text = ''

        if not os.path.exists(CONFIG_FILE):
            QtCore.QTimer.singleShot(500, self.show_first_time_settings)

    def append_log(self, text):
        """向日志窗口和状态栏输出日志"""
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if '\n' in text:
            lines = text.split('\n')
            formatted_lines = [f"[{ts}] {line}" for line in lines]
            full_log_text = "\n".join(formatted_lines)
            # 状态栏只显示最后一条
            self._last_status_text = lines[-1]
        else:
            full_log_text = f"[{ts}] {text}"
            self._last_status_text = text

        if self.log_window:
            self.log_window.append_log(full_log_text)

        self.update_status_label()

    def update_status_label(self):
        """更新状态栏（基础文本 + 选择计数）"""
        try:
            count = 0
            for i in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(i)
                if it and it.checkState(0) == Qt.CheckState.Checked:
                    count += 1
            base = getattr(self, '_last_status_text', '') or ''
            # 超长文本（含 URL）截断显示，完整内容见日志窗口
            if len(base) > 150:
                base = base[:150] + '…'
            if count > 0:
                self.status.setText(f"{base} （已选择 {count} 个）")
            else:
                self.status.setText(base)
        except Exception:
            pass

    def on_search_changed(self, text):
        """搜索框文本变化 → 过滤作品列表"""
        text = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if not item:
                continue
            if not text:
                item.setHidden(False)
            else:
                title = item.text(5).lower()
                author = item.text(2).lower()
                item.setHidden(text not in title and text not in author)

    def on_header_section_clicked(self, logical_index):
        """处理表头点击事件"""
        if logical_index == 5:  # 类型列
            # 切换菜单显示状态
            header = self.tree.header()
            if header:
                # 获取列的视觉区域
                left = header.sectionPosition(logical_index)
                width = header.sectionSize(logical_index)
                height = header.height()
                
                # 计算菜单显示位置，使右侧对齐
                menu_width = self.type_filter_menu.sizeHint().width()
                point = QtCore.QPoint(left + width - menu_width, height)
                global_point = self.tree.mapToGlobal(point)
                
                # 切换菜单显示/隐藏状态
                if self.type_filter_menu.isVisible():
                    self.type_filter_menu.hide()
                else:
                    # 只有在点击第5列时才在精确位置显示
                    self.type_filter_menu.popup(global_point)
    
    def on_type_filter_changed(self, state):
        """处理类型筛选变化"""
        # 防止在同步过程中再次触发
        if getattr(self, '_programmatic_change', False):
            return
        self.apply_type_filter()

    def apply_type_filter(self):
        """应用类型筛选到列表项的选择状态（作品级类型）"""
        select_video = self.video_checkbox.isChecked()
        select_image = self.image_checkbox.isChecked()
        select_live = self.live_checkbox.isChecked()

        self.tree.setUpdatesEnabled(False)
        try:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item:
                    item_type = item.text(4)  # 第4列=作品类型

                    should_select = False
                    if item_type == '视频' and select_video:
                        should_select = True
                    elif item_type == '视频+图集' and select_video and select_image:
                        should_select = True
                    elif item_type == '图集' and select_image:
                        should_select = True
                    elif item_type == '图集+实况' and (select_image or select_live):
                        should_select = True
                    elif item_type == '实况图集' and select_live:
                        should_select = True

                    # 全选时选中所有
                    if select_video and select_image and select_live:
                        should_select = True

                    if should_select:
                        item.setCheckState(0, Qt.CheckState.Checked)
                    else:
                        item.setCheckState(0, Qt.CheckState.Unchecked)
        finally:
            self.tree.setUpdatesEnabled(True)

        self.sync_filter_checkboxes()

    def sync_filter_checkboxes(self):
        """同步筛选复选框状态（作品级类型）"""
        if getattr(self, '_programmatic_change', False):
            return

        video_total = 0
        video_selected = 0
        image_total = 0
        image_selected = 0
        live_total = 0
        live_selected = 0

        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item:
                item_type = item.text(4)  # 第4列=作品类型
                is_selected = item.checkState(0) == Qt.CheckState.Checked

                # 视频 / 视频+图集 → 计入视频
                if item_type in ('视频', '视频+图集'):
                    video_total += 1
                    if is_selected:
                        video_selected += 1

                # 图集 / 图集+实况 / 视频+图集 → 计入图集
                if item_type in ('图集', '图集+实况', '视频+图集'):
                    image_total += 1
                    if is_selected:
                        image_selected += 1

                # 实况图集 / 图集+实况 → 计入实况
                if item_type in ('实况图集', '图集+实况'):
                    live_total += 1
                    if is_selected:
                        live_selected += 1
        
        self._programmatic_change = True  # 防止循环触发
        try:
            if video_total > 0:
                if video_selected == video_total:
                    self.video_checkbox.setCheckState(Qt.CheckState.Checked)
                elif video_selected == 0:
                    self.video_checkbox.setCheckState(Qt.CheckState.Unchecked)
                else:
                    self.video_checkbox.setCheckState(Qt.CheckState.PartiallyChecked)
            
            if image_total > 0:
                if image_selected == image_total:
                    self.image_checkbox.setCheckState(Qt.CheckState.Checked)
                elif image_selected == 0:
                    self.image_checkbox.setCheckState(Qt.CheckState.Unchecked)
                else:
                    self.image_checkbox.setCheckState(Qt.CheckState.PartiallyChecked)
            
            if live_total > 0:
                if live_selected == live_total:
                    self.live_checkbox.setCheckState(Qt.CheckState.Checked)
                elif live_selected == 0:
                    self.live_checkbox.setCheckState(Qt.CheckState.Unchecked)
                else:
                    self.live_checkbox.setCheckState(Qt.CheckState.PartiallyChecked)
        finally:
            self._programmatic_change = False

    def on_tree_selection_changed(self):
        """处理列表选择变化 (行选 -> 勾选)"""
        if getattr(self, '_programmatic_change', False):
            return
        self._programmatic_change = True
        try:
            self.tree.setUpdatesEnabled(False)
            try:
                for i in range(self.tree.topLevelItemCount()):
                    it = self.tree.topLevelItem(i)
                    if it:
                        if it.isSelected():
                            it.setCheckState(0, Qt.CheckState.Checked)
                        else:
                            it.setCheckState(0, Qt.CheckState.Unchecked)
            finally:
                self.tree.setUpdatesEnabled(True)
        finally:
            self._programmatic_change = False
        self.update_status_label()
        self.sync_filter_checkboxes()

    def on_tree_item_changed(self, item, column):
        """处理复选框变化 (勾选 -> 行选)"""
        if getattr(self, '_programmatic_change', False):
            return
        self._programmatic_change = True
        try:
            if column == 0:
                state = item.checkState(0)
                if state == Qt.CheckState.Checked:
                    item.setSelected(True)
                else:
                    item.setSelected(False)
        finally:
            self._programmatic_change = False
        self.update_status_label()
        self.sync_filter_checkboxes()

    def on_progress(self, done, total):
        """更新进度条"""
        if not self.progress.isVisible():
            self.progress.show()
            
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        pct = int((done / max(1, total)) * 100)
        self.progress.setFormat(f"%v / %m ({pct}%)")
        
        # 完成时变绿
        try:
            if total > 0 and done >= total:
                self.progress.setStyleSheet(
                    "QProgressBar { border: none; border-radius: 0px; background: #f0f0f0; text-align: center; }"
                    "QProgressBar::chunk { background-color: #4CC14C; border-radius: 0px; }"
                )
            else:
                # 恢复进行中颜色（蓝色）
                self.progress.setStyleSheet(
                    "QProgressBar { border: none; border-radius: 0px; background: #f0f0f0; text-align: center; }"
                    "QProgressBar::chunk { background-color: #5aa6ff; border-radius: 0px; }"
                )
        except Exception:
            pass
    
    def on_download_finished(self):
        """下载完成处理（确保进度条是绿色，并更新下载状态列）"""
        try:
            maxv = self.progress.maximum() or self.progress.value() or 1
            self.progress.setValue(maxv)
            if hasattr(self.worker, '_download_stop_requested') and self.worker._download_stop_requested:
                self.progress.setFormat(f"%v / %m (已停止)")
                self.progress.hide()
            else:
                self.progress.setFormat(f"%v / %m (完成)")
            self.progress.setStyleSheet(
                "QProgressBar { border: none; border-radius: 0px; background: #f0f0f0; text-align: center; }"
                "QProgressBar::chunk { background-color: #4CC14C; border-radius: 0px; }"
            )

            # 将本次下载的作品标记为「已下载」或「失败」
            done_ids = getattr(self, '_downloading_ids', set())
            failed_ids = set()
            for t in getattr(self.worker, '_failed_tasks', []):
                aid = t.get('aweme_id', '')
                if aid:
                    failed_ids.add(aid)

            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item:
                    work = item.data(0, Qt.ItemDataRole.UserRole)
                    if work and work.get('aweme_id') in done_ids:
                        if work['aweme_id'] in failed_ids:
                            self._download_status[work['aweme_id']] = '失败'
                            item.setText(8, '失败')
                        else:
                            self._download_status[work['aweme_id']] = '已下载'
                            item.setText(8, '已下载')
        except Exception:
            pass

    def on_open_folder(self):
        """打开下载文件夹"""
        import subprocess
        base_folder = cfg.get('path', '') or os.getcwd()
        download_folder = os.path.join(base_folder, '作品下载')
        nickname = self.nickname_label.text() or ''
        unique_id = getattr(self, 'current_unique_id', '') or ''
        if nickname:
            folder_name = f"{nickname}-{unique_id}" if unique_id else nickname
            if getattr(self, '_fetch_mode', '') == 'favorite':
                folder_name += '-like'
            user_folder = os.path.join(download_folder, sanitize_filename(folder_name))
        else:
            user_folder = download_folder
        if not os.path.exists(user_folder):
            user_folder = download_folder if os.path.exists(download_folder) else base_folder
        try:
            if sys.platform.startswith('win'):
                os.startfile(user_folder)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', user_folder])
            else:
                subprocess.Popen(['xdg-open', user_folder])
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, '提示', f'无法打开文件夹: {e}')

    def on_export_excel(self):
        """导出Excel表格"""
        if not hasattr(self, 'all_awemes') or not self.all_awemes:
            QtWidgets.QMessageBox.warning(self, '提示', '没有作品数据可以导出')
            return

        self.export_excel_btn.setText('正在导出')
        self.export_excel_btn.setEnabled(False)

        all_awemes_copy = list(self.all_awemes)
        nickname = self.nickname_label.text() or '抖音用户'
        unique_id = getattr(self, 'current_unique_id', '') or ''
        if unique_id:
            excel_nickname = f"{nickname}-{unique_id}"
        else:
            excel_nickname = nickname

        if getattr(self, '_fetch_mode', '') == 'favorite':
            excel_nickname += '-like'

        base_folder = cfg.get('path', '') or os.getcwd()
        excel_base_folder = os.path.join(base_folder, '作品数据Excel')

        export_thread = threading.Thread(
            target=self.worker.export_excel, 
            args=(all_awemes_copy, excel_nickname, excel_base_folder), 
            daemon=True
        )
        export_thread.start()

    def on_export_urls(self):
        """导出视频直链"""
        if not hasattr(self, 'all_awemes') or not self.all_awemes:
            QtWidgets.QMessageBox.warning(self, '提示', '没有作品数据可以导出')
            return

        video_awemes = [aweme for aweme in self.all_awemes if not aweme.get('images')]
        if not video_awemes:
            QtWidgets.QMessageBox.warning(self, '提示', '没有视频作品可以导出直链')
            return

        try:
            base_folder = cfg.get('path', '') or os.getcwd()
            urls_folder = os.path.join(base_folder, '视频直链')

            try:
                if not os.path.exists(urls_folder):
                    os.makedirs(urls_folder, exist_ok=True)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, '错误', f'创建目录失败: {urls_folder}\n错误信息: {str(e)}')
                return

            nickname = self.nickname_label.text() or '抖音用户'
            unique_id = getattr(self, 'current_unique_id', '') or ''
            
            if unique_id:
                filename = f"{sanitize_filename(nickname)}-{unique_id}"
            else:
                filename = f"{sanitize_filename(nickname)}"

            if getattr(self, '_fetch_mode', '') == 'favorite':
                filename += '-like'
            filename += '.txt'
            filepath = os.path.join(urls_folder, filename)

            urls = []
            descs = []
            for aweme in video_awemes:
                video_info = aweme.get('video', {})
                if video_info:
                    bit_rate_list = video_info.get('bit_rate', [])
                    if bit_rate_list:
                        best = max(bit_rate_list, key=lambda x: x.get('bit_rate', 0))
                        url_list = best.get('play_addr', {}).get('url_list', [])
                        if len(url_list) >= 3:
                            full_url = url_list[2]
                            import re
                            video_id_match = re.search(r'video_id=([^&]*)', full_url)
                            file_id_match = re.search(r'file_id=([^&]*)', full_url)
                            if video_id_match and file_id_match:
                                video_id = video_id_match.group(1)
                                file_id = file_id_match.group(1)
                                simplified_url = f"https://www.douyin.com/aweme/v1/play/?video_id={video_id}&file_id={file_id}"
                                urls.append(simplified_url)
                                descs.append(aweme.get('desc', ''))

            add_title = cfg.get('add_title_when_export_urls', False)
            if add_title:
                if unique_id:
                    filename = f"{sanitize_filename(nickname)}-{unique_id}"
                else:
                    filename = f"{sanitize_filename(nickname)}"

                if getattr(self, '_fetch_mode', '') == 'favorite':
                    filename += '-like'
                filename += '_desc.txt'
                filepath = os.path.join(urls_folder, filename)

                try:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        for i, (desc, url) in enumerate(zip(descs, urls), 1):
                            f.write(f"{i}.{desc}\n{url}\n\n")
                except Exception as e:
                    QtWidgets.QMessageBox.critical(self, '错误', f'写入文件失败: {filepath}\n错误信息: {str(e)}')
                    return
            else:
                try:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        for url in urls:
                            f.write(url + '\n')
                except Exception as e:
                    QtWidgets.QMessageBox.critical(self, '错误', f'写入文件失败: {filepath}\n错误信息: {str(e)}')
                    return

            # 提示成功
            msg_box = QtWidgets.QMessageBox(self)
            msg_box.setWindowTitle('导出成功')
            msg_box.setText(f'视频直链已保存至:\n{filepath}')
            msg_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
            ok_button = msg_box.button(QtWidgets.QMessageBox.StandardButton.Ok)
            if ok_button: ok_button.setText('确认')
            msg_box.exec()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, '错误', f'导出直链失败: {str(e)}')
            self.append_log(f'[错误] 导出直链失败: {str(e)}')

    def _on_export_finished(self, filepath):
        """导出完成后的UI更新"""
        self.export_excel_btn.setText('导出Excel')
        self.export_excel_btn.setEnabled(True)
        msg_box = QtWidgets.QMessageBox(self)
        msg_box.setWindowTitle('导出成功')
        msg_box.setText(f'Excel文件已保存至:\n{filepath}')
        msg_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        ok_button = msg_box.button(QtWidgets.QMessageBox.StandardButton.Ok)
        if ok_button: ok_button.setText('确认')
        msg_box.exec()

    def _on_export_error(self, error_msg):
        """导出失败后的UI更新"""
        self.export_excel_btn.setText('导出Excel表格')
        self.export_excel_btn.setEnabled(True)
        QtWidgets.QMessageBox.warning(self, '导出失败', error_msg)
        self.append_log(error_msg)

    @staticmethod
    def _format_duration(ms):
        """毫秒 -> 'MM:SS' 或 'HH:MM:SS'"""
        if not ms:
            return ''
        s = int(ms) // 1000
        if s < 3600:
            return f'{s // 60:02d}:{s % 60:02d}'
        return f'{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}'

    @staticmethod
    def _format_media_info(work):
        """格式化 时长/数量 列的内容"""
        if work['video_count'] > 0:
            dur = MainWindow._format_duration(work.get('duration_ms', 0))
            parts = [dur] if dur else []
            total_imgs = work['image_count'] + work['live_count']
            if total_imgs > 0:
                live_str = f"{work['live_count']}实况" if work['live_count'] > 0 else ''
                img_str = f"{work['image_count']}图" if work['image_count'] > 0 else ''
                img_parts = '+'.join(filter(None, [img_str, live_str]))
                parts.append(f"{total_imgs}张({img_parts})")
            return ' + '.join(parts) if parts else ''
        total_imgs = work['image_count'] + work['live_count']
        parts = []
        if work['image_count'] > 0:
            parts.append(f"{work['image_count']}张图")
        if work['live_count'] > 0:
            parts.append(f"{work['live_count']}张实况")
        return '+'.join(parts) if parts else str(total_imgs)

    def on_tasks_received(self, vtasks, itasks, user_info, aweme_list):
        """接收 Worker 增量获取到的作品数据，按作品（aweme）分组展示"""
        self.progress.hide()

        nickname = user_info
        unique_id = ''
        if '|' in user_info:
            parts = user_info.split('|', 1)
            nickname = parts[0]
            unique_id = parts[1]

        self.nickname_label.setText(nickname or '')
        self.current_nickname = nickname or ''
        self.current_unique_id = unique_id

        new_works = parse_awemes_to_works(aweme_list or [])
        self.all_works.extend(new_works)

        if not hasattr(self, 'vtasks_all'):
            self.vtasks_all = []
        if not hasattr(self, 'itasks_all'):
            self.itasks_all = []
        self.vtasks_all.extend(vtasks or [])
        self.itasks_all.extend(itasks or [])

        # 批量提取模式下累加（worker.all_awemes 每个用户会重置）
        if getattr(self, '_batch_keep_existing', False):
            if not hasattr(self, 'all_awemes'):
                self.all_awemes = []
            self.all_awemes.extend(aweme_list or [])
        elif hasattr(self.worker, 'all_awemes'):
            self.all_awemes = self.worker.all_awemes
        else:
            if not hasattr(self, 'all_awemes'):
                self.all_awemes = []
            self.all_awemes.extend(aweme_list or [])
        # 当前用户（本次 fetch）的 awemes，供 on_fetch_finished 使用
        if not hasattr(self, '_current_fetch_awemes'):
            self._current_fetch_awemes = []
        self._current_fetch_awemes.extend(aweme_list or [])

        fetch_mode_label = '点赞' if getattr(self, '_fetch_mode', '') == 'favorite' else '主页'
        items_to_add = []
        idx = self.tree.topLevelItemCount() + 1

        for work in new_works:
            media_info = self._format_media_info(work)
            dl_status = self._download_status.get(work['aweme_id'], '')

            item = QtWidgets.QTreeWidgetItem([
                ' ', str(idx),
                work.get('author_nickname', ''),
                fetch_mode_label,
                work['work_type'],
                work['desc'],
                media_info,
                work.get('resolution', ''),
                dl_status,
                work['date_str'],
            ])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setData(0, Qt.ItemDataRole.UserRole, work)
            items_to_add.append(item)
            idx += 1

        if items_to_add:
            BATCH_SIZE = 100
            total_items = len(items_to_add)
            if total_items <= BATCH_SIZE:
                self.tree.setUpdatesEnabled(False)
                try:
                    self.tree.addTopLevelItems(items_to_add)
                finally:
                    self.tree.setUpdatesEnabled(True)
            else:
                for i in range(0, total_items, BATCH_SIZE):
                    batch = items_to_add[i:i + BATCH_SIZE]
                    self.tree.setUpdatesEnabled(False)
                    try:
                        self.tree.addTopLevelItems(batch)
                        QtWidgets.QApplication.processEvents()
                    finally:
                        self.tree.setUpdatesEnabled(True)

            self.clear_btn.setVisible(True)
            self.select_all_btn.setVisible(True)
            self.invert_btn.setVisible(True)

        self.vtasks = list(self.vtasks_all)
        self.itasks = list(self.itasks_all)
        self.tree.repaint()
        self.sync_filter_checkboxes()
        self._last_status_text = f'已获取 {len(self.all_works)} 个作品'
        self.update_status_label()

    def showEvent(self, a0):
        """窗口显示事件（用于修复列宽）"""
        try:
            header = self.tree.header()
            fm = self.tree.fontMetrics()
            target_px = fm.horizontalAdvance('汉' * 6) + 12
            if header:
                header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Fixed)
                header.resizeSection(4, int(target_px))
        except Exception:
            pass
        return super().showEvent(a0)

    def resizeEvent(self, a0):
        """窗口大小调整事件（用于修复列宽）"""
        try:
            header = self.tree.header()
            fm = self.tree.fontMetrics()
            target_px = fm.horizontalAdvance('汉' * 4) + 12
            if header:
                header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Fixed)
                header.resizeSection(4, int(target_px))
        except Exception:
            pass
        return super().resizeEvent(a0)
    
    def on_show_user_list(self):
        """显示用户列表窗口"""
        try:
            if self.user_list_window:
                self.user_list_window.load_users()
                self.user_list_window.show()
                self.user_list_window.raise_()
                self.user_list_window.activateWindow()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, '错误', f'无法打开用户列表: {e}')

    def start_batch_fetch(self, urls):
        """批量提取多个主页的作品（主页列表勾选的作者），作品累加到列表"""
        if not urls:
            return
        if self.fetch_btn.text() == '停止获取' or \
                (hasattr(self, '_thread') and self._thread and self._thread.is_alive()):
            QtWidgets.QMessageBox.warning(self, '提示', '当前有任务进行中，请等待完成或停止后再批量提取')
            return
        self._batch_fetch_queue = list(urls)
        self._batch_fetch_total = len(urls)
        self._batch_fetch_done = 0
        self.append_log(f'[信息] 开始批量提取 {len(urls)} 个主页的作品（列表累加展示）')
        self._batch_fetch_next()

    def _batch_fetch_next(self):
        """批量提取队列：获取下一个用户的作品"""
        queue = getattr(self, '_batch_fetch_queue', None)
        if not queue:
            # 全部完成
            total = getattr(self, '_batch_fetch_total', 0)
            if total:
                self.append_log(f'[完成] 批量提取完成：{total} 个主页，列表共 {self.tree.topLevelItemCount()} 个作品')
                self._batch_fetch_total = 0
                self._batch_fetch_done = 0
                self._batch_keep_existing = False
            return
        if getattr(self.worker, '_fetch_stop_requested', False):
            self._batch_fetch_queue = []
            self.append_log('[信息] 批量提取已停止')
            return
        url = queue.pop(0)
        self._batch_fetch_done = getattr(self, '_batch_fetch_done', 0) + 1
        # 第一个用户前清空列表，后续用户累加
        self._batch_keep_existing = self._batch_fetch_done > 1
        self.url_edit.setText(url)
        self.append_log(f"[信息] 批量提取进度 {self._batch_fetch_done}/{self._batch_fetch_total}")
        self.on_fetch()

    def on_fetch(self):
        """获取作品 / 停止获取"""
        if self.fetch_btn.text() == '停止获取':
            try:
                if hasattr(self.worker, '_fetch_stop_requested'):
                    self.worker._fetch_stop_requested = True
                # 批量提取模式下停止 → 清空队列
                self._batch_fetch_queue = []
                self.append_log('[信息] 已请求停止获取')
                # 立即更新按钮状态
                self.fetch_btn.setText('获取作品')
                self.fetch_btn.setProperty("running", False)
                style = self.style()
                if style:
                    style.unpolish(self.fetch_btn)
                    style.polish(self.fetch_btn)
                self.url_label_btn.setEnabled(True)
                self.settings_btn.setEnabled(True)
                self.clear_btn.setEnabled(True)
                self.select_all_btn.setEnabled(True)
                self.export_excel_btn.setEnabled(True)
                self.export_urls_btn.setEnabled(True)
                self.invert_btn.setEnabled(True)
                self.download_btn.setEnabled(True)
                self.like_checkbox.setEnabled(True)
            except Exception:
                pass
            if hasattr(self, '_thread') and self._thread and self._thread.is_alive():
                self._thread.join(timeout=3)
            return

        url = self.url_edit.text().strip()
        if not url:
            QtWidgets.QMessageBox.warning(self, '提示', '请输入主页链接')
            return
        cookie = cfg.get('cookie', '')
        if not cookie:
            QtWidgets.QMessageBox.warning(self, '提示', '请在设置中配置 Cookie')
            return
        
        self.url_label_btn.setEnabled(False)
        self.settings_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.select_all_btn.setEnabled(False)
        self.export_excel_btn.setEnabled(False)
        self.export_urls_btn.setEnabled(False)
        self.invert_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.like_checkbox.setEnabled(False)

        try:
            # 批量提取模式下：非第一个用户不清空列表，作品累加展示
            if not getattr(self, '_batch_keep_existing', False):
                self.tree.clear()
                self.vtasks_all = []
                self.itasks_all = []
                self.vtasks = []
                self.itasks = []
                self.all_awemes = []  # 清空aweme数据
                self.all_works = []   # 清空作品分组数据
                self._download_status = {}  # 清空下载状态
                self.current_nickname = ''
                if hasattr(self.worker, 'all_awemes'): self.worker.all_awemes = []  # 清空Worker中的aweme数据
                if hasattr(self.worker, '_completed_tasks'): self.worker._completed_tasks = []
                if hasattr(self.worker, '_failed_tasks'): self.worker._failed_tasks = []
                if hasattr(self.worker, '_total_received'): self.worker._total_received = 0
                self.progress.setValue(0)
                self.progress.hide()
                self.status.setText('')
                self.append_log('[信息] 已清空上次获取的列表')
            

        except Exception:
            pass
        
        self._current_fetch_awemes = []  # 记录本次 fetch 的 awemes（批量模式下用于区分用户）
        fetch_mode = 'favorite' if self.like_checkbox.isChecked() else 'post'
        self._fetch_mode = fetch_mode
        btn_text = '停止获取'
        self.fetch_btn.setText(btn_text)
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setProperty("running", True)
        style = self.style()
        if style:
            style.unpolish(self.fetch_btn)
            style.polish(self.fetch_btn)

        self.worker._fetch_stop_requested = False
        self._thread = threading.Thread(target=self.worker.fetch_tasks, args=(url, cookie, fetch_mode), daemon=True)
        self._thread.start()

    def closeEvent(self, a0):
        """窗口关闭事件"""
        running_tasks = False
        if hasattr(self, '_thread') and self._thread and self._thread.is_alive():
            running_tasks = True
        elif hasattr(self.worker, '_pause_requested') and getattr(self.worker, '_pause_requested', False):
            running_tasks = True
        
        if running_tasks:
            msg_box = QtWidgets.QMessageBox(self)
            msg_box.setWindowTitle('确认退出')
            msg_box.setText('检测到有下载任务正在运行，确定要关闭程序吗？\n\n注意：关闭程序将终止所有正在进行的下载任务。')
            msg_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel)
            msg_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Cancel)
            ok_button = msg_box.button(QtWidgets.QMessageBox.StandardButton.Ok)
            cancel_button = msg_box.button(QtWidgets.QMessageBox.StandardButton.Cancel)
            if ok_button: ok_button.setText('确认退出')
            if cancel_button: cancel_button.setText('取消')
            
            if msg_box.exec() != QtWidgets.QMessageBox.StandardButton.Ok:
                if a0:
                    a0.ignore()
                return
        
        # 确认关闭
        try:
            # 请求停止所有任务
            if hasattr(self.worker, '_fetch_stop_requested'):
                self.worker._fetch_stop_requested = True
            if hasattr(self.worker, '_pause_requested'):
                self.worker._pause_requested = True
            if hasattr(self.worker, '_download_stop_requested'):
                self.worker._download_stop_requested = True
            
            # 等待线程（最多5秒）
            if hasattr(self, '_thread') and self._thread and self._thread.is_alive():
                # 先尝试等待一小段时间
                self._thread.join(timeout=1.0)
                # 如果线程仍然活跃，强制设置标志并再次等待
                if self._thread.is_alive():
                    # 再等待4秒
                    self._thread.join(timeout=4.0)
                
            # 关闭所有子窗口
            for w in (self.log_window, self.user_list_window, self.settings_window):
                if w: 
                    try:
                        w.close()
                    except:
                        pass  # 忽略子窗口关闭时的异常
                
        except Exception as e:
            print(f"[警告] 关闭时清理资源出现异常: {e}")
        
        if a0:
            a0.accept()

    def on_download(self):
        """开始下载按钮处理"""
        # 检查是否正在下载（切换为停止）
        if self.download_btn.text() == '停止下载':
            try:
                if hasattr(self.worker, '_download_stop_requested'):
                    self.worker._download_stop_requested = True
                self.append_log('[信息] 已请求停止下载')
                # 立即更新按钮状态
                self.download_btn.setText('开始下载')
                
                # 设置 "running" 属性为 False，QSS会自动应用蓝色样式
                self.download_btn.setProperty("running", False)
                style = self.style()
                if style:
                    style.unpolish(self.download_btn)
                    style.polish(self.download_btn)
                self.progress.hide()

                self.url_label_btn.setEnabled(True)
                self.settings_btn.setEnabled(True)
                self.clear_btn.setEnabled(True)
                self.select_all_btn.setEnabled(True)
                self.export_excel_btn.setEnabled(True)
                self.export_urls_btn.setEnabled(True)
                self.invert_btn.setEnabled(True)
                self.fetch_btn.setEnabled(True)
                self.like_checkbox.setEnabled(True)
            except Exception:
                pass
            return

        selected = []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it and it.checkState(0) == Qt.CheckState.Checked:
                data = it.data(0, Qt.ItemDataRole.UserRole)
                if data:
                    selected.append(data)

        if not selected:
            QtWidgets.QMessageBox.warning(self, '提示', '请先选择要下载的作品')
            return

        # 将选中的作品展开为扁平的下载任务列表（按作者分文件夹）
        sel_v = []
        sel_i = []
        self._downloading_ids = set()

        base_folder = cfg.get('path', '') or os.getcwd()
        download_folder = os.path.join(base_folder, '作品下载')

        def author_folder_for(work):
            """根据作品自身作者信息计算文件夹：作品下载/昵称-unique_id"""
            nickname = work.get('author_nickname') or ''
            unique_id = ''
            aweme = work.get('aweme')
            author = aweme.get('author') if isinstance(aweme, dict) else None
            if isinstance(author, dict):
                unique_id = author.get('unique_id', '') or author.get('short_id', '') or ''
            if not nickname:
                # 兜底：作品缺少作者信息时用当前界面上的用户
                nickname = self.nickname_label.text() or 'Douyin_User'
                unique_id = unique_id or (getattr(self, 'current_unique_id', '') or '')
            folder_name = f"{nickname}-{unique_id}" if unique_id else (nickname or 'Douyin_Downloads')
            if getattr(self, '_fetch_mode', '') == 'favorite':
                folder_name += '-like'
            return os.path.join(download_folder, sanitize_filename(folder_name))

        user_folders = set()
        for work in selected:
            # 标记下载状态
            self._download_status[work['aweme_id']] = '下载中'
            self._downloading_ids.add(work['aweme_id'])
            # 每个作者一个文件夹，注入到该作品的所有任务中
            folder = author_folder_for(work)
            user_folders.add(folder)
            for t in work.get('video_tasks', []):
                t['base_folder'] = folder
            sel_v.extend(work.get('video_tasks', []))
            for t in work.get('image_tasks', []):
                t['base_folder'] = folder
            sel_i.extend(work.get('image_tasks', []))

        # 同步更新可见的「下载状态」列
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item:
                work = item.data(0, Qt.ItemDataRole.UserRole)
                if work and work.get('aweme_id') in self._downloading_ids:
                    item.setText(8, '下载中')

        # 逐个创建作者文件夹（下载器内部会再建 视频/图集 子目录）
        for folder in user_folders:
            if not safe_mkdir(folder):
                QtWidgets.QMessageBox.critical(self, '错误', f'创建目录失败: {folder}')
                return
        # 兜底文件夹（仅当任务缺少 base_folder 时使用）
        user_folder = sorted(user_folders)[0] if user_folders else download_folder
            
        threads = int(cfg.get('threads', DEFAULT_THREAD_COUNT))
        use_mix_folder = cfg.get('use_mix_folder', True)
        include_date = cfg.get('include_date_in_filename', True)

        def apply_settings_to_tasks(tasks, is_image):
            out = []
            for t in tasks:
                nt = dict(t)
                if not use_mix_folder:
                    nt['mix_name'] = None

                # 不再处理 desc 字符串，而是将配置存入 task
                nt['include_date_in_filename'] = include_date
                
                out.append(nt)
            return out

        sel_v_proc = apply_settings_to_tasks(sel_v, False)
        sel_i_proc = apply_settings_to_tasks(sel_i, True)

        self.progress.show()
        self.progress.setMaximum(max(1, len(sel_v_proc) + len(sel_i_proc)))
        self.progress.setValue(0)
        self.on_progress(0, max(1, len(sel_v_proc) + len(sel_i_proc))) # 恢复蓝色
        
        # 重置停止标志
        self.worker._download_stop_requested = False
        self.worker._pause_requested = False

        # 禁用所有按钮
        self.url_label_btn.setEnabled(False)
        self.settings_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.select_all_btn.setEnabled(False)
        self.export_excel_btn.setEnabled(False)
        self.export_urls_btn.setEnabled(False)
        self.invert_btn.setEnabled(False)
        self.fetch_btn.setEnabled(False)
        self.like_checkbox.setEnabled(False)

        # 设置下载按钮为停止下载按钮
        self.download_btn.setText('停止下载')
        self.download_btn.setEnabled(True)
        self.download_btn.setProperty("running", True)
        style = self.style()
        if style:
            style.unpolish(self.download_btn)
            style.polish(self.download_btn)
        self._thread = threading.Thread(
            target=self.worker.download_tasks, 
            args=(sel_v_proc, sel_i_proc, user_folder, threads), 
            daemon=True
        )
        self._thread.start()

    def on_fetch_finished(self):
        """获取完成处理（自动全选 + 保存用户完整资料到主页列表）"""
        try:
            url = self.url_edit.text().strip()
            nickname = self.current_nickname
            unique_id = self.current_unique_id

            if url and nickname:
                current_sec_user_id = extract_sec_user_id_from_url(url)
                if current_sec_user_id:
                    normalized_url = f"https://www.douyin.com/user/{current_sec_user_id}"

                    # 计算最后发布时间（从 aweme 列表中取最新）
                    last_publish_time = ''
                    awemes = getattr(self, '_current_fetch_awemes', None) or self.all_awemes or []
                    if awemes:
                        try:
                            timestamps = [a.get('create_time', 0) or 0 for a in awemes]
                            max_ts = max(t for t in timestamps if t > 0) if any(t > 0) else 0
                            if max_ts:
                                from datetime import datetime as dt
                                last_publish_time = dt.fromtimestamp(max_ts).strftime('%Y-%m-%d %H:%M:%S')
                        except Exception:
                            pass

                    # 从 worker 获取 profile 统计数据
                    profile_stats = {}
                    if hasattr(self.worker, 'session'):
                        from douyin_downloader.core.api import get_user_profile_info
                        prof, prof_err = get_user_profile_info(self.worker.session, current_sec_user_id)
                        if prof:
                            profile_stats = prof
                        elif prof_err:
                            self.append_log(f'[警告] 获取用户资料失败: {prof_err}')

                    users = cfg.get('users', [])
                    existing_idx = -1
                    for idx, user in enumerate(users):
                        user_sec = extract_sec_user_id_from_url(user.get('url', ''))
                        if user_sec == current_sec_user_id:
                            existing_idx = idx
                            break

                    user_entry = {
                        'username': nickname,
                        'url': normalized_url,
                        'group': '',
                        'sec_user_id': current_sec_user_id,
                        'last_publish_time': last_publish_time,
                    }
                    # 合并 API 返回的统计数据
                    stat_keys = ['following_count', 'follower_count', 'total_favorited',
                                 'favoriting_count', 'aweme_count']
                    for k in stat_keys:
                        if k in profile_stats:
                            user_entry[k] = profile_stats[k]

                    # 抖音 API 有时返回 aweme_count=0 但实际有作品，用实际数量修正
                    _cur_awemes = getattr(self, '_current_fetch_awemes', None)
                    if not user_entry.get('aweme_count') and _cur_awemes:
                        user_entry['aweme_count'] = len(_cur_awemes)

                    if existing_idx < 0:
                        users.append(user_entry)
                        self.append_log(f'[信息] 已保存用户: {nickname}')
                    else:
                        users[existing_idx].update(user_entry)
                        self.append_log(f'[信息] 已更新用户: {nickname}')

                    cfg['users'] = users
                    save_config(cfg)
        except Exception as e:
            self.append_log(f'[警告] 保存用户信息失败: {e}')

        try:
            if bool(cfg.get('auto_select_after_fetch', False)):
                self.on_select_all()
                self.append_log('[信息] 获取完成，已自动全选')
            else:
                self.append_log('[信息] 获取完成')
        except Exception as e:
            self.append_log(f'[警告] 获取完成处理失败: {e}')

    def on_settings(self):
        """显示设置窗口"""
        try:
            if self.settings_window:
                # 刷新设置窗口的显示内容
                self.settings_window.refresh_settings()
                self.settings_window.show()
                self.settings_window.raise_()
                self.settings_window.activateWindow()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, '错误', f'无法打开设置窗口: {e}')
    
    def show_first_time_settings(self):
        """首次启动时显示设置窗口"""
        msg_box = QtWidgets.QMessageBox(self)
        msg_box.setWindowTitle('欢迎使用')
        msg_box.setText(
            '欢迎使用抖音主页作品批量下载工具！\n\n'
            '检测到这是您第一次使用本程序，\n'
            '请先配置 Cookie 和保存路径。\n\n'
            '点击“确认”将打开设置窗口。'
        )
        msg_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        ok_button = msg_box.button(QtWidgets.QMessageBox.StandardButton.Ok)
        if ok_button: ok_button.setText('确认')
        msg_box.exec()
        
        self.on_settings()
    
    def on_status_click(self, event):
        """点击状态标签打开日志窗口"""
        try:
            if self.log_window:
                self.log_window.show()
                self.log_window.raise_()
                self.log_window.activateWindow()
        except Exception:
            pass

    def on_select_all(self):
        """全选"""
        self._programmatic_change = True
        try:
            self.tree.setUpdatesEnabled(False)
            try:
                for i in range(self.tree.topLevelItemCount()):
                    it = self.tree.topLevelItem(i)
                    if it:
                        it.setCheckState(0, Qt.CheckState.Checked)
                        it.setSelected(True)
            finally:
                self.tree.setUpdatesEnabled(True)
        finally:
            self._programmatic_change = False
        self.update_status_label()
        self.sync_filter_checkboxes()

    def on_invert(self):
        """反选"""
        self._programmatic_change = True
        try:
            self.tree.setUpdatesEnabled(False)
            try:
                for i in range(self.tree.topLevelItemCount()):
                    it = self.tree.topLevelItem(i)
                    if it:
                        current_state = it.checkState(0)
                        new_state = Qt.CheckState.Unchecked if current_state == Qt.CheckState.Checked else Qt.CheckState.Checked
                        it.setCheckState(0, new_state)
                        it.setSelected(new_state == Qt.CheckState.Checked)
            finally:
                self.tree.setUpdatesEnabled(True)
        finally:
            self._programmatic_change = False
        self.update_status_label()
        self.sync_filter_checkboxes()

    def on_clear_list(self):
        """清空列表"""
        msg_box = QtWidgets.QMessageBox(self)
        msg_box.setWindowTitle('确认')
        msg_box.setText('确定要清空当前列表吗？此操作不会删除已下载的文件。')
        msg_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel)
        msg_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        ok_button = msg_box.button(QtWidgets.QMessageBox.StandardButton.Ok)
        cancel_button = msg_box.button(QtWidgets.QMessageBox.StandardButton.Cancel)
        if ok_button: ok_button.setText('确认')
        if cancel_button: cancel_button.setText('取消')
        
        if msg_box.exec() != QtWidgets.QMessageBox.StandardButton.Ok:
            return
        
        try:
            self.tree.clear()
            self.vtasks_all = []
            self.itasks_all = []
            self.vtasks = []
            self.itasks = []
            self.all_awemes = []  # 同时清空aweme数据
            self.current_nickname = ''
            self.all_works = []
            self._download_status = {}
            self.progress.setValue(0)
            self.progress.hide()
            

        except Exception:
            pass
        
        self.append_log('[信息] 已清空当前列表')

    def on_worker_finished(self):
        """工作线程完成处理（Fetch 或 Download）"""
        self.url_label_btn.setEnabled(True)
        self.settings_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        self.select_all_btn.setEnabled(True)
        if OPENPYXL_AVAILABLE:
            self.export_excel_btn.setEnabled(True)
        self.export_urls_btn.setEnabled(True)
            
        self.invert_btn.setEnabled(True)
        self.download_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText('获取作品')
        self.like_checkbox.setEnabled(True)
        self.download_btn.setText('开始下载')
        
        # 设置 "running" 属性为 False，QSS会自动应用蓝色样式
        self.fetch_btn.setProperty("running", False)
        style = self.style()
        if style:
            style.unpolish(self.fetch_btn)
            style.polish(self.fetch_btn)
        self.download_btn.setProperty("running", False)
        style = self.style()
        if style:
            style.unpolish(self.download_btn)
            style.polish(self.download_btn)

        # 不再隐藏进度条，保持显示下载完成状态

        # 如果进度条是满的，确保是绿色
        if self.progress.value() == self.progress.maximum() and self.progress.maximum() > 0:
            self.on_download_finished()
        
        # 如果是用户主动停止下载，也调用下载完成的处理
        if hasattr(self.worker, '_download_stop_requested') and self.worker._download_stop_requested:
            self.on_download_finished()

        # 批量提取队列非空 → 稍作延迟后继续下一个用户
        if getattr(self, '_batch_fetch_queue', None):
            QtCore.QTimer.singleShot(300, self._batch_fetch_next)

    def _set_window_icon(self):
        """设置窗口图标，确保任务栏也显示正确的图标"""
        try:
            # Windows系统特殊处理任务栏图标
            if sys.platform.startswith('win'):
                import ctypes
                myappid = 'douyin.downloader.app'  # 设置应用程序用户模型ID
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            
            icon_bytes = get_app_icon()
            pixmap = QtGui.QPixmap()
            pixmap.loadFromData(icon_bytes)
            icon = QtGui.QIcon(pixmap)
            self.setWindowIcon(icon)
        except Exception as e:
            print(f"Warning: Failed to set window icon: {e}")
