# 表格仪表盘 UI 组件 — 展示所有管理表格的状态总览
import logging
import webbrowser
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QSplitter, QGroupBox,
    QMenu, QApplication
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction

logger = logging.getLogger("sheets_toolkit.ui.dashboard")


class DashboardWorker(QThread):
    """仪表盘数据加载工作线程"""
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, spreadsheet_ids):
        super().__init__()
        self.spreadsheet_ids = spreadsheet_ids

    def run(self):
        try:
            from services.sheet_service import SheetService
            results = []
            total = len(self.spreadsheet_ids)
            for i, sid in enumerate(self.spreadsheet_ids):
                sid = sid.strip()
                if not sid:
                    continue
                self.progress.emit(i, total, f"({i+1}/{total}) 获取信息...")
                try:
                    service = SheetService(sid)
                    title = service.get_spreadsheet_title()
                    meta = service.get_metadata()
                    file_info = service.get_file_info()
                    web_link = file_info.get("webViewLink", "")

                    # 收集每个工作表的详细信息
                    sheets_detail = []
                    total_rows = 0
                    for s in meta.get('sheets', []):
                        sheet_name = s['properties']['title']
                        sheet_id = s['properties']['sheetId']
                        grid = s['properties'].get('gridProperties', {})
                        grid_rows = grid.get('rowCount', 0)
                        grid_cols = grid.get('columnCount', 0)

                        # 读取实际数据行数
                        data_rows = 0
                        try:
                            data = service.read_data(sheet_name)
                            data_rows = len(data) if data else 0
                        except Exception:
                            pass

                        total_rows += data_rows

                        # 构造工作表链接（基于 spreadsheet 的 webViewLink + gid）
                        sheet_link = ""
                        if web_link:
                            # 移除尾部的 /edit... 并重新构造
                            base = web_link.split("/edit")[0]
                            sheet_link = f"{base}/edit#gid={sheet_id}"

                        sheets_detail.append({
                            "name": sheet_name,
                            "sheet_id": sheet_id,
                            "data_rows": data_rows,
                            "grid_rows": grid_rows,
                            "grid_cols": grid_cols,
                            "link": sheet_link,
                        })

                    sheet_names_str = ", ".join(
                        [s['name'] for s in sheets_detail[:5]]
                    ) + ("..." if len(sheets_detail) > 5 else "")

                    results.append({
                        "id": sid,
                        "title": title,
                        "sheet_count": len(sheets_detail),
                        "sheet_names": sheet_names_str,
                        "total_rows": total_rows,
                        "modified": file_info.get("modifiedTime", "")[:19].replace("T", " "),
                        "owner": file_info.get("owners", [{}])[0].get("emailAddress", ""),
                        "link": web_link,
                        "sheets_detail": sheets_detail,
                        "status": "success"
                    })
                except Exception as e:
                    results.append({
                        "id": sid, "title": sid[:20], "sheet_count": 0,
                        "sheet_names": "", "total_rows": 0,
                        "modified": "", "owner": "", "link": "",
                        "sheets_detail": [],
                        "status": "error", "error": str(e)
                    })
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class DashboardWidget(QWidget):
    """表格仪表盘面板"""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._worker = None
        self._results = []  # 缓存结果用于详情展示
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        title = QLabel("📋 表格仪表盘")
        title.setObjectName("section_title")
        layout.addWidget(title)

        help_label = QLabel(
            "输入多个表格链接，一览所有表格的标题、工作表数、数据量、修改时间等信息。\n"
            "💡 点击表格行可在下方查看该工作簿的所有工作表详情。"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        layout.addWidget(QLabel("📄 表格链接/ID（每行一个）："))
        self.ids_input = ClearableTextEdit()
        self.ids_input.setPlaceholderText("输入链接或 ID")
        self.ids_input.setMaximumHeight(80)
        layout.addWidget(self.ids_input)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("🔄 刷新仪表盘")
        self.start_btn.clicked.connect(self.refresh)
        btn_row.addWidget(self.start_btn)
        layout.addLayout(btn_row)

        # 汇总统计
        self.summary_label = QLabel("")
        layout.addWidget(self.summary_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # ======== 上下分割：主表格 + 工作表详情 ========
        splitter = QSplitter(Qt.Vertical)

        # --- 上半部分：工作簿概览表格 ---
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "标题", "工作表", "数据行", "修改时间", "所有者", "状态", "ID"
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(3, 140)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setColumnWidth(5, 50)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.currentCellChanged.connect(self._on_row_selected)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_main_table_context_menu)
        splitter.addWidget(self.table)

        # --- 下半部分：工作表详情面板 ---
        detail_group = QGroupBox("📑 工作表详情")
        detail_layout = QVBoxLayout(detail_group)
        detail_layout.setSpacing(4)

        self.detail_title_label = QLabel("请在上方选择一个工作簿以查看其工作表列表")
        self.detail_title_label.setStyleSheet("color: gray; font-style: italic;")
        detail_layout.addWidget(self.detail_title_label)

        # 打开工作簿链接按钮
        self.open_link_btn = QPushButton("🔗 在浏览器中打开工作簿")
        self.open_link_btn.setVisible(False)
        self.open_link_btn.clicked.connect(self._open_spreadsheet_link)
        detail_layout.addWidget(self.open_link_btn)

        # 工作表详情表格
        self.detail_table = QTableWidget()
        self.detail_table.setColumnCount(5)
        self.detail_table.setHorizontalHeaderLabels([
            "工作表名称", "数据行数", "网格行数", "网格列数", "操作"
        ])
        self.detail_table.setAlternatingRowColors(True)
        self.detail_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.detail_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.detail_table.setColumnWidth(1, 80)
        self.detail_table.setColumnWidth(2, 80)
        self.detail_table.setColumnWidth(3, 80)
        self.detail_table.setColumnWidth(4, 150)
        self.detail_table.verticalHeader().setDefaultSectionSize(30)
        self.detail_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.detail_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.detail_table.customContextMenuRequested.connect(self._on_detail_context_menu)
        detail_layout.addWidget(self.detail_table)

        # 工作表汇总
        self.detail_summary_label = QLabel("")
        detail_layout.addWidget(self.detail_summary_label)

        splitter.addWidget(detail_group)

        # 设置分割比例（上方 3 : 下方 2）
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)

    # ======== 当前选中工作簿的链接（用于浏览器打开） ========
    _current_link = ""

    def _open_spreadsheet_link(self):
        """在浏览器中打开当前选中的工作簿链接"""
        if self._current_link:
            webbrowser.open(self._current_link)

    def _get_ids(self):
        from ui.batch_backup_widget import extract_spreadsheet_id
        text = self.ids_input.toPlainText().strip()
        if text:
            return [extract_spreadsheet_id(l.strip()) for l in text.split('\n')
                    if extract_spreadsheet_id(l.strip())]
        elif self.controller and self.controller.service:
            return [self.controller.service.spreadsheet_id]
        return []

    def refresh(self):
        ids = self._get_ids()
        if not ids:
            self.status_label.setText("⚠️ 请输入表格 ID")
            return

        self.start_btn.setEnabled(False)
        self.start_btn.setText("⏳ 加载中...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(ids))
        self.table.setRowCount(0)
        self.detail_table.setRowCount(0)
        self.detail_title_label.setText("正在加载数据...")
        self.detail_title_label.setStyleSheet("color: gray; font-style: italic;")
        self.open_link_btn.setVisible(False)

        self._worker = DashboardWorker(ids)
        self._worker.progress.connect(lambda c, t, m: (
            self.progress_bar.setValue(c), self.status_label.setText(m)))
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, results):
        self._results = results  # 缓存结果
        self.progress_bar.setVisible(False)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(results))

        total_sheets = 0
        total_rows = 0
        ok_count = 0

        for i, r in enumerate(results):
            self.table.setItem(i, 0, QTableWidgetItem(r.get("title", "—")))

            sc = QTableWidgetItem()
            sc.setData(Qt.DisplayRole, r.get("sheet_count", 0))
            self.table.setItem(i, 1, sc)

            rc = QTableWidgetItem()
            rc.setData(Qt.DisplayRole, r.get("total_rows", 0))
            self.table.setItem(i, 2, rc)

            self.table.setItem(i, 3, QTableWidgetItem(r.get("modified", "—")))
            self.table.setItem(i, 4, QTableWidgetItem(r.get("owner", "—")))

            status = "✅" if r["status"] == "success" else "❌"
            item = QTableWidgetItem(status)
            if r["status"] == "error":
                item.setToolTip(r.get("error", ""))
            self.table.setItem(i, 5, item)
            self.table.setItem(i, 6, QTableWidgetItem(r.get("id", "")[:25]))

            if r["status"] == "success":
                ok_count += 1
                total_sheets += r.get("sheet_count", 0)
                total_rows += r.get("total_rows", 0)

        self.table.setSortingEnabled(True)

        self.summary_label.setText(
            f"📊 汇总: {ok_count} 个表格 | "
            f"{total_sheets} 个工作表 | "
            f"{total_rows:,} 行数据"
        )
        self.status_label.setText(f"✅ 加载完成")
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🔄 刷新仪表盘")
        self._worker = None

        # 默认选中第一行并展示详情
        if results:
            self.table.selectRow(0)
            self._show_sheet_detail(0)

    def _on_error(self, msg):
        self.status_label.setText(f"❌ {msg}")
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🔄 刷新仪表盘")
        self.progress_bar.setVisible(False)
        self._worker = None

    def _on_row_selected(self, row, col, prev_row, prev_col):
        """主表格选中行变化时，展示对应工作簿的工作表详情"""
        if row >= 0 and row < len(self._results):
            self._show_sheet_detail(row)

    def _show_sheet_detail(self, row_index):
        """展示指定工作簿的工作表详情"""
        if row_index < 0 or row_index >= len(self._results):
            return

        r = self._results[row_index]
        title = r.get("title", "未知")
        link = r.get("link", "")
        sheets = r.get("sheets_detail", [])

        # 更新标题
        self.detail_title_label.setText(
            f"📊 {title}  —  共 {len(sheets)} 个工作表，{r.get('total_rows', 0):,} 行数据"
        )
        self.detail_title_label.setStyleSheet(
            "font-weight: bold; font-size: 13px; padding: 4px 0;"
        )

        # 更新打开链接按钮
        self._current_link = link
        if link:
            self.open_link_btn.setVisible(True)
            self.open_link_btn.setText(f"🔗 在浏览器中打开: {title}")
        else:
            self.open_link_btn.setVisible(False)

        # 填充工作表详情表格
        self.detail_table.setRowCount(len(sheets))

        total_data_rows = 0
        for i, s in enumerate(sheets):
            # 工作表名称
            name_item = QTableWidgetItem(f"📄 {s['name']}")
            name_item.setToolTip(s.get("link", ""))
            self.detail_table.setItem(i, 0, name_item)

            # 数据行数
            dr_item = QTableWidgetItem()
            dr_item.setData(Qt.DisplayRole, s.get("data_rows", 0))
            self.detail_table.setItem(i, 1, dr_item)

            # 网格行数
            gr_item = QTableWidgetItem()
            gr_item.setData(Qt.DisplayRole, s.get("grid_rows", 0))
            self.detail_table.setItem(i, 2, gr_item)

            # 网格列数
            gc_item = QTableWidgetItem()
            gc_item.setData(Qt.DisplayRole, s.get("grid_cols", 0))
            self.detail_table.setItem(i, 3, gc_item)

            # 操作按钮：打开链接
            sheet_link = s.get("link", "")
            if sheet_link:
                open_btn = QPushButton("🔗 打开")
                open_btn.setToolTip(f"在浏览器中打开: {s['name']}")
                # 使用闭包捕获 sheet_link
                open_btn.clicked.connect(
                    lambda checked, url=sheet_link: webbrowser.open(url)
                )
                self.detail_table.setCellWidget(i, 4, open_btn)
            else:
                self.detail_table.setItem(i, 4, QTableWidgetItem("—"))

            total_data_rows += s.get("data_rows", 0)

        # 详情汇总
        self.detail_summary_label.setText(
            f"📋 汇总: {len(sheets)} 个工作表 | "
            f"总数据行: {total_data_rows:,}"
        )

    # ======== 右键菜单 ========

    def _copy_to_clipboard(self, text):
        """复制文本到剪贴板"""
        QApplication.clipboard().setText(text)

    def _on_main_table_context_menu(self, pos):
        """主表格右键菜单 — 复制标题、ID、链接等"""
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self._results):
            return

        r = self._results[row]
        menu = QMenu(self)

        # 复制标题
        title_text = r.get("title", "")
        if title_text:
            act = QAction(f"📋 复制标题: {title_text[:30]}", self)
            act.triggered.connect(lambda: self._copy_to_clipboard(title_text))
            menu.addAction(act)

        # 复制 ID
        sid = r.get("id", "")
        if sid:
            act = QAction(f"🔑 复制 ID: {sid[:25]}...", self)
            act.triggered.connect(lambda: self._copy_to_clipboard(sid))
            menu.addAction(act)

        # 复制链接
        link = r.get("link", "")
        if link:
            act = QAction("🔗 复制工作簿链接", self)
            act.triggered.connect(lambda: self._copy_to_clipboard(link))
            menu.addAction(act)

            menu.addSeparator()
            act = QAction("🌐 在浏览器中打开", self)
            act.triggered.connect(lambda: webbrowser.open(link))
            menu.addAction(act)

        # 复制所有者邮箱
        owner = r.get("owner", "")
        if owner:
            menu.addSeparator()
            act = QAction(f"👤 复制所有者: {owner}", self)
            act.triggered.connect(lambda: self._copy_to_clipboard(owner))
            menu.addAction(act)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _on_detail_context_menu(self, pos):
        """工作表详情表格右键菜单 — 复制表名、链接等"""
        row = self.detail_table.rowAt(pos.y())
        if row < 0:
            return

        # 从当前选中的主表格行获取 sheets_detail
        main_row = self.table.currentRow()
        if main_row < 0 or main_row >= len(self._results):
            return

        sheets = self._results[main_row].get("sheets_detail", [])
        if row >= len(sheets):
            return

        s = sheets[row]
        menu = QMenu(self)

        # 复制工作表名称
        name = s.get("name", "")
        if name:
            act = QAction(f"📋 复制表名: {name}", self)
            act.triggered.connect(lambda: self._copy_to_clipboard(name))
            menu.addAction(act)

        # 复制工作表链接
        link = s.get("link", "")
        if link:
            act = QAction("🔗 复制工作表链接", self)
            act.triggered.connect(lambda: self._copy_to_clipboard(link))
            menu.addAction(act)

            menu.addSeparator()
            act = QAction("🌐 在浏览器中打开", self)
            act.triggered.connect(lambda: webbrowser.open(link))
            menu.addAction(act)

        # 复制 Sheet ID
        sheet_id = s.get("sheet_id", "")
        if sheet_id is not None:
            menu.addSeparator()
            act = QAction(f"🔑 复制 Sheet ID: {sheet_id}", self)
            act.triggered.connect(lambda: self._copy_to_clipboard(str(sheet_id)))
            menu.addAction(act)

        # 复制行数信息
        menu.addSeparator()
        info = f"{name}: {s.get('data_rows', 0)} 行数据"
        act = QAction(f"📊 复制行数信息", self)
        act.triggered.connect(lambda: self._copy_to_clipboard(info))
        menu.addAction(act)

        menu.exec(self.detail_table.viewport().mapToGlobal(pos))
