from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QMessageBox, QFormLayout, QFrame
)
from PySide6.QtCore import Qt
from core.db import has_password, verify_password, update_password
import logging

logger = logging.getLogger("sheets_toolkit.ui.change_password")

class ChangePasswordDialog(QDialog):
    def __init__(self, username, parent=None):
        super().__init__(parent)
        self.username = username
        self.setWindowTitle("修改密码")
        self.setMinimumWidth(320)
        
        self.setup_ui()
        self.layout().setSizeConstraint(QVBoxLayout.SetFixedSize)
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题区
        title_label = QLabel(f"🔐 用户 <b>{self.username}</b> 的安全设置")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 15px; margin-bottom: 5px;")
        layout.addWidget(title_label)
        
        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)
        
        # 表单区
        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form_layout.setSpacing(10)
        
        self.has_pwd = has_password(self.username)
        
        # 原密码
        self.old_pwd_input = QLineEdit()
        self.old_pwd_input.setEchoMode(QLineEdit.Password)
        self.old_pwd_input.setMinimumWidth(200)
        if self.has_pwd:
            form_layout.addRow("原密码:", self.old_pwd_input)
            
        # 新密码
        self.new_pwd_input = QLineEdit()
        self.new_pwd_input.setEchoMode(QLineEdit.Password)
        self.new_pwd_input.setMinimumWidth(200)
        self.new_pwd_input.setPlaceholderText("留空表示清除密码" if self.has_pwd else "设置新密码，留空不设")
        form_layout.addRow("新密码:", self.new_pwd_input)
        
        # 确认密码
        self.confirm_pwd_input = QLineEdit()
        self.confirm_pwd_input.setEchoMode(QLineEdit.Password)
        self.confirm_pwd_input.setMinimumWidth(200)
        form_layout.addRow("确认新密码:", self.confirm_pwd_input)
        
        layout.addLayout(form_layout)
        
        # 底部按钮区
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        save_btn = QPushButton("💾 保存更改")
        save_btn.setMinimumWidth(100)
        save_btn.clicked.connect(self.save_password)
        btn_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setMinimumWidth(80)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
        
    def save_password(self):
        if self.has_pwd:
            old_pwd = self.old_pwd_input.text()
            if not verify_password(self.username, old_pwd):
                QMessageBox.warning(self, "错误", "原密码不正确！")
                return
                
        new_pwd = self.new_pwd_input.text()
        confirm_pwd = self.confirm_pwd_input.text()
        
        if new_pwd != confirm_pwd:
            QMessageBox.warning(self, "错误", "两次输入的新密码不一致！")
            return
            
        try:
            update_password(self.username, new_pwd)
            msg = f"账号 [{self.username}] 的密码已成功设置！" if new_pwd else f"账号 [{self.username}] 的密码已清除，下次登录无需验证密码。"
            QMessageBox.information(self, "成功", msg)
            logger.info(f"用户 {self.username} 修改了密码")
            self.accept()
        except Exception as e:
            logger.error(f"修改密码失败: {e}")
            QMessageBox.critical(self, "错误", f"修改密码失败: {e}")
