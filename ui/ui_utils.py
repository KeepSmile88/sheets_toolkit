# UI 实用工具：图标、消息框
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMessageBox


def icon(name):
    """加载图标（当前返回空图标，可扩展为真实图标文件）"""
    return QIcon()


def info(parent, title, message):
    """显示信息对话框"""
    QMessageBox.information(parent, title, message)


def error(parent, title, message):
    """显示错误对话框"""
    QMessageBox.critical(parent, title, message)


def confirm(parent, title, message):
    """显示确认对话框，返回 True/False"""
    reply = QMessageBox.question(
        parent, title, message,
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No
    )
    return reply == QMessageBox.Yes
