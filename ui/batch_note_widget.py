# 批量备注管理 UI 组件 — 写入、删除、清除全部备注
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar,
    QRadioButton, QButtonGroup, QGroupBox
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger("sheets_toolkit.ui.batch_note")


def col_letter_to_index(letter):
    """列字母转 0-based 索引 (A=0, B=1, AA=26...)"""
    letter = letter.upper().strip()
    index = 0
    for ch in letter:
        index = index * 26 + (ord(ch) - ord('A'))
    return index


class BatchNoteWorker(QThread):
    """备注操作工作线程"""
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, spreadsheet_ids, action, sheet_name=None,
                 row=None, col=None, note_text=None):
        super().__init__()
        self.spreadsheet_ids = spreadsheet_ids
        self.action = action
        self.sheet_name = sheet_name
        self.row = row
        self.col = col
        self.note_text = note_text

    def run(self):
        try:
            from services.sheet_service import SheetService
            results = SheetService.batch_manage_notes(
                self.spreadsheet_ids,
                self.action,
                self.sheet_name,
                self.row,
                self.col,
                self.note_text,
                progress_callback=self._on_progress
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, current, total, message):
        self.progress.emit(current, total, message)


class BatchNoteWidget(QWidget):
    """
    批量备注管理面板。
    提供三种模式：
    1. 写入备注 — 向指定位置写入备注内容
    2. 删除备注 — 删除指定位置的备注
    3. 清除全部 — 删除所有工作表中的全部备注
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
        title = QLabel("💬 批量备注管理")
        title.setObjectName("section_title")
        layout.addWidget(title)

        # 表格 ID 输入
        layout.addWidget(QLabel("📄 表格链接/ID（每行一个）："))
        self.ids_input = ClearableTextEdit()
        self.ids_input.setPlaceholderText(
            "输入 Google Sheets 链接或 ID，每行一个\n"
            "如不输入，将使用当前连接的表格"
        )
        self.ids_input.setMaximumHeight(90)
        layout.addWidget(self.ids_input)

        # 操作模式选择
        mode_group = QGroupBox("操作模式")
        mode_layout = QHBoxLayout(mode_group)

        self.mode_group = QButtonGroup(self)

        self.radio_write = QRadioButton("✍️ 写入备注")
        self.radio_write.setChecked(True)
        self.mode_group.addButton(self.radio_write, 0)
        mode_layout.addWidget(self.radio_write)

        self.radio_delete = QRadioButton("❌ 删除备注")
        self.mode_group.addButton(self.radio_delete, 1)
        mode_layout.addWidget(self.radio_delete)

        self.radio_clear = QRadioButton("🗑 清除全部备注")
        self.mode_group.addButton(self.radio_clear, 2)
        mode_layout.addWidget(self.radio_clear)

        self.mode_group.idToggled.connect(self._on_mode_changed)
        layout.addWidget(mode_group)

        # 参数区（写入/删除模式用）
        self.params_widget = QWidget()
        params = QVBoxLayout(self.params_widget)
        params.setContentsMargins(0, 0, 0, 0)

        row1 = QHBoxLayout()

        row1.addWidget(QLabel("📋 工作表名："))
        self.sheet_name_input = QLineEdit("Sheet1")
        self.sheet_name_input.setMaximumWidth(150)
        row1.addWidget(self.sheet_name_input)

        row1.addWidget(QLabel("📍 行号："))
        self.row_input = QLineEdit()
        self.row_input.setPlaceholderText("如 1（第1行）")
        self.row_input.setMaximumWidth(80)
        row1.addWidget(self.row_input)

        row1.addWidget(QLabel("列："))
        self.col_input = QLineEdit()
        self.col_input.setPlaceholderText("如 A")
        self.col_input.setMaximumWidth(60)
        row1.addWidget(self.col_input)

        params.addLayout(row1)

        # 备注内容（仅写入模式用）
        self.note_label = QLabel("📝 备注内容：")
        params.addWidget(self.note_label)

        self.note_input = ClearableTextEdit()
        self.note_input.setPlaceholderText("输入要写入的备注内容...")
        self.note_input.setMaximumHeight(60)
        params.addWidget(self.note_input)

        layout.addWidget(self.params_widget)

        # 按钮
        btn_row = QHBoxLayout()

        self.start_btn = QPushButton("🚀 执行")
        self.start_btn.clicked.connect(self.start_operation)
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
        self.result_table.setColumnCount(4)
        self.result_table.setHorizontalHeaderLabels(
            ["表格标题", "详情", "状态", "ID"]
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
        self.result_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch
        )
        self.result_table.verticalHeader().setDefaultSectionSize(28)
        layout.addWidget(self.result_table)

    def _on_mode_changed(self, button_id, checked):
        """切换操作模式时更新 UI"""
        if not checked:
            return
        mode = self.mode_group.checkedId()
        if mode == 2:  # 清除全部
            self.params_widget.setVisible(False)
            self.start_btn.setText("🚀 清除所有表格的全部备注")
        else:
            self.params_widget.setVisible(True)
            if mode == 0:  # 写入
                self.note_label.setVisible(True)
                self.note_input.setVisible(True)
                self.start_btn.setText("🚀 批量写入备注")
            else:  # 删除
                self.note_label.setVisible(False)
                self.note_input.setVisible(False)
                self.start_btn.setText("🚀 批量删除备注")

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

    def start_operation(self):
        """开始执行备注操作"""
        ids = self._get_ids()
        if not ids:
            self.status_label.setText("⚠️ 请输入表格 ID 或先连接表格")
            return

        mode = self.mode_group.checkedId()

        if mode == 2:
            # 清除全部备注
            action = "clear_all"
            sheet_name = None
            row = None
            col = None
            note_text = None
            self._log(f"🚀 开始清除 {len(ids)} 个表格的全部备注")
        else:
            sheet_name = self.sheet_name_input.text().strip()
            if not sheet_name:
                self.status_label.setText("⚠️ 请输入工作表名称")
                return

            row_text = self.row_input.text().strip()
            col_text = self.col_input.text().strip()

            if not row_text or not col_text:
                self.status_label.setText("⚠️ 请输入行号和列")
                return

            try:
                row = int(row_text) - 1  # 用户输入的是 1-based
                if row < 0:
                    raise ValueError()
            except ValueError:
                self.status_label.setText("⚠️ 行号格式无效（请输入正整数）")
                return

            if not col_text.isalpha():
                self.status_label.setText("⚠️ 列格式无效（请输入字母如 A, B, C）")
                return

            col = col_letter_to_index(col_text)

            if mode == 0:
                # 写入备注
                action = "write"
                note_text = self.note_input.toPlainText()
                if not note_text.strip():
                    self.status_label.setText("⚠️ 请输入备注内容")
                    return
                col_letter = col_text.upper()
                self._log(
                    f"🚀 批量写入备注到 {len(ids)} 个表格: "
                    f"{sheet_name}!{col_letter}{row + 1}"
                )
            else:
                # 删除备注
                action = "delete"
                note_text = None
                col_letter = col_text.upper()
                self._log(
                    f"🚀 批量删除 {len(ids)} 个表格的备注: "
                    f"{sheet_name}!{col_letter}{row + 1}"
                )

        # 禁用按钮，启动线程
        self.start_btn.setEnabled(False)
        self.start_btn.setText("⏳ 处理中...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(ids))
        self.progress_bar.setValue(0)
        self.result_table.setRowCount(0)

        self._worker = BatchNoteWorker(
            ids, action, sheet_name, row, col, note_text
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, current, total, message):
        self.progress_bar.setValue(current)
        self.status_label.setText(message)
        self._log(f"💬 {message}")

    def _on_finished(self, results):
        self.progress_bar.setValue(self.progress_bar.maximum())

        self.result_table.setRowCount(len(results))
        for i, r in enumerate(results):
            self.result_table.setItem(
                i, 0, QTableWidgetItem(r.get("title", "—"))
            )
            self.result_table.setItem(
                i, 1, QTableWidgetItem(r.get("detail", "—"))
            )
            status = "✅" if r["status"] == "success" else "❌"
            item = QTableWidgetItem(status)
            if r["status"] == "error":
                item.setToolTip(r.get("detail", ""))
            self.result_table.setItem(i, 2, item)
            self.result_table.setItem(
                i, 3, QTableWidgetItem(r.get("id", "—")[:25] + "...")
            )

        success = sum(1 for r in results if r["status"] == "success")
        msg = f"✅ 备注操作完成: {success}/{len(results)} 成功"
        self.status_label.setText(msg)
        self._log(msg)

        self._restore_btn()

    def _on_error(self, error_msg):
        self.status_label.setText(f"❌ 操作失败: {error_msg}")
        self._log(f"❌ 备注操作失败: {error_msg}")
        self._restore_btn()

    def _restore_btn(self):
        self.start_btn.setEnabled(True)
        mode = self.mode_group.checkedId()
        if mode == 0:
            self.start_btn.setText("🚀 批量写入备注")
        elif mode == 1:
            self.start_btn.setText("🚀 批量删除备注")
        else:
            self.start_btn.setText("🚀 清除所有表格的全部备注")
        self.progress_bar.setVisible(False)
        self._worker = None

    def clear_all(self):
        self.ids_input.clear()
        self.note_input.clear()
        self.result_table.setRowCount(0)
        self.status_label.setText("")
        self.progress_bar.setVisible(False)

    def _log(self, text):
        if self.controller and self.controller.view:
            self.controller.view.log(text)
