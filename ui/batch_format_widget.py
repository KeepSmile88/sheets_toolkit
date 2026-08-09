# 批量格式化 UI 组件 — 批量设置多个表格的单元格格式
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar,
    QComboBox, QCheckBox, QSpinBox, QColorDialog,
    QGroupBox
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor

logger = logging.getLogger("sheets_toolkit.ui.batch_format")


def col_letter_to_index(letter):
    letter = letter.upper().strip()
    idx = 0
    for ch in letter:
        idx = idx * 26 + (ord(ch) - ord('A'))
    return idx


class BatchFormatWorker(QThread):
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, ids, sheet_name, sr, er, sc, ec, fmt):
        super().__init__()
        self.ids = ids
        self.sheet_name = sheet_name
        self.sr, self.er, self.sc, self.ec = sr, er, sc, ec
        self.fmt = fmt

    def run(self):
        try:
            from services.sheet_service import SheetService
            results = SheetService.batch_format_range(
                self.ids, self.sheet_name,
                self.sr, self.er, self.sc, self.ec,
                self.fmt, self._p
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _p(self, c, t, m):
        self.progress.emit(c, t, m)


class BatchFormatWidget(QWidget):
    """批量格式化面板"""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._worker = None
        self._bg_color = None
        self._fg_color = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        title = QLabel("🎨 批量格式化")
        title.setObjectName("section_title")
        layout.addWidget(title)

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
        self.row_start.setValue(1)
        pos_row.addWidget(self.row_start)
        pos_row.addWidget(QLabel("结束行:"))
        self.row_end = QSpinBox()
        self.row_end.setMinimum(1)
        self.row_end.setValue(10)
        self.row_end.setMaximum(99999)
        pos_row.addWidget(self.row_end)
        pos_row.addWidget(QLabel("起始列:"))
        self.col_start = QLineEdit("A")
        self.col_start.setMaximumWidth(40)
        pos_row.addWidget(self.col_start)
        pos_row.addWidget(QLabel("结束列:"))
        self.col_end = QLineEdit("Z")
        self.col_end.setMaximumWidth(40)
        pos_row.addWidget(self.col_end)
        layout.addLayout(pos_row)

        # 格式选项
        fmt_group = QGroupBox("格式选项")
        fmt_layout = QVBoxLayout(fmt_group)

        # 背景色
        bg_row = QHBoxLayout()
        self.use_bg = QCheckBox("背景色:")
        bg_row.addWidget(self.use_bg)
        self.bg_btn = QPushButton("  选择颜色  ")
        self.bg_btn.clicked.connect(self._pick_bg)
        bg_row.addWidget(self.bg_btn)
        self.bg_preview = QLabel("  ")
        self.bg_preview.setFixedWidth(30)
        bg_row.addWidget(self.bg_preview)
        bg_row.addStretch()
        fmt_layout.addLayout(bg_row)

        # 字体颜色
        fg_row = QHBoxLayout()
        self.use_fg = QCheckBox("字体颜色:")
        fg_row.addWidget(self.use_fg)
        self.fg_btn = QPushButton("  选择颜色  ")
        self.fg_btn.clicked.connect(self._pick_fg)
        fg_row.addWidget(self.fg_btn)
        self.fg_preview = QLabel("  ")
        self.fg_preview.setFixedWidth(30)
        fg_row.addWidget(self.fg_preview)
        fg_row.addStretch()
        fmt_layout.addLayout(fg_row)

        # 字体选项行
        font_row = QHBoxLayout()
        self.use_bold = QCheckBox("粗体")
        font_row.addWidget(self.use_bold)
        self.use_italic = QCheckBox("斜体")
        font_row.addWidget(self.use_italic)
        font_row.addWidget(QLabel("字号:"))
        self.font_size = QSpinBox()
        self.font_size.setMinimum(0)
        self.font_size.setMaximum(72)
        self.font_size.setValue(0)
        self.font_size.setSpecialValueText("默认")
        font_row.addWidget(self.font_size)
        font_row.addStretch()
        fmt_layout.addLayout(font_row)

        # 对齐
        align_row = QHBoxLayout()
        align_row.addWidget(QLabel("水平对齐:"))
        self.h_align = QComboBox()
        self.h_align.addItems(["不设置", "LEFT", "CENTER", "RIGHT"])
        align_row.addWidget(self.h_align)
        align_row.addWidget(QLabel("垂直对齐:"))
        self.v_align = QComboBox()
        self.v_align.addItems(["不设置", "TOP", "MIDDLE", "BOTTOM"])
        align_row.addWidget(self.v_align)
        align_row.addStretch()
        fmt_layout.addLayout(align_row)

        layout.addWidget(fmt_group)

        # 按钮
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("🚀 批量应用格式")
        self.start_btn.clicked.connect(self.start_format)
        btn_row.addWidget(self.start_btn)
        layout.addLayout(btn_row)

        # 进度/结果
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

    def _pick_bg(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self._bg_color = color
            self.bg_preview.setStyleSheet(f"background-color: {color.name()};")
            self.use_bg.setChecked(True)

    def _pick_fg(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self._fg_color = color
            self.fg_preview.setStyleSheet(f"background-color: {color.name()};")
            self.use_fg.setChecked(True)

    def _build_format(self):
        """构建 Google Sheets API 格式字典"""
        fmt = {}
        if self.use_bg.isChecked() and self._bg_color:
            fmt["backgroundColor"] = {
                "red": self._bg_color.redF(),
                "green": self._bg_color.greenF(),
                "blue": self._bg_color.blueF()
            }
        text_fmt = {}
        if self.use_fg.isChecked() and self._fg_color:
            text_fmt["foregroundColor"] = {
                "red": self._fg_color.redF(),
                "green": self._fg_color.greenF(),
                "blue": self._fg_color.blueF()
            }
        if self.use_bold.isChecked():
            text_fmt["bold"] = True
        if self.use_italic.isChecked():
            text_fmt["italic"] = True
        if self.font_size.value() > 0:
            text_fmt["fontSize"] = self.font_size.value()
        if text_fmt:
            fmt["textFormat"] = text_fmt
        if self.h_align.currentText() != "不设置":
            fmt["horizontalAlignment"] = self.h_align.currentText()
        if self.v_align.currentText() != "不设置":
            fmt["verticalAlignment"] = self.v_align.currentText()
        return fmt

    def _get_ids(self):
        from ui.batch_backup_widget import extract_spreadsheet_id
        text = self.ids_input.toPlainText().strip()
        if text:
            return [extract_spreadsheet_id(l.strip()) for l in text.split('\n')
                    if extract_spreadsheet_id(l.strip())]
        elif self.controller and self.controller.service:
            return [self.controller.service.spreadsheet_id]
        return []

    def start_format(self):
        ids = self._get_ids()
        if not ids:
            self.status_label.setText("⚠️ 请输入表格 ID")
            return

        fmt = self._build_format()
        if not fmt:
            self.status_label.setText("⚠️ 请至少选择一项格式")
            return

        sheet_name = self.sheet_input.text().strip()
        sr = self.row_start.value() - 1
        er = self.row_end.value()
        sc = col_letter_to_index(self.col_start.text())
        ec = col_letter_to_index(self.col_end.text()) + 1

        self.start_btn.setEnabled(False)
        self.start_btn.setText("⏳ 格式化中...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(ids))
        self.result_table.setRowCount(0)

        self._worker = BatchFormatWorker(ids, sheet_name, sr, er, sc, ec, fmt)
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
            self.result_table.setItem(i, 1, QTableWidgetItem(r.get("id", "—")[:25]))
            s = "✅" if r["status"] == "success" else "❌"
            item = QTableWidgetItem(s)
            if r["status"] == "error":
                item.setToolTip(r.get("error", ""))
            self.result_table.setItem(i, 2, item)

        ok = sum(1 for r in results if r["status"] == "success")
        self.status_label.setText(f"✅ 格式化完成: {ok}/{len(results)}")
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 批量应用格式")
        self._worker = None

    def _on_error(self, msg):
        self.status_label.setText(f"❌ {msg}")
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 批量应用格式")
        self.progress_bar.setVisible(False)
        self._worker = None
