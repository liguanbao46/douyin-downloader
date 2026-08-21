# -*- coding: utf-8 -*-
"""
提取作品筛选条件面板（主页列表下方）
可折叠、单列分区，避免窄宽度下控件互相遮挡。
"""
try:
    from PyQt6 import QtWidgets, QtCore, QtGui
    from PyQt6.QtCore import Qt
except ImportError:
    raise

from douyin_downloader.gui import cfg
from douyin_downloader.utils.config import save_config
from douyin_downloader.core.work_filters import DEFAULT_EXTRACT_FILTERS, normalize_filters


def _section_title(text):
    lab = QtWidgets.QLabel(text)
    lab.setObjectName('FilterSectionTitle')
    return lab


def _hint(text):
    lab = QtWidgets.QLabel(text)
    lab.setObjectName('FilterHint')
    lab.setWordWrap(True)
    return lab


def _spin(min_v, max_v, value, width=120):
    """足够宽的数字框；单位用旁侧 Label。覆盖全局 padding，避免数字被箭头挡住。"""
    sp = QtWidgets.QSpinBox()
    sp.setRange(min_v, max_v)
    sp.setValue(value)
    sp.setFixedSize(width, 28)
    sp.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.UpDownArrows)
    sp.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    sp.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
    # 覆盖 app 全局 QSpinBox { padding: 6px }：左侧给数字，右侧留给箭头
    sp.setStyleSheet("""
        QSpinBox {
            padding: 0px;
            padding-left: 8px;
            padding-right: 22px;
            min-height: 28px;
            max-height: 28px;
            font-size: 12px;
        }
    """)
    return sp


class ExtractFilterPanel(QtWidgets.QWidget):
    """提取筛选：顶栏开关 + 可折叠单列条件"""

    changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('ExtractFilterPanel')
        self._updating = False
        self._body_expanded = False
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Maximum,
        )

        self.setStyleSheet("""
            #ExtractFilterPanel {
                background: #F2F2F7;
                border: 1px solid #E5E5EA;
                border-radius: 12px;
            }
            #FilterHeader {
                background: #FFFFFF;
                border-bottom: 1px solid #E5E5EA;
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
            }
            #FilterBodyInner {
                background: #F2F2F7;
            }
            #FilterCard {
                background: #FFFFFF;
                border: 1px solid #E5E5EA;
                border-radius: 8px;
            }
            #FilterSectionTitle {
                color: #6E6E73;
                font-size: 12px;
                font-weight: 600;
                background: transparent;
                padding-bottom: 2px;
            }
            #FilterHint {
                color: #8E8E93;
                font-size: 11px;
                background: transparent;
            }
            #FilterSummary {
                color: #6E6E73;
                font-size: 12px;
                background: transparent;
            }
            #FilterSummary[active="true"] {
                color: #007AFF;
            }
            #ExtractFilterPanel QLabel {
                color: #1D1D1F;
                font-size: 12px;
                background: transparent;
            }
            #ExtractFilterPanel QCheckBox {
                color: #1D1D1F;
                font-size: 12px;
                spacing: 6px;
                background: transparent;
                min-height: 22px;
            }
            #ExtractFilterPanel QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #E5E5EA;
                border-radius: 4px;
                background: #FFFFFF;
            }
            #ExtractFilterPanel QCheckBox::indicator:hover { border-color: #007AFF; }
            #ExtractFilterPanel QCheckBox::indicator:checked {
                background: #007AFF;
                border-color: #007AFF;
            }
            #ExtractFilterPanel QCheckBox:disabled { color: #AEAEB2; }
            #ExtractFilterPanel QSpinBox,
            #ExtractFilterPanel QDateTimeEdit {
                background: #FFFFFF;
                border: 1px solid #E5E5EA;
                border-radius: 6px;
                padding: 1px 8px;
                min-height: 26px;
                max-height: 28px;
                font-size: 12px;
                color: #1D1D1F;
            }
            #ExtractFilterPanel QSpinBox {
                /* 右侧留给上下箭头，防止数字被遮挡 */
                padding-right: 28px;
            }
            #ExtractFilterPanel QSpinBox:focus,
            #ExtractFilterPanel QDateTimeEdit:focus {
                border: 1px solid #007AFF;
            }
            #ExtractFilterPanel QSpinBox:disabled,
            #ExtractFilterPanel QDateTimeEdit:disabled {
                background: #F2F2F7;
                color: #AEAEB2;
            }
            #ExtractFilterPanel QScrollArea {
                background: transparent;
                border: none;
            }
            QPushButton#FilterToggleBtn {
                background: transparent;
                border: 1px solid #E5E5EA;
                color: #1D1D1F;
                padding: 4px 12px;
                font-size: 12px;
                font-weight: 400;
            }
            QPushButton#FilterToggleBtn:hover {
                border-color: #007AFF;
                color: #007AFF;
                background: #E8F2FF;
            }
            #ExtractFilterPanel QCheckBox#MasterSwitch {
                color: #1D1D1F;
                font-size: 13px;
                font-weight: 600;
                spacing: 8px;
            }
        """)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- header ----
        header = QtWidgets.QWidget()
        header.setObjectName('FilterHeader')
        header.setFixedHeight(42)
        h = QtWidgets.QHBoxLayout(header)
        h.setContentsMargins(12, 0, 12, 0)
        h.setSpacing(12)

        self.chk_enabled = QtWidgets.QCheckBox('启用提取筛选')
        self.chk_enabled.setObjectName('MasterSwitch')
        self.chk_enabled.setToolTip('关闭时提取全部作品；开启后按下方条件过滤')
        h.addWidget(self.chk_enabled)

        self.summary_label = QtWidgets.QLabel('未启用')
        self.summary_label.setObjectName('FilterSummary')
        h.addWidget(self.summary_label, 1)

        self.toggle_btn = QtWidgets.QPushButton('展开条件')
        self.toggle_btn.setObjectName('FilterToggleBtn')
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setFixedWidth(88)
        h.addWidget(self.toggle_btn)
        root.addWidget(header)

        # ---- scrollable body (单列，避免 2 列挤压遮挡) ----
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll.setMaximumHeight(300)

        self.body = QtWidgets.QWidget()
        self.body.setObjectName('FilterBodyInner')
        body_lay = QtWidgets.QVBoxLayout(self.body)
        body_lay.setContentsMargins(10, 8, 10, 10)
        body_lay.setSpacing(8)

        body_lay.addWidget(self._build_basic_card())
        body_lay.addWidget(self._build_time_card())
        body_lay.addWidget(self._build_media_card())
        body_lay.addWidget(self._build_attr_card())
        body_lay.addStretch(0)

        self.scroll.setWidget(self.body)
        root.addWidget(self.scroll)

        self._wire_mutual(self.chk_want_life, self.chk_no_life)
        self._wire_mutual(self.chk_want_goods, self.chk_no_goods)
        self._wire_mutual(self.chk_landscape, self.chk_no_landscape)
        self._wire_mutual(self.chk_member, self.chk_no_member)

        self.toggle_btn.clicked.connect(self._toggle_body)
        self.chk_enabled.stateChanged.connect(self._on_master_toggled)

        for w in self.findChildren(QtWidgets.QCheckBox):
            if w is not self.chk_enabled:
                w.stateChanged.connect(self._on_any_changed)
        for w in self.findChildren(QtWidgets.QSpinBox):
            w.valueChanged.connect(self._on_any_changed)
        for w in self.findChildren(QtWidgets.QDateTimeEdit):
            w.dateTimeChanged.connect(self._on_any_changed)

        self.load_from_cfg()
        self._set_body_visible(bool(self.chk_enabled.isChecked()))
        self._update_enabled_state()
        self._refresh_summary()

    # ---------- helpers ----------
    def _make_card(self):
        card = QtWidgets.QFrame()
        card.setObjectName('FilterCard')
        card.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Maximum,
        )
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        return card, lay

    def _range_row(self, checkbox, spin_min, spin_max, unit_text):
        """复选框独占一行；数值范围下一行缩进，避免横向挤叠"""
        wrap = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(checkbox)

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(22, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(spin_min)
        row.addWidget(QtWidgets.QLabel('至'))
        row.addWidget(spin_max)
        row.addWidget(QtWidgets.QLabel(unit_text))
        row.addStretch(1)
        v.addLayout(row)
        return wrap

    # ---------- cards ----------
    def _build_basic_card(self):
        card, lay = self._make_card()
        lay.addWidget(_section_title('基础'))

        row_type = QtWidgets.QHBoxLayout()
        row_type.setSpacing(16)
        self.chk_type_video = QtWidgets.QCheckBox('视频')
        self.chk_type_image = QtWidgets.QCheckBox('图文')
        row_type.addWidget(QtWidgets.QLabel('作品类型'))
        row_type.addWidget(self.chk_type_video)
        row_type.addWidget(self.chk_type_image)
        row_type.addStretch(1)
        lay.addLayout(row_type)

        row_limit = QtWidgets.QHBoxLayout()
        row_limit.setSpacing(8)
        row_limit.addWidget(QtWidgets.QLabel('每主页数量'))
        self.spin_limit = _spin(0, 9999, 0)
        self.spin_limit.setToolTip('0 表示不限制，提取全部')
        row_limit.addWidget(self.spin_limit)
        row_limit.addWidget(_hint('0 = 全部'))
        row_limit.addStretch(1)
        lay.addLayout(row_limit)

        self.chk_unrecorded = QtWidgets.QCheckBox('仅提取未记录作品 ID')
        self.chk_unrecorded.setToolTip('跳过该主页已提取过的作品，并在本次提取后记录新 ID')
        lay.addWidget(self.chk_unrecorded)
        return card

    def _build_time_card(self):
        card, lay = self._make_card()
        lay.addWidget(_section_title('时间'))

        self.chk_hours = QtWidgets.QCheckBox('仅近 N 小时内发布')
        self.spin_hours = _spin(1, 24 * 30, 10)
        hours_wrap = QtWidgets.QWidget()
        hv = QtWidgets.QVBoxLayout(hours_wrap)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(4)
        hv.addWidget(self.chk_hours)
        hr = QtWidgets.QHBoxLayout()
        hr.setContentsMargins(22, 0, 0, 0)
        hr.setSpacing(8)
        hr.addWidget(self.spin_hours)
        hr.addWidget(QtWidgets.QLabel('小时'))
        hr.addStretch(1)
        hv.addLayout(hr)
        lay.addWidget(hours_wrap)

        self.chk_start = QtWidgets.QCheckBox('不早于')
        self.dt_start = QtWidgets.QDateTimeEdit()
        self.dt_start.setCalendarPopup(True)
        self.dt_start.setDisplayFormat('yyyy-MM-dd HH:mm')
        self.dt_start.setDateTime(QtCore.QDateTime.currentDateTime())
        self.dt_start.setMinimumWidth(170)
        self.dt_start.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        row_s = QtWidgets.QHBoxLayout()
        row_s.setSpacing(8)
        row_s.addWidget(self.chk_start)
        row_s.addWidget(self.dt_start, 1)
        lay.addLayout(row_s)

        self.chk_end = QtWidgets.QCheckBox('不晚于')
        self.dt_end = QtWidgets.QDateTimeEdit()
        self.dt_end.setCalendarPopup(True)
        self.dt_end.setDisplayFormat('yyyy-MM-dd HH:mm')
        self.dt_end.setDateTime(QtCore.QDateTime.currentDateTime())
        self.dt_end.setMinimumWidth(170)
        self.dt_end.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        row_e = QtWidgets.QHBoxLayout()
        row_e.setSpacing(8)
        row_e.addWidget(self.chk_end)
        row_e.addWidget(self.dt_end, 1)
        lay.addLayout(row_e)
        return card

    def _build_media_card(self):
        card, lay = self._make_card()
        lay.addWidget(_section_title('媒体'))
        lay.addWidget(_hint('勾选后填写范围；输入框与单位分开，避免数字被箭头挡住'))

        self.chk_duration = QtWidgets.QCheckBox('限制视频时长')
        self.spin_dur_min = _spin(0, 36000, 10)
        self.spin_dur_max = _spin(0, 36000, 30)
        lay.addWidget(self._range_row(
            self.chk_duration, self.spin_dur_min, self.spin_dur_max, '秒'
        ))

        self.chk_images = QtWidgets.QCheckBox('限制图文张数')
        self.spin_img_min = _spin(1, 99, 1)
        self.spin_img_max = _spin(1, 99, 3)
        lay.addWidget(self._range_row(
            self.chk_images, self.spin_img_min, self.spin_img_max, '张'
        ))

        row_l = QtWidgets.QHBoxLayout()
        row_l.setSpacing(20)
        self.chk_landscape = QtWidgets.QCheckBox('只要横屏视频')
        self.chk_no_landscape = QtWidgets.QCheckBox('不要横屏视频')
        row_l.addWidget(self.chk_landscape)
        row_l.addWidget(self.chk_no_landscape)
        row_l.addStretch(1)
        lay.addLayout(row_l)
        return card

    def _build_attr_card(self):
        card, lay = self._make_card()
        lay.addWidget(_section_title('属性'))
        lay.addWidget(_hint('同一行左右互斥，只选一侧；依赖接口字段，未必全部能识别'))

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.chk_want_life = QtWidgets.QCheckBox('有本地生活')
        self.chk_no_life = QtWidgets.QCheckBox('无本地生活')
        self.chk_want_goods = QtWidgets.QCheckBox('只要商品')
        self.chk_no_goods = QtWidgets.QCheckBox('不要商品')
        self.chk_member = QtWidgets.QCheckBox('只要会员')
        self.chk_no_member = QtWidgets.QCheckBox('不要会员')
        grid.addWidget(self.chk_want_life, 0, 0)
        grid.addWidget(self.chk_no_life, 0, 1)
        grid.addWidget(self.chk_want_goods, 1, 0)
        grid.addWidget(self.chk_no_goods, 1, 1)
        grid.addWidget(self.chk_member, 2, 0)
        grid.addWidget(self.chk_no_member, 2, 1)
        lay.addLayout(grid)
        return card

    # ---------- interaction ----------
    def _toggle_body(self):
        self._set_body_visible(not self._body_expanded)

    def _set_body_visible(self, visible):
        self._body_expanded = bool(visible)
        self.scroll.setVisible(self._body_expanded)
        self.toggle_btn.setText('收起条件' if self._body_expanded else '展开条件')

    def _on_master_toggled(self, *_):
        if self._updating:
            return
        on = self.chk_enabled.isChecked()
        if on and not self._body_expanded:
            self._set_body_visible(True)
        self._update_enabled_state()
        self._refresh_summary()
        self.save_to_cfg()
        self.changed.emit()

    def _wire_mutual(self, a, b):
        def _is_checked(state):
            # PyQt6: stateChanged 可能传 int 或 CheckState；勿对 CheckState 再 int()
            return Qt.CheckState(state) == Qt.CheckState.Checked

        def on_a(state):
            if self._updating:
                return
            if _is_checked(state):
                self._updating = True
                b.setChecked(False)
                self._updating = False

        def on_b(state):
            if self._updating:
                return
            if _is_checked(state):
                self._updating = True
                a.setChecked(False)
                self._updating = False

        a.stateChanged.connect(on_a)
        b.stateChanged.connect(on_b)

    def _on_any_changed(self, *_):
        if self._updating:
            return
        self._update_enabled_state()
        self._refresh_summary()
        self.save_to_cfg()
        self.changed.emit()

    def _active_condition_count(self):
        f = self.get_filters()
        if not f.get('enabled'):
            return 0
        n = 0
        if not (f.get('type_video') and f.get('type_image')):
            n += 1
        if f.get('per_user_limit', 0) > 0:
            n += 1
        if f.get('only_unrecorded_ids'):
            n += 1
        if f.get('hours_enabled'):
            n += 1
        if f.get('start_time_enabled'):
            n += 1
        if f.get('end_time_enabled'):
            n += 1
        if f.get('duration_enabled'):
            n += 1
        if f.get('image_count_enabled'):
            n += 1
        if f.get('want_landscape') or f.get('want_no_landscape'):
            n += 1
        if f.get('want_local_life') or f.get('want_no_local_life'):
            n += 1
        if f.get('want_goods') or f.get('want_no_goods'):
            n += 1
        if f.get('want_member') or f.get('want_no_member'):
            n += 1
        return n

    def _refresh_summary(self):
        if not self.chk_enabled.isChecked():
            self.summary_label.setText('未启用 · 提取时不过滤')
            self.summary_label.setProperty('active', 'false')
        else:
            n = self._active_condition_count()
            self.summary_label.setText(f'已启用 · {n} 项条件生效')
            self.summary_label.setProperty('active', 'true')
        st = self.summary_label.style()
        if st:
            st.unpolish(self.summary_label)
            st.polish(self.summary_label)

    def _update_enabled_state(self):
        on = self.chk_enabled.isChecked()
        for w in self.body.findChildren(QtWidgets.QWidget):
            if isinstance(w, (QtWidgets.QCheckBox, QtWidgets.QSpinBox, QtWidgets.QDateTimeEdit, QtWidgets.QLabel)):
                w.setEnabled(on)
        if on:
            self.spin_hours.setEnabled(self.chk_hours.isChecked())
            self.dt_start.setEnabled(self.chk_start.isChecked())
            self.dt_end.setEnabled(self.chk_end.isChecked())
            self.spin_dur_min.setEnabled(self.chk_duration.isChecked())
            self.spin_dur_max.setEnabled(self.chk_duration.isChecked())
            self.spin_img_min.setEnabled(self.chk_images.isChecked())
            self.spin_img_max.setEnabled(self.chk_images.isChecked())

    def get_filters(self):
        return normalize_filters({
            'enabled': self.chk_enabled.isChecked(),
            'type_video': self.chk_type_video.isChecked(),
            'type_image': self.chk_type_image.isChecked(),
            'only_unrecorded_ids': self.chk_unrecorded.isChecked(),
            'hours_enabled': self.chk_hours.isChecked(),
            'hours': self.spin_hours.value(),
            'per_user_limit': self.spin_limit.value(),
            'want_local_life': self.chk_want_life.isChecked(),
            'want_no_local_life': self.chk_no_life.isChecked(),
            'want_goods': self.chk_want_goods.isChecked(),
            'want_no_goods': self.chk_no_goods.isChecked(),
            'start_time_enabled': self.chk_start.isChecked(),
            'start_time': self.dt_start.dateTime().toString('yyyy-MM-dd HH:mm:ss'),
            'end_time_enabled': self.chk_end.isChecked(),
            'end_time': self.dt_end.dateTime().toString('yyyy-MM-dd HH:mm:ss'),
            'duration_enabled': self.chk_duration.isChecked(),
            'duration_min': self.spin_dur_min.value(),
            'duration_max': self.spin_dur_max.value(),
            'want_landscape': self.chk_landscape.isChecked(),
            'want_no_landscape': self.chk_no_landscape.isChecked(),
            'image_count_enabled': self.chk_images.isChecked(),
            'image_count_min': self.spin_img_min.value(),
            'image_count_max': self.spin_img_max.value(),
            'want_member': self.chk_member.isChecked(),
            'want_no_member': self.chk_no_member.isChecked(),
        })

    def load_from_cfg(self):
        f = normalize_filters(cfg.get('extract_filters'))
        self._updating = True
        try:
            self.chk_enabled.setChecked(f['enabled'])
            self.chk_type_video.setChecked(f['type_video'])
            self.chk_type_image.setChecked(f['type_image'])
            self.chk_unrecorded.setChecked(f['only_unrecorded_ids'])
            self.chk_hours.setChecked(f['hours_enabled'])
            self.spin_hours.setValue(f['hours'] or DEFAULT_EXTRACT_FILTERS['hours'])
            self.spin_limit.setValue(f['per_user_limit'])
            self.chk_want_life.setChecked(f['want_local_life'])
            self.chk_no_life.setChecked(f['want_no_local_life'])
            self.chk_want_goods.setChecked(f['want_goods'])
            self.chk_no_goods.setChecked(f['want_no_goods'])
            self.chk_start.setChecked(f['start_time_enabled'])
            self.chk_end.setChecked(f['end_time_enabled'])
            self.chk_duration.setChecked(f['duration_enabled'])
            self.spin_dur_min.setValue(f['duration_min'])
            self.spin_dur_max.setValue(f['duration_max'])
            self.chk_landscape.setChecked(f['want_landscape'])
            self.chk_no_landscape.setChecked(f['want_no_landscape'])
            self.chk_images.setChecked(f['image_count_enabled'])
            self.spin_img_min.setValue(f['image_count_min'])
            self.spin_img_max.setValue(f['image_count_max'])
            self.chk_member.setChecked(f['want_member'])
            self.chk_no_member.setChecked(f['want_no_member'])
            for attr, key in ((self.dt_start, 'start_time'), (self.dt_end, 'end_time')):
                s = f.get(key) or ''
                dt = QtCore.QDateTime.fromString(s, 'yyyy-MM-dd HH:mm:ss')
                if not dt.isValid():
                    dt = QtCore.QDateTime.fromString(s, 'yyyy-MM-dd HH:mm')
                if not dt.isValid():
                    dt = QtCore.QDateTime.currentDateTime()
                attr.setDateTime(dt)
        finally:
            self._updating = False
        self._update_enabled_state()
        self._refresh_summary()

    def save_to_cfg(self):
        cfg['extract_filters'] = self.get_filters()
        save_config(cfg)
