# main.py — 应用入口
import sys
import os
import logging

# 确保项目根目录在 Python 路径中
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from core.logger import setup_logger
from core.config import AppConfig
from ui.theme_manager import ThemeManager
from ui.main_window import MainWindow


def main():
    # 初始化配置
    config = AppConfig()

    # 初始化日志
    log_level = getattr(logging, config.get("log_level", "INFO"), logging.INFO)
    logger = setup_logger(level=log_level)
    logger.info("=== Sheets Toolkit 启动 ===")

    # 创建应用
    app = QApplication(sys.argv)
    app.setApplicationName("Sheets Toolkit")
    
    # 设置应用全局图标
    icon_path = os.path.join(BASE_DIR, "resources", "main.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # 初始化主题管理器
    theme_manager = ThemeManager(app)
    theme = config.get("theme", "light")
    theme_manager.apply_theme(theme)

    # 主题切换时保存到配置
    def on_theme_changed(name):
        config.set("theme", name)
    theme_manager.theme_changed.connect(on_theme_changed)

    # 显示登录对话框
    from ui.login_dialog import LoginDialog
    login_dialog = LoginDialog()
    if login_dialog.exec() != LoginDialog.Accepted:
        sys.exit(0)
    
    user_role = login_dialog.get_role()
    username = login_dialog.get_username()
    logger.info(f"用户已登录，角色: {user_role}，用户名: {username}")

    # 创建并显示主窗口
    window = MainWindow(theme_manager=theme_manager, role=user_role, username=username)
    window.show()

    logger.info("应用界面已显示")
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
