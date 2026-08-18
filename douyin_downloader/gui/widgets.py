#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GUI - 自定义控件与样式
"""
import sys
try:
    from PyQt6 import QtWidgets, QtCore
    from PyQt6.QtCore import Qt
except ImportError:
    print("[错误] PyQt6 未安装或无法导入: \n请安装 PyQt6 后重试（pip install PyQt6）。")
    sys.exit(1)

class NoFocusRectStyle(QtWidgets.QProxyStyle):
    """自定义样式类，用于禁用列表/树的焦点虚线框"""
    def drawPrimitive(self, element, option, painter, widget=None):
        # 不绘制焦点虚线框，保持界面干净
        if element == QtWidgets.QStyle.PrimitiveElement.PE_FrameFocusRect:
            return
        super().drawPrimitive(element, option, painter, widget)


def attach_header_checkbox(tree, checkmark_svg_path='', tooltip='全选'):
    """
    在 QTreeWidget 第 0 列表头放置全选复选框。
    返回 (checkbox, reposition_fn)。
    """
    header = tree.header()
    cb = QtWidgets.QCheckBox(header)
    cb.setToolTip(tooltip)
    cb.setTristate(True)
    cb.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    cb.setCursor(Qt.CursorShape.PointingHandCursor)
    svg = checkmark_svg_path.replace('\\', '/')
    cb.setStyleSheet(f"""
        QCheckBox {{
            spacing: 0px;
            margin: 0px;
            padding: 0px;
            background: transparent;
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border: 1px solid #c0c4cc;
            border-radius: 2px;
            background: #ffffff;
        }}
        QCheckBox::indicator:hover {{ border: 1px solid #409EFF; }}
        QCheckBox::indicator:checked {{
            background-color: #409EFF;
            border: 1px solid #409EFF;
            image: url({svg});
        }}
        QCheckBox::indicator:indeterminate {{
            background-color: #a0cfff;
            border: 1px solid #409EFF;
        }}
    """)

    def reposition():
        if not header:
            return
        x = header.sectionViewportPosition(0)
        w = header.sectionSize(0)
        h = header.height()
        side = 18
        cb.setFixedSize(side, side)
        cb.move(x + max(0, (w - side) // 2), max(0, (h - side) // 2))
        cb.raise_()
        cb.show()

    header.sectionResized.connect(lambda *_: reposition())
    header.geometriesChanged.connect(reposition)
    QtCore.QTimer.singleShot(0, reposition)
    return cb, reposition
