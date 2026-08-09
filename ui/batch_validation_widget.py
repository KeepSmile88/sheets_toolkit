# 批量数据验证 UI 组件 — 批量为多个表格设置数据验证规则
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar,
    QComboBox, QSpinBox, QGroupBox
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger("sheets_toolkit.ui.batch_validation")


def col_letter_to_index(letter):
    letter = letter.upper().strip()
    idx = 0
    for ch in letter:
        idx = idx * 26 + (ord(ch) - ord('A'))
    return idx


class BatchValidationWorker(QThread):
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, ids, sheet_name, sr, er, sc, ec, rule):
        super().__init__()
        self.ids = ids
        self.sheet_name = sheet_name
        self.sr, self.er, self.sc, self.ec = sr, er, sc, ec
        self.rule = rule

    def run(self):
        try:
            from services.sheet_service import SheetService
            results = SheetService.batch_set_validation(
                self.ids, self.sheet_name,
                self.sr, self.er, self.sc, self.ec,
                self.rule, self._p
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _p(self, c, t, m):
        self.progress.emit(c, t, m)


class BatchValidationWidget(QWidget):
    """批量数据验证面板"""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._worker = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        title = QLabel("✅ 批量数据验证")
        title.setObjectName("section_title")
        layout.addWidget(title)

        help_label = QLabel(
            "批量为多个表格的指定区域设置数据验证规则（下拉列表、数值范围、日期等）。"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        # 表格 ID
        layout.addWidget(QLabel("📄 表格链接/ID（每行一个）："))
        self.ids_input = ClearableTextEdit()
        self.ids_input.setPlaceholderText("输入链接或 ID，不输入则使用当前表格")
        self.ids_input.setMaximumHeight(80)
        layout.addWidget(self.ids_input)

        # 区域
        pos_row = QHBoxLayout()
        pos_row.addWidget(QLabel("Sheet:"))
        self.sheet_input = QLineEdit("Sheet1")
        self.sheet_input.setMaximumWidth(120)
        pos_row.addWidget(self.sheet_input)
        pos_row.addWidget(QLabel("起始行:"))
        self.row_start = QSpinBox()
        self.row_start.setMinimum(1)
        self.row_start.setValue(2)
        pos_row.addWidget(self.row_start)
        pos_row.addWidget(QLabel("结束行:"))
        self.row_end = QSpinBox()
        self.row_end.setMinimum(1)
        self.row_end.setValue(100)
        self.row_end.setMaximum(99999)
        pos_row.addWidget(self.row_end)
        pos_row.addWidget(QLabel("列:"))
        self.col_input = QLineEdit("A")
        self.col_input.setMaximumWidth(50)
        pos_row.addWidget(self.col_input)
        layout.addLayout(pos_row)

        # 验证规则
        rule_group = QGroupBox("验证规则")
        rule_layout = QVBoxLayout(rule_group)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("类型:"))
        self.rule_type = QComboBox()
        self.rule_type.addItems([
            "下拉列表 (ONE_OF_LIST)",
            "数值范围 (NUMBER_BETWEEN)",
            "大于 (NUMBER_GREATER)",
            "小于 (NUMBER_LESS)",
            "日期有效 (DATE_IS_VALID)",
            "文本包含 (TEXT_CONTAINS)",
            "自定义公式 (CUSTOM_FORMULA)"
        ])
        self.rule_type.currentIndexChanged.connect(self._on_type_changed)
        type_row.addWidget(self.rule_type)
        rule_layout.addLayout(type_row)

        # 值输入
        val_row = QHBoxLayout()
        val_row.addWidget(QLabel("值:"))
        self.val1_input = QLineEdit()
        self.val1_input.setPlaceholderText("选项1,选项2,选项3（逗号分隔）")
        val_row.addWidget(self.val1_input)
        self.val2_label = QLabel("至:")
        val_row.addWidget(self.val2_label)
        self.val2_input = QLineEdit()
        self.val2_input.setPlaceholderText("最大值")
        self.val2_input.setMaximumWidth(100)
        val_row.addWidget(self.val2_input)
        rule_layout.addLayout(val_row)

        self._on_type_changed(0)
        layout.addWidget(rule_group)

        # 按钮
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("🚀 批量设置验证")
        self.start_btn.clicked.connect(self.start_validation)
        btn_row.addWidget(self.start_btn)
        layout.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.result_table = QTableWidget()
        self.result_table.setColumnCount(3)
        self.result_table.setHorizontalHeaderLabels(["标题", "ID", "状态"])
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.result_table.setColumnWidth(2, 60)
        layout.addWidget(self.result_table)

    def _on_type_changed(self, idx):
        """根据验证类型调整输入框"""
        type_text = self.rule_type.currentText()
        if "NUMBER_BETWEEN" in type_text:
            self.val1_input.setPlaceholderText("最小值")
            self.val2_label.setVisible(True)
            self.val2_input.setVisible(True)
        elif "ONE_OF_LIST" in type_text:
            self.val1_input.setPlaceholderText("选项1,选项2,选项3（逗号分隔）")
            self.val2_label.setVisible(False)
            self.val2_input.setVisible(False)
        elif "DATE_IS_VALID" in type_text:
            self.val1_input.setPlaceholderText("（无需输入值）")
            self.val2_label.setVisible(False)
            self.val2_input.setVisible(False)
        elif "CUSTOM_FORMULA" in type_text:
            self.val1_input.setPlaceholderText("如 =LEN(A2)>5")
            self.val2_label.setVisible(False)
            self.val2_input.setVisible(False)
        else:
            self.val1_input.setPlaceholderText("值")
            self.val2_label.setVisible(False)
            self.val2_input.setVisible(False)

    def _build_rule(self):
        """构建 Google Sheets API 数据验证规则"""
        type_text = self.rule_type.currentText()

        if "ONE_OF_LIST" in type_text:
            items = [v.strip() for v in self.val1_input.text().split(',') if v.strip()]
            if not items:
                return None
            return {
                "condition": {
                    "type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": v} for v in items]
                },
                "showCustomUi": True,
                "strict": True
            }
        elif "NUMBER_BETWEEN" in type_text:
            v1 = self.val1_input.text().strip()
            v2 = self.val2_input.text().strip()
            if not v1 or not v2:
                return None
            return {
                "condition": {
                    "type": "NUMBER_BETWEEN",
                    "values": [
                        {"userEnteredValue": v1},
                        {"userEnteredValue": v2}
                    ]
                },
                "strict": True
            }
        elif "NUMBER_GREATER" in type_text:
            v = self.val1_input.text().strip()
            if not v:
                return None
            return {
                "condition": {
                    "type": "NUMBER_GREATER",
                    "values": [{"userEnteredValue": v}]
                },
                "strict": True
            }
        elif "NUMBER_LESS" in type_text:
            v = self.val1_input.text().strip()
            if not v:
                return None
            return {
                "condition": {
                    "type": "NUMBER_LESS",
                    "values": [{"userEnteredValue": v}]
                },
                "strict": True
            }
        elif "DATE_IS_VALID" in type_text:
            return {
                "condition": {"type": "DATE_IS_VALID"},
                "strict": True
            }
        elif "TEXT_CONTAINS" in type_text:
            v = self.val1_input.text().strip()
            if not v:
                return None
            return {
                "condition": {
                    "type": "TEXT_CONTAINS",
                    "values": [{"userEnteredValue": v}]
                }
            }
        elif "CUSTOM_FORMULA" in type_text:
            v = self.val1_input.text().strip()
            if not v:
                return None
            return {
                "condition": {
                    "type": "CUSTOM_FORMULA",
                    "values": [{"userEnteredValue": v}]
                }
            }
        return None

    def _get_ids(self):
        from ui.batch_backup_widget import extract_spreadsheet_id
        text = self.ids_input.toPlainText().strip()
        if text:
            return [extract_spreadsheet_id(l.strip()) for l in text.split('\n')
                    if extract_spreadsheet_id(l.strip())]
        elif self.controller and self.controller.service:
            return [self.controller.service.spreadsheet_id]
        return []

    def start_validation(self):
        ids = self._get_ids()
        if not ids:
            self.status_label.setText("⚠️ 请输入表格 ID")
            return

        rule = self._build_rule()
        if not rule:
            self.status_label.setText("⚠️ 请填写验证规则的值")
            return

        sheet_name = self.sheet_input.text().strip()
        sr = self.row_start.value() - 1
        er = self.row_end.value()
        col = self.col_input.text().strip()
        if not col.isalpha():
            self.status_label.setText("⚠️ 列格式无效")
            return
        sc = col_letter_to_index(col)
        ec = sc + 1

        self.start_btn.setEnabled(False)
        self.start_btn.setText("⏳ 设置中...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(ids))
        self.result_table.setRowCount(0)

        self._worker = BatchValidationWorker(ids, sheet_name, sr, er, sc, ec, rule)
        self._worker.progress.connect(lambda c, t, m: (
            self.progress_bar.setValue(c), self.status_label.setText(m)))
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, results):
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.result_table.setRowCount(len(results))
        for i, r in enumerate(results):
            self.result_table.setItem(i, 0, QTableWidgetItem(r.get("title", "—")))
            self.result_table.setItem(i, 1, QTableWidgetItem(r.get("id", "")[:25]))
            s = "✅" if r["status"] == "success" else "❌"
            item = QTableWidgetItem(s)
            if r["status"] == "error":
                item.setToolTip(r.get("error", ""))
            self.result_table.setItem(i, 2, item)

        ok = sum(1 for r in results if r["status"] == "success")
        self.status_label.setText(f"✅ 验证规则设置完成: {ok}/{len(results)}")
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 批量设置验证")
        self._worker = None

    def _on_error(self, msg):
        self.status_label.setText(f"❌ {msg}")
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 批量设置验证")
        self.progress_bar.setVisible(False)
        self._worker = None
