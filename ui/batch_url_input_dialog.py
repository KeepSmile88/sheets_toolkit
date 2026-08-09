import re
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt

class BatchUrlInputDialog(QDialog):
    """
    手动批量输入表格链接对话框。
    允许用户粘贴包含换行的多个链接，通过正则解析出 Spreadsheet IDs。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔗 批量导入表格链接")
        self.setMinimumSize(500, 400)
        self.entries = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("请输入或粘贴要批量处理的 Google Sheets 链接：")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        desc = QLabel(
            "提示：可以一次性粘贴多行。即使混入文字，程序也能自动从中提取出合法的表格 ID。"
        )
        desc.setStyleSheet("color: gray;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(
            "例如:\n"
            "https://docs.google.com/spreadsheets/d/1BxiMVs0X_x_x/edit\n"
            "1BxiMVs0X_x_x\n"
            "..."
        )
        layout.addWidget(self.text_edit)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.parse_btn = QPushButton("解析并导入")
        self.parse_btn.setStyleSheet("background-color: #1976D2; color: white;")
        self.parse_btn.clicked.connect(self._parse_and_accept)
        btn_layout.addWidget(self.parse_btn)

        layout.addLayout(btn_layout)

    def _parse_and_accept(self):
        text = self.text_edit.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "提示", "请输入有效内容！")
            return

        # 利用正则匹配完整的 ID
        # Google Spreadsheet ID 通常是 44 位的字母数字组合
        # 或者使用与原软件 extract_spreadsheet_id 一致的正则
        # 先简单的 \b([a-zA-Z0-9-_]{44})\b 或者匹配 d/后面的
        
        extracted_ids = set()
        
        # 匹配 URL 中的 ID
        url_matches = re.findall(r'/d/([a-zA-Z0-9-_]+)', text)
        for m in url_matches:
            extracted_ids.add(m)
            
        # 匹配看起来像 ID 的独立字符串（长度通常大于20）
        lines = text.replace(',', '\n').split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # 纯文本且看起来像ID（没在url_matches中提取出来的）
            if re.match(r'^[a-zA-Z0-9-_]{20,}$', line):
                extracted_ids.add(line)

        if not extracted_ids:
            QMessageBox.warning(self, "解析失败", "未能从输入中提取出有效的表格 ID，请检查格式。")
            return

        self.entries = []
        for i, sid in enumerate(extracted_ids):
            self.entries.append({
                "id": sid,
                "spreadsheet_id": sid,
                "name": f"手动导入表格 {i+1}"
            })

        self.accept()

    def get_entries(self):
        return self.entries
