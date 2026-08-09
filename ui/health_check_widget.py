# 健康检查 UI 组件 — 扫描多个表格的公式错误、空表、修改时间等
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QTreeWidget, QTreeWidgetItem
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import Qt, QThread, Signal

logger = logging.getLogger("sheets_toolkit.ui.health_check")


class HealthCheckWorker(QThread):
    """健康检查工作线程"""
    progress = Signal(str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, spreadsheet_ids):
        super().__init__()
        self.spreadsheet_ids = spreadsheet_ids

    def run(self):
        try:
            from services.sheet_service import SheetService
            reports = []
            total = len(self.spreadsheet_ids)
            for i, sid in enumerate(self.spreadsheet_ids):
                sid = sid.strip()
                if not sid:
                    continue
                self.progress.emit(f"🔍 检查 ({i+1}/{total})...")
                try:
                    service = SheetService(sid)
                    report = service.health_check()
                    report["status"] = "success"
                    reports.append(report)
                except Exception as e:
                    reports.append({
                        "title": sid[:20] + "...",
                        "spreadsheet_id": sid,
                        "status": "error",
                        "error": str(e)
                    })
            self.finished.emit(reports)
        except Exception as e:
            self.error.emit(str(e))


class HealthCheckWidget(QWidget):
    """表格健康检查面板"""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._worker = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        title = QLabel("🏥 表格健康检查")
        title.setObjectName("section_title")
        layout.addWidget(title)

        help_label = QLabel(
            "扫描表格中的公式错误、空工作表、数据量等健康指标。"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        # 输入
        layout.addWidget(QLabel("📄 表格链接/ID（每行一个）："))
        self.ids_input = ClearableTextEdit()
        self.ids_input.setPlaceholderText("输入链接或 ID，不输入则使用当前连接的表格")
        self.ids_input.setMaximumHeight(80)
        layout.addWidget(self.ids_input)

        # 按钮
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("🚀 开始检查")
        self.start_btn.clicked.connect(self.start_check)
        btn_row.addWidget(self.start_btn)
        layout.addLayout(btn_row)

        # 进度
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # 结果树
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["项目", "值"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 300)
        layout.addWidget(self.tree)

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

    def start_check(self):
        ids = self._get_ids()
        if not ids:
            self.status_label.setText("⚠️ 请输入表格 ID")
            return

        self.start_btn.setEnabled(False)
        self.start_btn.setText("⏳ 检查中...")
        self.progress_bar.setVisible(True)
        self.tree.clear()

        self._worker = HealthCheckWorker(ids)
        self._worker.progress.connect(lambda m: self.status_label.setText(m))
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, reports):
        self.progress_bar.setVisible(False)
        self.tree.clear()

        total_errors = 0
        total_empty = 0

        for report in reports:
            # 每个表格一个顶层节点
            root = QTreeWidgetItem(self.tree)
            title = report.get("title", "未知")
            status = report.get("status", "error")

            if status == "error":
                root.setText(0, f"❌ {title}")
                root.setText(1, report.get("error", "未知错误"))
                continue

            errors = report.get("errors_found", 0)
            empty = report.get("empty_sheets", 0)
            total_errors += errors
            total_empty += empty

            icon = "✅" if errors == 0 else "⚠️"
            root.setText(0, f"{icon} {title}")
            root.setText(1, f"{report.get('sheet_count',0)} 个工作表, {report.get('total_rows',0)} 行数据")

            # 基本信息
            info = QTreeWidgetItem(root)
            info.setText(0, "📋 基本信息")
            info.setText(1, f"最后修改: {report.get('last_modified','未知')[:19]}")

            if report.get("owner"):
                owner = QTreeWidgetItem(root)
                owner.setText(0, "👤 所有者")
                owner.setText(1, report.get("owner", ""))

            # 空工作表
            if empty > 0:
                empty_node = QTreeWidgetItem(root)
                empty_node.setText(0, f"📭 空工作表")
                empty_node.setText(1, f"{empty} 个")

            # 各工作表
            for sheet in report.get("sheets", []):
                s_node = QTreeWidgetItem(root)
                s_name = sheet.get("name", "")
                s_errors = sheet.get("errors", [])
                s_icon = "✅" if not s_errors else "❌"
                s_node.setText(0, f"{s_icon} {s_name}")
                rows_info = f"{sheet.get('data_rows', 0)} 行数据"
                if sheet.get("is_empty"):
                    rows_info = "空表"
                s_node.setText(1, rows_info)

                # 错误详情
                for err in s_errors:
                    err_node = QTreeWidgetItem(s_node)
                    err_node.setText(0, f"  🔴 {err['cell']}: {err['error']}")
                    err_node.setText(1, err.get("value", ""))

        self.tree.expandAll()

        msg = f"✅ 检查完成: {len(reports)} 个表格, {total_errors} 个错误, {total_empty} 个空表"
        self.status_label.setText(msg)
        self._log(msg)

        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 开始检查")
        self._worker = None

    def _on_error(self, msg):
        self.status_label.setText(f"❌ {msg}")
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 开始检查")
        self.progress_bar.setVisible(False)
        self._worker = None

    def _log(self, text):
        if self.controller and self.controller.view:
            self.controller.view.log(text)
