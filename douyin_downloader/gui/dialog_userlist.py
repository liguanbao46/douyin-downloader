#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GUI - 增强版主页列表（用户管理弹窗）
展示已保存用户的完整统计数据。
"""
import sys
try:
    from PyQt6 import QtWidgets, QtCore, QtGui
    from PyQt6.QtCore import Qt
except ImportError:
    print("[错误] PyQt6 未安装或无法导入: \n请安装 PyQt6 后重试（pip install PyQt6）。")
    sys.exit(1)

from douyin_downloader.gui import cfg
from douyin_downloader.utils.config import save_config
from douyin_downloader.core.api import extract_sec_user_id_from_url
from .widgets import NoFocusRectStyle


class UserListWindow(QtWidgets.QDialog):
    """增强版主页列表窗口 — 展示用户完整统计"""

    # 列定义：(列名, 数据key, 对齐方式)
    COLS = [
        ('选择', None, 'center'),
        ('序号', '_idx', 'center'),
        ('分组', 'group', 'left'),
        ('作者', 'username', 'left'),
        ('关注数量', 'following_count', 'right'),
        ('粉丝数量', 'follower_count', 'right'),
        ('获赞数量', 'total_favorited', 'right'),
        ('喜欢数量', 'favoriting_count', 'right'),
        ('作品数量', 'aweme_count', 'right'),
        ('最后发布作品时间', 'last_publish_time', 'center'),
    ]

    def __init__(self, parent=None, checkmark_svg_path=''):
        super().__init__(parent)
        self.checkmark_svg_path = checkmark_svg_path
        self.setWindowTitle('主页列表')
        self.setModal(False)
        self.resize(1100, 500)

        layout = QtWidgets.QVBoxLayout(self)

        # 工具栏
        toolbar = QtWidgets.QHBoxLayout()
        self.add_btn = QtWidgets.QPushButton('+ 添加主页')
        self.batch_import_btn = QtWidgets.QPushButton('批量导入')
        self.refresh_stats_btn = QtWidgets.QPushButton('刷新数据')
        self.fetch_works_btn = QtWidgets.QPushButton('提取作品')
        self.delete_btn = QtWidgets.QPushButton('删除')
        self.export_btn = QtWidgets.QPushButton('导出列表')
        self.close_btn = QtWidgets.QPushButton('关闭')

        toolbar.addWidget(self.add_btn)
        toolbar.addWidget(self.batch_import_btn)
        toolbar.addWidget(self.refresh_stats_btn)
        toolbar.addWidget(self.fetch_works_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.export_btn)
        toolbar.addWidget(self.delete_btn)
        toolbar.addWidget(self.close_btn)
        layout.addLayout(toolbar)

        # 表格
        self.user_tree = QtWidgets.QTreeWidget()
        self.user_tree.setStyle(NoFocusRectStyle())
        headers = [c[0] for c in self.COLS]
        self.user_tree.setHeaderLabels(headers)
        self.user_tree.setRootIsDecorated(False)
        self.user_tree.setUniformRowHeights(True)
        self.user_tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.user_tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.user_tree.setAttribute(QtCore.Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.user_tree.setAlternatingRowColors(True)

        fm = self.user_tree.fontMetrics()
        width0 = fm.horizontalAdvance('选择') + 16
        col_widths = [width0, 50, 70, 120, 80, 80, 80, 80, 80, 150]
        for i, w in enumerate(col_widths):
            if i < self.user_tree.columnCount():
                self.user_tree.setColumnWidth(i, w)

        header = self.user_tree.header()
        if header:
            header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Stretch)  # 作者列拉伸
            header.setSectionsMovable(False)
            header.setStretchLastSection(False)

        layout.addWidget(self.user_tree)

        # 底部状态栏
        status_bar = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel('')
        self.select_all_btn = QtWidgets.QPushButton('全选')
        status_bar.addWidget(self.status_label)
        status_bar.addStretch()
        status_bar.addWidget(self.select_all_btn)
        layout.addLayout(status_bar)

        # 信号连接
        self.add_btn.clicked.connect(self.on_add_user)
        self.batch_import_btn.clicked.connect(self.on_batch_import)
        self.refresh_stats_btn.clicked.connect(self.on_refresh_stats)
        self.fetch_works_btn.clicked.connect(self.on_fetch_checked)
        self.delete_btn.clicked.connect(self.on_delete)
        self.export_btn.clicked.connect(self.on_export)
        self.close_btn.clicked.connect(self.close)
        self.select_all_btn.clicked.connect(self.on_select_all)
        self.user_tree.itemSelectionChanged.connect(self.on_selection_changed)
        self.user_tree.itemDoubleClicked.connect(self.on_double_click_fetch)

        self.setStyleSheet("""
            QDialog { background-color: #ffffff; }
            QTreeWidget {
                background: #ffffff; border: 1px solid #e4e7ed;
                alternate-background-color: #fafbfc; gridline-color: #f2f6fc;
                selection-background-color: #d9eaff; font-size: 13px;
                show-decoration-selected: 0;
            }
            QTreeWidget::item { padding: 2px 4px; color: #222222; outline: 0; height: 28px; }
            QTreeWidget::item:focus { outline: 0; border: 0; }
            QTreeWidget::item:hover { background: #f3f8fe; }
            QTreeWidget::item:selected { background: #cfe4ff; color: #000000; }
            QTreeWidget::item:selected:active { background: #cfe4ff; outline: 0; }
            QTreeWidget::item:selected:!active { background: #cfe4ff; outline: 0; }
            QTreeWidget::indicator {
                width: 16px; height: 16px; border: 1px solid #c0c4cc;
                border-radius: 2px; background: #ffffff;
            }
            QTreeWidget::indicator:hover { border: 1px solid #409EFF; }
            QTreeWidget::indicator:checked {
                background-color: #409EFF; border: 1px solid #409EFF;
                image: url(""" + self.checkmark_svg_path + r""");
            }
            QPushButton {
                background-color: #409EFF; border: 1px solid #409EFF; color: white;
                padding: 5px 14px; border-radius: 0px; font-weight: 500; font-size: 13px;
            }
            QPushButton:hover { background-color: #66b1ff; border: 1px solid #66b1ff; }
            QPushButton:pressed { background-color: #3a8ee6; border: 1px solid #3a8ee6; }
            QLabel { color: #666666; font-size: 12px; }
        """)

        self.load_users()

    def _fmt_num(self, val):
        """格式化数字显示"""
        if val is None or val == '':
            return '-'
        try:
            n = int(val)
            if n >= 10000:
                return f'{n / 10000:.1f}万'
            return str(n)
        except (ValueError, TypeError):
            return str(val or '-')

    def load_users(self):
        """加载用户列表到表格"""
        self.user_tree.clear()
        users = cfg.get('users', [])
        updated = False

        # 标准化 URL
        for user in users:
            original_url = user.get('url', '')
            if original_url and not original_url.startswith('https://www.douyin.com/user/'):
                sec_user_id = extract_sec_user_id_from_url(original_url)
                if sec_user_id:
                    normalized_url = f"https://www.douyin.com/user/{sec_user_id}"
                    if original_url != normalized_url:
                        user['url'] = normalized_url
                        updated = True

        if updated:
            cfg['users'] = users
            save_config(cfg)

        for idx, user in enumerate(users, start=1):
            user['_idx'] = idx
            values = []
            for col_idx, (col_name, key, align) in enumerate(self.COLS):
                if col_idx == 0:  # 选择列
                    values.append(' ')
                elif key == '_idx':
                    values.append(str(idx))
                else:
                    val = user.get(key, '')
                    if key in ('following_count', 'follower_count', 'total_favorited',
                               'favoriting_count', 'aweme_count'):
                        values.append(self._fmt_num(val))
                    else:
                        values.append(str(val or ''))

            item = QtWidgets.QTreeWidgetItem(values)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setData(0, Qt.ItemDataRole.UserRole, user)
            self.user_tree.addTopLevelItem(item)

        total = len(users)
        self.status_label.setText(f'共 {total} 个主页')

    def _fetch_profile_for_sec(self, sec_user_id):
        """获取用户资料 + 最新作品发布时间，返回 (profile_dict, error_msg)

        profile_dict 为 None 表示获取失败，此时 error_msg 包含原因。
        成功时 profile_dict 包含 last_publish_time 字段。
        """
        main_window = self.parent()
        if not main_window or not hasattr(main_window, 'worker'):
            return None, '主窗口未初始化或缺少 worker'
        cookie = cfg.get('cookie', '')
        if not cookie:
            return None, '未配置 Cookie，请先在设置中粘贴 Cookie'
        session = main_window.worker.session
        referer = f'https://www.douyin.com/user/{sec_user_id}'
        session.headers.update({'Cookie': cookie, 'Referer': referer})

        from douyin_downloader.core.api import (
            get_user_profile_info, build_aweme_post_url, api_request_with_retry,
        )
        from urllib.parse import quote, urlencode

        try:
            profile, error = get_user_profile_info(session, sec_user_id)
            if not profile or error:
                return None, error or 'API 未返回有效数据'
        except Exception as e:
            return None, f'获取用户资料异常: {e}'

        # 额外请求一页作品（count=10）获取最新发布时间
        # 注：列表第一个可能是置顶作品，需取 create_time 最大值
        try:
            abogus = main_window.worker.abogus
            params, base_url = build_aweme_post_url(sec_user_id, 0, 10, True)
            a_bogus = quote(abogus.get_value(params), safe='')
            params['a_bogus'] = a_bogus
            req_url = base_url + '?' + urlencode(params)
            r = api_request_with_retry(session, req_url, max_retries=1)
            data = r.json()
            aweme_list = data.get('aweme_list', []) or []
            if aweme_list:
                timestamps = [a.get('create_time', 0) or 0 for a in aweme_list]
                max_ts = max(t for t in timestamps if t > 0) if any(t > 0 for t in timestamps) else 0
                if max_ts:
                    from datetime import datetime as dt
                    profile['last_publish_time'] = dt.fromtimestamp(max_ts).strftime('%Y-%m-%d %H:%M:%S')
                else:
                    profile['last_publish_time'] = ''
                # 抖音 API 有时返回 aweme_count=0 但实际有作品，用实际数量修正
                if not profile.get('aweme_count'):
                    profile['aweme_count'] = len(aweme_list)
            else:
                profile['last_publish_time'] = ''
        except Exception as e:
            print(f'[警告] 获取最新作品时间失败: {e}')

        return profile, None

    def on_add_user(self):
        """手动添加主页链接（添加后自动获取资料数据）"""
        url, ok = QtWidgets.QInputDialog.getText(
            self, '添加主页', '请输入抖音用户主页链接：',
            text='https://www.douyin.com/user/'
        )
        if not ok or not url.strip():
            return

        url = url.strip()
        sec_user_id = extract_sec_user_id_from_url(url)
        if not sec_user_id:
            QtWidgets.QMessageBox.warning(self, '错误', '无法从链接中提取用户ID，请检查链接是否正确。')
            return

        normalized_url = f"https://www.douyin.com/user/{sec_user_id}"

        # 检查是否已存在
        users = cfg.get('users', [])
        for u in users:
            existing_sec = extract_sec_user_id_from_url(u.get('url', ''))
            if existing_sec == sec_user_id:
                QtWidgets.QMessageBox.information(self, '提示', '该主页已在列表中。')
                return

        # 添加后立即自动获取资料
        entry = {
            'username': '', 'url': normalized_url, 'group': '',
            'sec_user_id': sec_user_id,
        }
        profile, error = self._fetch_profile_for_sec(sec_user_id)
        if profile:
            for k in ('nickname', 'following_count', 'follower_count',
                      'total_favorited', 'favoriting_count', 'aweme_count',
                      'last_publish_time'):
                if k in profile:
                    entry[k] = profile[k]
            if not entry.get('username') and profile.get('nickname'):
                entry['username'] = profile['nickname']

        users.append(entry)
        cfg['users'] = users
        save_config(cfg)
        self.load_users()

        if profile:
            self.status_label.setText(f'已添加并获取资料: {entry.get("username") or sec_user_id}')
        else:
            self.status_label.setText(f'已添加主页（未获取到资料: {error}）')

    def on_batch_import(self):
        """批量导入主页链接（每行一个链接，自动获取资料）"""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('批量导入主页')
        dialog.resize(500, 300)
        dl = QtWidgets.QVBoxLayout(dialog)
        dl.addWidget(QtWidgets.QLabel('每行粘贴一个抖音主页链接：'))
        text_edit = QtWidgets.QPlainTextEdit()
        text_edit.setPlaceholderText(
            'https://www.douyin.com/user/MS4w...\n'
            'https://www.douyin.com/user/MS4w...'
        )
        dl.addWidget(text_edit)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QtWidgets.QPushButton('导入')
        cancel_btn = QtWidgets.QPushButton('取消')
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        dl.addLayout(btn_row)
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)

        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        lines = [l.strip() for l in text_edit.toPlainText().splitlines() if l.strip()]
        if not lines:
            return

        # 解析链接并去重
        users = cfg.get('users', [])
        existing_secs = {extract_sec_user_id_from_url(u.get('url', '')) for u in users}
        new_secs = []
        for line in lines:
            sec = extract_sec_user_id_from_url(line)
            if sec and sec not in existing_secs:
                new_secs.append(sec)
                existing_secs.add(sec)

        if not new_secs:
            QtWidgets.QMessageBox.information(self, '提示', '没有新的主页需要导入（链接无效或已存在）')
            return

        # 逐个获取资料
        success = 0
        failed = 0
        for i, sec in enumerate(new_secs):
            self.status_label.setText(f'正在获取 {i + 1}/{len(new_secs)} ...')
            QtWidgets.QApplication.processEvents()

            entry = {
                'username': '', 'url': f'https://www.douyin.com/user/{sec}',
                'group': '', 'sec_user_id': sec,
            }
            profile, error = self._fetch_profile_for_sec(sec)
            if profile:
                for k in ('nickname', 'following_count', 'follower_count',
                          'total_favorited', 'favoriting_count', 'aweme_count',
                          'last_publish_time'):
                    if k in profile:
                        entry[k] = profile[k]
                if not entry.get('username') and profile.get('nickname'):
                    entry['username'] = profile['nickname']
                success += 1
            else:
                failed += 1

            users.append(entry)

        cfg['users'] = users
        save_config(cfg)
        self.load_users()
        self.status_label.setText(f'批量导入完成: 成功 {success} 个, 失败 {failed} 个')

    def on_refresh_stats(self):
        """刷新选中行的统计数据"""
        selected_items = [self.user_tree.topLevelItem(i)
                          for i in range(self.user_tree.topLevelItemCount())
                          if self.user_tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]
        if not selected_items:
            QtWidgets.QMessageBox.warning(self, '提示', '请先勾选要刷新的用户')
            return

        reply = QtWidgets.QMessageBox.question(
            self, '确认',
            f'确定要刷新 {len(selected_items)} 个用户的统计数据吗？\n需要有效的 Cookie。',
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        cookie = cfg.get('cookie', '')
        if not cookie:
            QtWidgets.QMessageBox.warning(self, '错误', '请先在设置中配置 Cookie')
            return

        refreshed = 0
        for item in selected_items:
            user = item.data(0, Qt.ItemDataRole.UserRole)
            if not user:
                continue
            sec = extract_sec_user_id_from_url(user.get('url', ''))
            if not sec:
                continue

            profile, error = self._fetch_profile_for_sec(sec)
            if profile:
                user.update(profile)
                # profile 用 'nickname'，表格显示用 'username'，需同步
                if not user.get('username') and profile.get('nickname'):
                    user['username'] = profile['nickname']
                # 更新配置中的用户记录
                users = cfg.get('users', [])
                for u in users:
                    if extract_sec_user_id_from_url(u.get('url', '')) == sec:
                        u.update(profile)
                        if not u.get('username') and profile.get('nickname'):
                            u['username'] = profile['nickname']
                        break
                save_config(cfg)
                refreshed += 1
            else:
                print(f'[警告] 刷新 {sec} 失败: {error}')

        self.load_users()
        QtWidgets.QMessageBox.information(self, '完成', f'已刷新 {refreshed} 个用户的数据')

    def on_fetch_checked(self):
        """提取勾选作者的作品 → 主窗口批量获取，作品累加到列表"""
        urls = []
        for i in range(self.user_tree.topLevelItemCount()):
            item = self.user_tree.topLevelItem(i)
            if item and item.checkState(0) == Qt.CheckState.Checked:
                user = item.data(0, Qt.ItemDataRole.UserRole)
                if user and user.get('url'):
                    urls.append(user['url'])
        if not urls:
            QtWidgets.QMessageBox.warning(self, '提示', '请先勾选要提取作品的作者')
            return

        main_window = self.parent()
        if not main_window or not hasattr(main_window, 'start_batch_fetch'):
            return
        self.status_label.setText(f'开始批量提取 {len(urls)} 个主页的作品...')
        main_window.show()
        main_window.raise_()
        main_window.start_batch_fetch(urls)

    def on_delete(self):
        """删除选中的用户"""
        selected_items = []
        for i in range(self.user_tree.topLevelItemCount()):
            item = self.user_tree.topLevelItem(i)
            if item and item.checkState(0) == Qt.CheckState.Checked:
                selected_items.append(item)

        if not selected_items:
            QtWidgets.QMessageBox.warning(self, '提示', '请先选择要删除的用户')
            return

        msg_box = QtWidgets.QMessageBox(self)
        msg_box.setWindowTitle('确认')
        msg_box.setText(f'确定要删除选中的 {len(selected_items)} 个用户吗？')
        msg_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel)
        msg_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        button_ok = msg_box.button(QtWidgets.QMessageBox.StandardButton.Ok)
        button_cancel = msg_box.button(QtWidgets.QMessageBox.StandardButton.Cancel)
        if button_ok: button_ok.setText('确认')
        if button_cancel: button_cancel.setText('取消')

        if msg_box.exec() != QtWidgets.QMessageBox.StandardButton.Ok:
            return

        users_to_remove = [item.data(0, Qt.ItemDataRole.UserRole) for item in selected_items]
        new_users = [u for u in cfg.get('users', []) if u not in users_to_remove]
        cfg['users'] = new_users
        save_config(cfg)
        self.load_users()

    def on_export(self):
        """导出用户列表为 CSV"""
        from datetime import datetime
        import csv
        import os

        users = cfg.get('users', [])
        if not users:
            QtWidgets.QMessageBox.warning(self, '提示', '没有可导出的数据')
            return

        default_name = f"主页列表_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, '导出列表', default_name, 'CSV 文件 (*.csv);;所有文件 (*)'
        )
        if not path:
            return

        fieldnames = ['序号', '分组', '作者', '关注数量', '粉丝数量', '获赞数量',
                       '喜欢数量', '作品数量', '最后发布作品时间', '主页链接']
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for idx, u in enumerate(users, start=1):
                    row = {'序号': idx, '主页链接': u.get('url', '')}
                    for fn in fieldnames[1:-1]:
                        key_map = {
                            '分组': 'group', '作者': 'username',
                            '关注数量': 'following_count', '粉丝数量': 'follower_count',
                            '获赞数量': 'total_favorited', '喜欢数量': 'favoriting_count',
                            '作品数量': 'aweme_count', '最后发布作品时间': 'last_publish_time',
                        }
                        row[fn] = u.get(key_map.get(fn, ''), '') or ''
                    writer.writerow(row)
            QtWidgets.QMessageBox.information(self, '导出成功', f'已导出到:\n{path}')
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, '导出失败', str(e))

    def on_select_all(self):
        """全选/反选"""
        has_unchecked = any(
            self.user_tree.topLevelItem(i).checkState(0) != Qt.CheckState.Checked
            for i in range(self.user_tree.topLevelItemCount())
        )
        new_state = Qt.CheckState.Checked if has_unchecked else Qt.CheckState.Unchecked
        for i in range(self.user_tree.topLevelItemCount()):
            self.user_tree.topLevelItem(i).setCheckState(0, new_state)

    def on_selection_changed(self):
        """行选中 → 同步复选框"""
        selected = self.user_tree.selectedItems()
        for i in range(self.user_tree.topLevelItemCount()):
            item = self.user_tree.topLevelItem(i)
            if item:
                item.setCheckState(0, Qt.CheckState.Checked if item in selected else Qt.CheckState.Unchecked)

    def on_double_click_fetch(self, item, column):
        """双击行 → 获取该用户作品"""
        user = item.data(0, Qt.ItemDataRole.UserRole)
        if not user:
            return
        main_window = self.parent()
        if main_window:
            if hasattr(main_window, 'url_edit'):
                url_edit = getattr(main_window, 'url_edit', None)
                if url_edit:
                    url_edit.setText(user.get('url', ''))
            if hasattr(main_window, 'on_fetch'):
                getattr(main_window, 'on_fetch')()
