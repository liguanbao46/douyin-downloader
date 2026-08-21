#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GUI 启动入口
"""
import sys
import tempfile
import os
try:
    from PyQt6 import QtWidgets, QtGui
except ImportError:
    print("[错误] PyQt6 未安装或无法导入: \n请安装 PyQt6 后重试（pip install PyQt6）。")
    sys.exit(1)

from douyin_downloader.constants import ICON_BYTES, ICON_BYTES_OPTIONS, CUSTOM_ICON_PATH, OPENPYXL_AVAILABLE
from douyin_downloader.utils.config import load_config
from douyin_downloader.gui.main_window import MainWindow

from douyin_downloader import gui

def get_app_icon():
    """获取应用程序图标"""
    icon_choice = gui.cfg.get('icon_choice', 'default')

    if icon_choice == 'custom' and os.path.exists(CUSTOM_ICON_PATH):
        try:
            with open(CUSTOM_ICON_PATH, 'rb') as f:
                custom_icon_bytes = f.read()
            return custom_icon_bytes
        except Exception as e:
            print(f"Warning: Failed to load custom icon: {e}")

    return ICON_BYTES_OPTIONS.get(icon_choice, ICON_BYTES)


def run_gui():
    """启动PyQt6图形界面"""
    app = QtWidgets.QApplication(sys.argv)

    # Windows系统特殊处理任务栏图标
    if sys.platform.startswith('win'):
        import ctypes
        myappid = 'douyin.downloader.app'  # 应用用户模型ID，确保任务栏图标正确显示
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    loaded_cfg = load_config()
    gui.cfg.update(loaded_cfg)

    try:
        icon_bytes = get_app_icon()
        with tempfile.NamedTemporaryFile(suffix='.ico', delete=False) as tmp:
            tmp.write(icon_bytes)
            tmp_icon_path = tmp.name
        app_icon = QtGui.QIcon(tmp_icon_path)
        app.setWindowIcon(app_icon)
    except Exception as e:
        print(f"Warning: Failed to create temp icon: {e}")

    checkmark_path = ''
    try:
        checkmark_svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path fill="white" stroke="white" stroke-width="0.5" d="M13.5 4l-7 7-3.5-3.5 1.5-1.5 2 2 5.5-5.5z"/></svg>'
        with tempfile.NamedTemporaryFile(suffix='.svg', delete=False, mode='wb') as tmp_check:
            tmp_check.write(checkmark_svg)
            checkmark_path = tmp_check.name.replace('\\', '/')
    except Exception as e:
        print(f"Warning: Failed to create temp checkmark svg: {e}")

    try:
        app.setStyleSheet(f"""
        /* Apple/Pinguo design system global stylesheet */
        QWidget {{
            background-color: #FFFFFF;
            color: #1D1D1F;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            font-size: 13px;
        }}
        QMainWindow, QDialog {{
            background-color: #FFFFFF;
        }}
        QLabel {{
            background-color: transparent;
            color: #1D1D1F;
        }}

        QWidget#works_page {{
            background-color: #F2F2F7;
        }}
        QFrame#settings_card {{
            background-color: #FFFFFF;
            border: 1px solid #E5E5EA;
            border-radius: 12px;
        }}
        QLabel#section_title {{
            color: #6E6E73;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }}
        QPushButton#type_filter_btn {{
            background-color: #FFFFFF;
            color: #1D1D1F;
            border: 1px solid #E5E5EA;
            border-radius: 12px;
            padding: 4px 12px;
        }}
        QPushButton#type_filter_btn:hover {{
            background-color: #F2F2F7;
        }}
        QPushButton#icon_btn {{
            background-color: transparent;
            color: #1D1D1F;
            border: none;
            border-radius: 12px;
            padding: 4px;
        }}
        QPushButton#icon_btn:hover {{
            background-color: #E5E5EA;
        }}

        /* ---------------- 按钮 ---------------- */
        QPushButton {{
            background-color: #F2F2F7;
            color: #1D1D1F;
            border: none;
            padding: 6px 14px;
            border-radius: 12px;
            font-weight: 500;
            font-size: 13px;
            outline: none;
        }}
        QPushButton:hover {{
            background-color: #E5E5EA;
        }}
        QPushButton:pressed {{
            background-color: #D1D1D6;
        }}
        QPushButton:disabled {{
            background-color: #F2F2F7;
            color: #AEAEB2;
        }}
        QPushButton:checked {{
            background-color: #E5E5EA;
        }}

        /* Primary buttons */
        QPushButton#fetch_btn, QPushButton#download_btn, QPushButton#save_settings_btn {{
            background-color: #007AFF;
            color: #FFFFFF;
            border-radius: 12px;
        }}
        QPushButton#fetch_btn:hover, QPushButton#download_btn:hover, QPushButton#save_settings_btn:hover {{
            background-color: #0064D6;
        }}
        QPushButton#fetch_btn:pressed, QPushButton#download_btn:pressed, QPushButton#save_settings_btn:pressed {{
            background-color: #004FAD;
        }}
        QPushButton#fetch_btn:disabled, QPushButton#download_btn:disabled, QPushButton#save_settings_btn:disabled {{
            background-color: #9FCBFF;
            color: #FFFFFF;
        }}

        /* clear_btn now uses the default secondary style to match the HTML prototype */
        /*
        QPushButton#clear_btn {{
            background-color: #FF3B30;
            color: #FFFFFF;
        }}
        QPushButton#clear_btn:hover {{
            background-color: #D32F2F;
        }}
        QPushButton#clear_btn:pressed {{
            background-color: #B71C1C;
        }}
        QPushButton#clear_btn:disabled {{
            background-color: #FFCCC9;
            color: #FFFFFF;
        }}
        */

        /* "停止"按钮的红色样式（通过 running="true" 属性激活） */
        QPushButton[running="true"] {{
            background-color: #FF3B30;
            color: #FFFFFF;
            padding: 6px 14px;
            border: none;
            border-radius: 12px;
            font-weight: 500;
            font-size: 13px;
        }}
        QPushButton[running="true"]:hover {{
            background-color: #D32F2F;
        }}
        QPushButton[running="true"]:pressed {{
            background-color: #B71C1C;
        }}
        QPushButton[running="true"]:disabled {{
            background-color: #FFCCC9;
            color: #FFFFFF;
        }}

        /* URL label button */
        QPushButton#url_label_btn {{
            background-color: transparent;
            color: #1D1D1F;
            padding: 0px;
            font-weight: 600;
        }}
        QPushButton#url_label_btn:hover {{
            color: #007AFF;
        }}

        /* ---------------- 输入框 ---------------- */
        QLineEdit, QTextEdit, QSpinBox {{
            border: 1px solid #E5E5EA;
            background-color: #FFFFFF;
            color: #1D1D1F;
            padding: 6px;
            border-radius: 8px;
            font-size: 13px;
        }}
        QLineEdit:focus, QTextEdit:focus, QSpinBox:focus {{
            border: 2px solid #007AFF;
        }}
        QLineEdit:disabled, QTextEdit:disabled, QSpinBox:disabled {{
            background-color: #F2F2F7;
            color: #8E8E93;
        }}

        /* ---------------- 复选框 ---------------- */
        QCheckBox {{
            spacing: 8px;
            font-size: 13px;
            color: #1D1D1F;
            background-color: transparent;
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border: 1px solid #E5E5EA;
            border-radius: 5px;
            background-color: #FFFFFF;
        }}
        QCheckBox::indicator:hover {{
            border: 1px solid #007AFF;
        }}
        QCheckBox::indicator:checked {{
            background-color: #007AFF;
            border: 1px solid #007AFF;
            image: url("{checkmark_path}");
        }}
        QCheckBox::indicator:checked:hover {{
            background-color: #0064D6;
            border: 1px solid #0064D6;
        }}

        /* ---------------- 列表复选框 (QTreeWidget) ---------------- */
        QTreeView::indicator, QTreeWidget::indicator {{
            width: 16px;
            height: 16px;
            border: 1px solid #E5E5EA;
            border-radius: 4px;
            background-color: #FFFFFF;
        }}
        QTreeView::indicator:hover, QTreeWidget::indicator:hover {{
            border: 1px solid #007AFF;
        }}
        QTreeView::indicator:checked, QTreeWidget::indicator:checked {{
            background-color: #007AFF;
            border: 1px solid #007AFF;
            image: url("{checkmark_path}");
        }}

        /* ---------------- 列表 QTreeWidget ---------------- */
        QTreeWidget {{
            background-color: #FFFFFF;
            border: 1px solid #E5E5EA;
            border-radius: 8px;
            outline: none;
            font-size: 13px;
            alternate-background-color: #F2F2F7;
        }}
        QTreeWidget::item {{
            padding: 6px 4px;
            color: #1D1D1F;
            border: none;
            outline: none;
        }}
        QTreeWidget::item:hover {{
            background-color: #F2F2F7;
        }}
        QTreeWidget::item:selected,
        QTreeWidget::item:selected:active,
        QTreeWidget::item:selected:!active {{
            background-color: #E5E5EA;
            color: #1D1D1F;
        }}
        QHeaderView::section {{
            background-color: #FFFFFF;
            color: #6E6E73;
            padding: 6px 4px;
            border: none;
            border-bottom: 1px solid #E5E5EA;
            font-weight: 600;
            font-size: 12px;
        }}

        /* ---------------- 侧边栏 QListWidget ---------------- */
        QListWidget {{
            background-color: #F2F2F7;
            border: none;
            border-right: 1px solid #E5E5EA;
            outline: none;
            font-size: 13px;
            padding: 8px 6px;
        }}
        QListWidget::item {{
            padding: 8px 12px;
            color: #1D1D1F;
            border-radius: 8px;
        }}
        QListWidget::item:hover {{
            background-color: #E5E5EA;
        }}
        QListWidget::item:selected {{
            background-color: #007AFF;
            color: #FFFFFF;
        }}

        /* ---------------- 进度条 ---------------- */
        QProgressBar {{
            border: none;
            background-color: #F2F2F7;
            height: 8px;
            border-radius: 4px;
            text-align: center;
            font-size: 12px;
            color: #6E6E73;
        }}
        QProgressBar::chunk {{
            background-color: #007AFF;
            border-radius: 4px;
        }}

        /* ---------------- 滚动条 ---------------- */
        QScrollBar:vertical {{
            border: none;
            background-color: transparent;
            width: 10px;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background-color: #C7C7CC;
            border-radius: 5px;
            min-height: 20px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: #AEAEB2;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
            background: none;
        }}
        QScrollBar:horizontal {{
            border: none;
            background-color: transparent;
            height: 10px;
            margin: 0px;
        }}
        QScrollBar::handle:horizontal {{
            background-color: #C7C7CC;
            border-radius: 5px;
            min-width: 20px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background-color: #AEAEB2;
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
            background: none;
        }}

        /* ---------------- 菜单 ---------------- */
        QMenu {{
            background-color: #FFFFFF;
            border: 1px solid #E5E5EA;
            border-radius: 8px;
            padding: 6px;
        }}
        QMenu::item {{
            padding: 6px 12px;
            border-radius: 6px;
        }}
        QMenu::item:selected {{
            background-color: #F2F2F7;
            color: #1D1D1F;
        }}

        /* ---------------- 图标预览按钮 ---------------- */
        IconPreviewButton {{
            background-color: #FFFFFF;
            border: 1px solid #E5E5EA;
            border-radius: 8px;
        }}
        IconPreviewButton:hover {{
            border: 1px solid #007AFF;
        }}
        IconPreviewButton:checked {{
            background-color: #E8F2FF;
            border: 2px solid #007AFF;
        }}
        """)
    except Exception as e:
        print(f"Warning: Failed to set stylesheet: {e}")

    w = MainWindow(checkmark_path)
    w.show()
    app.exec()
