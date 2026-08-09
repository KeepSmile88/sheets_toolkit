# 数据预览组件 — 在 QTableWidget 中展示 Sheet 数据
# 支持手动拖拽列宽 + 一键自适应列宽
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel, QHeaderView
)
from PySide6.QtCore import Qt

logger = logging.getLogger("sheets_toolkit.ui.data_preview")


class DataPreviewWidget(QWidget):
    """
    数据预览面板：在表格中展示从 Google Sheets 读取的数据。
    支持刷新、手动拖拽列宽、一键自适应列宽。
    """

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._data = []
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 工具栏
        toolbar = QHBoxLayout()
        self.info_label = QLabel("📊 数据预览 — 请先连接表格并点击刷新")
        self.info_label.setObjectName("section_title")

        self.refresh_btn = QPushButton("🔄 刷新数据")
        self.refresh_btn.setObjectName("secondary_btn")
        self.refresh_btn.clicked.connect(self.refresh_data)
        self.refresh_btn.setMaximumWidth(120)

        self.auto_fit_btn = QPushButton("📐 自适应列宽")
        self.auto_fit_btn.clicked.connect(self.auto_fit_columns)
        self.auto_fit_btn.setMaximumWidth(120)

        self.stretch_btn = QPushButton("↔️ 均匀拉伸")
        self.stretch_btn.clicked.connect(self.stretch_columns)
        self.stretch_btn.setMaximumWidth(120)

        toolbar.addWidget(self.info_label)
        toolbar.addStretch()
        toolbar.addWidget(self.auto_fit_btn)
        toolbar.addWidget(self.stretch_btn)
        toolbar.addWidget(self.refresh_btn)
        layout.addLayout(toolbar)

        # 数据表格（默认支持手动拖拽列宽）
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        # 使用 Interactive 模式：允许手动拖拽调整列宽
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Interactive
        )
        # 最后一列拉伸填充剩余空间
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(28)
        # 允许双击表头边缘自适应该列宽度
        self.table.horizontalHeader().setSectionsClickable(True)

        layout.addWidget(self.table)

    def refresh_data(self):
        """从 Controller 获取当前 Sheet 数据"""
        if not self.controller.service:
            self.info_label.setText("⚠️ 请先连接表格")
            return

        try:
            view = self.controller.view
            sheet_name = view.sheet_list.currentText()
            if not sheet_name:
                self.info_label.setText("⚠️ 请先选择工作表")
                return

            # 直接传入工作表名称，即可获取该工作表所有已使用区域的数据
            range_str = sheet_name
            self.info_label.setText("⏳ 正在拉取数据，请稍候...")
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()

            data = self.controller.service.read_data(range_str)

            truncate_msg = ""
            if data and len(data) > 1000:
                data = data[:1000]
                truncate_msg = " (⚠️ 数据量过大，为防止卡顿仅渲染前 1000 行)"

            self.set_data(data)

            if truncate_msg:
                self.info_label.setText(self.info_label.text() + truncate_msg)

        except Exception as e:
            self.info_label.setText(f"❌ 读取失败: {str(e)}")
            logger.error(f"数据预览刷新失败: {e}")

    def showEvent(self, event):
        """当预览面板可见时，自动触发表格数据刷新"""
        super().showEvent(event)
        if self.controller.is_connected:
            self.refresh_data()

    def set_data(self, data):
        """设置表格数据"""
        self._data = data
        self.table.clear()

        if not data:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.info_label.setText("📊 暂无数据")
            return

        # 第一行作为表头
        headers = data[0] if data else []
        rows = data[1:] if len(data) > 1 else []
        max_cols = max(len(row) for row in data) if data else 0

        self.table.setColumnCount(max_cols)
        self.table.setRowCount(len(rows))

        # 设置表头
        header_labels = []
        for i in range(max_cols):
            if i < len(headers):
                header_labels.append(str(headers[i]))
            else:
                header_labels.append(f"列{i + 1}")
        self.table.setHorizontalHeaderLabels(header_labels)

        # 填充数据
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                item = QTableWidgetItem(str(cell))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, item)

        # 数据加载后自动适应列宽
        self.auto_fit_columns()

        self.info_label.setText(f"📊 共 {len(rows)} 行 × {max_cols} 列")
        logger.info(f"数据预览已刷新: {len(rows)} 行 × {max_cols} 列")

    def auto_fit_columns(self):
        """自适应列宽：根据内容调整每列宽度"""
        header = self.table.horizontalHeader()
        # 先切换到 ResizeToContents 自动计算
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        # 立即切回 Interactive 以允许后续手动拖拽
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Interactive
        )
        # 最后一列仍然拉伸
        self.table.horizontalHeader().setStretchLastSection(True)

    def stretch_columns(self):
        """均匀拉伸：所有列等宽填满表格"""
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )

    @property
    def data(self):
        return self._data
