from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QMessageBox, QWidget
)
from PySide6.QtCore import Qt
from core.db import has_password, verify_password

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("登录 - Sheets Toolkit")
        self.setMinimumWidth(320)
        self.role = "user" # default
        self.username = ""
        
        self.setup_ui()
        # 强制按内容调整高度，同时由于有 MinimumWidth，不会被横向挤压
        self.layout().setSizeConstraint(QVBoxLayout.SetFixedSize)
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        title_label = QLabel("欢迎使用 Sheets Toolkit")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 15px;")
        layout.addWidget(title_label)
        
        # 账号/角色输入
        account_layout = QHBoxLayout()
        lbl_account = QLabel("账号／角色:")
        lbl_account.setFixedWidth(75)
        lbl_account.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        account_layout.addWidget(lbl_account)
        
        self.account_input = QLineEdit()
        self.account_input.setMinimumWidth(220)
        self.account_input.setPlaceholderText("留空 (默认账号 guest) 或输入新账号...")
        self.account_input.textChanged.connect(self.on_account_changed)
        account_layout.addWidget(self.account_input)
        layout.addLayout(account_layout)
        
        # 密码输入框 (仅当账号为admin时可见)
        self.password_layout = QHBoxLayout()
        self.password_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_pwd = QLabel("用户密码:")
        self.lbl_pwd.setFixedWidth(75)
        self.lbl_pwd.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.password_layout.addWidget(self.lbl_pwd)
        
        self.password_input = QLineEdit()
        self.password_input.setMinimumWidth(220)
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_layout.addWidget(self.password_input)
        
        self.password_widget = QWidget()
        self.password_widget.setLayout(self.password_layout)
        self.password_widget.setVisible(False)
        layout.addWidget(self.password_widget)
        
        # 按钮
        btn_layout = QHBoxLayout()
        self.login_btn = QPushButton("登录")
        self.login_btn.clicked.connect(self.check_login)
        btn_layout.addWidget(self.login_btn)
        layout.addLayout(btn_layout)
        
        # 初始化检查空状态（guest）
        self.on_account_changed("")
        
    def on_account_changed(self, text):
        account = text.strip()
        if not account:
            account = "guest"
            
        if account == "admin":
            self.lbl_pwd.setText("管理员密码:")
        else:
            self.lbl_pwd.setText("用户密码:")

        if has_password(account) or account == "admin":
            self.password_widget.setVisible(True)
        else:
            self.password_widget.setVisible(False)
            
    def check_login(self):
        account = self.account_input.text().strip()
        if not account:
            account = "guest"
            
        input_pwd = self.password_input.text()
        
        # 统一校验密码
        if has_password(account) or account == "admin":
            if not verify_password(account, input_pwd):
                QMessageBox.warning(self, "密码错误", "密码不正确！")
                return
                
        if account == "admin":
            self.role = "admin"
        else:
            self.role = "user"
            
        self.username = account
            
        self.accept()
        
    def get_role(self):
        return self.role
        
    def get_username(self):
        return self.username
