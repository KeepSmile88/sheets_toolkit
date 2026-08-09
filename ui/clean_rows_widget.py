# 批量清理行 UI 组件 — 支持多工作表选择、预览、批量清理
import logging
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QDateEdit,
    QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QSplitter,
    QGroupBox, QMessageBox, QScrollArea, QSizePolicy
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import Qt, QDate, QThread, Signal

from ui.flow_layout import FlowLayout

logger = logging.getLogger("sheets_toolkit.ui.clean_rows")


class SheetListLoader(QThread):
    """加载工作表名称列表的后台线程"""
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, spreadsheet_id):
        super().__init__()
        self.spreadsheet_id = spreadsheet_id

    def run(self):
        try:
            from services.sheet_service import SheetService
            service = SheetService(self.spreadsheet_id)
            sheets = service.list_sheets()
            self.finished.emit(sheets)
        except Exception as e:
            self.error.emit(str(e))


class PreviewWorker(QThread):
    """预览扫描工作线程 — 只读不删除"""
    progress = Signal(str)
    finished = Signal(list)  # list[dict] 每个工作表的预览结果
    error = Signal(str)

    def __init__(self, spreadsheet_ids, sheet_names, date_column,
                 cutoff_date, skip_header=True):
        super().__init__()
        self.spreadsheet_ids = spreadsheet_ids
        self.sheet_names = sheet_names
        self.date_column = date_column
        self.cutoff_date = cutoff_date
        self.skip_header = skip_header

    def run(self):
        try:
            from services.sheet_service import SheetService
            all_previews = []
            total_sheets = len(self.spreadsheet_ids) * len(self.sheet_names)
            count = 0

            for sid in self.spreadsheet_ids:
                sid = sid.strip()
                if not sid:
                    continue
                try:
                    service = SheetService(sid)
                    title = service.get_spreadsheet_title()

                    for sn in self.sheet_names:
                        count += 1
                        self.progress.emit(
                            f"🔍 ({count}/{total_sheets}) 扫描: {title} / {sn}"
                        )
                        try:
                            preview = service.preview_rows_to_delete(
                                sn, self.date_column, self.cutoff_date,
                                self.skip_header,
                                progress_callback=lambda m: self.progress.emit(m)
                            )
                            preview["spreadsheet_id"] = sid
                            preview["spreadsheet_title"] = title
                            all_previews.append(preview)
                        except Exception as e:
                            all_previews.append({
                                "spreadsheet_id": sid,
                                "spreadsheet_title": title,
                                "sheet_name": sn,
                                "total_rows": 0,
                                "rows_to_delete": [],
                                "deleted_by_date": 0,
                                "deleted_empty": 0,
                                "total_to_delete": 0,
                                "header": [],
                                "error": str(e)
                            })
                except Exception as e:
                    self.progress.emit(f"❌ {sid[:20]}... 连接失败: {e}")
                    for sn in self.sheet_names:
                        all_previews.append({
                            "spreadsheet_id": sid,
                            "spreadsheet_title": sid[:20],
                            "sheet_name": sn,
                            "total_rows": 0, "rows_to_delete": [],
                            "deleted_by_date": 0, "deleted_empty": 0,
                            "total_to_delete": 0, "header": [],
                            "error": str(e)
                        })
            self.finished.emit(all_previews)
        except Exception as e:
            self.error.emit(str(e))


class CleanRowsWorker(QThread):
    """行清理工作线程 — 支持多工作表"""
    progress = Signal(str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, spreadsheet_ids, sheet_names, date_column,
                 cutoff_date, skip_header=True):
        super().__init__()
        self.spreadsheet_ids = spreadsheet_ids
        self.sheet_names = sheet_names
        self.date_column = date_column
        self.cutoff_date = cutoff_date
        self.skip_header = skip_header

    def run(self):
        try:
            from services.sheet_service import SheetService
            results = []
            total = len(self.spreadsheet_ids) * len(self.sheet_names)
            count = 0

            for sid in self.spreadsheet_ids:
                sid = sid.strip()
                if not sid:
                    continue
                try:
                    service = SheetService(sid)
                    title = service.get_spreadsheet_title()

                    for sn in self.sheet_names:
                        count += 1
                        self.progress.emit(
                            f"📋 ({count}/{total}) 清理: {title} / {sn}"
                        )
                        try:
                            result = service.delete_rows_by_date_and_empty(
                                sn, self.date_column, self.cutoff_date,
                                self.skip_header,
                                progress_callback=lambda m: self.progress.emit(m)
                            )
                            results.append({
                                "id": sid, "title": title,
                                "sheet_name": sn,
                                "deleted_by_date": result["deleted_by_date"],
                                "deleted_empty": result["deleted_empty"],
                                "total": result["total_deleted"],
                                "status": "success"
                            })
                        except Exception as e:
                            results.append({
                                "id": sid, "title": title,
                                "sheet_name": sn,
                                "deleted_by_date": 0, "deleted_empty": 0,
                                "total": 0,
                                "status": "error", "error": str(e)
                            })
                            self.progress.emit(f"❌ {title}/{sn} 失败: {e}")
                except Exception as e:
                    for sn in self.sheet_names:
                        results.append({
                            "id": sid, "title": sid[:20],
                            "sheet_name": sn,
                            "deleted_by_date": 0, "deleted_empty": 0,
                            "total": 0,
                            "status": "error", "error": str(e)
                        })
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class CleanRowsWidget(QWidget):
    """批量清理行面板 — 支持多工作表选择、预览确认、批量执行"""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._worker = None
        self._preview_worker = None
        self._sheet_loader = None
        self._preview_data = []  # 缓存预览结果
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 标题
        title = QLabel("🧹 批量清理行")
        title.setObjectName("section_title")
        layout.addWidget(title)

        help_label = QLabel(
            "删除指定工作表中日期早于截止日期的行和空白行。\n"
            "支持多个表格和多个工作表同时清理，清理前可预览待删除行。"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        # ======== 表格 ID 输入 ========
        layout.addWidget(QLabel("📄 表格 ID / 链接（每行一个）："))
        self.ids_input = ClearableTextEdit()
        self.ids_input.setPlaceholderText(
            "输入 Google Sheets ID 或链接，每行一个\n"
            "如不输入，将使用侧边栏中当前连接的表格"
        )
        self.ids_input.setMaximumHeight(80)
        layout.addWidget(self.ids_input)

        # ======== 工作表选择区域 ========
        sheet_group = QGroupBox("📋 工作表选择")
        sheet_group_layout = QVBoxLayout(sheet_group)

        # 刷新按钮行
        refresh_row = QHBoxLayout()
        self.refresh_sheets_btn = QPushButton("🔄 读取工作表列表")
        self.refresh_sheets_btn.clicked.connect(self.load_sheet_names)
        refresh_row.addWidget(self.refresh_sheets_btn)

        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.setMaximumWidth(60)
        self.select_all_btn.clicked.connect(self._select_all_sheets)
        refresh_row.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("取消全选")
        self.deselect_all_btn.setMaximumWidth(80)
        self.deselect_all_btn.clicked.connect(self._deselect_all_sheets)
        refresh_row.addWidget(self.deselect_all_btn)

        refresh_row.addStretch()  # 防止按钮被拉伸占满整行
        sheet_group_layout.addLayout(refresh_row)

        # 工作表 Checkbox 流式布局（放在 QScrollArea 中）
        self._sheet_checkboxes = []  # 存储所有 checkbox 引用
        self._sheet_flow_container = QWidget()
        self._sheet_flow_layout = FlowLayout(self._sheet_flow_container, margin=6, h_spacing=12, v_spacing=6)

        self._sheet_scroll = QScrollArea()
        self._sheet_scroll.setWidgetResizable(True)
        self._sheet_scroll.setWidget(self._sheet_flow_container)
        self._sheet_scroll.setMaximumHeight(110)
        self._sheet_scroll.setMinimumHeight(40)
        self._sheet_scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #ccc; border-radius: 4px; }"
        )
        sheet_group_layout.addWidget(self._sheet_scroll)

        self.sheet_status_label = QLabel("💡 点击「读取工作表列表」自动获取工作表名")
        self.sheet_status_label.setStyleSheet("color: gray; font-style: italic;")
        sheet_group_layout.addWidget(self.sheet_status_label)

        layout.addWidget(sheet_group)

        # ======== 参数行 ========
        params = QHBoxLayout()

        params.addWidget(QLabel("📅 日期列："))
        self.col_input = QLineEdit("A")
        self.col_input.setPlaceholderText("A")
        self.col_input.setMaximumWidth(60)
        params.addWidget(self.col_input)

        params.addWidget(QLabel("📆 截止日期："))
        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setDisplayFormat("yyyy-MM-dd")
        params.addWidget(self.date_input)

        params.addStretch()
        layout.addLayout(params)

        # 选项行
        options = QHBoxLayout()
        self.skip_header_cb = QCheckBox("跳过表头（第一行）")
        self.skip_header_cb.setChecked(True)
        options.addWidget(self.skip_header_cb)
        options.addStretch()
        layout.addLayout(options)

        # ======== 按钮行 ========
        btn_row = QHBoxLayout()

        self.preview_btn = QPushButton("👁 预览待删除行")
        self.preview_btn.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; "
            "padding: 2px 12px; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1976D2; }"
        )
        self.preview_btn.clicked.connect(self.start_preview)
        btn_row.addWidget(self.preview_btn)

        self.start_btn = QPushButton("🚀 执行清理")
        self.start_btn.setEnabled(False)
        self.start_btn.setToolTip("请先预览确认后再执行清理")
        btn_row.addWidget(self.start_btn)
        self.start_btn.clicked.connect(self.start_clean)

        clear_btn = QPushButton("🗑 清空")
        clear_btn.setObjectName("danger_btn")
        clear_btn.clicked.connect(self.clear_all)
        clear_btn.setMaximumWidth(80)
        btn_row.addWidget(clear_btn)

        layout.addLayout(btn_row)

        # ======== 进度 ========
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # ======== 预览 + 结果区域（上下分割） ========
        splitter = QSplitter(Qt.Vertical)

        # --- 预览表格 ---
        preview_group = QGroupBox("👁 预览 — 待删除行")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_summary = QLabel("")
        preview_layout.addWidget(self.preview_summary)

        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(5)
        self.preview_table.setHorizontalHeaderLabels([
            "表格", "工作表", "行号", "原因", "内容预览"
        ])
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents)
        self.preview_table.setColumnWidth(2, 50)
        self.preview_table.setColumnWidth(3, 140)
        self.preview_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.Stretch)
        self.preview_table.verticalHeader().setDefaultSectionSize(24)
        splitter.addWidget(preview_group)

        # --- 执行结果表格 ---
        result_group = QGroupBox("📊 执行结果")
        result_layout = QVBoxLayout(result_group)

        self.result_table = QTableWidget()
        self.result_table.setColumnCount(6)
        self.result_table.setHorizontalHeaderLabels(
            ["表格标题", "工作表", "日期过期", "空行", "总删除", "状态"]
        )
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.result_table.setColumnWidth(1, 100)
        self.result_table.setColumnWidth(2, 70)
        self.result_table.setColumnWidth(3, 50)
        self.result_table.setColumnWidth(4, 70)
        self.result_table.setColumnWidth(5, 50)
        self.result_table.verticalHeader().setDefaultSectionSize(28)
        result_layout.addWidget(self.result_table)
        splitter.addWidget(result_group)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)

    # ======== 工作表列表加载 ========

    def load_sheet_names(self):
        """从当前连接的表格或输入的第一个 ID 读取工作表列表"""
        ids = self._get_ids()
        if not ids:
            self.sheet_status_label.setText("⚠️ 请先输入表格 ID 或连接表格")
            return

        self.refresh_sheets_btn.setEnabled(False)
        self.refresh_sheets_btn.setText("⏳ 加载中...")
        self.sheet_status_label.setText("正在读取工作表列表...")

        self._sheet_loader = SheetListLoader(ids[0])
        self._sheet_loader.finished.connect(self._on_sheets_loaded)
        self._sheet_loader.error.connect(self._on_sheets_error)
        self._sheet_loader.start()

    def _on_sheets_loaded(self, sheet_names):
        """工作表列表加载完成 — 动态生成 checkbox"""
        self._clear_sheet_checkboxes()

        for name in sheet_names:
            cb = QCheckBox(name)
            cb.setChecked(True)  # 默认全选
            cb.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            cb.stateChanged.connect(self._update_sheet_status)
            self._sheet_flow_layout.addWidget(cb)
            self._sheet_checkboxes.append(cb)

        # 强制刷新布局
        self._sheet_flow_container.adjustSize()

        self._update_sheet_status()
        self.refresh_sheets_btn.setEnabled(True)
        self.refresh_sheets_btn.setText("🔄 读取工作表列表")
        self._sheet_loader = None

    def _on_sheets_error(self, msg):
        self.sheet_status_label.setText(f"❌ 加载失败: {msg}")
        self.refresh_sheets_btn.setEnabled(True)
        self.refresh_sheets_btn.setText("🔄 读取工作表列表")
        self._sheet_loader = None

    def _clear_sheet_checkboxes(self):
        """清除所有工作表 checkbox"""
        for cb in self._sheet_checkboxes:
            self._sheet_flow_layout.removeWidget(cb)
            cb.deleteLater()
        self._sheet_checkboxes.clear()

    def _update_sheet_status(self, _state=None):
        """实时更新工作表选中计数"""
        total = len(self._sheet_checkboxes)
        if total == 0:
            return
        selected = sum(1 for cb in self._sheet_checkboxes if cb.isChecked())
        if selected == total:
            self.sheet_status_label.setText(
                f"✅ 共 {total} 个工作表（已全选）")
            self.sheet_status_label.setStyleSheet(
                "color: green; font-weight: bold;")
        elif selected == 0:
            self.sheet_status_label.setText(
                f"⚠️ 共 {total} 个工作表（未选择任何工作表）")
            self.sheet_status_label.setStyleSheet(
                "color: orange; font-style: italic;")
        else:
            self.sheet_status_label.setText(
                f"📋 已选择 {selected}/{total} 个工作表")
            self.sheet_status_label.setStyleSheet(
                "color: #1976D2; font-weight: bold;")

    def _select_all_sheets(self):
        for cb in self._sheet_checkboxes:
            cb.setChecked(True)

    def _deselect_all_sheets(self):
        for cb in self._sheet_checkboxes:
            cb.setChecked(False)

    def _get_selected_sheets(self):
        """获取用户勾选的工作表名称列表"""
        return [cb.text() for cb in self._sheet_checkboxes if cb.isChecked()]

    # ======== ID 提取 ========

    def _get_ids(self):
        from ui.batch_backup_widget import extract_spreadsheet_id
        text = self.ids_input.toPlainText().strip()
        if text:
            ids = []
            for line in text.split('\n'):
                sid = extract_spreadsheet_id(line.strip())
                if sid:
                    ids.append(sid)
            return ids
        elif self.controller and self.controller.service:
            return [self.controller.service.spreadsheet_id]
        return []

    # ======== 参数验证 ========

    def _validate_params(self):
        """验证参数，返回 (ids, sheet_names, col, cutoff) 或 None"""
        ids = self._get_ids()
        if not ids:
            self.status_label.setText("⚠️ 请输入表格 ID 或先连接表格")
            return None

        sheet_names = self._get_selected_sheets()
        if not sheet_names:
            self.status_label.setText("⚠️ 请选择至少一个工作表")
            return None

        col = self.col_input.text().strip().upper()
        if not col or not col.isalpha():
            self.status_label.setText("⚠️ 日期列格式无效（请输入列字母如 A, B, C）")
            return None

        qdate = self.date_input.date()
        cutoff = datetime(qdate.year(), qdate.month(), qdate.day())

        return ids, sheet_names, col, cutoff

    # ======== 预览 ========

    def start_preview(self):
        """启动预览扫描"""
        params = self._validate_params()
        if not params:
            return
        ids, sheet_names, col, cutoff = params

        self.preview_btn.setEnabled(False)
        self.preview_btn.setText("⏳ 扫描中...")
        self.start_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.preview_table.setRowCount(0)
        self.preview_summary.setText("正在扫描...")

        self._log(
            f"🔍 开始预览: {len(ids)} 个表格, "
            f"{len(sheet_names)} 个工作表, 日期列={col}, "
            f"截止={cutoff.strftime('%Y-%m-%d')}"
        )

        self._preview_worker = PreviewWorker(
            ids, sheet_names, col, cutoff,
            self.skip_header_cb.isChecked()
        )
        self._preview_worker.progress.connect(
            lambda m: self.status_label.setText(m))
        self._preview_worker.finished.connect(self._on_preview_finished)
        self._preview_worker.error.connect(self._on_preview_error)
        self._preview_worker.start()

    def _on_preview_finished(self, previews):
        self._preview_data = previews
        self.progress_bar.setVisible(False)
        self.preview_btn.setEnabled(True)
        self.preview_btn.setText("👁 预览待删除行")

        # 汇总统计
        total_to_delete = sum(p.get("total_to_delete", 0) for p in previews)
        total_date = sum(p.get("deleted_by_date", 0) for p in previews)
        total_empty = sum(p.get("deleted_empty", 0) for p in previews)
        errors = [p for p in previews if "error" in p]

        # 填充预览表格 — 限制最多显示 500 行
        all_rows = []
        for p in previews:
            stitle = p.get("spreadsheet_title", "")
            sname = p.get("sheet_name", "")
            if "error" in p:
                all_rows.append((stitle, sname, "—", f"❌ {p['error']}", ""))
            else:
                for r in p.get("rows_to_delete", []):
                    all_rows.append((
                        stitle, sname,
                        str(r["row_index"]),
                        r["reason"],
                        r["preview"]
                    ))

        display_rows = all_rows[:500]
        self.preview_table.setRowCount(len(display_rows))
        for i, (st, sn, rn, reason, preview) in enumerate(display_rows):
            self.preview_table.setItem(i, 0, QTableWidgetItem(st))
            self.preview_table.setItem(i, 1, QTableWidgetItem(sn))
            self.preview_table.setItem(i, 2, QTableWidgetItem(rn))
            self.preview_table.setItem(i, 3, QTableWidgetItem(reason))
            self.preview_table.setItem(i, 4, QTableWidgetItem(preview))

        truncated = f"（仅显示前 500 行）" if len(all_rows) > 500 else ""
        err_msg = f", {len(errors)} 个错误" if errors else ""
        self.preview_summary.setText(
            f"🔍 预览结果: 共 {total_to_delete} 行待删除 "
            f"(日期过期: {total_date}, 空行: {total_empty}){err_msg} {truncated}"
        )

        if total_to_delete > 0:
            self.start_btn.setEnabled(True)
            self.start_btn.setToolTip("")
            self.status_label.setText(
                f"✅ 扫描完成 — 共 {total_to_delete} 行待删除，"
                f"请确认后点击「执行清理」"
            )
        else:
            self.start_btn.setEnabled(False)
            self.status_label.setText("✅ 扫描完成 — 没有需要删除的行")

        self._preview_worker = None

    def _on_preview_error(self, msg):
        self.status_label.setText(f"❌ 预览失败: {msg}")
        self.preview_btn.setEnabled(True)
        self.preview_btn.setText("👁 预览待删除行")
        self.progress_bar.setVisible(False)
        self._preview_worker = None

    # ======== 执行清理 ========

    def start_clean(self):
        """确认后执行清理"""
        params = self._validate_params()
        if not params:
            return
        ids, sheet_names, col, cutoff = params

        total_to_delete = sum(
            p.get("total_to_delete", 0) for p in self._preview_data
        )

        # 二次确认
        reply = QMessageBox.warning(
            self, "⚠️ 确认删除",
            f"即将从 {len(ids)} 个表格的 {len(sheet_names)} 个工作表中\n"
            f"删除共 {total_to_delete} 行数据。\n\n"
            f"此操作不可撤销，确定要继续吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.start_btn.setEnabled(False)
        self.start_btn.setText("⏳ 清理中...")
        self.preview_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.result_table.setRowCount(0)

        self._log(
            f"🚀 开始清理 {len(ids)} 个表格, "
            f"{len(sheet_names)} 个工作表"
        )

        self._worker = CleanRowsWorker(
            ids, sheet_names, col, cutoff,
            self.skip_header_cb.isChecked()
        )
        self._worker.progress.connect(
            lambda m: (self.status_label.setText(m), self._log(m)))
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, results):
        self.progress_bar.setVisible(False)

        self.result_table.setRowCount(len(results))
        total_date = total_empty = total_all = 0

        for i, r in enumerate(results):
            self.result_table.setItem(
                i, 0, QTableWidgetItem(r.get("title", "—")))
            self.result_table.setItem(
                i, 1, QTableWidgetItem(r.get("sheet_name", "—")))
            self.result_table.setItem(
                i, 2, QTableWidgetItem(str(r.get("deleted_by_date", 0))))
            self.result_table.setItem(
                i, 3, QTableWidgetItem(str(r.get("deleted_empty", 0))))
            self.result_table.setItem(
                i, 4, QTableWidgetItem(str(r.get("total", 0))))

            status = "✅" if r["status"] == "success" else "❌"
            item = QTableWidgetItem(status)
            if r["status"] == "error":
                item.setToolTip(r.get("error", ""))
            self.result_table.setItem(i, 5, item)

            if r["status"] == "success":
                total_date += r.get("deleted_by_date", 0)
                total_empty += r.get("deleted_empty", 0)
                total_all += r.get("total", 0)

        success = sum(1 for r in results if r["status"] == "success")
        msg = (
            f"✅ 清理完成: {success}/{len(results)} 成功, "
            f"共删除 {total_all} 行 (日期: {total_date}, 空行: {total_empty})"
        )
        self.status_label.setText(msg)
        self._log(msg)

        self.start_btn.setEnabled(False)
        self.start_btn.setText("🚀 执行清理")
        self.start_btn.setToolTip("请先预览确认后再执行清理")
        self.preview_btn.setEnabled(True)
        self._worker = None

    def _on_error(self, error_msg):
        self.status_label.setText(f"❌ 清理失败: {error_msg}")
        self._log(f"❌ 清理失败: {error_msg}")
        self.start_btn.setEnabled(False)
        self.start_btn.setText("🚀 执行清理")
        self.preview_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self._worker = None

    def clear_all(self):
        self.ids_input.clear()
        self._clear_sheet_checkboxes()
        self.preview_table.setRowCount(0)
        self.result_table.setRowCount(0)
        self.status_label.setText("")
        self.preview_summary.setText("")
        self.progress_bar.setVisible(False)
        self.start_btn.setEnabled(False)
        self._preview_data = []

    def _log(self, text):
        if self.controller and self.controller.view:
            self.controller.view.log(text)
