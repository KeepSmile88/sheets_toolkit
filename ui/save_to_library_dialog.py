import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QLineEdit, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt

from services.spreadsheet_library import AccountManager

logger = logging.getLogger("sheets_toolkit.ui.save_to_library_dialog")


class SaveToLibraryDialog(QDialog):
    """
    保存到表格库对话框。
    允许用户选择目标账号、分组（支持输入新分组），并提供可选备注。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📥 保存到表格库")
        self.setMinimumWidth(350)
        self.account_mgr = AccountManager()
        self._setup_ui()
        self._load_accounts()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 账号选择
        acc_layout = QHBoxLayout()
        acc_layout.addWidget(QLabel("👤 目标账号:"))
        self.account_combo = QComboBox()
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        acc_layout.addWidget(self.account_combo, 1)
        layout.addLayout(acc_layout)

        # 分组选择
        group_layout = QHBoxLayout()
        group_layout.addWidget(QLabel("📂 目标分组:"))
        self.group_combo = QComboBox()
        self.group_combo.setEditable(True)
        self.group_combo.setToolTip("选择已有分组，或直接输入新分组名称")
        group_layout.addWidget(self.group_combo, 1)
        layout.addLayout(group_layout)

        # 备注
        note_layout = QHBoxLayout()
        note_layout.addWidget(QLabel("📝 备注信息:"))
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("(可选) 添加备注...")
        note_layout.addWidget(self.note_input, 1)
        layout.addLayout(note_layout)

        layout.addStretch()

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setObjectName("primary_btn")
        self.btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_ok)
        
        layout.addLayout(btn_layout)

    def _load_accounts(self):
        self.account_combo.clear()
        accounts = self.account_mgr.accounts
        if not accounts:
            QMessageBox.warning(self, "无账号", "未找到表格库账号，请先在表格库管理器中创建。")
            self.reject()
            return
            
        for acc in accounts:
            self.account_combo.addItem(acc["name"], userData=acc["id"])
            
        # 默认选中当前活动的账号
        active_idx = self.account_mgr.active_index
        if 0 <= active_idx < len(accounts):
            self.account_combo.setCurrentIndex(active_idx)
            
    def _on_account_changed(self, index):
        if index < 0:
            return
        acc_id = self.account_combo.itemData(index)
        self._load_groups(acc_id)
        
    def _load_groups(self, acc_id):
        self.group_combo.clear()
        lib = self.account_mgr.get_library(acc_id)
        if not lib:
            return
            
        group_names = lib.get_group_names()
        # 排除默认可能重复的，虽然直接添加也行
        if "默认" not in group_names:
            self.group_combo.addItem("默认")
        self.group_combo.addItems(group_names)
        
        # 默认选中第一个或"默认"
        idx = self.group_combo.findText("默认")
        if idx >= 0:
            self.group_combo.setCurrentIndex(idx)
            
    def get_selection(self):
        """返回 (account_id, group_name, notes)"""
        acc_id = self.account_combo.currentData()
        group_name = self.group_combo.currentText().strip()
        if not group_name:
            group_name = "默认"
        notes = self.note_input.text().strip()
        return acc_id, group_name, notes
