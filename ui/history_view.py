# 操作历史视图 — 记录所有已执行的命令及结果
import logging
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel, QHeaderView
)
from PySide6.QtCore import Qt

logger = logging.getLogger("sheets_toolkit.ui.history")


class HistoryView(QWidget):
    """
    操作历史面板 — 展示已执行命令的时间、描述和结果。
    支持撤销最近的可撤销操作。
    """

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 工具栏
        toolbar = QHBoxLayout()
        title = QLabel("📜 操作历史")
        title.setObjectName("section_title")

        self.undo_btn = QPushButton("↩️ 撤销上一步")
        self.undo_btn.setObjectName("secondary_btn")
        self.undo_btn.clicked.connect(self.undo_last)
        self.undo_btn.setMaximumWidth(130)

        clear_btn = QPushButton("🗑 清空")
        clear_btn.setObjectName("danger_btn")
        clear_btn.clicked.connect(self.clear_history)
        clear_btn.setMaximumWidth(80)

        toolbar.addWidget(title)
        toolbar.addStretch()
        toolbar.addWidget(self.undo_btn)
        toolbar.addWidget(clear_btn)
        layout.addLayout(toolbar)

        # 历史表格
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["时间", "操作", "结果", "可撤销"])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 90)
        self.table.setColumnWidth(3, 65)
        self.table.verticalHeader().setDefaultSectionSize(28)
        layout.addWidget(self.table)

    def add_entry(self, command, result_text, success=True):
        """添加一条历史记录"""
        row = self.table.rowCount()
        self.table.insertRow(row)

        time_str = datetime.now().strftime("%H:%M:%S")
        desc = getattr(command, 'description', str(command))
        is_undoable = getattr(command, 'is_undoable', False)

        self.table.setItem(row, 0, QTableWidgetItem(time_str))
        self.table.setItem(row, 1, QTableWidgetItem(desc))

        result_item = QTableWidgetItem(result_text if success else f"❌ {result_text}")
        self.table.setItem(row, 2, result_item)

        undo_text = "✅" if is_undoable else "—"
        self.table.setItem(row, 3, QTableWidgetItem(undo_text))

        # 滚动到最新行
        self.table.scrollToBottom()

    def undo_last(self):
        """撤销最近一条可撤销的操作"""
        if self.controller:
            result = self.controller.undo_last()
            if result:
                self.add_entry_text("撤销操作", result)

    def add_entry_text(self, desc, result_text):
        """添加简单文字记录"""
        row = self.table.rowCount()
        self.table.insertRow(row)
        time_str = datetime.now().strftime("%H:%M:%S")
        self.table.setItem(row, 0, QTableWidgetItem(time_str))
        self.table.setItem(row, 1, QTableWidgetItem(desc))
        self.table.setItem(row, 2, QTableWidgetItem(result_text))
        self.table.setItem(row, 3, QTableWidgetItem("—"))
        self.table.scrollToBottom()

    def clear_history(self):
        """清空历史记录"""
        self.table.setRowCount(0)
