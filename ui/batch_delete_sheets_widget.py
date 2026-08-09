# 批量删除 UI 组件 — 支持删除工作簿（垃圾桶/彻底删除）和删除子工作表（加载+勾选+删除）
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QComboBox, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QMessageBox, QMenu,
    QApplication, QFileDialog
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QClipboard, QAction, QIcon

logger = logging.getLogger("sheets_toolkit.ui.batch_delete_sheets")


# ========================
# 工作线程
# ========================

class DeleteSpreadsheetWorker(QThread):
    """批量删除工作簿的工作线程"""
    progress = Signal(int, int, str)  # current, total, message
    finished = Signal(list)           # results
    error = Signal(str)

    def __init__(self, spreadsheet_ids, mode="trash"):
        super().__init__()
        self.spreadsheet_ids = spreadsheet_ids
        self.mode = mode  # "trash" 或 "permanent"

    def run(self):
        try:
            from services.sheet_service import SheetService
            if self.mode == "trash":
                results = SheetService.batch_trash_spreadsheets(
                    self.spreadsheet_ids,
                    progress_callback=self._on_progress
                )
            else:
                results = SheetService.batch_permanently_delete_spreadsheets(
                    self.spreadsheet_ids,
                    progress_callback=self._on_progress
                )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, current, total, message):
        self.progress.emit(current, total, message)


class LoadSheetsWorker(QThread):
    """加载多个表格的子工作表信息的工作线程"""
    progress = Signal(int, int, str)  # current, total, message
    finished = Signal(list)           # [{id, title, sheets: [name1, name2, ...]}]
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
                try:
                    self.progress.emit(
                        i, total,
                        f"正在加载 ({i + 1}/{total}): {sid[:20]}..."
                    )
                    service = SheetService(sid)
                    title = service.get_spreadsheet_title()
                    sheets = service.list_sheets()
                    results.append({
                        "id": sid,
                        "title": title,
                        "sheets": sheets
                    })
                except Exception as e:
                    results.append({
                        "id": sid,
                        "title": f"加载失败: {str(e)[:30]}",
                        "sheets": [],
                        "error": str(e)
                    })

            self.progress.emit(total, total, f"加载完成: {len(results)} 个表格")
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class DeleteSheetTabsWorker(QThread):
    """批量删除子工作表的工作线程"""
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, delete_map):
        """
        Args:
            delete_map: dict, {spreadsheet_id: [sheet_name_1, ...]}
        """
        super().__init__()
        self.delete_map = delete_map

    def run(self):
        try:
            from services.sheet_service import SheetService
            results = SheetService.batch_delete_sheets(
                self.delete_map,
                progress_callback=self._on_progress
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, current, total, message):
        self.progress.emit(current, total, message)


class CheckStatusWorker(QThread):
    """批量检测文件状态的工作线程"""
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, spreadsheet_ids):
        super().__init__()
        self.spreadsheet_ids = spreadsheet_ids

    def run(self):
        try:
            from services.sheet_service import SheetService
            results = SheetService.batch_check_spreadsheet_status(
                self.spreadsheet_ids,
                progress_callback=self._on_progress
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, current, total, message):
        self.progress.emit(current, total, message)


class RestoreSpreadsheetWorker(QThread):
    """批量恢复工作簿的工作线程"""
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, spreadsheet_ids):
        super().__init__()
        self.spreadsheet_ids = spreadsheet_ids

    def run(self):
        try:
            from services.sheet_service import SheetService
            results = SheetService.batch_restore_spreadsheets(
                self.spreadsheet_ids,
                progress_callback=self._on_progress
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, current, total, message):
        self.progress.emit(current, total, message)


class ExportSpreadsheetWorker(QThread):
    """批量导出工作簿的工作线程"""
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, spreadsheet_ids, save_dir):
        super().__init__()
        self.spreadsheet_ids = spreadsheet_ids
        self.save_dir = save_dir

    def run(self):
        try:
            from services.sheet_service import SheetService
            results = SheetService.batch_export_spreadsheets(
                self.spreadsheet_ids,
                self.save_dir,
                progress_callback=self._on_progress
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, current, total, message):
        self.progress.emit(current, total, message)


# ========================
# 主组件
# ========================

class BatchDeleteSheetsWidget(QWidget):
    """
    批量删除面板。
    Tab 1：删除整个工作簿（移到垃圾桶 / 彻底删除）
    Tab 2：删除子工作表（加载 → 勾选 → 删除）
    """

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._delete_worker = None
        self._load_worker = None
        self._delete_tabs_worker = None
        self._check_worker = None
        # 缓存加载的表格信息，供删除时使用
        self._loaded_data = []
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 标题
        title = QLabel("🗑 批量删除")
        title.setObjectName("section_title")
        layout.addWidget(title)

        # Tab 页签
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_tab_spreadsheet(), "📄 删除工作簿")
        self.tabs.addTab(self._build_tab_sheet_tabs(), "📋 删除子工作表")
        self.tabs.addTab(self._build_tab_check_status(), "🔍 检测文件状态")
        layout.addWidget(self.tabs)

    # ========================
    # Tab 1: 删除工作簿
    # ========================

    def _build_tab_spreadsheet(self):
        """构建「删除工作簿」Tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(8)

        # 说明
        help_label = QLabel(
            "批量删除多个 Google Sheets 工作簿。\n"
            "每行输入一个表格链接或 ID。支持「移到垃圾桶」和「彻底删除」两种模式。"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        # 链接输入区
        layout.addWidget(QLabel("📄 表格链接/ID（每行一个）："))
        self.wb_ids_input = ClearableTextEdit()
        self.wb_ids_input.setPlaceholderText(
            "粘贴 Google Sheets 链接或 ID，每行一个，例如：\n"
            "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit\n"
            "或直接输入 ID"
        )
        self.wb_ids_input.setMaximumHeight(140)
        layout.addWidget(self.wb_ids_input)

        # 删除模式
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("🔧 删除模式："))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["🗑 移到垃圾桶", "💀 彻底删除（不可恢复）"])
        self.mode_combo.setCurrentIndex(0)
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # 按钮行
        btn_row = QHBoxLayout()

        self.wb_preview_btn = QPushButton("🔍 解析预览")
        self.wb_preview_btn.setObjectName("secondary_btn")
        self.wb_preview_btn.clicked.connect(self._wb_preview)
        btn_row.addWidget(self.wb_preview_btn)

        self.wb_delete_btn = QPushButton("🗑 执行删除")
        self.wb_delete_btn.clicked.connect(self._wb_start_delete)
        btn_row.addWidget(self.wb_delete_btn)

        wb_clear_btn = QPushButton("🧹 清空")
        wb_clear_btn.setObjectName("danger_btn")
        wb_clear_btn.clicked.connect(self._wb_clear)
        wb_clear_btn.setMaximumWidth(80)
        btn_row.addWidget(wb_clear_btn)

        layout.addLayout(btn_row)

        # 进度条
        self.wb_progress = QProgressBar()
        self.wb_progress.setVisible(False)
        layout.addWidget(self.wb_progress)

        # 状态标签
        self.wb_status = QLabel("")
        layout.addWidget(self.wb_status)

        # 结果表格
        self.wb_result_table = QTableWidget()
        self.wb_result_table.setColumnCount(4)
        self.wb_result_table.setHorizontalHeaderLabels(
            ["表格标题", "ID", "操作结果", "状态"]
        )
        self.wb_result_table.setAlternatingRowColors(True)
        self.wb_result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.wb_result_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.wb_result_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.wb_result_table.setColumnWidth(2, 120)
        self.wb_result_table.setColumnWidth(3, 60)
        self.wb_result_table.verticalHeader().setDefaultSectionSize(28)
        layout.addWidget(self.wb_result_table)

        return tab

    def _wb_parse_ids(self):
        """解析工作簿链接输入，提取 Spreadsheet ID"""
        from ui.batch_backup_widget import extract_spreadsheet_id
        text = self.wb_ids_input.toPlainText()
        lines = text.strip().split('\n')
        ids = []
        invalid = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            sid = extract_spreadsheet_id(line)
            if sid:
                ids.append(sid)
            else:
                invalid.append(line)
        return ids, invalid

    def _wb_preview(self):
        """解析预览工作簿链接"""
        ids, invalid = self._wb_parse_ids()

        self.wb_result_table.setRowCount(len(ids) + len(invalid))
        for i, sid in enumerate(ids):
            self.wb_result_table.setItem(i, 0, QTableWidgetItem("—"))
            self.wb_result_table.setItem(i, 1, QTableWidgetItem(sid))
            self.wb_result_table.setItem(i, 2, QTableWidgetItem("待执行"))
            self.wb_result_table.setItem(i, 3, QTableWidgetItem("✅ 有效"))

        for j, line in enumerate(invalid):
            row = len(ids) + j
            self.wb_result_table.setItem(row, 0, QTableWidgetItem("—"))
            self.wb_result_table.setItem(row, 1, QTableWidgetItem(line[:40]))
            self.wb_result_table.setItem(row, 2, QTableWidgetItem("—"))
            self.wb_result_table.setItem(row, 3, QTableWidgetItem("❌ 无效"))

        self.wb_status.setText(
            f"解析完成: {len(ids)} 个有效 ID, {len(invalid)} 个无效输入"
        )
        self._log(f"🔍 解析预览: {len(ids)} 个有效, {len(invalid)} 个无效")

    def _wb_start_delete(self):
        """开始删除工作簿"""
        ids, _ = self._wb_parse_ids()
        if not ids:
            self.wb_status.setText("⚠️ 请输入至少一个有效的表格链接或 ID")
            return

        mode = "trash" if self.mode_combo.currentIndex() == 0 else "permanent"

        # 二次确认对话框
        if mode == "permanent":
            # 彻底删除使用更强烈的警告
            reply = QMessageBox.warning(
                self, "⚠️ 危险操作确认",
                f"您即将 **彻底永久删除** {len(ids)} 个工作簿！\n\n"
                f"此操作不可恢复，删除后无法找回。\n\n"
                f"确定要继续吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
        else:
            reply = QMessageBox.question(
                self, "确认删除",
                f"确定要将 {len(ids)} 个工作簿移到垃圾桶吗？\n\n"
                f"移到垃圾桶后可以在 Google Drive 中恢复。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

        if reply != QMessageBox.Yes:
            return

        # 禁用按钮并启动工作线程
        self.wb_delete_btn.setEnabled(False)
        self.wb_delete_btn.setText("⏳ 删除中...")
        self.wb_progress.setVisible(True)
        self.wb_progress.setMaximum(len(ids))
        self.wb_progress.setValue(0)
        self.wb_result_table.setRowCount(0)

        mode_text = "移到垃圾桶" if mode == "trash" else "彻底删除"
        self._log(f"🗑 开始{mode_text} {len(ids)} 个工作簿")

        self._delete_worker = DeleteSpreadsheetWorker(ids, mode)
        self._delete_worker.progress.connect(self._wb_on_progress)
        self._delete_worker.finished.connect(self._wb_on_finished)
        self._delete_worker.error.connect(self._wb_on_error)
        self._delete_worker.start()

    def _wb_on_progress(self, current, total, message):
        self.wb_progress.setValue(current)
        self.wb_status.setText(message)
        self._log(f"🗑 {message}")

    def _wb_on_finished(self, results):
        self.wb_progress.setValue(self.wb_progress.maximum())

        self.wb_result_table.setRowCount(len(results))
        for i, r in enumerate(results):
            self.wb_result_table.setItem(
                i, 0, QTableWidgetItem(r.get("title", "—"))
            )
            sid = r.get("id", "—")
            self.wb_result_table.setItem(
                i, 1, QTableWidgetItem(sid[:25] + "..." if len(sid) > 25 else sid)
            )
            self.wb_result_table.setItem(
                i, 2, QTableWidgetItem(r.get("detail", "—"))
            )
            status = "✅" if r["status"] == "success" else "❌"
            status_item = QTableWidgetItem(status)
            if r["status"] == "error":
                status_item.setToolTip(r.get("detail", ""))
            self.wb_result_table.setItem(i, 3, status_item)

        success = sum(1 for r in results if r["status"] == "success")
        msg = f"✅ 删除完成: {success}/{len(results)} 成功"
        self.wb_status.setText(msg)
        self._log(msg)

        self.wb_delete_btn.setEnabled(True)
        self.wb_delete_btn.setText("🗑 执行删除")
        self._delete_worker = None

    def _wb_on_error(self, error_msg):
        self.wb_status.setText(f"❌ 操作失败: {error_msg}")
        self._log(f"❌ 删除工作簿失败: {error_msg}")
        self.wb_delete_btn.setEnabled(True)
        self.wb_delete_btn.setText("🗑 执行删除")
        self.wb_progress.setVisible(False)
        self._delete_worker = None

    def _wb_clear(self):
        self.wb_ids_input.clear()
        self.wb_result_table.setRowCount(0)
        self.wb_status.setText("")
        self.wb_progress.setVisible(False)

    # ========================
    # Tab 2: 删除子工作表
    # ========================

    def _build_tab_sheet_tabs(self):
        """构建「删除子工作表」Tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(8)

        # 说明
        help_label = QLabel(
            "批量删除多个 Google Sheets 中的子工作表（Sheet Tab）。\n"
            "输入表格链接后点击「加载工作表」，系统会展示所有子工作表供您勾选删除。"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        # 链接输入区
        layout.addWidget(QLabel("📄 表格链接/ID（每行一个）："))
        self.st_ids_input = ClearableTextEdit()
        self.st_ids_input.setPlaceholderText(
            "粘贴 Google Sheets 链接或 ID，每行一个"
        )
        self.st_ids_input.setMaximumHeight(100)
        layout.addWidget(self.st_ids_input)

        # 按钮行：加载
        load_row = QHBoxLayout()

        self.st_load_btn = QPushButton("📥 加载工作表")
        self.st_load_btn.clicked.connect(self._st_load_sheets)
        load_row.addWidget(self.st_load_btn)

        self.st_select_all_btn = QPushButton("☑ 全选")
        self.st_select_all_btn.setObjectName("secondary_btn")
        self.st_select_all_btn.clicked.connect(self._st_select_all)
        self.st_select_all_btn.setMaximumWidth(80)
        load_row.addWidget(self.st_select_all_btn)

        self.st_deselect_all_btn = QPushButton("☐ 全不选")
        self.st_deselect_all_btn.setObjectName("secondary_btn")
        self.st_deselect_all_btn.clicked.connect(self._st_deselect_all)
        self.st_deselect_all_btn.setMaximumWidth(80)
        load_row.addWidget(self.st_deselect_all_btn)

        load_row.addStretch()

        st_clear_btn = QPushButton("🧹 清空")
        st_clear_btn.setObjectName("danger_btn")
        st_clear_btn.clicked.connect(self._st_clear)
        st_clear_btn.setMaximumWidth(80)
        load_row.addWidget(st_clear_btn)

        layout.addLayout(load_row)

        # 树形展示区（加载后填充）
        self.st_tree = QTreeWidget()
        self.st_tree.setHeaderLabels(["工作表名称", "状态"])
        self.st_tree.setColumnWidth(0, 400)
        self.st_tree.setAlternatingRowColors(True)
        self.st_tree.itemChanged.connect(self._st_on_item_changed)
        layout.addWidget(self.st_tree)

        # 按钮行：删除
        delete_row = QHBoxLayout()

        self.st_delete_btn = QPushButton("🗑 删除选中的工作表")
        self.st_delete_btn.clicked.connect(self._st_start_delete)
        delete_row.addWidget(self.st_delete_btn)

        self.st_count_label = QLabel("已选: 0 个子工作表")
        delete_row.addWidget(self.st_count_label)

        delete_row.addStretch()
        layout.addLayout(delete_row)

        # 进度条
        self.st_progress = QProgressBar()
        self.st_progress.setVisible(False)
        layout.addWidget(self.st_progress)

        # 状态标签
        self.st_status = QLabel("")
        layout.addWidget(self.st_status)

        # 结果表格
        self.st_result_table = QTableWidget()
        self.st_result_table.setColumnCount(4)
        self.st_result_table.setHorizontalHeaderLabels(
            ["表格标题", "已删除", "跳过/未找到", "状态"]
        )
        self.st_result_table.setAlternatingRowColors(True)
        self.st_result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.st_result_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.st_result_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.st_result_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch
        )
        self.st_result_table.setColumnWidth(3, 60)
        self.st_result_table.verticalHeader().setDefaultSectionSize(28)
        layout.addWidget(self.st_result_table)

        return tab

    def _st_parse_ids(self):
        """解析子工作表页面的链接输入"""
        from ui.batch_backup_widget import extract_spreadsheet_id
        text = self.st_ids_input.toPlainText()
        lines = text.strip().split('\n')
        ids = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            sid = extract_spreadsheet_id(line)
            if sid:
                ids.append(sid)
        return ids

    def _st_load_sheets(self):
        """加载所有表格的子工作表信息"""
        ids = self._st_parse_ids()
        if not ids:
            self.st_status.setText("⚠️ 请输入至少一个有效的表格链接或 ID")
            return

        self.st_load_btn.setEnabled(False)
        self.st_load_btn.setText("⏳ 加载中...")
        self.st_progress.setVisible(True)
        self.st_progress.setMaximum(len(ids))
        self.st_progress.setValue(0)
        self.st_tree.clear()
        self._loaded_data = []
        self.st_result_table.setRowCount(0)

        self._log(f"📥 开始加载 {len(ids)} 个表格的工作表信息")

        self._load_worker = LoadSheetsWorker(ids)
        self._load_worker.progress.connect(self._st_on_load_progress)
        self._load_worker.finished.connect(self._st_on_load_finished)
        self._load_worker.error.connect(self._st_on_load_error)
        self._load_worker.start()

    def _st_on_load_progress(self, current, total, message):
        self.st_progress.setValue(current)
        self.st_status.setText(message)

    def _st_on_load_finished(self, results):
        """加载完成，填充树形控件"""
        self.st_progress.setValue(self.st_progress.maximum())
        self._loaded_data = results

        # 暂时阻止信号以避免 itemChanged 被多次触发
        self.st_tree.blockSignals(True)
        self.st_tree.clear()

        for item_data in results:
            sid = item_data["id"]
            title = item_data["title"]
            sheets = item_data.get("sheets", [])
            has_error = "error" in item_data

            # 父节点：表格标题
            parent = QTreeWidgetItem(self.st_tree)
            parent.setText(0, f"📄 {title}")
            parent.setText(1, f"{len(sheets)} 个子工作表" if not has_error else "❌ 加载失败")
            parent.setData(0, Qt.UserRole, sid)  # 存储 spreadsheet_id
            parent.setFlags(parent.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            parent.setCheckState(0, Qt.Unchecked)

            if has_error:
                parent.setToolTip(0, item_data["error"])
                continue

            # 子节点：各个子工作表
            for sheet_name in sheets:
                child = QTreeWidgetItem(parent)
                child.setText(0, f"  📋 {sheet_name}")
                child.setText(1, "")
                child.setData(0, Qt.UserRole, sheet_name)  # 存储工作表名称
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Unchecked)

        self.st_tree.expandAll()
        self.st_tree.blockSignals(False)

        total_sheets = sum(len(r.get("sheets", [])) for r in results)
        success_count = sum(1 for r in results if "error" not in r)
        self.st_status.setText(
            f"加载完成: {success_count} 个表格, 共 {total_sheets} 个子工作表"
        )
        self._log(
            f"📥 加载完成: {success_count} 个表格, {total_sheets} 个子工作表"
        )

        self.st_load_btn.setEnabled(True)
        self.st_load_btn.setText("📥 加载工作表")
        self._load_worker = None

        self._st_update_count()

    def _st_on_load_error(self, error_msg):
        self.st_status.setText(f"❌ 加载失败: {error_msg}")
        self._log(f"❌ 加载工作表失败: {error_msg}")
        self.st_load_btn.setEnabled(True)
        self.st_load_btn.setText("📥 加载工作表")
        self.st_progress.setVisible(False)
        self._load_worker = None

    def _st_on_item_changed(self, item, column):
        """勾选状态变化时更新计数"""
        if column == 0:
            self._st_update_count()

    def _st_update_count(self):
        """统计已勾选的子工作表数量"""
        count = 0
        root = self.st_tree.invisibleRootItem()
        for i in range(root.childCount()):
            parent = root.child(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.checkState(0) == Qt.Checked:
                    count += 1
        self.st_count_label.setText(f"已选: {count} 个子工作表")

    def _st_select_all(self):
        """全选所有子工作表"""
        self.st_tree.blockSignals(True)
        root = self.st_tree.invisibleRootItem()
        for i in range(root.childCount()):
            parent = root.child(i)
            parent.setCheckState(0, Qt.Checked)
            for j in range(parent.childCount()):
                parent.child(j).setCheckState(0, Qt.Checked)
        self.st_tree.blockSignals(False)
        self._st_update_count()

    def _st_deselect_all(self):
        """全不选"""
        self.st_tree.blockSignals(True)
        root = self.st_tree.invisibleRootItem()
        for i in range(root.childCount()):
            parent = root.child(i)
            parent.setCheckState(0, Qt.Unchecked)
            for j in range(parent.childCount()):
                parent.child(j).setCheckState(0, Qt.Unchecked)
        self.st_tree.blockSignals(False)
        self._st_update_count()

    def _st_collect_checked(self):
        """
        收集所有勾选的子工作表，构建 delete_map。

        Returns:
            dict: {spreadsheet_id: [sheet_name_1, sheet_name_2, ...]}
        """
        delete_map = {}
        root = self.st_tree.invisibleRootItem()

        for i in range(root.childCount()):
            parent = root.child(i)
            sid = parent.data(0, Qt.UserRole)
            if not sid:
                continue

            checked_sheets = []
            total_sheets = parent.childCount()

            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.checkState(0) == Qt.Checked:
                    sheet_name = child.data(0, Qt.UserRole)
                    if sheet_name:
                        checked_sheets.append(sheet_name)

            # 如果用户勾选了全部子工作表，自动保留最后一个
            if checked_sheets and len(checked_sheets) >= total_sheets:
                kept = checked_sheets.pop()
                self._log(
                    f"⚠️ {parent.text(0)}: 至少需保留一个工作表，"
                    f"自动取消「{kept}」的勾选"
                )

            if checked_sheets:
                delete_map[sid] = checked_sheets

        return delete_map

    def _st_start_delete(self):
        """开始删除勾选的子工作表"""
        delete_map = self._st_collect_checked()

        if not delete_map:
            self.st_status.setText("⚠️ 请先勾选要删除的子工作表")
            return

        # 统计总数
        total_sheets = sum(len(v) for v in delete_map.values())
        total_workbooks = len(delete_map)

        # 二次确认
        reply = QMessageBox.warning(
            self, "确认删除子工作表",
            f"确定要删除以下内容吗？\n\n"
            f"涉及 {total_workbooks} 个工作簿\n"
            f"共计 {total_sheets} 个子工作表\n\n"
            f"此操作不可撤销！",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 禁用按钮并启动
        self.st_delete_btn.setEnabled(False)
        self.st_delete_btn.setText("⏳ 删除中...")
        self.st_progress.setVisible(True)
        self.st_progress.setMaximum(len(delete_map))
        self.st_progress.setValue(0)
        self.st_result_table.setRowCount(0)

        self._log(
            f"🗑 开始删除 {total_workbooks} 个工作簿中的 "
            f"{total_sheets} 个子工作表"
        )

        self._delete_tabs_worker = DeleteSheetTabsWorker(delete_map)
        self._delete_tabs_worker.progress.connect(self._st_on_delete_progress)
        self._delete_tabs_worker.finished.connect(self._st_on_delete_finished)
        self._delete_tabs_worker.error.connect(self._st_on_delete_error)
        self._delete_tabs_worker.start()

    def _st_on_delete_progress(self, current, total, message):
        self.st_progress.setValue(current)
        self.st_status.setText(message)
        self._log(f"🗑 {message}")

    def _st_on_delete_finished(self, results):
        self.st_progress.setValue(self.st_progress.maximum())

        self.st_result_table.setRowCount(len(results))
        for i, r in enumerate(results):
            # 表格标题
            self.st_result_table.setItem(
                i, 0, QTableWidgetItem(r.get("title", "—"))
            )
            # 已删除的工作表
            deleted = r.get("deleted", [])
            self.st_result_table.setItem(
                i, 1, QTableWidgetItem(", ".join(deleted) if deleted else "—")
            )
            # 跳过/未找到
            skipped = r.get("skipped", []) + r.get("not_found", [])
            self.st_result_table.setItem(
                i, 2, QTableWidgetItem(
                    ", ".join(skipped) if skipped else "—"
                )
            )
            # 状态
            status = "✅" if r["status"] == "success" else "❌"
            status_item = QTableWidgetItem(status)
            if r["status"] == "error":
                status_item.setToolTip(r.get("detail", ""))
            self.st_result_table.setItem(i, 3, status_item)

        success = sum(1 for r in results if r["status"] == "success")
        total_deleted = sum(len(r.get("deleted", [])) for r in results)
        msg = (
            f"✅ 删除完成: {success}/{len(results)} 个工作簿处理成功, "
            f"共删除 {total_deleted} 个子工作表"
        )
        self.st_status.setText(msg)
        self._log(msg)

        self.st_delete_btn.setEnabled(True)
        self.st_delete_btn.setText("🗑 删除选中的工作表")
        self._delete_tabs_worker = None

    def _st_on_delete_error(self, error_msg):
        self.st_status.setText(f"❌ 删除失败: {error_msg}")
        self._log(f"❌ 删除子工作表失败: {error_msg}")
        self.st_delete_btn.setEnabled(True)
        self.st_delete_btn.setText("🗑 删除选中的工作表")
        self.st_progress.setVisible(False)
        self._delete_tabs_worker = None

    def _st_clear(self):
        """清空子工作表页面"""
        self.st_ids_input.clear()
        self.st_tree.clear()
        self.st_result_table.setRowCount(0)
        self.st_status.setText("")
        self.st_progress.setVisible(False)
        self.st_count_label.setText("已选: 0 个子工作表")
        self._loaded_data = []

    # ========================
    # Tab 3: 检测文件状态
    # ========================

    def _build_tab_check_status(self):
        """构建「检测文件状态」Tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(8)

        # 说明
        help_label = QLabel(
            "批量检测多个 Google Sheets 工作簿的文件状态。\n"
            "输入表格链接后点击检测，系统会判断每个文件是否存在、是否在垃圾桶中、是否已被彻底删除。"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        # 链接输入区
        layout.addWidget(QLabel("📄 表格链接/ID（每行一个）："))
        self.cs_ids_input = ClearableTextEdit()
        self.cs_ids_input.setPlaceholderText(
            "粘贴 Google Sheets 链接或 ID，每行一个\n"
            "系统将检测每个文件的状态：正常 / 垃圾桶 / 已彻底删除"
        )
        self.cs_ids_input.setMaximumHeight(140)
        layout.addWidget(self.cs_ids_input)

        # 按钮行
        btn_row = QHBoxLayout()

        self.cs_check_btn = QPushButton("🔍 开始检测")
        self.cs_check_btn.clicked.connect(self._cs_start_check)
        btn_row.addWidget(self.cs_check_btn)

        cs_clear_btn = QPushButton("🧹 清空")
        cs_clear_btn.setObjectName("danger_btn")
        cs_clear_btn.clicked.connect(self._cs_clear)
        cs_clear_btn.setMaximumWidth(80)
        btn_row.addWidget(cs_clear_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 进度条
        self.cs_progress = QProgressBar()
        self.cs_progress.setVisible(False)
        layout.addWidget(self.cs_progress)

        # 状态标签
        self.cs_status = QLabel("")
        layout.addWidget(self.cs_status)

        # 结果表格
        self.cs_result_table = QTableWidget()
        self.cs_result_table.setColumnCount(4)
        self.cs_result_table.setHorizontalHeaderLabels(
            ["表格标题", "ID", "文件状态", "详情"]
        )
        self.cs_result_table.setAlternatingRowColors(True)
        self.cs_result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cs_result_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.cs_result_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.cs_result_table.setColumnWidth(2, 130)
        self.cs_result_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch
        )
        self.cs_result_table.verticalHeader().setDefaultSectionSize(28)

        # 启用整行多选，保证右键能正确获取选中行
        self.cs_result_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.cs_result_table.setSelectionMode(QTableWidget.ExtendedSelection)

        # 启用右键菜单
        self.cs_result_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.cs_result_table.customContextMenuRequested.connect(self._cs_show_context_menu)

        layout.addWidget(self.cs_result_table)

        return tab

    def _cs_parse_ids(self):
        """解析检测页面的链接输入"""
        from ui.batch_backup_widget import extract_spreadsheet_id
        text = self.cs_ids_input.toPlainText()
        lines = text.strip().split('\n')
        ids = []
        invalid = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            sid = extract_spreadsheet_id(line)
            if sid:
                ids.append(sid)
            else:
                invalid.append(line)
        return ids, invalid

    def _cs_start_check(self):
        """开始批量检测文件状态"""
        ids, invalid = self._cs_parse_ids()
        if not ids:
            self.cs_status.setText("⚠️ 请输入至少一个有效的表格链接或 ID")
            return

        if invalid:
            self._log(f"⚠️ 跳过 {len(invalid)} 个无效输入")

        self.cs_check_btn.setEnabled(False)
        self.cs_check_btn.setText("⏳ 检测中...")
        self.cs_progress.setVisible(True)
        self.cs_progress.setMaximum(len(ids))
        self.cs_progress.setValue(0)
        self.cs_result_table.setRowCount(0)

        self._log(f"🔍 开始检测 {len(ids)} 个文件的状态")

        self._check_worker = CheckStatusWorker(ids)
        self._check_worker.progress.connect(self._cs_on_progress)
        self._check_worker.finished.connect(self._cs_on_finished)
        self._check_worker.error.connect(self._cs_on_error)
        self._check_worker.start()

    def _cs_on_progress(self, current, total, message):
        self.cs_progress.setValue(current)
        self.cs_status.setText(message)

    def _cs_on_finished(self, results):
        """检测完成，填充结果表格"""
        self.cs_progress.setValue(self.cs_progress.maximum())

        # 状态对应的显示文字和图标
        status_display = {
            "active": "✅ 正常",
            "trashed": "🗑 垃圾桶",
            "deleted": "💀 已彻底删除",
            "no_access": "🔒 无权限",
            "error": "❌ 检测失败",
        }

        self.cs_result_table.setRowCount(len(results))
        for i, r in enumerate(results):
            # 表格标题
            self.cs_result_table.setItem(
                i, 0, QTableWidgetItem(r.get("title", "—"))
            )
            # ID
            sid = r.get("id", "—")
            id_item = QTableWidgetItem(sid[:25] + "..." if len(sid) > 25 else sid)
            # 保存完整的 sid 供右键菜单使用
            if sid != "—":
                id_item.setData(Qt.UserRole, sid)
            self.cs_result_table.setItem(i, 1, id_item)
            # 文件状态
            file_status = r.get("file_status", "error")
            status_text = status_display.get(file_status, f"❓ {file_status}")
            self.cs_result_table.setItem(
                i, 2, QTableWidgetItem(status_text)
            )
            # 详情
            self.cs_result_table.setItem(
                i, 3, QTableWidgetItem(r.get("detail", "—"))
            )

        # 统计汇总
        active = sum(1 for r in results if r["file_status"] == "active")
        trashed = sum(1 for r in results if r["file_status"] == "trashed")
        deleted = sum(1 for r in results if r["file_status"] == "deleted")
        other = len(results) - active - trashed - deleted

        msg = (
            f"✅ 检测完成: "
            f"{active} 正常, {trashed} 在垃圾桶, {deleted} 已彻底删除"
        )
        if other > 0:
            msg += f", {other} 其他"
        self.cs_status.setText(msg)
        self._log(f"🔍 {msg}")

        self.cs_check_btn.setEnabled(True)
        self.cs_check_btn.setText("🔍 开始检测")
        self._check_worker = None

    def _cs_on_error(self, error_msg):
        self.cs_status.setText(f"❌ 检测失败: {error_msg}")
        self._log(f"❌ 检测文件状态失败: {error_msg}")
        self.cs_check_btn.setEnabled(True)
        self.cs_check_btn.setText("🔍 开始检测")
        self.cs_progress.setVisible(False)
        self._check_worker = None

    def _cs_clear(self):
        """清空检测页面"""
        self.cs_ids_input.clear()
        self.cs_result_table.setRowCount(0)
        self.cs_status.setText("")
        self.cs_progress.setVisible(False)

    # ------------------
    # 右键菜单功能
    # ------------------

    def _cs_show_context_menu(self, pos):
        """显示右键菜单"""
        selected_rows = self.cs_result_table.selectionModel().selectedRows()
        
        # 降级处理：如果没有选中整行，尝试获取当前选中的单元格所在的行
        if not selected_rows:
            indexes = self.cs_result_table.selectedIndexes()
            if indexes:
                rows = set(index.row() for index in indexes)
                # 将这些 row 转化为 model index 传过去
                model = self.cs_result_table.model()
                selected_rows = [model.index(r, 0) for r in rows]
            
            if not selected_rows:
                return

        menu = QMenu(self)

        # 获取选中的 ID 和当前状态
        copy_action = QAction("📋 复制链接/ID", self)
        copy_action.triggered.connect(lambda: self._cs_menu_copy(selected_rows))
        menu.addAction(copy_action)

        menu.addSeparator()

        restore_action = QAction("✅ 恢复正常", self)
        restore_action.triggered.connect(lambda: self._cs_menu_restore(selected_rows))
        menu.addAction(restore_action)

        trash_action = QAction("🗑 移到垃圾桶", self)
        trash_action.triggered.connect(lambda: self._cs_menu_trash(selected_rows))
        menu.addAction(trash_action)

        delete_action = QAction("💀 彻底永久删除", self)
        delete_action.triggered.connect(lambda: self._cs_menu_delete(selected_rows))
        menu.addAction(delete_action)

        menu.addSeparator()

        export_action = QAction("📥 导出数据为 Excel", self)
        export_action.triggered.connect(lambda: self._cs_menu_export(selected_rows))
        menu.addAction(export_action)

        # 必须使用 viewport().mapToGlobal(pos) 否则菜单位置会跑偏
        menu.exec_(self.cs_result_table.viewport().mapToGlobal(pos))

    def _cs_get_ids_from_rows(self, rows):
        ids = []
        for index in rows:
            row = index.row()
            sid_item = self.cs_result_table.item(row, 1)
            if sid_item and sid_item.text() != "—":
                # 这里 UI 上可能是缩略的，真实的 ID 我们需要确保。
                # 之前写入的时候截断了 ID: sid[:25] + "..." if len(sid) > 25 else sid
                # 这会导致无法取到真实 ID。因此需要从 data() 里拿或者不要截断。
                # 由于原代码把截断字符直接放进 text，我们需要修复。
                # 为了不改原代码，直接从 tooltip 获取可能最简单。由于原代码没设 tooltip，最好设一下。
                # 但是考虑到之前代码写入：self.cs_result_table.setItem(i, 1, QTableWidgetItem(sid[:25] + "..."))
                # 为简便起见，我们可以直接从输入框的 ids 或者利用 itemData，
                # 但更安全的做法是修改 _cs_on_finished 在设值时把真实 id 放入 UserRole。
                # 因为没存，这里我通过 item.data 获取，等下在 _cs_on_finished 补上 setData。
                sid = sid_item.data(Qt.UserRole)
                if sid:
                    ids.append(sid)
        return ids

    def _cs_menu_copy(self, rows):
        """复制选中行的 URL"""
        ids = self._cs_get_ids_from_rows(rows)
        if not ids:
            return
        urls = [f"https://docs.google.com/spreadsheets/d/{sid}/edit" for sid in ids]
        QApplication.clipboard().setText("\n".join(urls))
        self._log(f"📋 已复制 {len(urls)} 个链接到剪贴板")
        self.cs_status.setText(f"📋 已复制 {len(urls)} 个链接")

    def _cs_menu_restore(self, rows):
        ids = self._cs_get_ids_from_rows(rows)
        if not ids:
            return
        
        reply = QMessageBox.question(
            self, "恢复文件",
            f"确定要从垃圾桶恢复 {len(ids)} 个工作簿吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes: return

        self._start_action_worker(RestoreSpreadsheetWorker(ids), "恢复中...")

    def _cs_menu_trash(self, rows):
        ids = self._cs_get_ids_from_rows(rows)
        if not ids:
            return

        reply = QMessageBox.question(
            self, "移到垃圾桶",
            f"确定要将 {len(ids)} 个工作簿移到垃圾桶吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes: return

        self._start_action_worker(DeleteSpreadsheetWorker(ids, "trash"), "移到垃圾桶...")

    def _cs_menu_delete(self, rows):
        ids = self._cs_get_ids_from_rows(rows)
        if not ids:
            return

        reply = QMessageBox.warning(
            self, "⚠️ 彻底删除确认",
            f"确定要彻底永久删除 {len(ids)} 个工作簿吗？\n\n此操作不可恢复！",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes: return

        self._start_action_worker(DeleteSpreadsheetWorker(ids, "permanent"), "彻底删除中...")

    def _cs_menu_export(self, rows):
        ids = self._cs_get_ids_from_rows(rows)
        if not ids:
            return

        save_dir = QFileDialog.getExistingDirectory(self, "选择导出保存目录")
        if not save_dir:
            return

        self._start_action_worker(ExportSpreadsheetWorker(ids, save_dir), "导出中...")

    def _start_action_worker(self, worker, action_text):
        """通用的动作 Worker 启动器"""
        self.cs_check_btn.setEnabled(False)
        self.cs_check_btn.setText(f"⏳ {action_text}")
        self.cs_progress.setVisible(True)
        self.cs_progress.setValue(0)
        # 借用 _check_worker 的位置存放临时 worker
        self._check_worker = worker
        self._check_worker.progress.connect(self._cs_on_progress)
        self._check_worker.finished.connect(lambda res: self._on_action_finished(res, action_text))
        self._check_worker.error.connect(self._cs_on_error)
        self._check_worker.start()

    def _on_action_finished(self, results, action_text):
        """右键菜单执行完成的回调，更新详情并修改文件状态列"""
        self.cs_progress.setValue(self.cs_progress.maximum())
        
        success = sum(1 for r in results if r.get("status") == "success")
        msg = f"✅ [{action_text.strip('. ')}] 完成: 成功 {success} / {len(results)}"
        self.cs_status.setText(msg)
        self._log(msg)

        # 确定需要更新的状态文字
        new_status = None
        if "恢复" in action_text:
            new_status = "✅ 正常"
        elif "垃圾桶" in action_text:
            new_status = "🗑 垃圾桶"
        elif "彻底删除" in action_text:
            new_status = "💀 已彻底删除"

        # 更新表格中的详情与状态
        for r in results:
            if r.get("status") != "success":
                continue
            sid = r.get("id")
            for row in range(self.cs_result_table.rowCount()):
                item = self.cs_result_table.item(row, 1)
                if item and item.data(Qt.UserRole) == sid:
                    # 更新状态列
                    if new_status:
                        status_item = self.cs_result_table.item(row, 2)
                        if status_item:
                            status_item.setText(new_status)

                    # 在详情列增加
                    detail_item = self.cs_result_table.item(row, 3)
                    if detail_item:
                        old_text = detail_item.text()
                        detail_item.setText(f"{old_text} | {r.get('detail', '')}")

        self.cs_check_btn.setEnabled(True)
        self.cs_check_btn.setText("🔍 开始检测")
        self._check_worker = None

    # ========================
    # 通用工具
    # ========================

    def _log(self, text):
        """输出日志到主窗口"""
        if self.controller and self.controller.view:
            self.controller.view.log(text)
