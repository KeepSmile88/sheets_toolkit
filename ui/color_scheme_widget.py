# 配色库 UI 组件 — 管理配色方案 + 快速应用到多个表格
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar,
    QSplitter, QGroupBox, QComboBox, QCheckBox,
    QSpinBox, QColorDialog, QMessageBox
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor

from services.color_scheme_library import ColorSchemeLibrary

logger = logging.getLogger("sheets_toolkit.ui.color_scheme")


def col_letter_to_index(letter):
    letter = letter.upper().strip()
    idx = 0
    for ch in letter:
        idx = idx * 26 + (ord(ch) - ord('A'))
    return idx


class ApplyColorWorker(QThread):
    """配色应用工作线程"""
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, ids, sheet_name, sr, er, sc, ec, fmt):
        super().__init__()
        self.ids = ids
        self.sheet_name = sheet_name
        self.sr, self.er, self.sc, self.ec = sr, er, sc, ec
        self.fmt = fmt

    def run(self):
        try:
            from services.sheet_service import SheetService
            results = SheetService.batch_format_range(
                self.ids, self.sheet_name,
                self.sr, self.er, self.sc, self.ec,
                self.fmt, self._p
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _p(self, c, t, m):
        self.progress.emit(c, t, m)


class ColorSchemeWidget(QWidget):
    """
    配色库面板 — 左侧管理配色方案，右侧快速应用到表格。
    """

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.library = ColorSchemeLibrary()
        self._worker = None
        self._selected_id = None
        self._edit_bg = None
        self._edit_fg = None
        self.setup_ui()
        self.refresh_table()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        title = QLabel("🎨 配色库")
        title.setObjectName("section_title")
        layout.addWidget(title)

        splitter = QSplitter(Qt.Horizontal)

        # ======= 左侧：配色管理 =======
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 4, 0)

        # 分类过滤
        filter_row = QHBoxLayout()
        self.cat_filter = QComboBox()
        self.cat_filter.addItem("全部分类")
        self.cat_filter.currentTextChanged.connect(self._on_filter)
        filter_row.addWidget(self.cat_filter)
        ll.addLayout(filter_row)

        # 配色列表
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["名称", "预览", "说明", "分类"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(1, 60)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(3, 60)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setAlternatingRowColors(True)
        self.table.currentCellChanged.connect(self._on_select)
        ll.addWidget(self.table)

        # 编辑区
        edit_group = QGroupBox("配色详情")
        el = QVBoxLayout(edit_group)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("名称:"))
        self.edit_name = QLineEdit()
        r1.addWidget(self.edit_name)
        r1.addWidget(QLabel("分类:"))
        self.edit_cat = QLineEdit()
        self.edit_cat.setMaximumWidth(80)
        r1.addWidget(self.edit_cat)
        el.addLayout(r1)

        # 颜色选择
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("背景色:"))
        self.bg_btn = QPushButton("  选择  ")
        self.bg_btn.clicked.connect(self._pick_bg)
        r2.addWidget(self.bg_btn)
        self.bg_preview = QLabel("  ")
        self.bg_preview.setFixedWidth(30)
        self.bg_preview.setFixedHeight(20)
        r2.addWidget(self.bg_preview)

        r2.addWidget(QLabel("字体色:"))
        self.fg_btn = QPushButton("  选择  ")
        self.fg_btn.clicked.connect(self._pick_fg)
        r2.addWidget(self.fg_btn)
        self.fg_preview = QLabel("  ")
        self.fg_preview.setFixedWidth(30)
        self.fg_preview.setFixedHeight(20)
        r2.addWidget(self.fg_preview)

        self.edit_bold = QCheckBox("粗体")
        r2.addWidget(self.edit_bold)
        el.addLayout(r2)

        r3 = QHBoxLayout()
        r3.addWidget(QLabel("说明:"))
        self.edit_desc = QLineEdit()
        r3.addWidget(self.edit_desc)
        el.addLayout(r3)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("➕ 新增")
        add_btn.clicked.connect(self._add)
        btn_row.addWidget(add_btn)
        save_btn = QPushButton("💾 保存")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        del_btn = QPushButton("🗑 删除")
        del_btn.setObjectName("danger_btn")
        del_btn.clicked.connect(self._delete)
        btn_row.addWidget(del_btn)
        el.addLayout(btn_row)

        ll.addWidget(edit_group)

        # ======= 右侧：应用配色 =======
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 0, 0, 0)

        apply_title = QLabel("🚀 应用配色")
        apply_title.setObjectName("section_title")
        rl.addWidget(apply_title)

        self.selected_label = QLabel("📋 未选择配色方案")
        self.selected_label.setWordWrap(True)
        rl.addWidget(self.selected_label)

        # 区域
        pos_row = QHBoxLayout()
        pos_row.addWidget(QLabel("Sheet:"))
        self.apply_sheet = QLineEdit("Sheet1")
        self.apply_sheet.setMaximumWidth(100)
        pos_row.addWidget(self.apply_sheet)
        pos_row.addWidget(QLabel("行:"))
        self.apply_row_start = QSpinBox()
        self.apply_row_start.setMinimum(1)
        self.apply_row_start.setValue(1)
        pos_row.addWidget(self.apply_row_start)
        pos_row.addWidget(QLabel("至"))
        self.apply_row_end = QSpinBox()
        self.apply_row_end.setMinimum(1)
        self.apply_row_end.setValue(1)
        self.apply_row_end.setMaximum(99999)
        pos_row.addWidget(self.apply_row_end)
        pos_row.addWidget(QLabel("列:"))
        self.apply_col_start = QLineEdit("A")
        self.apply_col_start.setMaximumWidth(40)
        pos_row.addWidget(self.apply_col_start)
        pos_row.addWidget(QLabel("至"))
        self.apply_col_end = QLineEdit("Z")
        self.apply_col_end.setMaximumWidth(40)
        pos_row.addWidget(self.apply_col_end)
        rl.addLayout(pos_row)

        rl.addWidget(QLabel("📄 表格链接/ID（每行一个）："))
        self.ids_input = ClearableTextEdit()
        self.ids_input.setPlaceholderText("输入链接或 ID，不输入则使用当前表格")
        rl.addWidget(self.ids_input)

        self.apply_btn = QPushButton("🚀 批量应用配色")
        self.apply_btn.clicked.connect(self._apply)
        rl.addWidget(self.apply_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        rl.addWidget(self.progress_bar)
        self.status_label = QLabel("")
        rl.addWidget(self.status_label)

        self.result_table = QTableWidget()
        self.result_table.setColumnCount(3)
        self.result_table.setHorizontalHeaderLabels(["标题", "ID", "状态"])
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.result_table.setColumnWidth(2, 60)
        rl.addWidget(self.result_table)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([400, 450])
        layout.addWidget(splitter)

    # ========================
    # 配色管理
    # ========================

    def refresh_table(self, schemes=None):
        items = schemes if schemes is not None else self.library.schemes
        self.table.setRowCount(len(items))
        for i, s in enumerate(items):
            name_item = QTableWidgetItem(s.get("name", ""))
            name_item.setData(Qt.UserRole, s.get("id"))
            self.table.setItem(i, 0, name_item)

            # 颜色预览
            preview = QTableWidgetItem("  ■ Aa  ")
            bg = s.get("bg", {})
            fg = s.get("fg", {})
            bg_color = QColor(
                int(bg.get("red", 1) * 255),
                int(bg.get("green", 1) * 255),
                int(bg.get("blue", 1) * 255)
            )
            fg_color = QColor(
                int(fg.get("red", 0) * 255),
                int(fg.get("green", 0) * 255),
                int(fg.get("blue", 0) * 255)
            )
            preview.setBackground(bg_color)
            preview.setForeground(fg_color)
            self.table.setItem(i, 1, preview)

            self.table.setItem(i, 2, QTableWidgetItem(s.get("description", "")))
            self.table.setItem(i, 3, QTableWidgetItem(s.get("category", "")))

        # 更新分类
        cats = self.library.get_categories()
        cur = self.cat_filter.currentText()
        self.cat_filter.blockSignals(True)
        self.cat_filter.clear()
        self.cat_filter.addItem("全部分类")
        self.cat_filter.addItems(cats)
        idx = self.cat_filter.findText(cur)
        if idx >= 0:
            self.cat_filter.setCurrentIndex(idx)
        self.cat_filter.blockSignals(False)

    def _on_select(self, row, col, prev_row, prev_col):
        if row < 0:
            return
        item = self.table.item(row, 0)
        if not item:
            return
        sid = item.data(Qt.UserRole)
        entry = self.library.get_by_id(sid)
        if not entry:
            return

        self._selected_id = sid
        self.edit_name.setText(entry.get("name", ""))
        self.edit_cat.setText(entry.get("category", ""))
        self.edit_desc.setText(entry.get("description", ""))
        self.edit_bold.setChecked(entry.get("bold", False))

        bg = entry.get("bg", {})
        fg = entry.get("fg", {})
        self._edit_bg = QColor(int(bg.get("red",1)*255), int(bg.get("green",1)*255), int(bg.get("blue",1)*255))
        self._edit_fg = QColor(int(fg.get("red",0)*255), int(fg.get("green",0)*255), int(fg.get("blue",0)*255))
        self.bg_preview.setStyleSheet(f"background-color: {self._edit_bg.name()};")
        self.fg_preview.setStyleSheet(f"background-color: {self._edit_fg.name()};")

        self.selected_label.setText(
            f"📋 已选: {entry['name']}\n   {entry.get('description','')}"
        )

    def _on_filter(self, cat):
        if cat == "全部分类":
            self.refresh_table()
        else:
            self.refresh_table([s for s in self.library.schemes if s.get("category") == cat])

    def _pick_bg(self):
        c = QColorDialog.getColor(self._edit_bg or QColor(255,255,255))
        if c.isValid():
            self._edit_bg = c
            self.bg_preview.setStyleSheet(f"background-color: {c.name()};")

    def _pick_fg(self):
        c = QColorDialog.getColor(self._edit_fg or QColor(0,0,0))
        if c.isValid():
            self._edit_fg = c
            self.fg_preview.setStyleSheet(f"background-color: {c.name()};")

    def _add(self):
        name = self.edit_name.text().strip()
        if not name:
            return
        bg = {"red": self._edit_bg.redF(), "green": self._edit_bg.greenF(), "blue": self._edit_bg.blueF()} if self._edit_bg else {"red":1,"green":1,"blue":1}
        fg = {"red": self._edit_fg.redF(), "green": self._edit_fg.greenF(), "blue": self._edit_fg.blueF()} if self._edit_fg else {"red":0,"green":0,"blue":0}
        self.library.add(name, bg, fg, self.edit_bold.isChecked(),
                         self.edit_cat.text().strip() or "通用",
                         self.edit_desc.text().strip())
        self.refresh_table()

    def _save(self):
        if not self._selected_id:
            return
        bg = {"red": self._edit_bg.redF(), "green": self._edit_bg.greenF(), "blue": self._edit_bg.blueF()} if self._edit_bg else None
        fg = {"red": self._edit_fg.redF(), "green": self._edit_fg.greenF(), "blue": self._edit_fg.blueF()} if self._edit_fg else None
        kwargs = {"name": self.edit_name.text().strip(),
                  "category": self.edit_cat.text().strip(),
                  "description": self.edit_desc.text().strip(),
                  "bold": self.edit_bold.isChecked()}
        if bg:
            kwargs["bg"] = bg
        if fg:
            kwargs["fg"] = fg
        self.library.update(self._selected_id, **kwargs)
        self.refresh_table()

    def _delete(self):
        if not self._selected_id:
            return
        entry = self.library.get_by_id(self._selected_id)
        name = entry.get("name", "") if entry else ""
        if QMessageBox.question(self, "确认", f"删除 '{name}'？",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.library.delete(self._selected_id)
            self._selected_id = None
            self.refresh_table()

    # ========================
    # 批量应用
    # ========================

    def _get_ids(self):
        from ui.batch_backup_widget import extract_spreadsheet_id
        text = self.ids_input.toPlainText().strip()
        if text:
            return [extract_spreadsheet_id(l.strip()) for l in text.split('\n')
                    if extract_spreadsheet_id(l.strip())]
        elif self.controller and self.controller.service:
            return [self.controller.service.spreadsheet_id]
        return []

    def _apply(self):
        if not self._selected_id:
            self.status_label.setText("⚠️ 请先选择配色方案")
            return

        entry = self.library.get_by_id(self._selected_id)
        if not entry:
            return

        ids = self._get_ids()
        if not ids:
            self.status_label.setText("⚠️ 请输入表格 ID")
            return

        fmt = self.library.to_sheets_format(entry)
        sheet_name = self.apply_sheet.text().strip() or "Sheet1"
        sr = self.apply_row_start.value() - 1
        er = self.apply_row_end.value()
        sc = col_letter_to_index(self.apply_col_start.text())
        ec = col_letter_to_index(self.apply_col_end.text()) + 1

        self.apply_btn.setEnabled(False)
        self.apply_btn.setText("⏳ 应用中...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(ids))
        self.result_table.setRowCount(0)

        self._worker = ApplyColorWorker(ids, sheet_name, sr, er, sc, ec, fmt)
        self._worker.progress.connect(lambda c, t, m: (
            self.progress_bar.setValue(c), self.status_label.setText(m)))
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, results):
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.result_table.setRowCount(len(results))
        for i, r in enumerate(results):
            self.result_table.setItem(i, 0, QTableWidgetItem(r.get("title", "—")))
            self.result_table.setItem(i, 1, QTableWidgetItem(r.get("id", "")[:25]))
            s = "✅" if r["status"] == "success" else "❌"
            item = QTableWidgetItem(s)
            if r["status"] == "error":
                item.setToolTip(r.get("error", ""))
            self.result_table.setItem(i, 2, item)

        ok = sum(1 for r in results if r["status"] == "success")
        self.status_label.setText(f"✅ 配色应用完成: {ok}/{len(results)}")
        self.apply_btn.setEnabled(True)
        self.apply_btn.setText("🚀 批量应用配色")
        self._worker = None

    def _on_error(self, msg):
        self.status_label.setText(f"❌ {msg}")
        self.apply_btn.setEnabled(True)
        self.apply_btn.setText("🚀 批量应用配色")
        self.progress_bar.setVisible(False)
        self._worker = None
