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
            border: 1px solid #E5E5EA;
            border-radius: 4px;
            background: #FFFFFF;
        }}
        QCheckBox::indicator:hover {{ border: 1px solid #007AFF; }}
        QCheckBox::indicator:checked {{
            background-color: #007AFF;
            border: 1px solid #007AFF;
            image: url({svg});
        }}
        QCheckBox::indicator:indeterminate {{
            background-color: #9FCBFF;
            border: 1px solid #007AFF;
        }}
    """)

    def reposition():
        if not header:
            return
        h = header.height()
        x = header.sectionViewportPosition(0)
        w = header.sectionSize(0)

        # 用样式计算行内复选框指示器的真实位置，让表头全选框与行内复选框精确对齐
        ind_x = x + 2
        ind_y = max(0, (h - 16) // 2)
        ind_w = 16
        try:
            style = tree.style()
            opt = QtWidgets.QStyleOptionViewItem()
            opt.rect = QtCore.QRect(x, 0, w, h)
            opt.features = QtWidgets.QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
            opt.checkState = Qt.CheckState.Unchecked
            ind = style.subElementRect(
                QtWidgets.QStyle.SubElement.SE_ItemViewItemCheckIndicator, opt, tree
            )
            if ind.isValid() and ind.width() > 0:
                ind_x = ind.x()
                ind_y = ind.y()
                ind_w = ind.width()
        except Exception:
            pass

        cb.setFixedSize(ind_w, ind_w)
        cb.move(ind_x, ind_y)
        cb.raise_()
        cb.show()

    header.sectionResized.connect(lambda *_: reposition())
    header.geometriesChanged.connect(reposition)
    QtCore.QTimer.singleShot(0, reposition)
    return cb, reposition
