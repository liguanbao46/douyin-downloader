#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GUI界面 - 主窗口
"""
import os
import re
import sys
import threading
from collections import Counter
from datetime import datetime
try:
    from PyQt6 import QtWidgets, QtCore, QtGui
    from PyQt6.QtCore import Qt
except ImportError:
    print("[错误] PyQt6 未安装或无法导入: \n请安装 PyQt6 后重试（pip install PyQt6）。")
    sys.exit(1)

from douyin_downloader.constants import (
    TEXT_APP_NAME, OPENPYXL_AVAILABLE, DEFAULT_THREAD_COUNT, CONFIG_FILE, 
    ICON_BYTES_OPTIONS, CUSTOM_ICON_PATH,
    DEFAULT_MONITOR_INTERVAL_MINUTES, MONITOR_INTERVAL_MIN, MONITOR_INTERVAL_MAX,
    AWEME_ID_RECORDS_FILE,
)
from douyin_downloader.utils.config import save_config
from douyin_downloader.utils.file_utils import sanitize_filename, safe_mkdir
from douyin_downloader.core.api import extract_sec_user_id_from_url
from douyin_downloader.core.parser import parse_awemes_to_works
from douyin_downloader.core.work_filters import (
    normalize_filters, filter_works,
    load_aweme_id_records, save_aweme_id_records,
    recorded_ids_for_user, add_recorded_ids,
)
from douyin_downloader.gui.worker import Worker
from douyin_downloader.gui import cfg
from douyin_downloader.gui.widgets import NoFocusRectStyle, attach_header_checkbox
from douyin_downloader.gui.dialog_log import LogWindow
from douyin_downloader.gui.dialog_userlist import UserListWindow
from douyin_downloader.gui.dialog_settings import SettingsWindow
from douyin_downloader.gui.dialog_myworks import MyWorksWindow


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
    user_save_ready = QtCore.pyqtSignal(object, int, str)  # entry, existing_idx, log_msg
    monitor_poll_finished = QtCore.pyqtSignal(object)  # list of poll results

    def __init__(self, checkmark_svg_path=''):
        super().__init__()
        self.checkmark_svg_path = checkmark_svg_path
        self.setWindowTitle(TEXT_APP_NAME)
        self.resize(1200, 700)
        # 设置窗口图标，确保任务栏也显示正确的图标
        self._set_window_icon()
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        central_layout = QtWidgets.QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # 顶部导航栏
        self.top_nav = QtWidgets.QWidget()
        self.top_nav.setObjectName('top_nav')
        self.top_nav.setFixedHeight(40)
        self.top_nav.setStyleSheet('background-color: #FFFFFF; border-bottom: 1px solid #E5E5EA;')
        top_layout = QtWidgets.QHBoxLayout(self.top_nav)
        top_layout.setContentsMargins(12, 0, 12, 0)
        top_layout.setSpacing(8)
        brand_label = QtWidgets.QLabel('抖音下载器')
        brand_font = brand_label.font()
        brand_font.setPointSize(14)
        brand_font.setBold(True)
        brand_label.setFont(brand_font)
        top_layout.addWidget(brand_label)
        top_layout.addStretch()
        self.view_log_btn = QtWidgets.QPushButton('查看日志')
        self.settings_btn_top = QtWidgets.QPushButton('⚙')
        self.settings_btn_top.setObjectName('icon_btn')
        self.settings_btn_top.setToolTip('设置')
        icon_font = QtGui.QFont('Segoe UI Symbol')
        icon_font.setPointSize(14)
        self.settings_btn_top.setFont(icon_font)
        top_layout.addWidget(self.view_log_btn)
        top_layout.addWidget(self.settings_btn_top)
        central_layout.addWidget(self.top_nav)

        # 主体：侧边栏 + 页面栈
        body = QtWidgets.QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        central_layout.addLayout(body, 1)

        # 左侧导航
        self.nav_list = QtWidgets.QListWidget()
        self.nav_list.setFixedWidth(200)
        self.nav_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav_list.addItem('作品列表')
        self.nav_list.addItem('主页列表')
        self.nav_list.addItem('我的主页提取')
        self.nav_list.setCurrentRow(0)
        body.addWidget(self.nav_list)

        self.page_stack = QtWidgets.QStackedWidget()
        body.addWidget(self.page_stack, 1)

        works_page = QtWidgets.QWidget()
        works_page.setObjectName('works_page')
        lay = QtWidgets.QVBoxLayout(works_page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        # 第一行：主页链接
        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(8)
        self.url_label_btn = QtWidgets.QPushButton('主页链接:')
        self.url_label_btn.setObjectName('url_label_btn')
        self.url_label_btn.setFlat(True)
        self.url_label_btn.setCursor(QtGui.QCursor(Qt.CursorShape.PointingHandCursor))
        row1.addWidget(self.url_label_btn)
        self.url_edit = QtWidgets.QLineEdit()
        self.url_edit.setPlaceholderText('粘贴抖音主页链接，例如 https://www.douyin.com/user/xxx')
        row1.addWidget(self.url_edit, 1)
        self.like_checkbox = QtWidgets.QCheckBox('点赞作品')
        row1.addWidget(self.like_checkbox)
        self.latest_only_checkbox = QtWidgets.QCheckBox('仅最新')
        self.latest_only_checkbox.setToolTip('只获取第一页最新作品，不翻页拉取历史')
        self.latest_only_checkbox.setChecked(bool(cfg.get('fetch_latest_only', False)))
        row1.addWidget(self.latest_only_checkbox)
        self.fetch_btn = QtWidgets.QPushButton('获取作品')
        self.fetch_btn.setObjectName('fetch_btn')
        row1.addWidget(self.fetch_btn)
        lay.addLayout(row1)

        # 第二行：按钮组
        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(8)
        left_btns = QtWidgets.QHBoxLayout()
        left_btns.setSpacing(8)
        self.settings_btn = QtWidgets.QPushButton('设置')
        self.export_urls_btn = QtWidgets.QPushButton('导出直链')
        self.export_excel_btn = QtWidgets.QPushButton('导出Excel')
        left_btns.addWidget(self.settings_btn)
        left_btns.addWidget(self.export_urls_btn)
        left_btns.addWidget(self.export_excel_btn)
        right_btns = QtWidgets.QHBoxLayout()
        right_btns.setSpacing(8)
        self.select_all_btn = QtWidgets.QPushButton('全选')
        self.invert_btn = QtWidgets.QPushButton('反选')
        self.clear_btn = QtWidgets.QPushButton('清空列表')
        self.download_btn = QtWidgets.QPushButton('开始下载')
        self.download_btn.setObjectName('download_btn')
        self.open_folder_btn = QtWidgets.QPushButton('打开文件夹')
        right_btns.addWidget(self.select_all_btn)
        right_btns.addWidget(self.invert_btn)
        right_btns.addWidget(self.clear_btn)
        right_btns.addWidget(self.download_btn)
        right_btns.addWidget(self.open_folder_btn)
        row2.addLayout(left_btns)
        row2.addStretch()
        row2.addLayout(right_btns)
        lay.addLayout(row2)

        if not OPENPYXL_AVAILABLE:
            self.export_excel_btn.setEnabled(False)
            self.export_excel_btn.setToolTip("请先安装 'openpyxl' (pip install openpyxl) 以启用此功能")

        # 第三行：搜索 + 类型筛选
        row3 = QtWidgets.QHBoxLayout()
        row3.setSpacing(8)
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText('搜索作品标题或作者...')
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(280)
        row3.addWidget(self.search_edit)
        row3.addStretch()
        self.type_filter_btn = QtWidgets.QPushButton('类型 ▼')
        self.type_filter_btn.setObjectName('type_filter_btn')
        row3.addWidget(self.type_filter_btn)
        lay.addLayout(row3)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setStyle(NoFocusRectStyle())
        self.tree.setHeaderLabels(['', '序号', '作者', '提取方式', '作品类型', '作品标题', '时长/数量', '分辨率', '下载状态', '发布时间'])

        self.type_filter_menu = QtWidgets.QMenu(self)
        self.type_filter_menu.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.type_filter_menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
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
        hdr_h = fm.height() + 18
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
            header.setSortIndicatorShown(True)

        self._sort_column = -1
        self._sort_order = Qt.SortOrder.AscendingOrder

        self.header_select_all, self._reposition_header_select_all = attach_header_checkbox(
            self.tree, self.checkmark_svg_path, tooltip='全选 / 取消全选'
        )
        self.header_select_all.clicked.connect(self.on_header_select_all_clicked)

        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setAttribute(QtCore.Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.tree.setFrameShape(QtWidgets.QFrame.Shape.Box)
        self.tree.setAlternatingRowColors(True)
        lay.addWidget(self.tree)

        # 底部进度与状态
        bottom = QtWidgets.QHBoxLayout()
        bottom.setSpacing(12)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setFixedHeight(10)
        self.progress.setTextVisible(False)
        bottom.addWidget(self.progress, 1)
        self.progress.hide()
        self.status = QtWidgets.QLabel('')
        # 长文本（如下载失败的 URL）自动换行，避免撑大窗口宽度
        self.status.setWordWrap(True)
        self.status.setMinimumWidth(0)
        self.status.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Minimum)
        self.status.setCursor(QtGui.QCursor(Qt.CursorShape.PointingHandCursor))
        self.status.setMouseTracking(True)
        bottom.addWidget(self.status)
        bottom.addWidget(QtWidgets.QLabel('当前用户:'))
        self.nickname_label = QtWidgets.QLabel('')
        nickname_font = self.nickname_label.font()
        nickname_font.setBold(True)
        self.nickname_label.setFont(nickname_font)
        bottom.addWidget(self.nickname_label)
        lay.addLayout(bottom)

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
        self.user_list_window = UserListWindow(None, self.checkmark_svg_path)
        self.myworks_window = MyWorksWindow(self)
        self.settings_window = SettingsWindow(self, self.checkmark_svg_path)
        self.settings_window.hide()

        self.page_stack.addWidget(works_page)
        self.page_stack.addWidget(self.user_list_window)
        self.page_stack.addWidget(self.myworks_window)
        self.nav_list.currentRowChanged.connect(self.on_nav_changed)

        self.worker = Worker()
        self._thread = None
        self._monitor_running = False
        self._monitor_poll_running = False
        self._monitor_pending_updates = []  # [{sec, new_awemes}, ...]
        self._monitor_timer = QtCore.QTimer(self)
        self._monitor_timer.timeout.connect(self.on_monitor_tick)

        self.url_label_btn.clicked.connect(self.on_show_user_list)
        self.fetch_btn.clicked.connect(self.on_fetch)
        self.download_btn.clicked.connect(self.on_download)
        self.settings_btn.clicked.connect(self.on_settings)
        self.settings_btn_top.clicked.connect(self.on_settings)
        self.view_log_btn.clicked.connect(lambda: (self.log_window.show(), self.log_window.raise_(), self.log_window.activateWindow()))
        self.type_filter_btn.clicked.connect(self.on_type_filter_btn_clicked)
        self.latest_only_checkbox.stateChanged.connect(self.on_latest_only_changed)
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
        self.user_save_ready.connect(self._apply_user_save)
        self.monitor_poll_finished.connect(self._on_monitor_poll_finished)
        self.myworks_window.extract_requested.connect(self.on_myworks_extract)

        self.tree.itemSelectionChanged.connect(self.on_tree_selection_changed)
        self.tree.itemChanged.connect(self.on_tree_item_changed)
        self.tree.itemDoubleClicked.connect(self.on_tree_item_double_clicked)

        self._programmatic_change = False  # 防止联动循环
        self._last_status_text = ''

        if not os.path.exists(CONFIG_FILE):
            QtCore.QTimer.singleShot(500, self.show_first_time_settings)

        QtCore.QTimer.singleShot(800, self.reload_monitor_timer)

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
            self.sync_header_select_all()
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
        """表头点击：作品类型列弹出筛选；其余可排序列切换升/降序"""
        if logical_index == 0:
            return
        if logical_index == 4:
            header = self.tree.header()
            if header:
                left = header.sectionPosition(logical_index)
                width = header.sectionSize(logical_index)
                height = header.height()
                menu_width = self.type_filter_menu.sizeHint().width()
                point = QtCore.QPoint(left + width - menu_width, height)
                global_point = self.tree.mapToGlobal(point)
                if self.type_filter_menu.isVisible():
                    self.type_filter_menu.hide()
                else:
                    self.type_filter_menu.popup(global_point)
            return

        if self._sort_column == logical_index:
            if self._sort_order == Qt.SortOrder.AscendingOrder:
                self._sort_order = Qt.SortOrder.DescendingOrder
            else:
                self._sort_order = Qt.SortOrder.AscendingOrder
        else:
            self._sort_column = logical_index
            self._sort_order = Qt.SortOrder.AscendingOrder

        self.sort_works_by_column(self._sort_column, self._sort_order)
        header = self.tree.header()
        if header:
            header.setSortIndicator(self._sort_column, self._sort_order)

    def on_type_filter_btn_clicked(self):
        """类型筛选按钮点击时弹出筛选菜单"""
        self.type_filter_menu.popup(self.type_filter_btn.mapToGlobal(QtCore.QPoint(0, self.type_filter_btn.height())))

    @staticmethod
    def _resolution_sort_key(text):
        """分辨率文本 -> 像素面积，便于数值排序"""
        if not text:
            return 0
        m = re.match(r'(\d+)\s*[x×X]\s*(\d+)', str(text))
        if not m:
            return 0
        return int(m.group(1)) * int(m.group(2))

    def _work_sort_key(self, item, column):
        """按列计算排序键（优先用 UserRole 中的作品数据）"""
        work = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if column == 1:
            try:
                return int(item.text(1))
            except (TypeError, ValueError):
                return 0
        if column == 2:
            return (work.get('author_nickname') or item.text(2) or '').lower()
        if column == 3:
            return item.text(3) or ''
        if column == 5:
            return (work.get('desc') or item.text(5) or '').lower()
        if column == 6:
            duration = int(work.get('duration_ms') or 0)
            if duration > 0:
                return (0, duration)
            img_n = int(work.get('image_count') or 0) + int(work.get('live_count') or 0)
            return (1, img_n)
        if column == 7:
            return self._resolution_sort_key(work.get('resolution') or item.text(7))
        if column == 8:
            return item.text(8) or ''
        if column == 9:
            return int(work.get('create_time') or 0)
        return item.text(column) or ''

    def sort_works_by_column(self, column, order):
        """按指定列对作品列表排序，并重写序号"""
        count = self.tree.topLevelItemCount()
        if count <= 1:
            return

        reverse = order == Qt.SortOrder.DescendingOrder
        self.tree.setUpdatesEnabled(False)
        try:
            items = [self.tree.takeTopLevelItem(0) for _ in range(count)]
            items.sort(key=lambda it: self._work_sort_key(it, column), reverse=reverse)
            for i, item in enumerate(items, start=1):
                item.setText(1, str(i))
            self.tree.addTopLevelItems(items)
        finally:
            self.tree.setUpdatesEnabled(True)

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

    @staticmethod
    def work_web_url(work):
        """作品在抖音网页版的链接"""
        if not work:
            return ''
        aweme_id = work.get('aweme_id') or ''
        if not aweme_id:
            aweme = work.get('aweme') if isinstance(work.get('aweme'), dict) else {}
            aweme_id = (aweme or {}).get('aweme_id') or ''
        if not aweme_id:
            return ''
        work_type = work.get('work_type') or ''
        # 图集/实况走 note，视频走 video
        if '图集' in work_type or '实况' in work_type:
            return f'https://www.douyin.com/note/{aweme_id}'
        return f'https://www.douyin.com/video/{aweme_id}'

    def on_tree_item_double_clicked(self, item, column):
        """双击作品行 → 在浏览器打开该作品"""
        if not item:
            return
        work = item.data(0, Qt.ItemDataRole.UserRole)
        url = self.work_web_url(work)
        if not url:
            QtWidgets.QMessageBox.warning(self, '提示', '无法构造作品链接（缺少 aweme_id）')
            return
        try:
            import webbrowser
            webbrowser.open(url)
            self.append_log(f'[信息] 已在浏览器打开作品: {url}')
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, '提示', f'无法打开浏览器: {e}')

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
        

    
    def on_download_finished(self):
        """下载完成处理（确保进度条是绿色，并更新下载状态列）"""
        try:
            maxv = self.progress.maximum() or self.progress.value() or 1
            self.progress.setValue(maxv)
            stopped = bool(
                getattr(self.worker, '_download_stop_requested', False)
            )
            if stopped:
                self.progress.setFormat(f"%v / %m (已停止)")
                self.progress.hide()
            else:
                self.progress.setFormat(f"%v / %m (完成)")

            # 按作品统计成功/失败文件数，避免「停止」后未完成项被标成已下载
            success_counts = Counter()
            for rec in getattr(self.worker, '_completed_tasks', []):
                task = rec.get('task') if isinstance(rec, dict) else None
                if isinstance(task, dict):
                    aid = task.get('aweme_id', '')
                    if aid:
                        success_counts[aid] += 1

            failed_counts = Counter()
            for t in getattr(self.worker, '_failed_tasks', []):
                if isinstance(t, dict):
                    aid = t.get('aweme_id', '')
                    if aid:
                        failed_counts[aid] += 1

            expected_counts = getattr(self, '_download_task_counts', {}) or {}
            done_ids = getattr(self, '_downloading_ids', set())

            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if not item:
                    continue
                work = item.data(0, Qt.ItemDataRole.UserRole)
                if not work:
                    continue
                aid = work.get('aweme_id', '')
                if aid not in done_ids:
                    continue

                expected = int(expected_counts.get(aid, 0) or 0)
                ok = int(success_counts.get(aid, 0))
                fail = int(failed_counts.get(aid, 0))

                if ok + fail == 0:
                    status = ''
                elif fail and ok == 0:
                    status = '失败'
                elif fail and ok > 0:
                    status = '部分完成'
                elif expected > 0 and ok >= expected:
                    status = '已下载'
                elif stopped:
                    status = '部分完成' if ok > 0 else ''
                else:
                    status = '已下载' if ok > 0 else ''

                self._download_status[aid] = status
                item.setText(8, status)
        except Exception:
            pass

    def author_folder_for_work(self, work, download_folder=None):
        """根据作品作者信息计算下载目录：作品下载/昵称-unique_id"""
        base_folder = cfg.get('path', '') or os.getcwd()
        if download_folder is None:
            download_folder = os.path.join(base_folder, '作品下载')
        nickname = (work or {}).get('author_nickname') or ''
        unique_id = ''
        aweme = (work or {}).get('aweme')
        author = aweme.get('author') if isinstance(aweme, dict) else None
        if isinstance(author, dict):
            unique_id = author.get('unique_id', '') or author.get('short_id', '') or ''
        if not nickname:
            nickname = self.nickname_label.text() or 'Douyin_User'
            unique_id = unique_id or (getattr(self, 'current_unique_id', '') or '')
        folder_name = f"{nickname}-{unique_id}" if unique_id else (nickname or 'Douyin_Downloads')
        if getattr(self, '_fetch_mode', '') == 'favorite':
            folder_name += '-like'
        return os.path.join(download_folder, sanitize_filename(folder_name))

    def on_open_folder(self):
        """打开下载文件夹：优先勾选作品对应作者目录；多作者则打开「作品下载」根目录"""
        import subprocess
        base_folder = cfg.get('path', '') or os.getcwd()
        download_folder = os.path.join(base_folder, '作品下载')

        folders = []
        seen = set()
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if not it or it.checkState(0) != Qt.CheckState.Checked:
                continue
            work = it.data(0, Qt.ItemDataRole.UserRole)
            if not work:
                continue
            folder = self.author_folder_for_work(work, download_folder)
            if folder not in seen:
                seen.add(folder)
                folders.append(folder)

        if len(folders) == 1:
            target = folders[0]
        elif len(folders) > 1:
            target = download_folder
            self.append_log(f'[信息] 勾选作品涉及 {len(folders)} 个作者目录，已打开「作品下载」根目录')
        else:
            nickname = self.nickname_label.text() or ''
            unique_id = getattr(self, 'current_unique_id', '') or ''
            if nickname:
                folder_name = f"{nickname}-{unique_id}" if unique_id else nickname
                if getattr(self, '_fetch_mode', '') == 'favorite':
                    folder_name += '-like'
                target = os.path.join(download_folder, sanitize_filename(folder_name))
            else:
                target = download_folder

        if not os.path.exists(target):
            if os.path.exists(download_folder):
                target = download_folder
            else:
                target = base_folder
        try:
            if sys.platform.startswith('win'):
                os.startfile(target)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', target])
            else:
                subprocess.Popen(['xdg-open', target])
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

    def _maybe_stop_fetch_by_time(self, aweme_list, filters):
        """时间筛选：本页已全部早于范围时停止翻页"""
        if not filters.get('enabled') or not aweme_list:
            return
        import time as _time
        cutoffs = []
        if filters.get('hours_enabled') and int(filters.get('hours') or 0) > 0:
            cutoffs.append(int(_time.time()) - int(filters['hours']) * 3600)
        if filters.get('start_time_enabled') and filters.get('start_time'):
            try:
                from datetime import datetime as _dt
                dt = _dt.strptime(str(filters['start_time']), '%Y-%m-%d %H:%M:%S')
                cutoffs.append(int(dt.timestamp()))
            except Exception:
                pass
        if not cutoffs:
            return
        cutoff = max(cutoffs)
        try:
            times = [int(a.get('create_time') or 0) for a in aweme_list]
            times = [t for t in times if t > 0]
            if times and max(times) < cutoff:
                self.worker._fetch_no_more_pages = True
                self.append_log('[筛选] 已超出发布时间范围，结束翻页')
        except Exception:
            pass

    def _flush_pending_recorded_ids(self):
        """把本次提取通过筛选的作品 ID 写入未记录库"""
        ids = getattr(self, '_pending_record_ids', None) or []
        sec = getattr(self, '_pending_record_sec', '') or ''
        self._pending_record_ids = []
        self._pending_record_sec = ''
        if not ids or not sec:
            return
        records = load_aweme_id_records(AWEME_ID_RECORDS_FILE)
        add_recorded_ids(records, sec, ids)
        save_aweme_id_records(AWEME_ID_RECORDS_FILE, records)

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

        # 应用提取筛选
        filters = normalize_filters(cfg.get('extract_filters'))
        if getattr(self, 'user_list_window', None) and getattr(self.user_list_window, 'filter_panel', None):
            try:
                filters = self.user_list_window.filter_panel.get_filters()
                cfg['extract_filters'] = filters
            except Exception:
                pass

        recorded = set()
        sec = extract_sec_user_id_from_url(self.url_edit.text().strip()) or ''
        if filters.get('enabled') and filters.get('only_unrecorded_ids'):
            records = load_aweme_id_records(AWEME_ID_RECORDS_FILE)
            recorded = recorded_ids_for_user(records, sec)

        if not hasattr(self, '_filter_per_user_counts') or self._filter_per_user_counts is None:
            self._filter_per_user_counts = {}

        if filters.get('enabled'):
            kept, rejected = filter_works(
                new_works, filters,
                recorded_ids=recorded,
                per_user_counts=self._filter_per_user_counts,
            )
            if rejected:
                self.append_log(f'[筛选] 本页过滤 {rejected} 个，保留 {len(kept)} 个')
            new_works = kept
            self._maybe_stop_fetch_by_time(aweme_list or [], filters)
            limit = int(filters.get('per_user_limit') or 0)
            if limit > 0 and any(n >= limit for n in self._filter_per_user_counts.values()):
                try:
                    self.worker._fetch_no_more_pages = True
                except Exception:
                    pass
                self.append_log(f'[筛选] 已达每主页上限 {limit}，结束翻页')

            if filters.get('only_unrecorded_ids'):
                if not hasattr(self, '_pending_record_ids') or self._pending_record_ids is None:
                    self._pending_record_ids = []
                for w in new_works:
                    aid = w.get('aweme_id')
                    if aid:
                        self._pending_record_ids.append(str(aid))
                self._pending_record_sec = sec

        kept_v, kept_i = [], []
        for w in new_works:
            kept_v.extend(w.get('video_tasks') or [])
            kept_i.extend(w.get('image_tasks') or [])

        self.all_works.extend(new_works)

        if not hasattr(self, 'vtasks_all'):
            self.vtasks_all = []
        if not hasattr(self, 'itasks_all'):
            self.itasks_all = []
        self.vtasks_all.extend(kept_v)
        self.itasks_all.extend(kept_i)

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
    
    def on_nav_changed(self, row):
        """左侧导航切换页面（切换不清空作品列表）"""
        if row < 0:
            return
        self.page_stack.setCurrentIndex(row)
        if row == 1 and self.user_list_window:
            try:
                self.user_list_window.load_users()
            except Exception:
                pass
        if row == 2 and self.myworks_window:
            try:
                self.myworks_window.refresh_info_if_needed()
            except Exception:
                pass

    def show_works_page(self):
        """切换到作品列表页（保留树数据）"""
        if self.nav_list.currentRow() != 0:
            self.nav_list.setCurrentRow(0)
        else:
            self.page_stack.setCurrentIndex(0)

    def show_user_list_page(self):
        """切换到主页列表页并刷新"""
        if self.nav_list.currentRow() != 1:
            self.nav_list.setCurrentRow(1)
        else:
            self.page_stack.setCurrentIndex(1)
            if self.user_list_window:
                self.user_list_window.load_users()

    def on_show_user_list(self):
        """显示主页列表页面"""
        try:
            self.show_user_list_page()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, '错误', f'无法打开用户列表: {e}')

    def on_myworks_extract(self, url, mode, latest_only):
        """我的主页提取：填充链接与选项，切换到作品列表并自动开始获取
        mode: 'post' 作品 / 'favorite' 点赞作品 / 'collect' 收藏作品
        """
        if self.fetch_btn.text() == '停止获取' or \
                (hasattr(self, '_thread') and self._thread and self._thread.is_alive()):
            QtWidgets.QMessageBox.warning(self, '提示', '当前有任务进行中，请等待完成或停止后再提取')
            return
        self.like_checkbox.setChecked(mode == 'favorite')
        self.latest_only_checkbox.setChecked(bool(latest_only))
        self.url_edit.setText(url)
        # collect 模式无对应勾选框，通过强制模式传递给 on_fetch
        self._force_fetch_mode = 'collect' if mode == 'collect' else None
        _names = {'post': '作品', 'favorite': '点赞作品', 'collect': '收藏作品'}
        self.append_log(f'[信息] 我的主页提取：开始获取当前登录账号的{_names.get(mode, "作品")}')
        if self.nav_list.currentRow() != 0:
            self.nav_list.setCurrentRow(0)
        # 延迟触发，确保页面切换完成后再启动获取
        QtCore.QTimer.singleShot(100, self.on_fetch)

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
        self._batch_user_cancelled = False
        self.append_log(f'[信息] 开始批量提取 {len(urls)} 个主页的作品（列表累加展示）')
        self._batch_fetch_next()

    def _batch_fetch_next(self):
        """批量提取队列：获取下一个用户的作品"""
        queue = getattr(self, '_batch_fetch_queue', None)
        if queue is None:
            return
        if getattr(self, '_batch_user_cancelled', False):
            self._batch_fetch_queue = None
            self._batch_fetch_total = 0
            self.append_log('[信息] 批量提取已停止')
            return
        if not queue:
            # 全部完成
            total = getattr(self, '_batch_fetch_total', 0)
            if total:
                works_count = self.tree.topLevelItemCount()
                self.append_log(f'[完成] 批量提取完成：{total} 个主页，列表共 {works_count} 个作品')
                self._batch_fetch_total = 0
                self._batch_fetch_done = 0
                self._batch_keep_existing = False
                self._batch_fetch_queue = None
                if self.user_list_window:
                    try:
                        self.user_list_window.status_label.setText(
                            f'批量提取完成：{total} 个主页，作品列表共 {works_count} 个'
                        )
                    except Exception:
                        pass
                QtWidgets.QMessageBox.information(
                    self,
                    '提取完成',
                    f'已完成 {total} 个主页的作品提取。\n作品列表共 {works_count} 个作品。',
                )
            return
        url = queue.pop(0)
        self._batch_fetch_done = getattr(self, '_batch_fetch_done', 0) + 1
        # 第一个用户前清空列表，后续用户累加
        self._batch_keep_existing = self._batch_fetch_done > 1
        self.url_edit.setText(url)
        self.append_log(f"[信息] 批量提取进度 {self._batch_fetch_done}/{self._batch_fetch_total}")
        # 上一用户若因筛选结束翻页，标志必须清掉，否则会影响本用户
        try:
            self.worker._fetch_no_more_pages = False
            self.worker._fetch_stop_requested = False
        except Exception:
            pass
        self.on_fetch()

    def on_fetch(self):
        """获取作品 / 停止获取"""
        if self.fetch_btn.text() == '停止获取':
            try:
                if hasattr(self.worker, '_fetch_stop_requested'):
                    self.worker._fetch_stop_requested = True
                # 批量提取模式下停止 → 清空队列
                self._batch_user_cancelled = True
                self._batch_fetch_queue = None
                self._batch_fetch_total = 0
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
                self.latest_only_checkbox.setEnabled(True)
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
        self.latest_only_checkbox.setEnabled(False)

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
        self._filter_per_user_counts = {}
        self._pending_record_ids = []
        self._pending_record_sec = ''
        # 「我的主页提取」的收藏模式通过强制模式传入（无对应勾选框）
        fetch_mode = getattr(self, '_force_fetch_mode', None)
        if fetch_mode:
            self._force_fetch_mode = None  # 一次性，用后即清
        else:
            fetch_mode = 'favorite' if self.like_checkbox.isChecked() else 'post'
        latest_only = bool(self.latest_only_checkbox.isChecked())
        cfg['fetch_latest_only'] = latest_only
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
        self.worker._fetch_no_more_pages = False
        self._thread = threading.Thread(
            target=self.worker.fetch_tasks,
            args=(url, cookie, fetch_mode, latest_only),
            daemon=True,
        )
        self._thread.start()

    def on_latest_only_changed(self, _state):
        """仅最新勾选变化时写入配置"""
        cfg['fetch_latest_only'] = bool(self.latest_only_checkbox.isChecked())
        try:
            save_config(cfg)
        except Exception:
            pass

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
            for w in (self.log_window, self.settings_window):
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
                self.latest_only_checkbox.setEnabled(True)
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
        self._download_task_counts = {}

        base_folder = cfg.get('path', '') or os.getcwd()
        download_folder = os.path.join(base_folder, '作品下载')

        # 图集扁平镜像（以博主为父级，无需单独路径）：启用后图集在原有结构
        # （作品下载/{博主}/图集/{标题}/）之外，额外复制一份到扁平目录
        # （作品下载/{博主}/图片/，不建逐个图集子目录）——两个并存
        flat_image_enabled = bool(cfg.get('flat_image_enabled', False))
        download_live_cover = bool(cfg.get('download_live_cover', False))

        user_folders = set()
        for work in selected:
            # 标记下载状态
            self._download_status[work['aweme_id']] = '下载中'
            self._downloading_ids.add(work['aweme_id'])
            n_tasks = len(work.get('video_tasks', [])) + len(work.get('image_tasks', []))
            if download_live_cover:
                n_tasks += len(work.get('cover_tasks', []))
            self._download_task_counts[work['aweme_id']] = n_tasks
            # 每个作者一个文件夹：视频/图集主结构均在「作品下载」下
            author_folder = self.author_folder_for_work(work, download_folder)
            user_folders.add(author_folder)
            # 扁平镜像目录：与博主文件夹同级同路径（作品下载/{博主}/图片/）
            flat_mirror_folder = author_folder if flat_image_enabled else None
            for t in work.get('video_tasks', []):
                t['base_folder'] = author_folder
            sel_v.extend(work.get('video_tasks', []))
            for t in work.get('image_tasks', []):
                t['base_folder'] = author_folder
                if flat_mirror_folder:
                    t['flat_mirror_folder'] = flat_mirror_folder
                else:
                    t.pop('flat_mirror_folder', None)
            sel_i.extend(work.get('image_tasks', []))
            if download_live_cover:
                for t in work.get('cover_tasks', []):
                    t['base_folder'] = author_folder
                    if flat_mirror_folder:
                        t['flat_mirror_folder'] = flat_mirror_folder
                    else:
                        t.pop('flat_mirror_folder', None)
                sel_i.extend(work.get('cover_tasks', []))

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
        self.latest_only_checkbox.setEnabled(False)

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
        """获取完成处理（自动全选 + 后台保存用户资料到主页列表）"""
        try:
            self._flush_pending_recorded_ids()
            url = self.url_edit.text().strip()
            nickname = self.current_nickname
            awemes = list(getattr(self, '_current_fetch_awemes', None) or [])
            cookie = cfg.get('cookie', '')
            session_headers = dict(getattr(self.worker.session, 'headers', {}) or {})

            if url and nickname:
                current_sec_user_id = extract_sec_user_id_from_url(url)
                if current_sec_user_id:
                    users = cfg.get('users', [])
                    existing_idx = -1
                    for idx, user in enumerate(users):
                        user_sec = extract_sec_user_id_from_url(user.get('url', ''))
                        if user_sec == current_sec_user_id:
                            existing_idx = idx
                            break

                    def _bg_fetch_and_save():
                        last_publish_time = ''
                        if awemes:
                            try:
                                timestamps = [a.get('create_time', 0) or 0 for a in awemes]
                                max_ts = max(t for t in timestamps if t > 0) if any(t > 0 for t in timestamps) else 0
                                if max_ts:
                                    last_publish_time = datetime.fromtimestamp(max_ts).strftime('%Y-%m-%d %H:%M:%S')
                            except Exception:
                                pass

                        profile_stats = {}
                        try:
                            from douyin_downloader.core.api import get_user_profile_info
                            import requests as _req
                            sess = _req.Session()
                            sess.headers.update(session_headers)
                            if cookie:
                                sess.headers['Cookie'] = cookie
                            sess.headers['Referer'] = f'https://www.douyin.com/user/{current_sec_user_id}'
                            prof, prof_err = get_user_profile_info(sess, current_sec_user_id)
                            if prof:
                                profile_stats = prof
                            elif prof_err:
                                self.worker.log_signal.emit(f'[警告] 获取用户资料失败: {prof_err}')
                        except Exception as e:
                            self.worker.log_signal.emit(f'[警告] 获取用户资料异常: {e}')

                        normalized_url = f"https://www.douyin.com/user/{current_sec_user_id}"
                        user_entry = {
                            'username': nickname,
                            'url': normalized_url,
                            'sec_user_id': current_sec_user_id,
                            'last_publish_time': last_publish_time,
                        }
                        for k in ('following_count', 'follower_count', 'total_favorited',
                                  'favoriting_count', 'aweme_count'):
                            if k in profile_stats:
                                user_entry[k] = profile_stats[k]
                        if not user_entry.get('aweme_count') and awemes:
                            user_entry['aweme_count'] = len(awemes)

                        if existing_idx < 0:
                            user_entry['group'] = ''
                            log_msg = f'[信息] 已保存用户: {nickname}'
                        else:
                            log_msg = f'[信息] 已更新用户: {nickname}'
                        self.user_save_ready.emit(user_entry, existing_idx, log_msg)

                    threading.Thread(target=_bg_fetch_and_save, daemon=True).start()
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

    def _apply_user_save(self, user_entry, existing_idx, log_msg):
        """主线程应用后台拉取到的用户资料（保留已有分组）"""
        try:
            users = cfg.get('users', [])
            if existing_idx < 0:
                users.append(user_entry)
            elif 0 <= existing_idx < len(users):
                users[existing_idx].update(user_entry)
            else:
                users.append(user_entry)
            cfg['users'] = users
            save_config(cfg)
            if log_msg:
                self.append_log(log_msg)
        except Exception as e:
            self.append_log(f'[警告] 保存用户信息失败: {e}')

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

    def on_header_select_all_clicked(self):
        """表头全选框：有未勾选则全选，否则取消全选"""
        has_unchecked = any(
            self.tree.topLevelItem(i)
            and self.tree.topLevelItem(i).checkState(0) != Qt.CheckState.Checked
            for i in range(self.tree.topLevelItemCount())
        )
        if has_unchecked:
            self.on_select_all()
        else:
            self.on_deselect_all()

    def sync_header_select_all(self):
        """根据行勾选状态同步表头全选框"""
        cb = getattr(self, 'header_select_all', None)
        if not cb:
            return
        total = self.tree.topLevelItemCount()
        checked = 0
        for i in range(total):
            it = self.tree.topLevelItem(i)
            if it and it.checkState(0) == Qt.CheckState.Checked:
                checked += 1
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
        self.sync_header_select_all()

    def on_deselect_all(self):
        """取消全选"""
        self._programmatic_change = True
        try:
            self.tree.setUpdatesEnabled(False)
            try:
                for i in range(self.tree.topLevelItemCount()):
                    it = self.tree.topLevelItem(i)
                    if it:
                        it.setCheckState(0, Qt.CheckState.Unchecked)
                        it.setSelected(False)
            finally:
                self.tree.setUpdatesEnabled(True)
        finally:
            self._programmatic_change = False
        self.update_status_label()
        self.sync_filter_checkboxes()
        self.sync_header_select_all()

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
        self.sync_header_select_all()

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
        self.sync_header_select_all()

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
        self.latest_only_checkbox.setEnabled(True)
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

        # 批量提取进行中 → 稍作延迟后继续下一个（或收尾弹窗）
        if getattr(self, '_batch_fetch_queue', None) is not None:
            QtCore.QTimer.singleShot(300, self._batch_fetch_next)

        # 监控自动下载结束 → 回写水位
        if getattr(self, '_monitor_running', False):
            self._finish_monitor_download()

    def _is_worker_busy(self):
        """手动获取/下载或监控任务进行中"""
        if getattr(self, '_monitor_running', False) or getattr(self, '_monitor_poll_running', False):
            return True
        if self.fetch_btn.text() == '停止获取':
            return True
        if self.download_btn.text() == '停止下载':
            return True
        t = getattr(self, '_thread', None)
        if t is not None and t.is_alive():
            return True
        if getattr(self, '_batch_fetch_queue', None) is not None:
            return True
        return False

    def reload_monitor_timer(self):
        """根据设置启停监控定时器"""
        try:
            self._monitor_timer.stop()
        except Exception:
            pass
        enabled = bool(cfg.get('monitor_enabled', False))
        monitored = [u for u in cfg.get('users', []) if u.get('monitor')]
        if not enabled:
            return
        if not monitored:
            self.append_log('[监控] 已启用，但尚未勾选监控用户')
            return
        try:
            minutes = int(cfg.get('monitor_interval_minutes', DEFAULT_MONITOR_INTERVAL_MINUTES))
        except Exception:
            minutes = DEFAULT_MONITOR_INTERVAL_MINUTES
        minutes = max(MONITOR_INTERVAL_MIN, min(MONITOR_INTERVAL_MAX, minutes))
        cfg['monitor_interval_minutes'] = minutes
        self._monitor_timer.start(minutes * 60 * 1000)
        self.append_log(f'[监控] 已启动，间隔 {minutes} 分钟，监控 {len(monitored)} 人')
        # 启动后稍晚做一次检查（避免与启动瞬间手动操作冲突）
        QtCore.QTimer.singleShot(3000, self.on_monitor_tick)

    def on_monitor_tick(self):
        """定时检查监控用户是否有新作品"""
        if not bool(cfg.get('monitor_enabled', False)):
            return
        monitored = [u for u in cfg.get('users', []) if u.get('monitor')]
        if not monitored:
            return
        if self._is_worker_busy():
            self.append_log('[监控] 本轮跳过（正在手动任务或监控进行中）')
            return
        cookie = cfg.get('cookie', '')
        if not cookie:
            self.append_log('[监控] 本轮跳过（未配置 Cookie）')
            return

        self._monitor_poll_running = True
        self.append_log(f'[监控] 开始检查 {len(monitored)} 个主页…')
        users_snapshot = [dict(u) for u in monitored]

        def _poll():
            from douyin_downloader.core.monitor import (
                resolve_user_sec, fetch_user_aweme_page, filter_new_awemes,
            )
            results = []
            for user in users_snapshot:
                name = user.get('username') or user.get('sec_user_id') or '未知'
                sec = resolve_user_sec(user)
                if not sec:
                    self.worker.log_signal.emit(f'[监控] 跳过 {name}：无法解析用户 ID')
                    continue
                awemes, err = fetch_user_aweme_page(sec, cookie)
                if err:
                    self.worker.log_signal.emit(f'[监控] {name} 检查失败: {err}')
                    continue
                since = int(user.get('monitor_since') or 0)
                seen = user.get('monitor_seen_ids') or []
                new_awemes = filter_new_awemes(awemes, since, seen)
                results.append({
                    'user': user,
                    'sec': sec,
                    'name': name,
                    'new_awemes': new_awemes,
                    'page_count': len(awemes),
                })
            self.monitor_poll_finished.emit(results)

        threading.Thread(target=_poll, daemon=True).start()

    def _on_monitor_poll_finished(self, results):
        """监控轮询结束：有新作则自动下载"""
        self._monitor_poll_running = False
        results = results or []
        total_new = 0
        pending = []
        for r in results:
            n = len(r.get('new_awemes') or [])
            name = r.get('name') or ''
            if n:
                total_new += n
                pending.append(r)
                self.append_log(f'[监控] {name} 发现 {n} 个新作品')
            else:
                self.append_log(f'[监控] {name} 无新作品（本页 {r.get("page_count", 0)}）')

        if not pending:
            self.append_log('[监控] 本轮完成，无新作品')
            return

        if self._is_worker_busy():
            self.append_log('[监控] 发现新作品但当前忙碌，本轮改下次再下')
            return

        self.append_log(f'[监控] 发现共 {total_new} 个新作品，开始自动下载')
        self._start_monitor_download(pending)

    def _start_monitor_download(self, pending_results):
        """将监控发现的新作品展开为下载任务并启动"""
        from douyin_downloader.core.parser import parse_awemes_to_works

        sel_v = []
        sel_i = []
        user_folders = set()
        base_folder = cfg.get('path', '') or os.getcwd()
        download_folder = os.path.join(base_folder, '作品下载')
        self._downloading_ids = set()
        self._download_task_counts = {}
        self._monitor_pending_updates = []

        use_mix_folder = cfg.get('use_mix_folder', True)
        include_date = cfg.get('include_date_in_filename', True)
        flat_image_enabled = bool(cfg.get('flat_image_enabled', False))
        download_live_cover = bool(cfg.get('download_live_cover', False))

        for r in pending_results:
            awemes = r.get('new_awemes') or []
            if not awemes:
                continue
            works = parse_awemes_to_works(awemes)
            self._monitor_pending_updates.append({
                'sec': r.get('sec'),
                'new_awemes': awemes,
            })
            for work in works:
                folder = self.author_folder_for_work(work, download_folder)
                user_folders.add(folder)
                # 扁平镜像目录：与博主文件夹同路径（作品下载/{博主}/图片/）
                flat_mirror_folder = folder if flat_image_enabled else None
                aid = work.get('aweme_id', '')
                if aid:
                    self._download_status[aid] = '下载中'
                    self._downloading_ids.add(aid)
                    n_tasks = len(work.get('video_tasks', [])) + len(work.get('image_tasks', []))
                    if download_live_cover:
                        n_tasks += len(work.get('cover_tasks', []))
                    self._download_task_counts[aid] = n_tasks
                for t in work.get('video_tasks', []):
                    nt = dict(t)
                    nt['base_folder'] = folder
                    if not use_mix_folder:
                        nt['mix_name'] = None
                    nt['include_date_in_filename'] = include_date
                    sel_v.append(nt)
                for t in work.get('image_tasks', []):
                    nt = dict(t)
                    nt['base_folder'] = folder
                    if flat_mirror_folder:
                        nt['flat_mirror_folder'] = flat_mirror_folder
                    if not use_mix_folder:
                        nt['mix_name'] = None
                    nt['include_date_in_filename'] = include_date
                    sel_i.append(nt)
                if download_live_cover:
                    for t in work.get('cover_tasks', []):
                        nt = dict(t)
                        nt['base_folder'] = folder
                        if flat_mirror_folder:
                            nt['flat_mirror_folder'] = flat_mirror_folder
                        if not use_mix_folder:
                            nt['mix_name'] = None
                        nt['include_date_in_filename'] = include_date
                        sel_i.append(nt)

        if not sel_v and not sel_i:
            self.append_log('[监控] 新作品无可下载媒体，跳过')
            self._apply_monitor_watermarks(self._monitor_pending_updates)
            self._monitor_pending_updates = []
            return

        for folder in user_folders:
            if not safe_mkdir(folder):
                self.append_log(f'[监控] 创建目录失败: {folder}')
                return

        user_folder = sorted(user_folders)[0] if user_folders else download_folder
        threads = int(cfg.get('threads', DEFAULT_THREAD_COUNT))
        cookie = cfg.get('cookie', '')
        if cookie:
            self.worker.session.headers.update({'Cookie': cookie})

        self._monitor_running = True
        self.worker._download_stop_requested = False
        self.worker._pause_requested = False

        self.progress.show()
        total_n = max(1, len(sel_v) + len(sel_i))
        self.progress.setMaximum(total_n)
        self.progress.setValue(0)
        self.on_progress(0, total_n)

        self.url_label_btn.setEnabled(False)
        self.settings_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.select_all_btn.setEnabled(False)
        self.export_excel_btn.setEnabled(False)
        self.export_urls_btn.setEnabled(False)
        self.invert_btn.setEnabled(False)
        self.fetch_btn.setEnabled(False)
        self.like_checkbox.setEnabled(False)
        self.latest_only_checkbox.setEnabled(False)
        self.download_btn.setText('停止下载')
        self.download_btn.setEnabled(True)
        self.download_btn.setProperty("running", True)
        style = self.style()
        if style:
            style.unpolish(self.download_btn)
            style.polish(self.download_btn)

        self._thread = threading.Thread(
            target=self.worker.download_tasks,
            args=(sel_v, sel_i, user_folder, threads),
            daemon=True,
        )
        self._thread.start()

    def _apply_monitor_watermarks(self, pending_updates):
        """根据已处理的新作品推进各用户水位线"""
        from douyin_downloader.core.monitor import advance_watermark, resolve_user_sec
        if not pending_updates:
            return
        users = cfg.get('users', [])
        changed = False
        for upd in pending_updates:
            sec = upd.get('sec') or ''
            new_awemes = upd.get('new_awemes') or []
            for u in users:
                u_sec = resolve_user_sec(u)
                if u_sec != sec:
                    continue
                since, seen = advance_watermark(
                    u.get('monitor_since'), u.get('monitor_seen_ids'), new_awemes
                )
                u['monitor_since'] = since
                u['monitor_seen_ids'] = seen
                changed = True
                break
        if changed:
            cfg['users'] = users
            save_config(cfg)

    def _finish_monitor_download(self):
        """监控下载收尾"""
        pending = getattr(self, '_monitor_pending_updates', []) or []
        self._apply_monitor_watermarks(pending)
        self._monitor_pending_updates = []
        self._monitor_running = False
        self.append_log('[监控] 自动下载完成，水位已更新')
        try:
            if (
                self.user_list_window
                and getattr(self, 'page_stack', None)
                and self.page_stack.currentWidget() is self.user_list_window
            ):
                self.user_list_window.load_users()
        except Exception:
            pass

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
