# 公式库 UI 组件 — 管理保存的公式 + 一键批量应用到多个表格
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar,
    QSplitter, QGroupBox, QComboBox, QMessageBox
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import Qt, QThread, Signal

from services.formula_library import FormulaLibrary

logger = logging.getLogger("sheets_toolkit.ui.formula_library")


class ApplyFormulaWorker(QThread):
    """公式应用工作线程"""
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, spreadsheet_ids, sheet_name, cell, formula):
        super().__init__()
        self.spreadsheet_ids = spreadsheet_ids
        self.sheet_name = sheet_name
        self.cell = cell
        self.formula = formula

    def run(self):
        try:
            from services.sheet_service import SheetService
            results = SheetService.batch_write_formula_to_sheets(
                self.spreadsheet_ids,
                self.sheet_name,
                self.cell,
                self.formula,
                progress_callback=self._on_progress
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, current, total, message):
        self.progress.emit(current, total, message)


class FormulaLibraryWidget(QWidget):
    """
    公式库面板 — 分为左右两部分：
    左侧：公式列表管理（查看、新增、编辑、删除）
    右侧：应用公式（输入表格链接 + 位置，一键批量写入）
    """

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.library = FormulaLibrary()
        self._worker = None
        self._selected_id = None
        self.setup_ui()
        self.refresh_table()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        title = QLabel("📚 公式库")
        title.setObjectName("section_title")
        layout.addWidget(title)

        # 左右分割
        splitter = QSplitter(Qt.Horizontal)

        # ======= 左侧：公式管理 =======
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)

        # 搜索+分类
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索公式...")
        self.search_input.textChanged.connect(self.on_search)
        search_row.addWidget(self.search_input)

        self.cat_filter = QComboBox()
        self.cat_filter.addItem("全部分类")
        self.cat_filter.currentTextChanged.connect(self.on_filter)
        self.cat_filter.setMaximumWidth(120)
        search_row.addWidget(self.cat_filter)
        left_layout.addLayout(search_row)

        # 公式列表
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["名称", "公式", "位置", "分类"])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 70)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.currentCellChanged.connect(self.on_select)
        left_layout.addWidget(self.table)

        # 编辑区
        edit_group = QGroupBox("公式详情")
        edit_layout = QVBoxLayout(edit_group)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("名称:"))
        self.edit_name = QLineEdit()
        r1.addWidget(self.edit_name)
        r1.addWidget(QLabel("分类:"))
        self.edit_cat = QLineEdit()
        self.edit_cat.setMaximumWidth(80)
        r1.addWidget(self.edit_cat)
        edit_layout.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("公式:"))
        self.edit_formula = QLineEdit()
        self.edit_formula.setPlaceholderText("=SUM(B2:B100)")
        r2.addWidget(self.edit_formula)
        edit_layout.addLayout(r2)

        r3 = QHBoxLayout()
        r3.addWidget(QLabel("Sheet:"))
        self.edit_sheet = QLineEdit("Sheet1")
        self.edit_sheet.setMaximumWidth(100)
        r3.addWidget(self.edit_sheet)
        r3.addWidget(QLabel("单元格:"))
        self.edit_cell = QLineEdit("A1")
        self.edit_cell.setMaximumWidth(60)
        r3.addWidget(self.edit_cell)
        r3.addWidget(QLabel("说明:"))
        self.edit_desc = QLineEdit()
        r3.addWidget(self.edit_desc)
        edit_layout.addLayout(r3)

        # 按钮行
        btn_row = QHBoxLayout()
        add_btn = QPushButton("➕ 新增")
        add_btn.clicked.connect(self.add_formula)
        btn_row.addWidget(add_btn)

        save_btn = QPushButton("💾 保存修改")
        save_btn.setObjectName("secondary_btn")
        save_btn.clicked.connect(self.save_formula)
        btn_row.addWidget(save_btn)

        del_btn = QPushButton("🗑 删除")
        del_btn.setObjectName("danger_btn")
        del_btn.clicked.connect(self.delete_formula)
        btn_row.addWidget(del_btn)

        edit_layout.addLayout(btn_row)
        left_layout.addWidget(edit_group)

        # ======= 右侧：应用公式 =======
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)

        apply_title = QLabel("🚀 应用公式")
        apply_title.setObjectName("section_title")
        right_layout.addWidget(apply_title)

        help_label = QLabel(
            "从左侧选择公式，输入表格链接，\n"
            "即可将公式批量写入到所有表格的指定位置。\n"
            "也可覆盖默认的工作表名和单元格。"
        )
        help_label.setWordWrap(True)
        right_layout.addWidget(help_label)

        # 当前选中的公式
        self.selected_label = QLabel("📋 未选择公式")
        self.selected_label.setWordWrap(True)
        right_layout.addWidget(self.selected_label)

        # 覆盖位置
        override_row = QHBoxLayout()
        override_row.addWidget(QLabel("Sheet:"))
        self.apply_sheet = QLineEdit()
        self.apply_sheet.setPlaceholderText("使用公式默认值")
        self.apply_sheet.setMaximumWidth(120)
        override_row.addWidget(self.apply_sheet)
        override_row.addWidget(QLabel("单元格:"))
        self.apply_cell = QLineEdit()
        self.apply_cell.setPlaceholderText("使用默认值")
        self.apply_cell.setMaximumWidth(80)
        override_row.addWidget(self.apply_cell)
        right_layout.addLayout(override_row)

        # 表格 ID 输入
        right_layout.addWidget(QLabel("📄 表格链接/ID（每行一个）："))
        self.ids_input = ClearableTextEdit()
        self.ids_input.setPlaceholderText(
            "输入 Google Sheets 链接或 ID，每行一个\n"
            "如不输入，将使用当前连接的表格"
        )
        right_layout.addWidget(self.ids_input)

        # 应用按钮
        self.apply_btn = QPushButton("🚀 批量应用公式")
        self.apply_btn.clicked.connect(self.apply_formula)
        right_layout.addWidget(self.apply_btn)

        # 进度
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        right_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        right_layout.addWidget(self.status_label)

        # 结果
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(3)
        self.result_table.setHorizontalHeaderLabels(["表格标题", "ID", "状态"])
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.result_table.setColumnWidth(2, 60)
        self.result_table.verticalHeader().setDefaultSectionSize(28)
        right_layout.addWidget(self.result_table)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([450, 400])
        layout.addWidget(splitter)

    # ========================
    # 公式列表管理
    # ========================

    def refresh_table(self, formulas=None):
        """刷新公式列表"""
        items = formulas if formulas is not None else self.library.formulas
        self.table.setRowCount(len(items))

        for i, f in enumerate(items):
            name_item = QTableWidgetItem(f.get("name", ""))
            name_item.setData(Qt.UserRole, f.get("id"))
            self.table.setItem(i, 0, name_item)
            self.table.setItem(i, 1, QTableWidgetItem(f.get("formula", "")))
            pos = f"{f.get('sheet_name', '')}!{f.get('cell', '')}"
            self.table.setItem(i, 2, QTableWidgetItem(pos))
            self.table.setItem(i, 3, QTableWidgetItem(f.get("category", "")))

        # 更新分类过滤器
        cats = self.library.get_categories()
        current = self.cat_filter.currentText()
        self.cat_filter.blockSignals(True)
        self.cat_filter.clear()
        self.cat_filter.addItem("全部分类")
        self.cat_filter.addItems(cats)
        idx = self.cat_filter.findText(current)
        if idx >= 0:
            self.cat_filter.setCurrentIndex(idx)
        self.cat_filter.blockSignals(False)

    def on_select(self, row, col, prev_row, prev_col):
        """选中公式时填充编辑区"""
        if row < 0:
            return
        item = self.table.item(row, 0)
        if not item:
            return
        fid = item.data(Qt.UserRole)
        entry = self.library.get_by_id(fid)
        if not entry:
            return
        self._selected_id = fid
        self.edit_name.setText(entry.get("name", ""))
        self.edit_formula.setText(entry.get("formula", ""))
        self.edit_sheet.setText(entry.get("sheet_name", "Sheet1"))
        self.edit_cell.setText(entry.get("cell", "A1"))
        self.edit_desc.setText(entry.get("description", ""))
        self.edit_cat.setText(entry.get("category", "通用"))

        self.selected_label.setText(
            f"📋 已选: {entry['name']}\n"
            f"   公式: {entry['formula']}\n"
            f"   位置: {entry.get('sheet_name', '')}!{entry.get('cell', '')}"
        )

    def on_search(self, text):
        """搜索公式"""
        if text.strip():
            results = self.library.search(text)
            self.refresh_table(results)
        else:
            self.refresh_table()

    def on_filter(self, cat):
        """按分类过滤"""
        if cat == "全部分类":
            self.refresh_table()
        else:
            filtered = [f for f in self.library.formulas if f.get("category") == cat]
            self.refresh_table(filtered)

    def add_formula(self):
        """新增公式"""
        name = self.edit_name.text().strip()
        formula = self.edit_formula.text().strip()
        if not name or not formula:
            self._log("⚠️ 请输入公式名称和公式内容")
            return

        self.library.add(
            name=name,
            formula=formula,
            description=self.edit_desc.text().strip(),
            sheet_name=self.edit_sheet.text().strip() or "Sheet1",
            cell=self.edit_cell.text().strip() or "A1",
            category=self.edit_cat.text().strip() or "通用"
        )
        self.refresh_table()
        self._log(f"➕ 已添加公式: {name}")
        # 清空编辑区
        self._clear_edit()

    def save_formula(self):
        """保存对选中公式的修改"""
        if not self._selected_id:
            self._log("⚠️ 请先选择要修改的公式")
            return

        self.library.update(
            self._selected_id,
            name=self.edit_name.text().strip(),
            formula=self.edit_formula.text().strip(),
            description=self.edit_desc.text().strip(),
            sheet_name=self.edit_sheet.text().strip(),
            cell=self.edit_cell.text().strip(),
            category=self.edit_cat.text().strip()
        )
        self.refresh_table()
        self._log(f"💾 已保存修改: {self.edit_name.text()}")

    def delete_formula(self):
        """删除选中的公式"""
        if not self._selected_id:
            self._log("⚠️ 请先选择要删除的公式")
            return

        entry = self.library.get_by_id(self._selected_id)
        name = entry.get("name", "未知") if entry else "未知"

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除公式 '{name}' 吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.library.delete(self._selected_id)
            self._selected_id = None
            self.refresh_table()
            self._clear_edit()
            self._log(f"🗑 已删除公式: {name}")

    def _clear_edit(self):
        """清空编辑区"""
        self.edit_name.clear()
        self.edit_formula.clear()
        self.edit_desc.clear()
        self.edit_sheet.setText("Sheet1")
        self.edit_cell.setText("A1")
        self.edit_cat.setText("通用")
        self._selected_id = None
        self.selected_label.setText("📋 未选择公式")

    # ========================
    # 批量应用
    # ========================

    def _get_ids(self):
        """获取要处理的表格 ID 列表"""
        from ui.batch_backup_widget import extract_spreadsheet_id
        text = self.ids_input.toPlainText().strip()
        if text:
            ids = []
            for line in text.split('\n'):
                sid = extract_spreadsheet_id(line.strip())
                if sid:
                    ids.append(sid)
            return ids
        else:
            if self.controller and self.controller.service:
                return [self.controller.service.spreadsheet_id]
            return []

    def apply_formula(self):
        """将选中的公式批量应用到表格"""
        if not self._selected_id:
            self.status_label.setText("⚠️ 请先从左侧选择一条公式")
            return

        entry = self.library.get_by_id(self._selected_id)
        if not entry:
            self.status_label.setText("⚠️ 公式不存在")
            return

        ids = self._get_ids()
        if not ids:
            self.status_label.setText("⚠️ 请输入表格 ID 或先连接表格")
            return

        # 使用覆盖值或默认值
        sheet_name = self.apply_sheet.text().strip() or entry.get("sheet_name", "Sheet1")
        cell = self.apply_cell.text().strip() or entry.get("cell", "A1")
        formula = entry["formula"]

        self.apply_btn.setEnabled(False)
        self.apply_btn.setText("⏳ 应用中...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(ids))
        self.progress_bar.setValue(0)
        self.result_table.setRowCount(0)

        self._log(
            f"🚀 应用公式 '{entry['name']}' 到 {len(ids)} 个表格: "
            f"{sheet_name}!{cell} = {formula}"
        )

        self._worker = ApplyFormulaWorker(ids, sheet_name, cell, formula)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, current, total, message):
        self.progress_bar.setValue(current)
        self.status_label.setText(message)
        self._log(f"📝 {message}")

    def _on_finished(self, results):
        self.progress_bar.setValue(self.progress_bar.maximum())

        self.result_table.setRowCount(len(results))
        for i, r in enumerate(results):
            self.result_table.setItem(i, 0, QTableWidgetItem(r.get("title", "—")))
            self.result_table.setItem(
                i, 1, QTableWidgetItem(r.get("source_id", "—")[:25] + "...")
            )
            status = "✅" if r["status"] == "success" else "❌"
            item = QTableWidgetItem(status)
            if r["status"] == "error":
                item.setToolTip(r.get("error", ""))
            self.result_table.setItem(i, 2, item)

        success = sum(1 for r in results if r["status"] == "success")
        msg = f"✅ 公式应用完成: {success}/{len(results)} 成功"
        self.status_label.setText(msg)
        self._log(msg)

        self.apply_btn.setEnabled(True)
        self.apply_btn.setText("🚀 批量应用公式")
        self._worker = None

    def _on_error(self, error_msg):
        self.status_label.setText(f"❌ 应用失败: {error_msg}")
        self._log(f"❌ 公式应用失败: {error_msg}")
        self.apply_btn.setEnabled(True)
        self.apply_btn.setText("🚀 批量应用公式")
        self.progress_bar.setVisible(False)
        self._worker = None

    def _log(self, text):
        if self.controller and self.controller.view:
            self.controller.view.log(text)
