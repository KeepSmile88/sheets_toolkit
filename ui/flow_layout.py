# 自适应流式布局 — 子控件根据容器宽度自动换行排列
from PySide6.QtWidgets import QLayout
from PySide6.QtCore import Qt, QRect, QSize, QPoint


class FlowLayout(QLayout):
    """自适应流式布局 — 子控件根据容器宽度自动换行排列"""

    def __init__(self, parent=None, margin=4, h_spacing=8, v_spacing=4):
        super().__init__(parent)
        self._items = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        if margin >= 0:
            self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0

        for item in self._items:
            w = item.widget()
            if w is None:
                continue
            item_size = item.sizeHint()
            next_x = x + item_size.width() + self._h_spacing

            if next_x - self._h_spacing > effective.right() + 1 and line_height > 0:
                x = effective.x()
                y = y + line_height + self._v_spacing
                next_x = x + item_size.width() + self._h_spacing
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))

            x = next_x
            line_height = max(line_height, item_size.height())

        return y + line_height - rect.y() + m.bottom()

    def clear_widgets(self):
        """清除布局中所有控件"""
        while self.count():
            item = self.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
