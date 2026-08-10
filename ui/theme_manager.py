# UI 主题管理器：支持浅色/深色主题切换
import os
import logging
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger("sheets_toolkit.ui.theme")

# 项目根目录
from ui.clearable_text_edit import ClearableTextEdit
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ===== 浅色主题 =====
LIGHT_THEME = """
/* ===== 浅色主题 ===== */
QMainWindow {
    background-color: #f0f2f5;
}

/* 左侧导航 */
QListWidget {
    background-color: #ffffff;
    border: none;
    border-right: 1px solid #e0e0e0;
    font-size: 14px;
    padding: 8px 0;
    outline: none;
}

QListWidget::item {
    padding: 2px 8px;
    border-radius: 0;
    margin: 2px 8px;
    border-radius: 8px;
    color: #555;
}

QListWidget::item:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4CAF50, stop:1 #66BB6A);
    color: white;
    font-weight: bold;
}

QListWidget::item:hover:!selected {
    background-color: #f5f5f5;
    color: #333;
}

/* 标签 */
QLabel {
    font-size: 13px;
    color: #444;
    font-weight: 500;
}

QLabel#section_title {
    font-size: 16px;
    font-weight: bold;
    color: #2e7d32;
    padding: 8px 0;
    max-height: 35px;
}

/* 按钮 */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #4CAF50, stop:1 #43A047);
    color: white;
    padding: 2px 12px;
    font-size: 13px;
    font-weight: 500;
    border: none;
    border-radius: 6px;
    min-height: 24px;
}

QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #66BB6A, stop:1 #4CAF50);
}

QPushButton:pressed {
    background-color: #388E3C;
}

QPushButton:disabled {
    background-color: #BDBDBD;
    color: #888;
}

QPushButton#danger_btn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #EF5350, stop:1 #E53935);
}

QPushButton#danger_btn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #EF5350, stop:1 #C62828);
}

QPushButton#secondary_btn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #42A5F5, stop:1 #1E88E5);
}

QPushButton#secondary_btn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #64B5F6, stop:1 #42A5F5);
}

/* 输入框 */
QComboBox, QLineEdit, QDateTimeEdit {
    padding: 4px 8px;
    font-size: 13px;
    border: 1px solid #ddd;
    border-radius: 6px;
    background: white;
    selection-background-color: #4CAF50;
}

QComboBox:focus, QLineEdit:focus, QDateTimeEdit:focus {
    border: 2px solid #4CAF50;
    padding: 4px 8px;
}

QComboBox::drop-down {
    border: none;
    width: 30px;
}

/* 日志区 */
ClearableTextEdit {
    background-color: #fafafa;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    padding: 8px;
    color: #333;
}

/* 数据表格 */
QTableWidget {
    background-color: #ffffff;
    font-size: 12px;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    gridline-color: #eee;
    selection-background-color: #E8F5E9;
    selection-color: #333;
}

QTableWidget::item {
    padding: 4px 8px;
}

QHeaderView::section {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #f5f5f5, stop:1 #eeeeee);
    padding: 6px 8px;
    border: none;
    border-bottom: 2px solid #4CAF50;
    font-weight: bold;
    font-size: 12px;
    color: #555;
}

/* 分割条 */
QSplitter::handle {
    background-color: #e0e0e0;
    width: 2px;
    height: 2px;
}

QSplitter::handle:hover {
    background-color: #4CAF50;
}

/* 状态栏 */
QStatusBar {
    background-color: #f5f5f5;
    border-top: 1px solid #e0e0e0;
    font-size: 12px;
    color: #666;
}

/* 工具提示 */
QToolTip {
    background-color: #333;
    color: white;
    border: none;
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 12px;
}

/* 滚动条 */
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #ccc;
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #aaa;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: transparent;
    height: 8px;
}

QScrollBar::handle:horizontal {
    background: #ccc;
    border-radius: 4px;
    min-width: 30px;
}

/* 菜单栏 */
QMenuBar {
    background-color: #ffffff;
    border-bottom: 1px solid #e0e0e0;
    font-size: 13px;
    padding: 2px;
}

QMenuBar::item {
    padding: 6px 12px;
    border-radius: 4px;
}

QMenuBar::item:selected {
    background-color: #E8F5E9;
}

QMenu {
    background-color: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    padding: 4px;
}

QMenu::item {
    padding: 8px 24px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #E8F5E9;
}

/* 进度条 */
QProgressBar {
    border: none;
    border-radius: 4px;
    background-color: #E0E0E0;
    text-align: center;
    font-size: 11px;
    max-height: 8px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4CAF50, stop:1 #66BB6A);
    border-radius: 4px;
}

/* 分组框 */
QGroupBox {
    font-weight: bold;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 16px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #2e7d32;
}
"""

# ===== 深色主题 =====
DARK_THEME = """
/* ===== 深色主题 ===== */
QMainWindow {
    background-color: #1e1e2e;
}

QListWidget {
    background-color: #1e1e2e;
    border: none;
    border-right: 1px solid #363650;
    font-size: 14px;
    padding: 8px 0;
    outline: none;
    color: #cdd6f4;
}

QListWidget::item {
    padding: 2px 4px;
    margin: 2px 8px;
    border-radius: 8px;
    color: #a6adc8;
}

QListWidget::item:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #a6e3a1, stop:1 #94e2d5);
    color: #1e1e2e;
    font-weight: bold;
}

QListWidget::item:hover:!selected {
    background-color: #313244;
    color: #cdd6f4;
}

QLabel {
    font-size: 13px;
    color: #bac2de;
    font-weight: 500;
}

QLabel#section_title {
    font-size: 16px;
    font-weight: bold;
    color: #a6e3a1;
    padding: 8px 0;
    max-height: 35px;
}

QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #a6e3a1, stop:1 #94e2d5);
    color: #1e1e2e;
    padding: 2px 12px;
    font-size: 13px;
    font-weight: bold;
    border: none;
    border-radius: 6px;
    min-height: 24px;
}

QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #94e2d5, stop:1 #89dceb);
}

QPushButton:pressed {
    background-color: #74c7ec;
}

QPushButton:disabled {
    background-color: #45475a;
    color: #6c7086;
}

QPushButton#danger_btn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #f38ba8, stop:1 #eba0ac);
}

QPushButton#danger_btn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #eba0ac, stop:1 #f38ba8);
}

QPushButton#secondary_btn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #89b4fa, stop:1 #74c7ec);
}

QComboBox, QLineEdit, QDateTimeEdit {
    padding: 8px 12px;
    font-size: 13px;
    border: 1px solid #45475a;
    border-radius: 6px;
    background: #313244;
    color: #cdd6f4;
    selection-background-color: #a6e3a1;
    selection-color: #1e1e2e;
}

QComboBox:focus, QLineEdit:focus, QDateTimeEdit:focus {
    border: 2px solid #a6e3a1;
    padding: 7px 11px;
}

QComboBox::drop-down {
    border: none;
    width: 30px;
}

QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    selection-background-color: #45475a;
    border: 1px solid #45475a;
}

ClearableTextEdit {
    background-color: #181825;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    border: 1px solid #313244;
    border-radius: 6px;
    padding: 8px;
    color: #a6adc8;
}

QTableWidget {
    background-color: #1e1e2e;
    font-size: 12px;
    border: 1px solid #313244;
    border-radius: 6px;
    gridline-color: #313244;
    selection-background-color: #313244;
    selection-color: #cdd6f4;
    color: #cdd6f4;
}

QTableWidget::item {
    padding: 4px 8px;
}

QHeaderView::section {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #313244, stop:1 #2a2a3c);
    padding: 6px 8px;
    border: none;
    border-bottom: 2px solid #a6e3a1;
    font-weight: bold;
    font-size: 12px;
    color: #a6adc8;
}

QSplitter::handle {
    background-color: #313244;
    width: 2px;
    height: 2px;
}

QSplitter::handle:hover {
    background-color: #a6e3a1;
}

QStatusBar {
    background-color: #181825;
    border-top: 1px solid #313244;
    font-size: 12px;
    color: #6c7086;
}

QToolTip {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 12px;
}

QScrollBar:vertical {
    background: transparent;
    width: 8px;
}

QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #585b70;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: transparent;
    height: 8px;
}

QScrollBar::handle:horizontal {
    background: #45475a;
    border-radius: 4px;
}

QMenuBar {
    background-color: #1e1e2e;
    border-bottom: 1px solid #313244;
    font-size: 13px;
    color: #cdd6f4;
    padding: 2px;
}

QMenuBar::item {
    padding: 6px 12px;
    border-radius: 4px;
}

QMenuBar::item:selected {
    background-color: #313244;
}

QMenu {
    background-color: #1e1e2e;
    border: 1px solid #313244;
    border-radius: 6px;
    padding: 4px;
    color: #cdd6f4;
}

QMenu::item {
    padding: 8px 24px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #313244;
}

QProgressBar {
    border: none;
    border-radius: 4px;
    background-color: #313244;
    text-align: center;
    font-size: 11px;
    max-height: 8px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #a6e3a1, stop:1 #94e2d5);
    border-radius: 4px;
}

QGroupBox {
    font-weight: bold;
    border: 1px solid #313244;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 16px;
    color: #cdd6f4;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #a6e3a1;
}
"""


class ThemeManager(QObject):
    """
    主题管理器 — 支持浅色/深色主题动态切换。
    """
    theme_changed = Signal(str)  # 主题切换信号

    THEMES = {
        "light": LIGHT_THEME,
        "dark": DARK_THEME,
    }

    def __init__(self, app):
        super().__init__()
        self.app = app
        self._current_theme = "light"

    @property
    def current_theme(self):
        return self._current_theme

    def apply_theme(self, theme_name):
        """应用指定主题"""
        if theme_name not in self.THEMES:
            logger.warning(f"未知主题: {theme_name}，使用浅色主题")
            theme_name = "light"

        self._current_theme = theme_name
        self.app.setStyleSheet(self.THEMES[theme_name])
        self.theme_changed.emit(theme_name)
        logger.info(f"已切换主题: {theme_name}")

    def toggle_theme(self):
        """切换浅色/深色主题"""
        new_theme = "dark" if self._current_theme == "light" else "light"
        self.apply_theme(new_theme)
        return new_theme
