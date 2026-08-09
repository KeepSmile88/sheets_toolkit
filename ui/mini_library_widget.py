# 表格库迷你浮动窗口 — 置顶显示，多账号切换 + 快速搜索 + 分组筛选 + 一键打开/连接
import logging
import webbrowser
import re
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QListWidget, QListWidgetItem,
    QToolButton, QApplication, QMenu, QScrollArea, QSizePolicy,
    QComboBox
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction

from services.spreadsheet_library import AccountManager
from ui.flow_layout import FlowLayout

logger = logging.getLogger("sheets_toolkit.ui.mini_library")


class MiniLibraryWindow(QWidget):
    """
    表格库迷你浮动窗口 — 始终置顶，紧凑布局。
    功能：分组快速筛选、搜索、一键在浏览器打开、一键连接表格。
    跟随主窗口主题（不硬编码样式），仅对迷你窗口特有元素设置少量样式。
    """

    # 当用户选择连接某个表格时发出此信号
    connect_requested = Signal(str, str)  # (spreadsheet_id_or_link, name)

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.account_mgr = AccountManager()
        self.library = self.account_mgr.get_active_library()
        self._all_entries = []
        self._current_group = "__all__"  # 当前选中的分组 ID
        self._group_buttons = []  # 分组按钮引用

        # 搜索防抖
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._do_search)

        self._setup_window()
        self._setup_ui()
        self._refresh()

    def _setup_window(self):
        """配置窗口属性：置顶 + 工具窗口"""
        self.setWindowTitle("📂 表格库（迷你）")
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowStaysOnTopHint
            | Qt.Tool  # 工具窗口不占任务栏
        )
        self.setMinimumSize(260, 180)
        self.resize(300, 400)

        # 紧凑样式 — 覆盖主题中过大的按钮/列表项尺寸
        self.setStyleSheet("""
            MiniLibraryWindow QLabel {
                font-size: 12px;
            }
            MiniLibraryWindow #mini_title {
                font-size: 13px;
                font-weight: bold;
            }
            MiniLibraryWindow QComboBox {
                padding: 2px 4px;
                font-size: 11px;
                min-height: 0px;
                max-height: 20px;
            }
            MiniLibraryWindow QComboBox::drop-down {
                width: 18px;
            }
            MiniLibraryWindow QLineEdit {
                padding: 3px 6px;
                font-size: 12px;
                min-height: 0px;
            }
            MiniLibraryWindow QPushButton {
                padding: 2px 8px;
                font-size: 11px;
                min-height: 20px;
            }
            MiniLibraryWindow QToolButton {
                padding: 1px;
                min-height: 0px;
            }
            MiniLibraryWindow #group_btn {
                padding: 1px 6px;
                min-height: 18px;
                border-radius: 9px;
                font-size: 11px;
            }
            MiniLibraryWindow #group_btn:checked {
                font-weight: bold;
            }
            MiniLibraryWindow QListWidget {
                font-size: 12px;
            }
            MiniLibraryWindow QListWidget::item {
                padding: 3px 6px;
                margin: 0px;
            }
            MiniLibraryWindow #count_label {
                font-size: 10px;
                font-style: italic;
            }
        """)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(3)

        # ======== 标题栏 ========
        title_row = QHBoxLayout()
        title_row.setSpacing(3)
        title_label = QLabel("📂")
        title_label.setObjectName("mini_title")
        title_row.addWidget(title_label)

        # 账号下拉选择
        self._account_combo = QComboBox()
        self._account_combo.setToolTip("切换账号")
        self._account_combo.setFixedHeight(22)
        self._account_combo.currentIndexChanged.connect(
            self._on_account_changed)
        title_row.addWidget(self._account_combo, 1)

        # 刷新按钮
        refresh_btn = QToolButton()
        refresh_btn.setText("🔄")
        refresh_btn.setToolTip("刷新列表")
        refresh_btn.setFixedSize(22, 22)
        refresh_btn.clicked.connect(self._refresh)
        title_row.addWidget(refresh_btn)

        # 置顶切换按钮
        self._pin_btn = QToolButton()
        self._pin_btn.setText("📌")
        self._pin_btn.setToolTip("取消置顶")
        self._pin_btn.setFixedSize(22, 22)
        self._pin_btn.setCheckable(True)
        self._pin_btn.setChecked(True)
        self._pin_btn.clicked.connect(self._toggle_pin)
        title_row.addWidget(self._pin_btn)

        layout.addLayout(title_row)

        # ======== 搜索栏 ========
        search_layout = QHBoxLayout()
        search_layout.setSpacing(3)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索表格...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self.search_input, 1)

        self._regex_btn = QToolButton()
        self._regex_btn.setText(".*")
        self._regex_btn.setToolTip("正则搜索")
        self._regex_btn.setCheckable(True)
        self._regex_btn.setFixedSize(22, 22)
        self._regex_btn.clicked.connect(self._do_search)
        search_layout.addWidget(self._regex_btn)

        layout.addLayout(search_layout)

        # ======== 分组 FlowLayout（在 QScrollArea 中） ========
        self._group_container = QWidget()
        self._group_flow = FlowLayout(
            self._group_container, margin=2, h_spacing=4, v_spacing=4
        )

        self._group_scroll = QScrollArea()
        self._group_scroll.setWidgetResizable(True)
        self._group_scroll.setWidget(self._group_container)
        self._group_scroll.setMaximumHeight(56)
        self._group_scroll.setMinimumHeight(24)
        self._group_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self._group_scroll)

        # ======== 筛选状态 ========
        filter_row = QHBoxLayout()
        self._filter_star_btn = QPushButton("⭐ 仅星标")
        self._filter_star_btn.setObjectName("group_btn")
        self._filter_star_btn.setCheckable(True)
        self._filter_star_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._filter_star_btn.clicked.connect(self._apply_filter)
        filter_row.addWidget(self._filter_star_btn)

        filter_row.addStretch()

        self._count_label = QLabel("")
        self._count_label.setObjectName("count_label")
        filter_row.addWidget(self._count_label)
        layout.addLayout(filter_row)

        # ======== 列表 ========
        self.list_widget = QListWidget()
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_click)
        layout.addWidget(self.list_widget)

        # ======== 底部按钮 ========
        btn_row = QHBoxLayout()
        btn_row.setSpacing(3)

        open_btn = QPushButton("🌐 打开")
        open_btn.setToolTip("在浏览器中打开选中的表格")
        open_btn.clicked.connect(self._open_in_browser)
        btn_row.addWidget(open_btn)

        connect_btn = QPushButton("🔗 连接")
        connect_btn.setToolTip("在工具箱中连接选中的表格")
        connect_btn.clicked.connect(self._connect_selected)
        btn_row.addWidget(connect_btn)

        copy_btn = QPushButton("📋 复制")
        copy_btn.setToolTip("复制表格链接到剪贴板")
        copy_btn.clicked.connect(self._copy_link)
        btn_row.addWidget(copy_btn)

        layout.addLayout(btn_row)

    # ======== 窗口控制 ========

    def _toggle_pin(self):
        """切换置顶状态"""
        if self._pin_btn.isChecked():
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self._pin_btn.setText("📌")
            self._pin_btn.setToolTip("取消置顶")
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
            self._pin_btn.setText("📍")
            self._pin_btn.setToolTip("置顶窗口")
        self.show()  # 修改 flags 后需重新 show

    # ======== 数据刷新 ========

    def _refresh(self):
        """重新加载表格库数据并刷新分组按钮和账号列表"""
        self.account_mgr = AccountManager()
        self._refresh_account_combo()
        self.library = self.account_mgr.get_active_library()
        if self.library:
            self._all_entries = self.library.entries
        else:
            self._all_entries = []
        self._rebuild_group_buttons()
        self._apply_filter()

    def _refresh_account_combo(self):
        """刷新账号下拉框"""
        self._account_combo.blockSignals(True)
        self._account_combo.clear()
        for acc in self.account_mgr.accounts:
            self._account_combo.addItem(acc["name"], acc["id"])
        idx = self.account_mgr.active_index
        if 0 <= idx < self._account_combo.count():
            self._account_combo.setCurrentIndex(idx)
        self._account_combo.blockSignals(False)

    def _on_account_changed(self, idx):
        """切换账号"""
        if idx < 0:
            return
        self.account_mgr.active_index = idx
        self.library = self.account_mgr.get_active_library()
        if self.library:
            self._all_entries = self.library.entries
        else:
            self._all_entries = []
        self._current_group = "__all__"
        self._rebuild_group_buttons()
        self._apply_filter()

    def _rebuild_group_buttons(self):
        """用 FlowLayout 动态生成分组按钮"""
        # 清除旧按钮
        self._group_flow.clear_widgets()
        self._group_buttons.clear()

        # "全部" 按钮
        all_btn = QPushButton("📁 全部")
        all_btn.setObjectName("group_btn")
        all_btn.setCheckable(True)
        all_btn.setChecked(self._current_group == "__all__")
        all_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        all_btn.clicked.connect(lambda: self._select_group("__all__"))
        self._group_flow.addWidget(all_btn)
        self._group_buttons.append(("__all__", all_btn))

        # 各分组按钮
        for gid, g in sorted(
            self.library.groups.items(),
            key=lambda x: x[1].get("name", "")
        ):
            name = g.get("name", gid)
            # 取最后一级名称用于显示（层级分组用 -> 分隔）
            short_name = name.split("->")[-1].strip()
            count = len(self.library.get_entries_by_group(gid))

            btn = QPushButton(f"{short_name} ({count})")
            btn.setObjectName("group_btn")
            btn.setCheckable(True)
            btn.setChecked(gid == self._current_group)
            btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            btn.setToolTip(name)  # 完整路径作为 tooltip
            btn.clicked.connect(lambda checked, g=gid: self._select_group(g))
            self._group_flow.addWidget(btn)
            self._group_buttons.append((gid, btn))

        self._group_container.adjustSize()

    def _select_group(self, gid):
        """选中某个分组"""
        self._current_group = gid

        # 更新按钮选中态
        for btn_gid, btn in self._group_buttons:
            btn.setChecked(btn_gid == gid)

        self._apply_filter()

    def _apply_filter(self):
        """根据当前分组、星标筛选和搜索关键词填充列表"""
        keyword = self.search_input.text().strip()
        keyword_lower = keyword.lower()
        only_star = self._filter_star_btn.isChecked()

        entries = self._all_entries

        # 分组筛选
        if self._current_group != "__all__":
            entries = [
                e for e in entries
                if e.get("group_id", "default") == self._current_group
            ]

        # 星标筛选
        if only_star:
            entries = [e for e in entries if e.get("is_starred", False)]

        # 搜索过滤
        if keyword:
            filtered = []
            is_regex = self._regex_btn.isChecked()
            pattern = None
            if is_regex:
                try:
                    pattern = re.compile(keyword, re.IGNORECASE)
                except re.error:
                    pass

            for e in entries:
                if pattern:
                    name = e.get("name", "")
                    notes = e.get("notes", "")
                    link = e.get("link", "")
                    tags = " ".join(e.get("tags", []))
                    if (pattern.search(name) or pattern.search(notes)
                            or pattern.search(link) or pattern.search(tags)):
                        filtered.append(e)
                else:
                    name = e.get("name", "").lower()
                    notes = e.get("notes", "").lower()
                    link = e.get("link", "").lower()
                    tags = " ".join(e.get("tags", [])).lower()
                    if (keyword_lower in name or keyword_lower in notes
                            or keyword_lower in link or keyword_lower in tags):
                        filtered.append(e)
            entries = filtered

        # 排序：星标置顶
        entries = sorted(entries, key=lambda x: (
            not x.get("is_starred", False),
            x.get("name", "")
        ))

        # 填充列表
        self.list_widget.clear()
        for e in entries:
            star = "⭐ " if e.get("is_starred", False) else ""
            group_name = self.library.get_group_name(e.get("group_id", "default"))
            # 只在"全部"模式下显示分组标签
            if self._current_group == "__all__":
                display = f"{star}{e.get('name', '未命名')}  [{group_name}]"
            else:
                display = f"{star}{e.get('name', '未命名')}"

            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, e)  # 存储完整条目
            item.setToolTip(
                f"名称: {e.get('name', '')}\n"
                f"分组: {group_name}\n"
                f"备注: {e.get('notes', '')}\n"
                f"链接: {e.get('link', '')}"
            )
            self.list_widget.addItem(item)

        self._count_label.setText(f"{len(entries)} 条")

    # ======== 搜索 ========

    def _on_search_changed(self, text):
        self._search_timer.start()

    def _do_search(self):
        self._apply_filter()

    # ======== 条目操作 ========

    def _get_selected_entry(self):
        """获取当前选中条目"""
        item = self.list_widget.currentItem()
        if item:
            return item.data(Qt.UserRole)
        return None

    def _on_item_double_click(self, item):
        """双击打开浏览器"""
        entry = item.data(Qt.UserRole)
        if entry:
            self._open_entry(entry)

    def _open_in_browser(self):
        entry = self._get_selected_entry()
        if entry:
            self._open_entry(entry)

    def _open_entry(self, entry):
        """在浏览器中打开"""
        link = entry.get("link", "")
        sid = entry.get("spreadsheet_id", "")
        if link and link.startswith("http"):
            webbrowser.open(link)
        elif sid:
            webbrowser.open(
                f"https://docs.google.com/spreadsheets/d/{sid}/edit")

    def _connect_selected(self):
        """连接到工具箱"""
        entry = self._get_selected_entry()
        if not entry:
            return

        link = entry.get("link", "") or entry.get("spreadsheet_id", "")
        name = entry.get("name", "")

        if link and self.controller and self.controller.view:
            self.controller.view.input_id.setText(link)
            self.controller.view.connect_sheet()
            self.connect_requested.emit(link, name)

    def _copy_link(self):
        """复制链接到剪贴板"""
        entry = self._get_selected_entry()
        if not entry:
            return

        link = entry.get("link", "")
        sid = entry.get("spreadsheet_id", "")
        text = link if link else (
            f"https://docs.google.com/spreadsheets/d/{sid}/edit" if sid else ""
        )
        if text:
            QApplication.clipboard().setText(text)

    def _show_context_menu(self, pos):
        """右键菜单"""
        entry = self._get_selected_entry()
        if not entry:
            return

        menu = QMenu(self)
        name = entry.get("name", "")

        open_act = QAction(f"🌐 在浏览器中打开: {name[:25]}", self)
        open_act.triggered.connect(lambda: self._open_entry(entry))
        menu.addAction(open_act)

        connect_act = QAction("🔗 连接到工具箱", self)
        connect_act.triggered.connect(self._connect_selected)
        menu.addAction(connect_act)

        menu.addSeparator()

        copy_link_act = QAction("📋 复制链接", self)
        copy_link_act.triggered.connect(self._copy_link)
        menu.addAction(copy_link_act)

        copy_name_act = QAction(f"📋 复制名称: {name[:25]}", self)
        copy_name_act.triggered.connect(
            lambda: QApplication.clipboard().setText(name))
        menu.addAction(copy_name_act)

        sid = entry.get("spreadsheet_id", "")
        if sid:
            menu.addSeparator()
            copy_id_act = QAction(f"🔑 复制 ID: {sid[:20]}...", self)
            copy_id_act.triggered.connect(
                lambda: QApplication.clipboard().setText(sid))
            menu.addAction(copy_id_act)

        menu.exec(self.list_widget.viewport().mapToGlobal(pos))
