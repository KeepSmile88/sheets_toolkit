from PySide6.QtWidgets import QTextEdit, QToolButton
from PySide6.QtCore import Qt

class ClearableTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_clear_button()

    def _setup_clear_button(self):
        self.btn_clear = QToolButton(self)
        self.btn_clear.setText("🧹")
        self.btn_clear.setToolTip("清空输入")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.setStyleSheet("""
            QToolButton {
                background: transparent;
                border: none;
                font-size: 14px;
                padding: 2px;
            }
            QToolButton:hover {
                background: rgba(0, 0, 0, 0.1);
                border-radius: 4px;
            }
        """)
        self.btn_clear.clicked.connect(self.clear)
        self.btn_clear.hide()

        self.textChanged.connect(self._update_clear_button_visibility)

    def _update_clear_button_visibility(self):
        if not self.isReadOnly() and self.toPlainText():
            self.btn_clear.show()
        else:
            self.btn_clear.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        
        btn_size = self.btn_clear.sizeHint()
        # Add 4px padding from top right
        x = self.width() - btn_size.width() - 4
        y = 4
        
        # Consider the vertical scrollbar width if it's visible
        if self.verticalScrollBar().isVisible():
            x -= self.verticalScrollBar().width()
            
        self.btn_clear.move(x, y)
