# 批量修改公式 UI 组件 — 向多个表格的指定位置写入/修改公式
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger("sheets_toolkit.ui.batch_formula")


class BatchFormulaWorker(QThread):
    """批量公式写入工作线程"""
    progress = Signal(int, int, str)   # current, total, message
    finished = Signal(list)            # results
    error = Signal(str)

    def __init__(self, spreadsheet_ids, sheet_name, cell_range, formula):
        super().__init__()
        self.spreadsheet_ids = spreadsheet_ids
        self.sheet_name = sheet_name
        self.cell_range = cell_range
        self.formula = formula

    def run(self):
        try:
            from services.sheet_service import SheetService
            results = SheetService.batch_write_formula_to_sheets(
                self.spreadsheet_ids,
                self.sheet_name,
                self.cell_range,
                self.formula,
                progress_callback=self._on_progress
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, current, total, message):
        self.progress.emit(current, total, message)


class BatchFormulaWidget(QWidget):
    """
    批量修改公式面板。
    向多个表格的指定工作表和单元格位置写入（或替换）函数公式。
    """

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._worker = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 标题
        title = QLabel("📝 批量修改公式")
        title.setObjectName("section_title")
        layout.addWidget(title)

        # 说明
        help_label = QLabel(
            "向多个 Google Sheets 的指定位置批量写入或修改函数公式。\n"
            "公式以 = 开头，如 =SUM(B2:B100)、=VLOOKUP(A2,Sheet2!A:B,2,0) 等。"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        # 表格 ID 输入
        layout.addWidget(QLabel("📄 表格链接/ID（每行一个）："))
        self.ids_input = ClearableTextEdit()
        self.ids_input.setPlaceholderText(
            "输入 Google Sheets 链接或 ID，每行一个\n"
            "如不输入，将使用侧边栏中当前连接的表格"
        )
        self.ids_input.setMaximumHeight(100)
        layout.addWidget(self.ids_input)

        # 参数行1：工作表和单元格
        row1 = QHBoxLayout()

        row1.addWidget(QLabel("📋 工作表名："))
        self.sheet_name_input = QLineEdit("Sheet1")
        self.sheet_name_input.setPlaceholderText("如 Sheet1")
        self.sheet_name_input.setMaximumWidth(150)
        row1.addWidget(self.sheet_name_input)

        row1.addWidget(QLabel("📍 单元格："))
        self.cell_input = QLineEdit()
        self.cell_input.setPlaceholderText("如 A1 或 D5")
        self.cell_input.setMaximumWidth(100)
        row1.addWidget(self.cell_input)

        layout.addLayout(row1)

        # 参数行2：公式输入
        layout.addWidget(QLabel("✨ 函数公式："))
        self.formula_input = QLineEdit()
        self.formula_input.setPlaceholderText(
            '输入公式，如 =SUM(B2:B100)、=IF(A2>0,"正","负")、=VLOOKUP(A2,Sheet2!A:B,2,0)'
        )
        layout.addWidget(self.formula_input)

        # 预览当前公式按钮
        preview_row = QHBoxLayout()

        self.preview_btn = QPushButton("🔍 预览当前公式")
        self.preview_btn.setObjectName("secondary_btn")
        self.preview_btn.clicked.connect(self.preview_formula)
        self.preview_btn.setMaximumWidth(150)
        preview_row.addWidget(self.preview_btn)

        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        preview_row.addWidget(self.preview_label)

        layout.addLayout(preview_row)

        # 按钮
        btn_row = QHBoxLayout()

        self.start_btn = QPushButton("🚀 批量写入公式")
        self.start_btn.clicked.connect(self.start_write)
        btn_row.addWidget(self.start_btn)

        clear_btn = QPushButton("🗑 清空")
        clear_btn.setObjectName("danger_btn")
        clear_btn.clicked.connect(self.clear_all)
        clear_btn.setMaximumWidth(80)
        btn_row.addWidget(clear_btn)

        layout.addLayout(btn_row)

        # 进度
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # 结果表格
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(3)
        self.result_table.setHorizontalHeaderLabels(
            ["表格标题", "ID", "状态"]
        )
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.result_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.result_table.setColumnWidth(2, 60)
        self.result_table.verticalHeader().setDefaultSectionSize(28)
        layout.addWidget(self.result_table)

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
            # 使用当前连接的表格
            if self.controller and self.controller.service:
                return [self.controller.service.spreadsheet_id]
            return []

    def preview_formula(self):
        """预览第一个表格中当前单元格的公式"""
        ids = self._get_ids()
        if not ids:
            self.preview_label.setText("⚠️ 请输入表格 ID 或先连接表格")
            return

        sheet_name = self.sheet_name_input.text().strip()
        cell = self.cell_input.text().strip().upper()
        if not sheet_name or not cell:
            self.preview_label.setText("⚠️ 请输入工作表名和单元格")
            return

        try:
            from services.sheet_service import SheetService
            service = SheetService(ids[0])
            range_str = f"{sheet_name}!{cell}"

            # 读取当前公式
            formulas = service.read_formulas(range_str)
            # 读取当前值
            values = service.read_data(range_str)

            formula_text = formulas[0][0] if formulas and formulas[0] else "（空）"
            value_text = values[0][0] if values and values[0] else "（空）"

            self.preview_label.setText(
                f"📋 当前公式: {formula_text}  |  当前值: {value_text}"
            )
            self._log(f"🔍 {range_str} 当前公式={formula_text}, 值={value_text}")

        except Exception as e:
            self.preview_label.setText(f"❌ 预览失败: {str(e)}")
            self._log(f"❌ 公式预览失败: {e}")

    def start_write(self):
        """开始批量写入公式"""
        ids = self._get_ids()
        if not ids:
            self.status_label.setText("⚠️ 请输入表格 ID 或先连接表格")
            self._log("⚠️ 没有找到有效的表格 ID")
            return

        sheet_name = self.sheet_name_input.text().strip()
        cell = self.cell_input.text().strip().upper()
        formula = self.formula_input.text().strip()

        if not sheet_name:
            self.status_label.setText("⚠️ 请输入工作表名称")
            return
        if not cell:
            self.status_label.setText("⚠️ 请输入目标单元格（如 A1, D5）")
            return
        if not formula:
            self.status_label.setText("⚠️ 请输入公式")
            return

        # 验证公式格式
        if not formula.startswith('='):
            self.status_label.setText("⚠️ 公式应以 = 开头（如 =SUM(A1:A10)）")
            return

        # 禁用按钮
        self.start_btn.setEnabled(False)
        self.start_btn.setText("⏳ 写入中...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(ids))
        self.progress_bar.setValue(0)
        self.result_table.setRowCount(0)

        self._log(
            f"🚀 开始向 {len(ids)} 个表格写入公式: "
            f"{sheet_name}!{cell} = {formula}"
        )

        # 启动工作线程
        self._worker = BatchFormulaWorker(ids, sheet_name, cell, formula)
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
            self.result_table.setItem(
                i, 0, QTableWidgetItem(r.get("title", "—"))
            )
            self.result_table.setItem(
                i, 1, QTableWidgetItem(r.get("source_id", "—")[:30] + "...")
            )
            status = "✅" if r["status"] == "success" else "❌"
            item = QTableWidgetItem(status)
            if r["status"] == "error":
                item.setToolTip(r.get("error", ""))
            self.result_table.setItem(i, 2, item)

        success = sum(1 for r in results if r["status"] == "success")
        msg = f"✅ 公式写入完成: {success}/{len(results)} 成功"
        self.status_label.setText(msg)
        self._log(msg)

        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 批量写入公式")
        self._worker = None

    def _on_error(self, error_msg):
        self.status_label.setText(f"❌ 写入失败: {error_msg}")
        self._log(f"❌ 批量写入公式失败: {error_msg}")
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 批量写入公式")
        self.progress_bar.setVisible(False)
        self._worker = None

    def clear_all(self):
        self.ids_input.clear()
        self.formula_input.clear()
        self.result_table.setRowCount(0)
        self.status_label.setText("")
        self.preview_label.setText("")
        self.progress_bar.setVisible(False)

    def _log(self, text):
        if self.controller and self.controller.view:
            self.controller.view.log(text)
