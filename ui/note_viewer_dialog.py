# 批注查看器 — 独立大窗口，查看指定表格区域的批注内容
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QSplitter, QGroupBox, QSpinBox,
    QProgressBar, QMessageBox
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import Qt, QThread, Signal

logger = logging.getLogger("sheets_toolkit.ui.note_viewer_dialog")


class NoteFetchWorker(QThread):
    """后台线程 — 获取指定区域的批注"""
    progress = Signal(str)
    finished = Signal(list)
    error = Signal(str)
    sheets_loaded = Signal(list)  # 工作表列表加载完成

    def __init__(self, spreadsheet_id, sheet_name=None,
                 start_row=0, end_row=None, start_col=0, end_col=None):
        super().__init__()
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.start_row = start_row
        self.end_row = end_row
        self.start_col = start_col
        self.end_col = end_col
        self._load_sheets_only = False

    def set_load_sheets_only(self, flag):
        """设置为仅加载工作表列表模式"""
        self._load_sheets_only = flag

    def run(self):
        try:
            from services.sheet_service import SheetService
            service = SheetService(self.spreadsheet_id)

            if self._load_sheets_only:
                self.progress.emit("正在获取工作表列表...")
                sheets = service.list_sheets()
                self.sheets_loaded.emit(sheets)
                return

            if not self.sheet_name:
                self.error.emit("请选择工作表")
                return

            self.progress.emit(f"正在获取 {self.sheet_name} 的批注数据...")
            notes = service.get_notes_in_range(
                self.sheet_name,
                start_row=self.start_row,
                end_row=self.end_row,
                start_col=self.start_col,
                end_col=self.end_col
            )
            self.finished.emit(notes)
        except Exception as e:
            self.error.emit(str(e))


class NoteViewerDialog(QDialog):
    """
    批注查看器 — 独立大窗口。

    支持选择工作表、指定区域，查看该区域内所有批注。
    下方详情面板可展示长批注的完整内容。
    """

    def __init__(self, spreadsheet_id, spreadsheet_name="", parent=None):
        super().__init__(parent)
        self.spreadsheet_id = spreadsheet_id
        self.spreadsheet_name = spreadsheet_name
        self._worker = None
        self._notes_data = []
        self._setup_ui()
        self._load_sheets()

    def _setup_ui(self):
        self.setWindowTitle(f"📝 批注查看器 — {self.spreadsheet_name or self.spreadsheet_id[:15]}")
        self.setMinimumSize(800, 550)
        self.resize(900, 650)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ======= 顶部工具栏 =======
        toolbar = QGroupBox("查询条件")
        tl = QVBoxLayout(toolbar)

        # 第一行：工作表选择
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("工作表:"))
        self.sheet_combo = QComboBox()
        self.sheet_combo.setMinimumWidth(150)
        self.sheet_combo.setPlaceholderText("加载中...")
        row1.addWidget(self.sheet_combo)
        row1.addStretch()
        tl.addLayout(row1)

        # 第二行：范围设置
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("起始行:"))
        self.start_row_spin = QSpinBox()
        self.start_row_spin.setRange(1, 99999)
        self.start_row_spin.setValue(1)
        self.start_row_spin.setToolTip("1-based 行号（留 1 表示从头开始）")
        row2.addWidget(self.start_row_spin)

        row2.addWidget(QLabel("结束行:"))
        self.end_row_spin = QSpinBox()
        self.end_row_spin.setRange(0, 99999)
        self.end_row_spin.setValue(0)
        self.end_row_spin.setToolTip("0 表示不限制")
        self.end_row_spin.setSpecialValueText("不限")
        row2.addWidget(self.end_row_spin)

        row2.addWidget(QLabel("起始列:"))
        self.start_col_input = QLineEdit("A")
        self.start_col_input.setMaximumWidth(50)
        self.start_col_input.setToolTip("列字母，如 A")
        row2.addWidget(self.start_col_input)

        row2.addWidget(QLabel("结束列:"))
        self.end_col_input = QLineEdit("")
        self.end_col_input.setMaximumWidth(50)
        self.end_col_input.setPlaceholderText("不限")
        self.end_col_input.setToolTip("列字母，如 Z（留空不限制）")
        row2.addWidget(self.end_col_input)

        self.load_btn = QPushButton("🔍 加载批注")
        self.load_btn.clicked.connect(self._load_notes)
        row2.addWidget(self.load_btn)

        tl.addLayout(row2)
        layout.addWidget(toolbar)

        # ======= 中间：表格 + 详情分割 =======
        splitter = QSplitter(Qt.Vertical)

        # 批注概览表格
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["单元格", "批注摘要", "完整批注"])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnHidden(2, True)  # 隐藏完整批注列（用于数据存储）
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.currentCellChanged.connect(self._on_row_select)
        splitter.addWidget(self.table)

        # 详情面板
        detail_group = QGroupBox("📄 批注详情")
        dl = QVBoxLayout(detail_group)
        self.detail_text = ClearableTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setPlaceholderText("选中上方列表中的某条批注即可在此查看完整内容")
        self.detail_text.setMinimumHeight(120)
        dl.addWidget(self.detail_text)
        splitter.addWidget(detail_group)

        splitter.setSizes([350, 200])
        layout.addWidget(splitter)

        # ======= 底部状态栏 =======
        bottom = QHBoxLayout()
        self.status_label = QLabel("")
        bottom.addWidget(self.status_label)
        bottom.addStretch()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(200)
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)  # 不确定进度模式
        bottom.addWidget(self.progress)
        layout.addLayout(bottom)

    # ========================
    # 列字母转换
    # ========================

    @staticmethod
    def _col_letter_to_index(letter):
        """将列字母转换为 0-based 索引（A=0, B=1, ..., AA=26）"""
        letter = letter.strip().upper()
        if not letter:
            return None
        result = 0
        for ch in letter:
            if not ch.isalpha():
                return None
            result = result * 26 + (ord(ch) - ord('A') + 1)
        return result - 1

    # ========================
    # 加载工作表列表
    # ========================

    def _load_sheets(self):
        """异步加载工作表列表"""
        self._worker = NoteFetchWorker(self.spreadsheet_id)
        self._worker.set_load_sheets_only(True)
        self._worker.sheets_loaded.connect(self._on_sheets_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.progress.connect(lambda msg: self.status_label.setText(msg))
        self.progress.setVisible(True)
        self._worker.start()

    def _on_sheets_loaded(self, sheets):
        """工作表列表加载完成"""
        self.progress.setVisible(False)
        self.sheet_combo.clear()
        self.sheet_combo.addItems(sheets)
        self.status_label.setText(f"✅ 已加载 {len(sheets)} 个工作表，请选择后点击加载批注")
        self._worker = None

    # ========================
    # 加载批注
    # ========================

    def _load_notes(self):
        """触发批注加载"""
        sheet_name = self.sheet_combo.currentText()
        if not sheet_name:
            self.status_label.setText("⚠️ 请先选择工作表")
            return

        # 解析范围参数
        start_row = self.start_row_spin.value() - 1  # 转为 0-based
        end_row_val = self.end_row_spin.value()
        end_row = end_row_val if end_row_val > 0 else None

        start_col_letter = self.start_col_input.text().strip()
        start_col = self._col_letter_to_index(start_col_letter)
        if start_col is None:
            start_col = 0

        end_col_letter = self.end_col_input.text().strip()
        end_col = self._col_letter_to_index(end_col_letter)
        if end_col is not None:
            end_col += 1  # 转为半开区间

        self.load_btn.setEnabled(False)
        self.load_btn.setText("⏳ 加载中...")
        self.progress.setVisible(True)
        self.table.setRowCount(0)
        self.detail_text.clear()

        self._worker = NoteFetchWorker(
            self.spreadsheet_id, sheet_name,
            start_row=start_row, end_row=end_row,
            start_col=start_col, end_col=end_col
        )
        self._worker.finished.connect(self._on_notes_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.progress.connect(lambda msg: self.status_label.setText(msg))
        self._worker.start()

    def _on_notes_loaded(self, notes):
        """批注加载完成 — 填充表格"""
        self.progress.setVisible(False)
        self.load_btn.setEnabled(True)
        self.load_btn.setText("🔍 加载批注")
        self._notes_data = notes
        self._worker = None

        self.table.setRowCount(len(notes))
        for i, n in enumerate(notes):
            # 单元格位置
            cell_item = QTableWidgetItem(n["cell"])
            cell_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 0, cell_item)

            # 批注摘要（最多显示 80 字符）
            note_text = n["note"]
            summary = note_text.replace("\n", " ")[:80]
            if len(note_text) > 80:
                summary += "..."
            self.table.setItem(i, 1, QTableWidgetItem(summary))

            # 完整批注（隐藏列，存储用）
            self.table.setItem(i, 2, QTableWidgetItem(note_text))

        self.status_label.setText(f"📝 共找到 {len(notes)} 条批注")

        # 自动选中第一行
        if notes:
            self.table.selectRow(0)

    def _on_error(self, msg):
        """错误处理"""
        self.progress.setVisible(False)
        self.load_btn.setEnabled(True)
        self.load_btn.setText("🔍 加载批注")
        self.status_label.setText(f"❌ {msg}")
        self._worker = None
        QMessageBox.warning(self, "错误", f"操作失败：\n{msg}")

    # ========================
    # 详情展示
    # ========================

    def _on_row_select(self, row, col, prev_row, prev_col):
        """选中行时在详情面板展示完整批注"""
        if row < 0 or row >= self.table.rowCount():
            self.detail_text.clear()
            return

        full_note_item = self.table.item(row, 2)
        cell_item = self.table.item(row, 0)
        if full_note_item and cell_item:
            cell_label = cell_item.text()
            self.detail_text.setPlainText(
                f"📍 单元格: {cell_label}\n"
                f"{'─' * 40}\n"
                f"{full_note_item.text()}"
            )
