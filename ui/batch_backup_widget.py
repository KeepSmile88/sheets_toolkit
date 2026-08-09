# 批量备份 UI 组件 — 支持输入多个表格链接/ID + 目标文件夹 ID
import re
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import Qt, QThread, Signal

logger = logging.getLogger("sheets_toolkit.ui.batch_backup")


def extract_spreadsheet_id(text):
    """
    从 Google Sheets 链接或纯 ID 中提取 Spreadsheet ID。
    支持格式：
      - https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
      - https://docs.google.com/spreadsheets/d/SPREADSHEET_ID
      - 纯 ID 字符串
    """
    text = text.strip()
    if not text:
        return None

    # 尝试从 URL 提取
    pattern = r'/spreadsheets/d/([a-zA-Z0-9_-]+)'
    match = re.search(pattern, text)
    if match:
        return match.group(1)

    # 如果不是 URL，视为纯 ID（至少 20 个字符的字母数字串）
    if re.match(r'^[a-zA-Z0-9_-]{10,}$', text):
        return text

    return None


class BatchBackupWorker(QThread):
    """批量备份工作线程"""
    progress = Signal(int, int, str)  # current, total, message
    finished = Signal(list)           # results
    error = Signal(str)               # error message

    def __init__(self, spreadsheet_ids, folder_id):
        super().__init__()
        self.spreadsheet_ids = spreadsheet_ids
        self.folder_id = folder_id

    def run(self):
        try:
            from services.sheet_service import SheetService
            results = SheetService.batch_backup_to_folder(
                self.spreadsheet_ids,
                self.folder_id,
                progress_callback=self._on_progress
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, current, total, message):
        self.progress.emit(current, total, message)


class BatchBackupWidget(QWidget):
    """
    批量备份面板。
    用户可输入多个 Google Sheets 链接或 ID（每行一个），
    指定目标 Google Drive 文件夹 ID，一键批量备份。
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
        title = QLabel("📦 批量备份")
        title.setObjectName("section_title")
        layout.addWidget(title)

        # 说明
        help_label = QLabel(
            "将多个 Google Sheets 备份到指定的 Drive 文件夹中。\n"
            "每行输入一个表格链接或 ID，支持直接粘贴 Google Sheets URL。"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        # 表格链接输入区
        layout.addWidget(QLabel("📄 表格链接/ID（每行一个）："))
        self.ids_input = ClearableTextEdit()
        self.ids_input.setPlaceholderText(
            "粘贴 Google Sheets 链接或 ID，每行一个，例如：\n"
            "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit\n"
            "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit\n"
            "或直接输入 ID：1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"
        )
        self.ids_input.setMaximumHeight(150)
        layout.addWidget(self.ids_input)

        # 目标文件夹 ID
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("📁 目标文件夹 ID："))
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText(
            "输入 Google Drive 文件夹 ID（从文件夹 URL 中获取）"
        )
        folder_row.addWidget(self.folder_input)
        layout.addLayout(folder_row)

        # 按钮行
        btn_row = QHBoxLayout()

        self.start_btn = QPushButton("🚀 开始批量备份")
        self.start_btn.clicked.connect(self.start_backup)
        btn_row.addWidget(self.start_btn)

        self.parse_btn = QPushButton("🔍 解析预览")
        self.parse_btn.setObjectName("secondary_btn")
        self.parse_btn.clicked.connect(self.preview_ids)
        btn_row.addWidget(self.parse_btn)

        clear_btn = QPushButton("🗑 清空")
        clear_btn.setObjectName("danger_btn")
        clear_btn.clicked.connect(self.clear_all)
        clear_btn.setMaximumWidth(80)
        btn_row.addWidget(clear_btn)

        layout.addLayout(btn_row)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # 状态标签
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # 结果表格
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(4)
        self.result_table.setHorizontalHeaderLabels(
            ["源表格标题", "源 ID", "备份 ID", "状态"]
        )
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.result_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.result_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch
        )
        self.result_table.setColumnWidth(3, 80)
        self.result_table.verticalHeader().setDefaultSectionSize(28)
        layout.addWidget(self.result_table)

    def _parse_ids(self):
        """解析输入文本，提取所有 Spreadsheet ID"""
        text = self.ids_input.toPlainText()
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

    def preview_ids(self):
        """解析并预览提取的 ID"""
        ids, invalid = self._parse_ids()

        self.result_table.setRowCount(len(ids) + len(invalid))
        for i, sid in enumerate(ids):
            self.result_table.setItem(i, 0, QTableWidgetItem("—"))
            self.result_table.setItem(i, 1, QTableWidgetItem(sid))
            self.result_table.setItem(i, 2, QTableWidgetItem("—"))
            self.result_table.setItem(i, 3, QTableWidgetItem("✅ 有效"))

        for j, line in enumerate(invalid):
            row = len(ids) + j
            self.result_table.setItem(row, 0, QTableWidgetItem("—"))
            self.result_table.setItem(row, 1, QTableWidgetItem(line[:40]))
            self.result_table.setItem(row, 2, QTableWidgetItem("—"))
            self.result_table.setItem(row, 3, QTableWidgetItem("❌ 无效"))

        self.status_label.setText(
            f"解析完成: {len(ids)} 个有效 ID, {len(invalid)} 个无效输入"
        )
        self._log(
            f"🔍 解析预览: {len(ids)} 个有效 ID, {len(invalid)} 个无效"
        )

    def start_backup(self):
        """开始批量备份"""
        ids, invalid = self._parse_ids()
        folder_id = self.folder_input.text().strip()

        if not ids:
            self.status_label.setText("⚠️ 请输入至少一个有效的表格链接或 ID")
            self._log("⚠️ 没有找到有效的表格 ID")
            return

        if not folder_id:
            self.status_label.setText("⚠️ 请输入目标文件夹 ID")
            self._log("⚠️ 请输入目标文件夹 ID")
            return

        if invalid:
            self._log(f"⚠️ 跳过 {len(invalid)} 个无效输入")

        # 禁用按钮
        self.start_btn.setEnabled(False)
        self.start_btn.setText("⏳ 备份中...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(ids))
        self.progress_bar.setValue(0)
        self.result_table.setRowCount(0)

        self._log(f"🚀 开始批量备份 {len(ids)} 个表格到文件夹 {folder_id}")

        # 启动工作线程
        self._worker = BatchBackupWorker(ids, folder_id)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, current, total, message):
        """进度回调"""
        self.progress_bar.setValue(current)
        self.status_label.setText(message)
        self._log(f"📦 {message}")

    def _on_finished(self, results):
        """备份完成回调"""
        self.progress_bar.setValue(self.progress_bar.maximum())

        # 填充结果表格
        self.result_table.setRowCount(len(results))
        for i, r in enumerate(results):
            self.result_table.setItem(
                i, 0, QTableWidgetItem(r.get("source_title", "—"))
            )
            self.result_table.setItem(
                i, 1, QTableWidgetItem(r.get("source_id", "—")[:25] + "...")
            )
            self.result_table.setItem(
                i, 2, QTableWidgetItem(r.get("backup_id", "—") or "—")
            )
            status = "✅" if r["status"] == "success" else "❌"
            status_item = QTableWidgetItem(status)
            if r["status"] == "error":
                status_item.setToolTip(r.get("error", ""))
            self.result_table.setItem(i, 3, status_item)

        success = sum(1 for r in results if r["status"] == "success")
        total = len(results)
        msg = f"✅ 批量备份完成: {success}/{total} 成功"
        self.status_label.setText(msg)
        self._log(msg)

        # 恢复按钮
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 开始批量备份")
        self._worker = None

    def _on_error(self, error_msg):
        """错误回调"""
        self.status_label.setText(f"❌ 批量备份失败: {error_msg}")
        self._log(f"❌ 批量备份失败: {error_msg}")
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 开始批量备份")
        self.progress_bar.setVisible(False)
        self._worker = None

    def clear_all(self):
        """清空所有输入和结果"""
        self.ids_input.clear()
        self.folder_input.clear()
        self.result_table.setRowCount(0)
        self.status_label.setText("")
        self.progress_bar.setVisible(False)

    def _log(self, text):
        """输出日志到主窗口"""
        if self.controller and self.controller.view:
            self.controller.view.log(text)
