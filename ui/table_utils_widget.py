# 表格辅助工具 — 聚合对比差异、字符比较、字符串拼接、文本转换、列拆分/合并、
#                 数据清洗、频次统计、行列转置、时间戳转换、批量读取子表等实用小工具
import re
import os
import csv
import logging
import difflib
from datetime import datetime, timezone, timedelta
from collections import Counter

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QLineEdit, QComboBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QRadioButton, QButtonGroup, QSpinBox, QSplitter, QMessageBox,
    QApplication, QGridLayout, QToolButton, QMenu, QFileDialog,
    QProgressBar, QAbstractItemView
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QAction

logger = logging.getLogger("sheets_toolkit.ui.table_utils")


# ================================================================
# 通用组件：从表格读取数据的面板
# ================================================================

class SheetDataSourcePanel(QWidget):
    """
    可复用的"从表格读取"小组件。
    点击展开后可选择工作表 + 输入范围 → 拉取数据填入目标文本框。
    """

    def __init__(self, controller, target_widget, parent=None):
        """
        Args:
            controller: SheetController 实例
            target_widget: 目标 ClearableTextEdit，数据拉取后写入此组件
        """
        super().__init__(parent)
        self.controller = controller
        self.target_widget = target_widget
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.sheet_combo = QComboBox()
        self.sheet_combo.setMinimumWidth(100)
        self.sheet_combo.setPlaceholderText("工作表")

        self.range_input = QLineEdit()
        self.range_input.setPlaceholderText("范围 如 A1:A50")
        self.range_input.setMaximumWidth(120)

        self.btn_refresh = QPushButton("🔄")
        self.btn_refresh.setToolTip("刷新工作表列表")
        self.btn_refresh.setMaximumWidth(30)
        self.btn_refresh.clicked.connect(self._load_sheets)

        self.btn_fetch = QPushButton("📥 读取")
        self.btn_fetch.setToolTip("从表格拉取数据填入输入框")
        self.btn_fetch.clicked.connect(self._fetch_data)

        layout.addWidget(QLabel("📊"))
        layout.addWidget(self.btn_refresh)
        layout.addWidget(self.sheet_combo)
        layout.addWidget(self.range_input)
        layout.addWidget(self.btn_fetch)

    def _load_sheets(self):
        """加载当前已连接表格的工作表列表"""
        if not self.controller or not self.controller.is_connected:
            QMessageBox.warning(self, "提示", "请先在左侧连接 Google Sheet")
            return
        try:
            sheets = self.controller.service.list_sheets()
            self.sheet_combo.clear()
            self.sheet_combo.addItems(sheets)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载工作表失败: {e}")

    def _fetch_data(self):
        """从表格拉取数据并填入目标文本框"""
        if not self.controller or not self.controller.is_connected:
            QMessageBox.warning(self, "提示", "请先在左侧连接 Google Sheet")
            return

        sheet_name = self.sheet_combo.currentText()
        if not sheet_name:
            QMessageBox.warning(self, "提示", "请先选择工作表")
            return

        range_str = self.range_input.text().strip()
        if range_str:
            full_range = f"'{sheet_name}'!{range_str}"
        else:
            full_range = sheet_name

        try:
            QApplication.processEvents()
            data = self.controller.service.read_data(full_range)
            if not data:
                QMessageBox.information(self, "提示", "未读取到数据")
                return

            # 将二维数据转为文本：每行用 tab 分隔，行之间用换行
            lines = []
            for row in data:
                lines.append("\t".join(str(c) for c in row))
            text = "\n".join(lines)
            self.target_widget.setPlainText(text)
        except Exception as e:
            QMessageBox.warning(self, "读取失败", str(e))


def _make_input_group(title, controller, parent=None):
    """
    创建一个带标题的输入区域，包含 ClearableTextEdit 和 SheetDataSourcePanel。
    返回 (group_widget, text_edit, source_panel)
    """
    group = QGroupBox(title)
    layout = QVBoxLayout(group)
    layout.setSpacing(4)

    text_edit = ClearableTextEdit()
    text_edit.setPlaceholderText(f"在此手动输入数据，或点击右侧从表格读取...")
    text_edit.setMinimumHeight(80)

    source_panel = SheetDataSourcePanel(controller, text_edit, parent)

    layout.addWidget(source_panel)
    layout.addWidget(text_edit)

    return group, text_edit, source_panel


# ================================================================
# Tab 1：对比差异
# ================================================================

class DiffComparePanel(QWidget):
    """行级差异对比面板"""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 输入区域（上方左右分栏）
        input_splitter = QSplitter(Qt.Horizontal)

        self.group_a, self.input_a, _ = _make_input_group("📄 文本 A", self.controller, self)
        self.group_b, self.input_b, _ = _make_input_group("📄 文本 B", self.controller, self)

        input_splitter.addWidget(self.group_a)
        input_splitter.addWidget(self.group_b)
        layout.addWidget(input_splitter, 2)

        # 选项与按钮行
        ctrl_layout = QHBoxLayout()

        self.chk_ignore_blank = QCheckBox("忽略空行")
        self.chk_ignore_case = QCheckBox("忽略大小写")
        ctrl_layout.addWidget(self.chk_ignore_blank)
        ctrl_layout.addWidget(self.chk_ignore_case)
        ctrl_layout.addStretch()

        self.btn_compare = QPushButton("🔍 开始对比")
        self.btn_compare.setObjectName("primary_btn")
        self.btn_compare.clicked.connect(self._perform_diff)
        ctrl_layout.addWidget(self.btn_compare)

        self.btn_copy = QPushButton("📋 复制结果")
        self.btn_copy.clicked.connect(self._copy_result)
        ctrl_layout.addWidget(self.btn_copy)

        layout.addLayout(ctrl_layout)

        # 输出区域
        output_group = QGroupBox("📊 差异结果")
        output_layout = QVBoxLayout(output_group)
        self.output = ClearableTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(100)
        output_layout.addWidget(self.output)

        self.status = QLabel("")
        output_layout.addWidget(self.status)

        layout.addWidget(output_group, 2)

    def _perform_diff(self):
        """执行行级差异对比"""
        text_a = self.input_a.toPlainText()
        text_b = self.input_b.toPlainText()

        lines_a = text_a.splitlines()
        lines_b = text_b.splitlines()

        # 忽略空行
        if self.chk_ignore_blank.isChecked():
            lines_a = [l for l in lines_a if l.strip()]
            lines_b = [l for l in lines_b if l.strip()]

        # 忽略大小写（对比用小写，显示用原文）
        if self.chk_ignore_case.isChecked():
            cmp_a = [l.lower() for l in lines_a]
            cmp_b = [l.lower() for l in lines_b]
        else:
            cmp_a = lines_a
            cmp_b = lines_b

        # 使用 unified_diff 生成差异
        diff = list(difflib.unified_diff(
            sorted(cmp_a), sorted(cmp_b),
            fromfile="文本 A", tofile="文本 B",
            lineterm=""
        ))

        if not diff:
            self.output.setHtml(
                "<p style='color: #4CAF50; font-size: 14px;'>✅ 两段文本完全相同，无差异。</p>"
            )
            self.status.setText("✅ 无差异")
            return

        # 使用 HTML 彩色渲染 diff 结果
        html_parts = ["<pre style='font-family: Consolas, monospace; font-size: 12px;'>"]
        add_count = 0
        del_count = 0

        for line in diff:
            escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if line.startswith("+++") or line.startswith("---"):
                html_parts.append(f"<span style='color: #666; font-weight: bold;'>{escaped}</span>")
            elif line.startswith("@@"):
                html_parts.append(f"<span style='color: #2196F3;'>{escaped}</span>")
            elif line.startswith("+"):
                html_parts.append(f"<span style='background: #e6ffe6; color: #2e7d32;'>{escaped}</span>")
                add_count += 1
            elif line.startswith("-"):
                html_parts.append(f"<span style='background: #ffe6e6; color: #c62828;'>{escaped}</span>")
                del_count += 1
            else:
                html_parts.append(escaped)

        html_parts.append("</pre>")
        self.output.setHtml("\n".join(html_parts))
        self.status.setText(f"📊 差异统计：新增 {add_count} 行，删除 {del_count} 行")

    def _copy_result(self):
        text = self.output.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status.setText("✅ 已复制到剪贴板")


# ================================================================
# Tab 2：字符比较（字符级高亮）
# ================================================================

class CharComparePanel(QWidget):
    """字符级差异比较面板，高亮显示每个字符的差异"""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 输入区域
        input_splitter = QSplitter(Qt.Horizontal)

        self.group_a, self.input_a, _ = _make_input_group("🔤 文本 A", self.controller, self)
        self.group_b, self.input_b, _ = _make_input_group("🔤 文本 B", self.controller, self)

        input_splitter.addWidget(self.group_a)
        input_splitter.addWidget(self.group_b)
        layout.addWidget(input_splitter, 2)

        # 按钮行
        ctrl_layout = QHBoxLayout()
        ctrl_layout.addStretch()

        self.btn_compare = QPushButton("🔍 字符级比较")
        self.btn_compare.setObjectName("primary_btn")
        self.btn_compare.clicked.connect(self._perform_char_diff)
        ctrl_layout.addWidget(self.btn_compare)

        self.btn_copy = QPushButton("📋 复制结果")
        self.btn_copy.clicked.connect(self._copy_result)
        ctrl_layout.addWidget(self.btn_copy)

        layout.addLayout(ctrl_layout)

        # 输出区域 — 文本 A 的标注视图
        output_group = QGroupBox("📊 字符级差异高亮")
        output_layout = QVBoxLayout(output_group)

        hint = QLabel("🟥 删除的字符　🟩 新增的字符　⬜ 相同的字符")
        hint.setStyleSheet("color: #666; font-size: 11px;")
        output_layout.addWidget(hint)

        self.output = ClearableTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(100)
        output_layout.addWidget(self.output)

        self.status = QLabel("")
        output_layout.addWidget(self.status)

        layout.addWidget(output_group, 2)

    def _perform_char_diff(self):
        """使用 SequenceMatcher 进行字符级比较"""
        text_a = self.input_a.toPlainText()
        text_b = self.input_b.toPlainText()

        if not text_a and not text_b:
            self.status.setText("⚠️ 请输入文本")
            return

        matcher = difflib.SequenceMatcher(None, text_a, text_b)
        opcodes = matcher.get_opcodes()

        html_parts = ["<pre style='font-family: Consolas, monospace; font-size: 13px; "
                       "line-height: 1.6; word-wrap: break-word; white-space: pre-wrap;'>"]

        equal_count = 0
        diff_count = 0

        for tag, i1, i2, j1, j2 in opcodes:
            a_chunk = text_a[i1:i2].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            b_chunk = text_b[j1:j2].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            # 将换行符转为可见标记
            a_display = a_chunk.replace("\n", "↵\n")
            b_display = b_chunk.replace("\n", "↵\n")

            if tag == "equal":
                html_parts.append(a_display)
                equal_count += (i2 - i1)
            elif tag == "delete":
                html_parts.append(
                    f"<span style='background: #ffcdd2; color: #b71c1c; "
                    f"text-decoration: line-through;'>{a_display}</span>"
                )
                diff_count += (i2 - i1)
            elif tag == "insert":
                html_parts.append(
                    f"<span style='background: #c8e6c9; color: #1b5e20;'>{b_display}</span>"
                )
                diff_count += (j2 - j1)
            elif tag == "replace":
                html_parts.append(
                    f"<span style='background: #ffcdd2; color: #b71c1c; "
                    f"text-decoration: line-through;'>{a_display}</span>"
                )
                html_parts.append(
                    f"<span style='background: #c8e6c9; color: #1b5e20;'>{b_display}</span>"
                )
                diff_count += max(i2 - i1, j2 - j1)

        html_parts.append("</pre>")
        self.output.setHtml("".join(html_parts))

        ratio = matcher.ratio()
        self.status.setText(
            f"📊 相似度: {ratio:.1%} | 相同字符: {equal_count} | 差异字符: {diff_count}"
        )

    def _copy_result(self):
        text = self.output.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status.setText("✅ 已复制到剪贴板")


# ================================================================
# Tab 3：字符串拼接
# ================================================================

class StringConcatPanel(QWidget):
    """字符串拼接面板，支持 CONCATENATE / TEXT_JOIN / 交叉拼接"""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 输入区域
        input_splitter = QSplitter(Qt.Horizontal)

        self.group_a, self.input_a, _ = _make_input_group(
            "📝 列表 A（每行一个值）", self.controller, self
        )
        self.group_b, self.input_b, _ = _make_input_group(
            "📝 列表 B（每行一个值）", self.controller, self
        )

        input_splitter.addWidget(self.group_a)
        input_splitter.addWidget(self.group_b)
        layout.addWidget(input_splitter, 2)

        # 模式与选项
        ctrl_layout = QHBoxLayout()

        ctrl_layout.addWidget(QLabel("模式:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "CONCATENATE（纵向拼接所有值）",
            "TEXT_JOIN（用分隔符连接所有值）",
            "交叉拼接（A1+B1, A2+B2...）"
        ])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        ctrl_layout.addWidget(self.mode_combo)

        ctrl_layout.addWidget(QLabel("分隔符:"))
        self.sep_input = QLineEdit(",")
        self.sep_input.setMaximumWidth(60)
        ctrl_layout.addWidget(self.sep_input)

        ctrl_layout.addStretch()

        self.btn_run = QPushButton("🔗 执行拼接")
        self.btn_run.setObjectName("primary_btn")
        self.btn_run.clicked.connect(self._perform_concat)
        ctrl_layout.addWidget(self.btn_run)

        self.btn_copy = QPushButton("📋 复制结果")
        self.btn_copy.clicked.connect(self._copy_result)
        ctrl_layout.addWidget(self.btn_copy)

        layout.addLayout(ctrl_layout)

        # 输出区域
        output_group = QGroupBox("📊 拼接结果")
        output_layout = QVBoxLayout(output_group)
        self.output = ClearableTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(80)
        output_layout.addWidget(self.output)
        self.status = QLabel("")
        output_layout.addWidget(self.status)
        layout.addWidget(output_group, 1)

    def _on_mode_changed(self, index):
        """根据模式切换分隔符输入框的可用性"""
        self.sep_input.setEnabled(index >= 1)

    def _perform_concat(self):
        """执行字符串拼接"""
        text_a = self.input_a.toPlainText()
        text_b = self.input_b.toPlainText()

        lines_a = text_a.splitlines() if text_a.strip() else []
        lines_b = text_b.splitlines() if text_b.strip() else []
        all_values = lines_a + lines_b

        mode = self.mode_combo.currentIndex()
        sep = self.sep_input.text()

        # 处理转义分隔符
        sep = sep.replace("\\n", "\n").replace("\\t", "\t")

        if mode == 0:
            # CONCATENATE — 直接拼接所有值
            result = "".join(all_values)
            self.output.setPlainText(result)
            self.status.setText(f"✅ 已拼接 {len(all_values)} 个值（总长度 {len(result)}）")

        elif mode == 1:
            # TEXT_JOIN — 用分隔符连接
            result = sep.join(all_values)
            self.output.setPlainText(result)
            self.status.setText(f"✅ 已用分隔符连接 {len(all_values)} 个值")

        elif mode == 2:
            # 交叉拼接 — A1+B1, A2+B2...
            max_len = max(len(lines_a), len(lines_b))
            results = []
            for i in range(max_len):
                a = lines_a[i] if i < len(lines_a) else ""
                b = lines_b[i] if i < len(lines_b) else ""
                results.append(f"{a}{sep}{b}")
            self.output.setPlainText("\n".join(results))
            self.status.setText(f"✅ 已交叉拼接 {max_len} 行")

    def _copy_result(self):
        text = self.output.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status.setText("✅ 已复制到剪贴板")


# ================================================================
# Tab 4：文本转换
# ================================================================

class TextTransformPanel(QWidget):
    """文本批量转换面板：大小写、去空白、提取、正则替换"""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 输入区域
        self.group_input, self.input_text, _ = _make_input_group(
            "📝 输入文本", self.controller, self
        )
        layout.addWidget(self.group_input, 2)

        # 操作选择区
        ops_group = QGroupBox("⚙️ 转换操作")
        ops_layout = QVBoxLayout(ops_group)

        # 第一行：预设转换
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("预设:"))
        self.op_combo = QComboBox()
        self.op_combo.addItems([
            "全部转大写 (UPPER)",
            "全部转小写 (LOWER)",
            "首字母大写 (PROPER)",
            "去除首尾空格 (TRIM)",
            "去除所有空格",
            "去除重复空格（合并为一个）",
            "提取数字",
            "提取邮箱地址",
            "提取 URL 链接",
            "自定义正则替换"
        ])
        self.op_combo.currentIndexChanged.connect(self._on_op_changed)
        row1.addWidget(self.op_combo, 1)
        ops_layout.addLayout(row1)

        # 第二行：正则替换参数（默认隐藏）
        self.regex_widget = QWidget()
        regex_layout = QHBoxLayout(self.regex_widget)
        regex_layout.setContentsMargins(0, 0, 0, 0)
        regex_layout.addWidget(QLabel("查找模式:"))
        self.regex_pattern = QLineEdit()
        self.regex_pattern.setPlaceholderText("正则表达式...")
        regex_layout.addWidget(self.regex_pattern, 1)
        regex_layout.addWidget(QLabel("替换为:"))
        self.regex_replace = QLineEdit()
        self.regex_replace.setPlaceholderText("替换内容...")
        regex_layout.addWidget(self.regex_replace, 1)
        self.regex_widget.setVisible(False)
        ops_layout.addWidget(self.regex_widget)

        layout.addWidget(ops_group)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_run = QPushButton("🔁 执行转换")
        self.btn_run.setObjectName("primary_btn")
        self.btn_run.clicked.connect(self._perform_transform)
        btn_layout.addWidget(self.btn_run)
        self.btn_copy = QPushButton("📋 复制结果")
        self.btn_copy.clicked.connect(self._copy_result)
        btn_layout.addWidget(self.btn_copy)
        layout.addLayout(btn_layout)

        # 输出
        output_group = QGroupBox("📊 转换结果")
        output_layout = QVBoxLayout(output_group)
        self.output = ClearableTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(80)
        output_layout.addWidget(self.output)
        self.status = QLabel("")
        output_layout.addWidget(self.status)
        layout.addWidget(output_group, 2)

    def _on_op_changed(self, index):
        """显示/隐藏正则替换参数"""
        self.regex_widget.setVisible(index == 9)

    def _perform_transform(self):
        """执行文本转换"""
        text = self.input_text.toPlainText()
        if not text:
            self.status.setText("⚠️ 请输入文本")
            return

        op = self.op_combo.currentIndex()
        lines = text.splitlines()

        try:
            if op == 0:  # 大写
                result = "\n".join(l.upper() for l in lines)
            elif op == 1:  # 小写
                result = "\n".join(l.lower() for l in lines)
            elif op == 2:  # 首字母大写
                result = "\n".join(l.title() for l in lines)
            elif op == 3:  # 去首尾空格
                result = "\n".join(l.strip() for l in lines)
            elif op == 4:  # 去所有空格
                result = "\n".join(l.replace(" ", "").replace("\t", "") for l in lines)
            elif op == 5:  # 去重复空格
                result = "\n".join(re.sub(r'\s+', ' ', l).strip() for l in lines)
            elif op == 6:  # 提取数字
                extracted = []
                for l in lines:
                    nums = re.findall(r'-?\d+\.?\d*', l)
                    extracted.append(", ".join(nums) if nums else "(无数字)")
                result = "\n".join(extracted)
            elif op == 7:  # 提取邮箱
                extracted = []
                for l in lines:
                    emails = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', l)
                    extracted.append(", ".join(emails) if emails else "(无邮箱)")
                result = "\n".join(extracted)
            elif op == 8:  # 提取 URL
                extracted = []
                for l in lines:
                    urls = re.findall(r'https?://[^\s<>"\']+', l)
                    extracted.append(", ".join(urls) if urls else "(无 URL)")
                result = "\n".join(extracted)
            elif op == 9:  # 正则替换
                pattern = self.regex_pattern.text()
                replacement = self.regex_replace.text()
                if not pattern:
                    self.status.setText("⚠️ 请输入正则表达式")
                    return
                result = "\n".join(re.sub(pattern, replacement, l) for l in lines)
            else:
                result = text

            self.output.setPlainText(result)
            self.status.setText(f"✅ 转换完成（处理 {len(lines)} 行）")

        except re.error as e:
            self.status.setText(f"❌ 正则表达式错误: {e}")
        except Exception as e:
            self.status.setText(f"❌ 转换失败: {e}")

    def _copy_result(self):
        text = self.output.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status.setText("✅ 已复制到剪贴板")


# ================================================================
# Tab 5：列拆分 / 合并
# ================================================================

class ColumnSplitMergePanel(QWidget):
    """列拆分/合并面板"""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 模式切换
        mode_layout = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.radio_split = QRadioButton("✂️ 拆分模式（一列拆为多列）")
        self.radio_merge = QRadioButton("🔗 合并模式（多列合为一列）")
        self.radio_split.setChecked(True)
        self.mode_group.addButton(self.radio_split, 0)
        self.mode_group.addButton(self.radio_merge, 1)
        mode_layout.addWidget(self.radio_split)
        mode_layout.addWidget(self.radio_merge)
        mode_layout.addStretch()
        self.mode_group.idToggled.connect(self._on_mode_toggled)
        layout.addLayout(mode_layout)

        # 输入区域
        self.group_input, self.input_text, _ = _make_input_group(
            "📝 输入数据（每行一条记录）", self.controller, self
        )
        layout.addWidget(self.group_input, 2)

        # 参数区
        param_layout = QHBoxLayout()
        param_layout.addWidget(QLabel("分隔符:"))
        self.sep_input = QLineEdit(",")
        self.sep_input.setMaximumWidth(80)
        param_layout.addWidget(self.sep_input)

        # 合并模式的格式模板
        self.merge_label = QLabel("合并模板:")
        self.merge_template = QLineEdit("{1} {2}")
        self.merge_template.setPlaceholderText("如: {1}-{2}_{3}")
        self.merge_template.setToolTip(
            "使用 {1}, {2}, {3}... 引用输入行中用 Tab 分隔的各列。\n"
            "例如输入 '张三\\t北京'，模板 '{1} - {2}' → '张三 - 北京'"
        )
        self.merge_label.setVisible(False)
        self.merge_template.setVisible(False)
        param_layout.addWidget(self.merge_label)
        param_layout.addWidget(self.merge_template, 1)

        param_layout.addStretch()

        self.btn_run = QPushButton("⚡ 执行")
        self.btn_run.setObjectName("primary_btn")
        self.btn_run.clicked.connect(self._perform)
        param_layout.addWidget(self.btn_run)

        self.btn_copy = QPushButton("📋 复制")
        self.btn_copy.clicked.connect(self._copy_result)
        param_layout.addWidget(self.btn_copy)

        layout.addLayout(param_layout)

        # 输出区域
        output_group = QGroupBox("📊 处理结果")
        output_layout = QVBoxLayout(output_group)
        self.output = ClearableTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(80)
        output_layout.addWidget(self.output)
        self.status = QLabel("")
        output_layout.addWidget(self.status)
        layout.addWidget(output_group, 2)

    def _on_mode_toggled(self, btn_id, checked):
        """切换拆分/合并模式时更新 UI"""
        if not checked:
            return
        is_merge = (btn_id == 1)
        self.merge_label.setVisible(is_merge)
        self.merge_template.setVisible(is_merge)
        if is_merge:
            self.input_text.setPlaceholderText(
                "每行一条记录，列之间用 Tab 分隔（从表格复制粘贴即可）"
            )
        else:
            self.input_text.setPlaceholderText(
                "每行一个值，将按分隔符拆分为多列"
            )

    def _perform(self):
        """执行拆分或合并"""
        text = self.input_text.toPlainText()
        if not text.strip():
            self.status.setText("⚠️ 请输入数据")
            return

        lines = text.splitlines()
        sep = self.sep_input.text()
        # 处理常用转义
        sep = sep.replace("\\t", "\t").replace("\\n", "\n")

        is_merge = self.radio_merge.isChecked()

        if not is_merge:
            # 拆分模式
            result_rows = []
            for line in lines:
                parts = line.split(sep)
                result_rows.append("\t".join(p.strip() for p in parts))
            self.output.setPlainText("\n".join(result_rows))
            max_cols = max(len(r.split("\t")) for r in result_rows) if result_rows else 0
            self.status.setText(f"✅ 已拆分 {len(lines)} 行 → 最多 {max_cols} 列（Tab 分隔）")
        else:
            # 合并模式
            template = self.merge_template.text()
            if not template:
                self.status.setText("⚠️ 请输入合并模板")
                return

            results = []
            for line in lines:
                cols = line.split("\t")
                merged = template
                for idx, col in enumerate(cols, 1):
                    merged = merged.replace(f"{{{idx}}}", col.strip())
                results.append(merged)

            self.output.setPlainText("\n".join(results))
            self.status.setText(f"✅ 已合并 {len(lines)} 行")

    def _copy_result(self):
        text = self.output.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status.setText("✅ 已复制到剪贴板")


# ================================================================
# Tab 6：数据清洗
# ================================================================

class DataCleanPanel(QWidget):
    """数据清洗面板：不可见字符、日期格式、全半角等"""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 输入
        self.group_input, self.input_text, _ = _make_input_group(
            "📝 待清洗数据", self.controller, self
        )
        layout.addWidget(self.group_input, 2)

        # 清洗选项（多选）
        opts_group = QGroupBox("🧹 清洗选项（可多选）")
        opts_layout = QGridLayout(opts_group)

        self.chk_invisible = QCheckBox("去除不可见字符（零宽空格、BOM 等）")
        self.chk_invisible.setChecked(True)
        self.chk_trim = QCheckBox("去除每行首尾空格")
        self.chk_trim.setChecked(True)
        self.chk_dup_spaces = QCheckBox("合并连续空格为单个")
        self.chk_fullwidth = QCheckBox("全角 → 半角（字母、数字、标点）")
        self.chk_halfwidth = QCheckBox("半角 → 全角（字母、数字、标点）")
        self.chk_normalize_date = QCheckBox("统一日期格式")
        self.chk_strip_comma = QCheckBox("去除数字中的千分位逗号")
        self.chk_strip_currency = QCheckBox("去除货币符号（$、¥、€ 等）")
        self.chk_empty_lines = QCheckBox("去除空行")

        opts_layout.addWidget(self.chk_invisible, 0, 0)
        opts_layout.addWidget(self.chk_trim, 0, 1)
        opts_layout.addWidget(self.chk_dup_spaces, 0, 2)
        opts_layout.addWidget(self.chk_fullwidth, 1, 0)
        opts_layout.addWidget(self.chk_halfwidth, 1, 1)
        opts_layout.addWidget(self.chk_normalize_date, 1, 2)
        opts_layout.addWidget(self.chk_strip_comma, 2, 0)
        opts_layout.addWidget(self.chk_strip_currency, 2, 1)
        opts_layout.addWidget(self.chk_empty_lines, 2, 2)

        # 日期目标格式
        date_layout = QHBoxLayout()
        date_layout.addWidget(QLabel("目标日期格式:"))
        self.date_format = QComboBox()
        self.date_format.addItems([
            "YYYY-MM-DD", "YYYY/MM/DD", "DD/MM/YYYY",
            "MM/DD/YYYY", "YYYY.MM.DD"
        ])
        date_layout.addWidget(self.date_format)
        date_layout.addStretch()
        opts_layout.addLayout(date_layout, 3, 0, 1, 3)

        layout.addWidget(opts_group)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_run = QPushButton("🧹 执行清洗")
        self.btn_run.setObjectName("primary_btn")
        self.btn_run.clicked.connect(self._perform_clean)
        btn_layout.addWidget(self.btn_run)
        self.btn_copy = QPushButton("📋 复制结果")
        self.btn_copy.clicked.connect(self._copy_result)
        btn_layout.addWidget(self.btn_copy)
        layout.addLayout(btn_layout)

        # 输出
        output_group = QGroupBox("📊 清洗结果")
        output_layout = QVBoxLayout(output_group)
        self.output = ClearableTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(80)
        output_layout.addWidget(self.output)
        self.status = QLabel("")
        output_layout.addWidget(self.status)
        layout.addWidget(output_group, 1)

    def _perform_clean(self):
        """执行数据清洗"""
        text = self.input_text.toPlainText()
        if not text.strip():
            self.status.setText("⚠️ 请输入数据")
            return

        lines = text.splitlines()
        changes = 0

        cleaned = []
        for line in lines:
            original = line

            # 去除不可见字符
            if self.chk_invisible.isChecked():
                # 去除 BOM、零宽空格、零宽连接符等
                line = line.replace('\ufeff', '').replace('\u200b', '')
                line = line.replace('\u200c', '').replace('\u200d', '')
                line = line.replace('\u00a0', ' ')  # 非断行空格 → 普通空格
                # 去除其他控制字符（保留换行和 tab）
                line = ''.join(c for c in line if c in '\t' or (ord(c) >= 32 or c == '\n'))

            # 去首尾空格
            if self.chk_trim.isChecked():
                line = line.strip()

            # 合并连续空格
            if self.chk_dup_spaces.isChecked():
                line = re.sub(r' {2,}', ' ', line)

            # 全角 → 半角
            if self.chk_fullwidth.isChecked():
                line = self._fullwidth_to_halfwidth(line)

            # 半角 → 全角
            if self.chk_halfwidth.isChecked():
                line = self._halfwidth_to_fullwidth(line)

            # 去千分位逗号
            if self.chk_strip_comma.isChecked():
                line = re.sub(r'(\d),(\d{3})', r'\1\2', line)
                # 再次处理多个逗号 如 1,000,000
                while re.search(r'(\d),(\d{3})', line):
                    line = re.sub(r'(\d),(\d{3})', r'\1\2', line)

            # 去货币符号
            if self.chk_strip_currency.isChecked():
                line = re.sub(r'[$¥€£₩₹￥＄]', '', line)

            # 统一日期格式
            if self.chk_normalize_date.isChecked():
                line = self._normalize_date(line)

            if line != original:
                changes += 1

            cleaned.append(line)

        # 去除空行
        if self.chk_empty_lines.isChecked():
            before = len(cleaned)
            cleaned = [l for l in cleaned if l.strip()]
            changes += (before - len(cleaned))

        self.output.setPlainText("\n".join(cleaned))
        self.status.setText(f"✅ 清洗完成（{len(cleaned)} 行，{changes} 处变更）")

    @staticmethod
    def _fullwidth_to_halfwidth(text):
        """全角转半角"""
        result = []
        for char in text:
            code = ord(char)
            if 0xFF01 <= code <= 0xFF5E:
                # 全角 ASCII 字符范围 → 半角
                result.append(chr(code - 0xFEE0))
            elif code == 0x3000:
                # 全角空格 → 半角空格
                result.append(' ')
            else:
                result.append(char)
        return ''.join(result)

    @staticmethod
    def _halfwidth_to_fullwidth(text):
        """半角转全角"""
        result = []
        for char in text:
            code = ord(char)
            if 0x21 <= code <= 0x7E:
                # 半角 ASCII 可打印字符 → 全角
                result.append(chr(code + 0xFEE0))
            elif code == 0x20:
                # 半角空格 → 全角空格
                result.append('\u3000')
            else:
                result.append(char)
        return ''.join(result)

    def _normalize_date(self, text):
        """尝试统一日期格式"""
        fmt_map = {
            "YYYY-MM-DD": "%Y-%m-%d",
            "YYYY/MM/DD": "%Y/%m/%d",
            "DD/MM/YYYY": "%d/%m/%Y",
            "MM/DD/YYYY": "%m/%d/%Y",
            "YYYY.MM.DD": "%Y.%m.%d",
        }
        target_fmt = fmt_map.get(self.date_format.currentText(), "%Y-%m-%d")

        # 常见输入格式
        input_formats = [
            "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y",
            "%Y.%m.%d", "%d.%m.%Y", "%d-%m-%Y",
            "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
        ]

        # 尝试在文本中识别日期并替换
        # 简单匹配日期样式的子串
        date_pattern = re.compile(
            r'\b(\d{1,4}[/\-\.]\d{1,2}[/\-\.]\d{1,4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?)\b'
        )

        def replace_date(match):
            date_str = match.group(1)
            for fmt in input_formats:
                try:
                    parsed = datetime.strptime(date_str.strip(), fmt)
                    return parsed.strftime(target_fmt)
                except ValueError:
                    continue
            return date_str  # 无法解析则保持原样

        return date_pattern.sub(replace_date, text)

    def _copy_result(self):
        text = self.output.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status.setText("✅ 已复制到剪贴板")


# ================================================================
# Tab 7：频次统计
# ================================================================

class FrequencyPanel(QWidget):
    """频次统计面板：统计每个值出现频次并排序"""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 输入
        self.group_input, self.input_text, _ = _make_input_group(
            "📝 输入数据（每行一个值）", self.controller, self
        )
        layout.addWidget(self.group_input, 2)

        # 选项与按钮
        ctrl_layout = QHBoxLayout()

        self.chk_ignore_case = QCheckBox("忽略大小写")
        self.chk_ignore_blank = QCheckBox("忽略空行")
        self.chk_ignore_blank.setChecked(True)
        self.chk_trim = QCheckBox("去除首尾空格")
        self.chk_trim.setChecked(True)

        ctrl_layout.addWidget(self.chk_ignore_case)
        ctrl_layout.addWidget(self.chk_ignore_blank)
        ctrl_layout.addWidget(self.chk_trim)

        ctrl_layout.addWidget(QLabel("排序:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["频次降序", "频次升序", "按值排序"])
        ctrl_layout.addWidget(self.sort_combo)

        ctrl_layout.addStretch()

        self.btn_run = QPushButton("📊 统计频次")
        self.btn_run.setObjectName("primary_btn")
        self.btn_run.clicked.connect(self._perform_count)
        ctrl_layout.addWidget(self.btn_run)

        self.btn_copy = QPushButton("📋 复制")
        self.btn_copy.clicked.connect(self._copy_result)
        ctrl_layout.addWidget(self.btn_copy)

        layout.addLayout(ctrl_layout)

        # 结果表格
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["值", "频次", "占比"])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 2)

        self.status = QLabel("")
        layout.addWidget(self.status)

    def _perform_count(self):
        """执行频次统计"""
        text = self.input_text.toPlainText()
        if not text.strip():
            self.status.setText("⚠️ 请输入数据")
            return

        lines = text.splitlines()

        # 预处理
        if self.chk_trim.isChecked():
            lines = [l.strip() for l in lines]
        if self.chk_ignore_blank.isChecked():
            lines = [l for l in lines if l]
        if self.chk_ignore_case.isChecked():
            lines = [l.lower() for l in lines]

        if not lines:
            self.status.setText("⚠️ 预处理后无有效数据")
            return

        counter = Counter(lines)
        total = len(lines)

        # 排序
        sort_mode = self.sort_combo.currentIndex()
        if sort_mode == 0:
            items = counter.most_common()
        elif sort_mode == 1:
            items = counter.most_common()
            items.reverse()
        else:
            items = sorted(counter.items(), key=lambda x: x[0])

        # 填充表格
        self.table.setRowCount(len(items))
        for row, (value, count) in enumerate(items):
            pct = count / total * 100

            self.table.setItem(row, 0, QTableWidgetItem(str(value)))

            count_item = QTableWidgetItem(str(count))
            count_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, count_item)

            pct_item = QTableWidgetItem(f"{pct:.1f}%")
            pct_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, pct_item)

        self.status.setText(
            f"✅ 共 {total} 条数据，{len(items)} 个不同值"
        )

    def _copy_result(self):
        """复制表格结果为 Tab 分隔文本"""
        rows = []
        rows.append("值\t频次\t占比")
        for r in range(self.table.rowCount()):
            cols = []
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                cols.append(item.text() if item else "")
            rows.append("\t".join(cols))
        if len(rows) > 1:
            QApplication.clipboard().setText("\n".join(rows))
            self.status.setText("✅ 已复制到剪贴板")


# ================================================================
# Tab 8：行列转置
# ================================================================

class TransposePanel(QWidget):
    """行列转置面板"""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 输入
        self.group_input, self.input_text, _ = _make_input_group(
            "📝 输入表格数据（Tab 分隔，从表格复制粘贴即可）", self.controller, self
        )
        self.input_text.setPlaceholderText(
            "从表格复制数据粘贴到这里（行用换行分隔，列用 Tab 分隔），\n"
            "或者点击上方从已连接的表格读取。\n\n"
            "示例：\n"
            "姓名\t年龄\t城市\n"
            "张三\t25\t北京\n"
            "李四\t30\t上海"
        )
        layout.addWidget(self.group_input, 2)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_transpose = QPushButton("🔄 行列转置")
        self.btn_transpose.setObjectName("primary_btn")
        self.btn_transpose.clicked.connect(self._perform_transpose)
        btn_layout.addWidget(self.btn_transpose)

        self.btn_copy = QPushButton("📋 复制结果")
        self.btn_copy.clicked.connect(self._copy_result)
        btn_layout.addWidget(self.btn_copy)

        layout.addLayout(btn_layout)

        # 输出
        output_group = QGroupBox("📊 转置结果")
        output_layout = QVBoxLayout(output_group)
        self.output = ClearableTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(100)
        output_layout.addWidget(self.output)
        self.status = QLabel("")
        output_layout.addWidget(self.status)
        layout.addWidget(output_group, 2)

    def _perform_transpose(self):
        """执行行列转置"""
        text = self.input_text.toPlainText()
        if not text.strip():
            self.status.setText("⚠️ 请输入数据")
            return

        lines = text.splitlines()
        # 解析为二维数组
        matrix = [line.split("\t") for line in lines]

        # 计算最大列数并补齐
        max_cols = max(len(row) for row in matrix)
        for row in matrix:
            while len(row) < max_cols:
                row.append("")

        rows_before = len(matrix)
        cols_before = max_cols

        # 转置
        transposed = list(zip(*matrix))

        # 输出
        result_lines = []
        for row in transposed:
            result_lines.append("\t".join(row))

        self.output.setPlainText("\n".join(result_lines))
        self.status.setText(
            f"✅ 转置完成: {rows_before}行×{cols_before}列 → {len(transposed)}行×{len(transposed[0]) if transposed else 0}列"
        )

    def _copy_result(self):
        text = self.output.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status.setText("✅ 已复制到剪贴板")


# ================================================================
# Tab 9：时间戳转换
# ================================================================

class TimestampPanel(QWidget):
    """Unix 时间戳 ↔ 可读日期 转换面板"""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # ====== 单值转换区 ======
        single_group = QGroupBox("🕐 单值转换")
        single_layout = QVBoxLayout(single_group)

        # 当前时间参考
        now_layout = QHBoxLayout()
        self.btn_now = QPushButton("⏱ 获取当前时间戳")
        self.btn_now.clicked.connect(self._fill_current_ts)
        now_layout.addWidget(self.btn_now)
        self.lbl_now = QLabel("")
        now_layout.addWidget(self.lbl_now, 1)
        single_layout.addLayout(now_layout)

        # 时间戳 → 日期
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("时间戳:"))
        self.ts_input = QLineEdit()
        self.ts_input.setPlaceholderText("如 1719300000 或 1719300000000（毫秒）")
        row1.addWidget(self.ts_input, 1)
        self.btn_ts_to_date = QPushButton("→ 转日期")
        self.btn_ts_to_date.clicked.connect(self._ts_to_date)
        row1.addWidget(self.btn_ts_to_date)
        self.ts_result = QLineEdit()
        self.ts_result.setReadOnly(True)
        self.ts_result.setPlaceholderText("转换结果")
        row1.addWidget(self.ts_result, 1)
        single_layout.addLayout(row1)

        # 日期 → 时间戳
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("日期:"))
        self.date_input = QLineEdit()
        self.date_input.setPlaceholderText("如 2025-06-25 12:00:00")
        row2.addWidget(self.date_input, 1)
        self.btn_date_to_ts = QPushButton("→ 转时间戳")
        self.btn_date_to_ts.clicked.connect(self._date_to_ts)
        row2.addWidget(self.btn_date_to_ts)
        self.date_result = QLineEdit()
        self.date_result.setReadOnly(True)
        self.date_result.setPlaceholderText("转换结果")
        row2.addWidget(self.date_result, 1)
        single_layout.addLayout(row2)

        # 时区选择
        tz_layout = QHBoxLayout()
        tz_layout.addWidget(QLabel("时区偏移:"))
        self.tz_combo = QComboBox()
        self.tz_combo.addItems([
            "UTC+0", "UTC+1", "UTC+2", "UTC+3", "UTC+4", "UTC+5",
            "UTC+5:30", "UTC+6", "UTC+7", "UTC+8", "UTC+9", "UTC+10",
            "UTC+11", "UTC+12", "UTC-1", "UTC-2", "UTC-3", "UTC-4",
            "UTC-5", "UTC-6", "UTC-7", "UTC-8", "UTC-9", "UTC-10"
        ])
        self.tz_combo.setCurrentIndex(9)  # 默认 UTC+8
        tz_layout.addWidget(self.tz_combo)

        tz_layout.addWidget(QLabel("单位:"))
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["自动检测", "秒 (s)", "毫秒 (ms)"])
        tz_layout.addWidget(self.unit_combo)

        tz_layout.addStretch()
        single_layout.addLayout(tz_layout)

        layout.addWidget(single_group)

        # ====== 批量转换区 ======
        batch_group = QGroupBox("📋 批量转换（每行一个值）")
        batch_layout = QVBoxLayout(batch_group)

        input_splitter = QSplitter(Qt.Horizontal)

        # 批量输入
        left_w = QWidget()
        left_l = QVBoxLayout(left_w)
        left_l.setContentsMargins(0, 0, 0, 0)
        self.batch_source = SheetDataSourcePanel(self.controller, None, self)
        self.batch_input = ClearableTextEdit()
        self.batch_input.setPlaceholderText("每行一个时间戳或日期...")
        self.batch_source.target_widget = self.batch_input
        left_l.addWidget(self.batch_source)
        left_l.addWidget(self.batch_input)

        # 批量输出
        right_w = QWidget()
        right_l = QVBoxLayout(right_w)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.addWidget(QLabel("📊 批量转换结果:"))
        self.batch_output = ClearableTextEdit()
        self.batch_output.setReadOnly(True)
        right_l.addWidget(self.batch_output)

        input_splitter.addWidget(left_w)
        input_splitter.addWidget(right_w)
        batch_layout.addWidget(input_splitter)

        # 批量按钮行
        batch_btn_layout = QHBoxLayout()

        self.batch_mode = QComboBox()
        self.batch_mode.addItems(["时间戳 → 日期", "日期 → 时间戳"])
        batch_btn_layout.addWidget(self.batch_mode)

        batch_btn_layout.addStretch()
        self.btn_batch = QPushButton("⚡ 批量转换")
        self.btn_batch.setObjectName("primary_btn")
        self.btn_batch.clicked.connect(self._batch_convert)
        batch_btn_layout.addWidget(self.btn_batch)

        self.btn_batch_copy = QPushButton("📋 复制结果")
        self.btn_batch_copy.clicked.connect(
            lambda: self._copy_text(self.batch_output.toPlainText())
        )
        batch_btn_layout.addWidget(self.btn_batch_copy)
        batch_layout.addLayout(batch_btn_layout)

        self.batch_status = QLabel("")
        batch_layout.addWidget(self.batch_status)

        layout.addWidget(batch_group, 1)

    def _get_tz_offset(self):
        """解析当前选择的时区偏移（小时）"""
        tz_text = self.tz_combo.currentText()  # 如 "UTC+8" 或 "UTC+5:30"
        tz_text = tz_text.replace("UTC", "")
        if ":" in tz_text:
            parts = tz_text.split(":")
            hours = int(parts[0])
            minutes = int(parts[1]) if len(parts) > 1 else 0
            if hours < 0:
                minutes = -minutes
            return timedelta(hours=hours, minutes=minutes)
        else:
            return timedelta(hours=int(tz_text) if tz_text else 0)

    def _parse_timestamp(self, ts_str):
        """解析时间戳字符串（自动识别秒/毫秒）"""
        ts_str = ts_str.strip()
        ts = float(ts_str)

        unit_mode = self.unit_combo.currentIndex()
        if unit_mode == 0:
            # 自动检测：大于 10^12 认为是毫秒
            if abs(ts) > 1e12:
                ts = ts / 1000.0
        elif unit_mode == 2:
            ts = ts / 1000.0

        return ts

    def _fill_current_ts(self):
        """填入当前时间戳"""
        import time
        now_ts = int(time.time())
        self.ts_input.setText(str(now_ts))
        tz = self._get_tz_offset()
        dt = datetime.fromtimestamp(now_ts, tz=timezone(tz))
        self.lbl_now.setText(
            f"当前: {now_ts} → {dt.strftime('%Y-%m-%d %H:%M:%S')} ({self.tz_combo.currentText()})"
        )

    def _ts_to_date(self):
        """时间戳 → 日期"""
        try:
            ts = self._parse_timestamp(self.ts_input.text())
            tz = self._get_tz_offset()
            dt = datetime.fromtimestamp(ts, tz=timezone(tz))
            self.ts_result.setText(dt.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as e:
            self.ts_result.setText(f"❌ {e}")

    def _date_to_ts(self):
        """日期 → 时间戳"""
        date_str = self.date_input.text().strip()
        if not date_str:
            self.date_result.setText("⚠️ 请输入日期")
            return

        formats = [
            "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S", "%Y/%m/%d",
            "%d/%m/%Y %H:%M:%S", "%d/%m/%Y",
        ]

        tz = self._get_tz_offset()

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                dt = dt.replace(tzinfo=timezone(tz))
                ts = int(dt.timestamp())
                self.date_result.setText(str(ts))
                return
            except ValueError:
                continue

        self.date_result.setText("❌ 无法解析日期格式")

    def _batch_convert(self):
        """批量转换"""
        text = self.batch_input.toPlainText()
        if not text.strip():
            self.batch_status.setText("⚠️ 请输入数据")
            return

        lines = text.splitlines()
        mode = self.batch_mode.currentIndex()
        tz = self._get_tz_offset()
        results = []
        errors = 0

        for line in lines:
            line = line.strip()
            if not line:
                results.append("")
                continue

            try:
                if mode == 0:
                    # 时间戳 → 日期
                    ts = self._parse_timestamp(line)
                    dt = datetime.fromtimestamp(ts, tz=timezone(tz))
                    results.append(dt.strftime("%Y-%m-%d %H:%M:%S"))
                else:
                    # 日期 → 时间戳
                    formats = [
                        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                        "%Y/%m/%d %H:%M:%S", "%Y/%m/%d",
                    ]
                    parsed = False
                    for fmt in formats:
                        try:
                            dt = datetime.strptime(line, fmt)
                            dt = dt.replace(tzinfo=timezone(tz))
                            results.append(str(int(dt.timestamp())))
                            parsed = True
                            break
                        except ValueError:
                            continue
                    if not parsed:
                        results.append(f"(无法解析: {line})")
                        errors += 1
            except Exception:
                results.append(f"(错误: {line})")
                errors += 1

        self.batch_output.setPlainText("\n".join(results))
        self.batch_status.setText(
            f"✅ 批量转换完成（{len(lines)} 行，{errors} 个错误）"
        )

    def _copy_text(self, text):
        if text:
            QApplication.clipboard().setText(text)
            self.batch_status.setText("✅ 已复制到剪贴板")


# ================================================================
# Tab 10：自动化切分对比
# ================================================================

class AutoSplitComparePanel(QWidget):
    """
    自动化切分对比面板：
    动态寻找混杂数据的分界点，自动切分为两组，并进行集合差异对比。
    """

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 1. 输入区域
        self.group_input, self.input_text, _ = _make_input_group(
            "📝 输入混合数据（包含前后两批数据，程序将自动寻找分界点）", self.controller, self
        )
        layout.addWidget(self.group_input, 1)

        # 2. 控制区域
        ctrl_layout = QHBoxLayout()
        self.chk_trim = QCheckBox("忽略行首尾空格")
        self.chk_trim.setChecked(True)
        self.chk_ignore_blank = QCheckBox("忽略空行")
        self.chk_ignore_blank.setChecked(True)
        self.chk_ignore_case = QCheckBox("忽略大小写")

        ctrl_layout.addWidget(self.chk_trim)
        ctrl_layout.addWidget(self.chk_ignore_blank)
        ctrl_layout.addWidget(self.chk_ignore_case)

        ctrl_layout.addStretch()

        self.btn_run = QPushButton("🔄 自动切分并对比")
        self.btn_run.setObjectName("primary_btn")
        self.btn_run.clicked.connect(self._perform_split_and_compare)
        ctrl_layout.addWidget(self.btn_run)
        layout.addLayout(ctrl_layout)

        # 3. 结果状态信息
        self.status = QLabel("就绪")
        self.status.setStyleSheet("color: #666; font-weight: bold; margin-top: 5px;")
        layout.addWidget(self.status)

        # 4. 输出区域（左右分栏显示只存在于 A 和只存在于 B 的数据）
        output_splitter = QSplitter(Qt.Horizontal)

        # 左侧：仅在 A (第一组)
        group_a_widget = QGroupBox("🔺 仅在第一组存在")
        layout_a = QVBoxLayout(group_a_widget)
        self.output_a = ClearableTextEdit()
        self.output_a.setReadOnly(True)
        btn_copy_a = QPushButton("📋 复制左侧")
        btn_copy_a.clicked.connect(lambda: self._copy_text(self.output_a.toPlainText()))
        layout_a.addWidget(self.output_a)
        layout_a.addWidget(btn_copy_a)

        # 右侧：仅在 B (第二组)
        group_b_widget = QGroupBox("🔻 仅在第二组存在")
        layout_b = QVBoxLayout(group_b_widget)
        self.output_b = ClearableTextEdit()
        self.output_b.setReadOnly(True)
        btn_copy_b = QPushButton("📋 复制右侧")
        btn_copy_b.clicked.connect(lambda: self._copy_text(self.output_b.toPlainText()))
        layout_b.addWidget(self.output_b)
        layout_b.addWidget(btn_copy_b)

        output_splitter.addWidget(group_a_widget)
        output_splitter.addWidget(group_b_widget)
        layout.addWidget(output_splitter, 2)

    def _perform_split_and_compare(self):
        text = self.input_text.toPlainText()
        if not text.strip():
            self.status.setText("⚠️ 请输入数据")
            return

        # 1. 基础清洗
        raw_lines = text.splitlines()
        all_lines = []
        original_map = {}  # 用于在忽略大小写时映射回原文

        for line in raw_lines:
            processed = line
            if self.chk_trim.isChecked():
                processed = processed.strip()
            if self.chk_ignore_blank.isChecked() and not processed:
                continue
                
            compare_val = processed.lower() if self.chk_ignore_case.isChecked() else processed
            all_lines.append(compare_val)
            if compare_val not in original_map:
                 original_map[compare_val] = line.strip() if self.chk_trim.isChecked() else line

        if len(all_lines) < 2:
            self.status.setText("⚠️ 数据量太少，无法切分")
            return

        # 2. 🔥 动态寻找分界点
        split_idx = len(all_lines)  # 默认在末尾
        seen_items = set()
        found = False

        for idx, item in enumerate(all_lines):
            # 动态检测机制：当前项见过，且后面连续 N 项也见过
            if item in seen_items:
                # 优先尝试寻找连续 3 个重复项
                if idx + 2 < len(all_lines) and all_lines[idx + 1] in seen_items and all_lines[idx + 2] in seen_items:
                    split_idx = idx
                    found = True
                    break
                # 退而求其次，寻找连续 2 个重复项
                elif idx + 1 < len(all_lines) and all_lines[idx + 1] in seen_items:
                    split_idx = idx
                    found = True
                    break
                # 如果是最后几行，或者数据本身很短，就以第一个重复项作为分界
                elif not found: 
                     split_idx = idx
                     found = True

            seen_items.add(item)

        if not found:
            self.status.setText("⚠️ 未检测到明显的数据循环，已默认分为一组。")
            split_idx = len(all_lines)

        # 3. 自动切分
        group_a = all_lines[:split_idx]
        group_b = all_lines[split_idx:]

        # 4. 集合对比
        set_a, set_b = set(group_a), set(group_b)
        only_in_a = sorted(list(set_a - set_b))
        only_in_b = sorted(list(set_b - set_a))

        # 还原原文显示
        display_a = [original_map.get(k, k) for k in only_in_a]
        display_b = [original_map.get(k, k) for k in only_in_b]

        self.output_a.setPlainText("\n".join(display_a))
        self.output_b.setPlainText("\n".join(display_b))

        status_msg = f"🎯 切分完成！"
        if found:
            start_item = original_map.get(all_lines[split_idx], all_lines[split_idx])
            status_msg += f" 第二组起点在第 {split_idx + 1} 行 ('{start_item}'...)"
        
        status_msg += f" | 第一组: {len(group_a)} 项, 第二组: {len(group_b)} 项"
        status_msg += f" | 仅左侧有: {len(only_in_a)}, 仅右侧有: {len(only_in_b)}"
        
        self.status.setText(status_msg)

    def _copy_text(self, text):
        if text:
            QApplication.clipboard().setText(text)
            # 使用 QMessageBox 避免覆盖详细的状态信息
            QMessageBox.information(self, "复制成功", "内容已复制到剪贴板！")

# ================================================================
# Tab 11：双列表集合对比
# ================================================================

class SetComparePanel(QWidget):
    """
    双列表集合对比面板：
    用户分别输入列表 A 和列表 B，进行集合操作，找出仅在 A 或仅在 B 存在的数据。
    输出格式与 Tab 10 保持一致。
    """

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        main_splitter = QSplitter(Qt.Vertical)

        # ================= 上半部分（输入 + 控制） =================
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)

        # 1. 输入区域（双面板）
        input_splitter = QSplitter(Qt.Horizontal)

        self.group_a, self.input_a, _ = _make_input_group("📝 列表 A", self.controller, self)
        self.group_b, self.input_b, _ = _make_input_group("📝 列表 B", self.controller, self)

        input_splitter.addWidget(self.group_a)
        input_splitter.addWidget(self.group_b)
        top_layout.addWidget(input_splitter, 1)

        # 2. 控制区域
        ctrl_layout = QHBoxLayout()
        self.chk_trim = QCheckBox("忽略行首尾空格")
        self.chk_trim.setChecked(True)
        self.chk_ignore_blank = QCheckBox("忽略空行")
        self.chk_ignore_blank.setChecked(True)
        self.chk_ignore_case = QCheckBox("忽略大小写")

        ctrl_layout.addWidget(self.chk_trim)
        ctrl_layout.addWidget(self.chk_ignore_blank)
        ctrl_layout.addWidget(self.chk_ignore_case)

        ctrl_layout.addStretch()

        self.btn_run = QPushButton("🔍 集合对比")
        self.btn_run.setObjectName("primary_btn")
        self.btn_run.clicked.connect(self._perform_compare)
        ctrl_layout.addWidget(self.btn_run)
        top_layout.addLayout(ctrl_layout)

        # 3. 结果状态信息
        self.status = QLabel("就绪")
        self.status.setStyleSheet("color: #666; font-weight: bold; margin-top: 5px;")
        top_layout.addWidget(self.status)
        
        main_splitter.addWidget(top_widget)

        # 4. 输出区域（使用 QTabWidget 展示 4 种结果）
        self.output_tabs = QTabWidget()
        
        # 4.1 A 独有
        self.output_a_unique = ClearableTextEdit()
        self.output_a_unique.setReadOnly(True)
        tab_a_unique = QWidget()
        lay_a_unique = QVBoxLayout(tab_a_unique)
        btn_copy_a_unique = QPushButton("📋 复制列表 A 独有")
        btn_copy_a_unique.clicked.connect(lambda: self._copy_text(self.output_a_unique.toPlainText()))
        lay_a_unique.addWidget(self.output_a_unique)
        lay_a_unique.addWidget(btn_copy_a_unique)
        self.output_tabs.addTab(tab_a_unique, "🔺 仅在 A")

        # 4.2 A 中共有
        self.output_a_shared = ClearableTextEdit()
        self.output_a_shared.setReadOnly(True)
        tab_a_shared = QWidget()
        lay_a_shared = QVBoxLayout(tab_a_shared)
        btn_copy_a_shared = QPushButton("📋 复制 A 中共有")
        btn_copy_a_shared.clicked.connect(lambda: self._copy_text(self.output_a_shared.toPlainText()))
        lay_a_shared.addWidget(self.output_a_shared)
        lay_a_shared.addWidget(btn_copy_a_shared)
        self.output_tabs.addTab(tab_a_shared, "🔵 A 中共有")

        # 4.3 B 独有
        self.output_b_unique = ClearableTextEdit()
        self.output_b_unique.setReadOnly(True)
        tab_b_unique = QWidget()
        lay_b_unique = QVBoxLayout(tab_b_unique)
        btn_copy_b_unique = QPushButton("📋 复制列表 B 独有")
        btn_copy_b_unique.clicked.connect(lambda: self._copy_text(self.output_b_unique.toPlainText()))
        lay_b_unique.addWidget(self.output_b_unique)
        lay_b_unique.addWidget(btn_copy_b_unique)
        self.output_tabs.addTab(tab_b_unique, "🔻 仅在 B")

        # 4.4 B 中共有
        self.output_b_shared = ClearableTextEdit()
        self.output_b_shared.setReadOnly(True)
        tab_b_shared = QWidget()
        lay_b_shared = QVBoxLayout(tab_b_shared)
        btn_copy_b_shared = QPushButton("📋 复制 B 中共有")
        btn_copy_b_shared.clicked.connect(lambda: self._copy_text(self.output_b_shared.toPlainText()))
        lay_b_shared.addWidget(self.output_b_shared)
        lay_b_shared.addWidget(btn_copy_b_shared)
        self.output_tabs.addTab(tab_b_shared, "🔵 B 中共有")

        # 4.5 A 在 B 中的数据（以 A 为键，在 B 中查找匹配项，展示 B 的原始数据）
        self.output_a_in_b = ClearableTextEdit()
        self.output_a_in_b.setReadOnly(True)
        tab_a_in_b = QWidget()
        lay_a_in_b = QVBoxLayout(tab_a_in_b)
        btn_copy_a_in_b = QPushButton("📋 复制 A 在 B 中的数据")
        btn_copy_a_in_b.clicked.connect(lambda: self._copy_text(self.output_a_in_b.toPlainText()))
        lay_a_in_b.addWidget(self.output_a_in_b)
        lay_a_in_b.addWidget(btn_copy_a_in_b)
        self.output_tabs.addTab(tab_a_in_b, "🟢 A 在 B 中")

        # 4.6 B 在 A 中的数据（以 B 为键，在 A 中查找匹配项，展示 A 的原始数据）
        self.output_b_in_a = ClearableTextEdit()
        self.output_b_in_a.setReadOnly(True)
        tab_b_in_a = QWidget()
        lay_b_in_a = QVBoxLayout(tab_b_in_a)
        btn_copy_b_in_a = QPushButton("📋 复制 B 在 A 中的数据")
        btn_copy_b_in_a.clicked.connect(lambda: self._copy_text(self.output_b_in_a.toPlainText()))
        lay_b_in_a.addWidget(self.output_b_in_a)
        lay_b_in_a.addWidget(btn_copy_b_in_a)
        self.output_tabs.addTab(tab_b_in_a, "🟠 B 在 A 中")

        # 4.7 A 不在 B 中（A 中存在但 B 中不存在的值，展示 A 的所有原始行）
        self.output_a_not_in_b = ClearableTextEdit()
        self.output_a_not_in_b.setReadOnly(True)
        tab_a_not_in_b = QWidget()
        lay_a_not_in_b = QVBoxLayout(tab_a_not_in_b)
        btn_copy_a_not_in_b = QPushButton("📋 复制 A 不在 B 中的数据")
        btn_copy_a_not_in_b.clicked.connect(lambda: self._copy_text(self.output_a_not_in_b.toPlainText()))
        lay_a_not_in_b.addWidget(self.output_a_not_in_b)
        lay_a_not_in_b.addWidget(btn_copy_a_not_in_b)
        self.output_tabs.addTab(tab_a_not_in_b, "🔴 A 不在 B 中")

        # 4.8 B 不在 A 中（B 中存在但 A 中不存在的值，展示 B 的所有原始行）
        self.output_b_not_in_a = ClearableTextEdit()
        self.output_b_not_in_a.setReadOnly(True)
        tab_b_not_in_a = QWidget()
        lay_b_not_in_a = QVBoxLayout(tab_b_not_in_a)
        btn_copy_b_not_in_a = QPushButton("📋 复制 B 不在 A 中的数据")
        btn_copy_b_not_in_a.clicked.connect(lambda: self._copy_text(self.output_b_not_in_a.toPlainText()))
        lay_b_not_in_a.addWidget(self.output_b_not_in_a)
        lay_b_not_in_a.addWidget(btn_copy_b_not_in_a)
        self.output_tabs.addTab(tab_b_not_in_a, "🟣 B 不在 A 中")

        main_splitter.addWidget(self.output_tabs)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 2)
        layout.addWidget(main_splitter)

    def _process_lines(self, text, original_map):
        """基础清洗辅助函数"""
        lines = []
        for line in text.splitlines():
            processed = line
            if self.chk_trim.isChecked():
                processed = processed.strip()
            if self.chk_ignore_blank.isChecked() and not processed:
                continue
                
            compare_val = processed.lower() if self.chk_ignore_case.isChecked() else processed
            lines.append(compare_val)
            if compare_val not in original_map:
                 original_map[compare_val] = line.strip() if self.chk_trim.isChecked() else line
        return lines

    def _process_lines_with_originals(self, text):
        """
        清洗并返回 (compare_val_list, compare_to_original_map)。
        compare_to_original_map 保留每个比较值对应的所有原始行（一对多）。
        """
        lines = []
        original_multi_map = {}  # compare_val -> [原始行, ...]
        for line in text.splitlines():
            processed = line
            if self.chk_trim.isChecked():
                processed = processed.strip()
            if self.chk_ignore_blank.isChecked() and not processed:
                continue
            compare_val = processed.lower() if self.chk_ignore_case.isChecked() else processed
            lines.append(compare_val)
            display_val = line.strip() if self.chk_trim.isChecked() else line
            original_multi_map.setdefault(compare_val, []).append(display_val)
        return lines, original_multi_map

    def _perform_compare(self):
        text_a = self.input_a.toPlainText()
        text_b = self.input_b.toPlainText()

        if not text_a.strip() and not text_b.strip():
            self.status.setText("⚠️ 请至少在一个列表中输入数据")
            return

        original_map = {}

        # 1. 基础清洗
        group_a = self._process_lines(text_a, original_map)
        group_b = self._process_lines(text_b, original_map)

        # 同时获取多值映射（用于 "A 在 B 中" / "B 在 A 中" 功能）
        _, orig_multi_a = self._process_lines_with_originals(text_a)
        _, orig_multi_b = self._process_lines_with_originals(text_b)

        # 2. 差异对比 (保留顺序和重复项)
        set_a, set_b = set(group_a), set(group_b)
        
        only_in_a = [x for x in group_a if x not in set_b]
        shared_in_a = [x for x in group_a if x in set_b]
        
        only_in_b = [x for x in group_b if x not in set_a]
        shared_in_b = [x for x in group_b if x in set_a]

        # 还原原文显示
        display_a_unique = [original_map.get(k, k) for k in only_in_a]
        display_a_shared = [original_map.get(k, k) for k in shared_in_a]
        
        display_b_unique = [original_map.get(k, k) for k in only_in_b]
        display_b_shared = [original_map.get(k, k) for k in shared_in_b]

        self.output_a_unique.setPlainText("\n".join(display_a_unique))
        self.output_a_shared.setPlainText("\n".join(display_a_shared))
        
        self.output_b_unique.setPlainText("\n".join(display_b_unique))
        self.output_b_shared.setPlainText("\n".join(display_b_shared))

        # 3. 计算 "A 在 B 中的数据" / "B 在 A 中的数据"
        #    以 A 的顺序遍历交集元素，展示 B 中对应的所有原始行
        display_a_in_b = []
        seen_a_in_b = set()
        for val in group_a:
            if val in set_b and val not in seen_a_in_b:
                seen_a_in_b.add(val)
                display_a_in_b.extend(orig_multi_b.get(val, []))

        #    以 B 的顺序遍历交集元素，展示 A 中对应的所有原始行
        display_b_in_a = []
        seen_b_in_a = set()
        for val in group_b:
            if val in set_a and val not in seen_b_in_a:
                seen_b_in_a.add(val)
                display_b_in_a.extend(orig_multi_a.get(val, []))

        self.output_a_in_b.setPlainText("\n".join(display_a_in_b))
        self.output_b_in_a.setPlainText("\n".join(display_b_in_a))

        # 4. 计算 "A 不在 B 中" / "B 不在 A 中"
        #    A 中独有的值，展示 A 的所有原始行（含重复）
        display_a_not_in_b = []
        seen_a_not_in_b = set()
        for val in group_a:
            if val not in set_b and val not in seen_a_not_in_b:
                seen_a_not_in_b.add(val)
                display_a_not_in_b.extend(orig_multi_a.get(val, []))

        #    B 中独有的值，展示 B 的所有原始行（含重复）
        display_b_not_in_a = []
        seen_b_not_in_a = set()
        for val in group_b:
            if val not in set_a and val not in seen_b_not_in_a:
                seen_b_not_in_a.add(val)
                display_b_not_in_a.extend(orig_multi_b.get(val, []))

        self.output_a_not_in_b.setPlainText("\n".join(display_a_not_in_b))
        self.output_b_not_in_a.setPlainText("\n".join(display_b_not_in_a))

        # 更新 Tab 标题以显示数量
        self.output_tabs.setTabText(0, f"🔺 仅在 A ({len(display_a_unique)})")
        self.output_tabs.setTabText(1, f"🔵 A 中共有 ({len(display_a_shared)})")
        self.output_tabs.setTabText(2, f"🔻 仅在 B ({len(display_b_unique)})")
        self.output_tabs.setTabText(3, f"🔵 B 中共有 ({len(display_b_shared)})")
        self.output_tabs.setTabText(4, f"🟢 A 在 B 中 ({len(display_a_in_b)})")
        self.output_tabs.setTabText(5, f"🟠 B 在 A 中 ({len(display_b_in_a)})")
        self.output_tabs.setTabText(6, f"🔴 A 不在 B 中 ({len(display_a_not_in_b)})")
        self.output_tabs.setTabText(7, f"🟣 B 不在 A 中 ({len(display_b_not_in_a)})")

        status_msg = f"🎯 对比完成！"
        status_msg += f" | 列表 A: {len(group_a)} 项, 列表 B: {len(group_b)} 项"
        
        self.status.setText(status_msg)

    def _copy_text(self, text):
        if text:
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "复制成功", "内容已复制到剪贴板！")

# ================================================================
# Tab 12：列号字母转换
# ================================================================

class ColumnConverterPanel(QWidget):
    """列号(1, 2) ↔ 字母(A, B) 转换面板"""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # ====== 单值转换区 ======
        single_group = QGroupBox("🔢 单值转换")
        single_layout = QVBoxLayout(single_group)

        # 数字 → 字母
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("数字列号:"))
        self.num_input = QLineEdit()
        self.num_input.setPlaceholderText("如 1, 26, 27")
        row1.addWidget(self.num_input, 1)
        self.btn_num_to_letter = QPushButton("→ 转字母")
        self.btn_num_to_letter.clicked.connect(self._num_to_letter)
        row1.addWidget(self.btn_num_to_letter)
        self.num_result = QLineEdit()
        self.num_result.setReadOnly(True)
        self.num_result.setPlaceholderText("字母结果 (如 A, Z, AA)")
        row1.addWidget(self.num_result, 1)
        single_layout.addLayout(row1)

        # 字母 → 数字
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("字母列名:"))
        self.letter_input = QLineEdit()
        self.letter_input.setPlaceholderText("如 A, Z, AA")
        row2.addWidget(self.letter_input, 1)
        self.btn_letter_to_num = QPushButton("→ 转数字")
        self.btn_letter_to_num.clicked.connect(self._letter_to_num)
        row2.addWidget(self.btn_letter_to_num)
        self.letter_result = QLineEdit()
        self.letter_result.setReadOnly(True)
        self.letter_result.setPlaceholderText("数字结果 (如 1, 26, 27)")
        row2.addWidget(self.letter_result, 1)
        single_layout.addLayout(row2)

        layout.addWidget(single_group)

        # ====== 批量转换区 ======
        batch_group = QGroupBox("📋 批量转换（每行一个值）")
        batch_layout = QVBoxLayout(batch_group)

        input_splitter = QSplitter(Qt.Horizontal)

        # 批量输入
        left_w = QWidget()
        left_l = QVBoxLayout(left_w)
        left_l.setContentsMargins(0, 0, 0, 0)
        self.batch_input = ClearableTextEdit()
        self.batch_input.setPlaceholderText("每行一个数字或字母...")
        left_l.addWidget(QLabel("📝 待转换列表:"))
        left_l.addWidget(self.batch_input)

        # 批量输出
        right_w = QWidget()
        right_l = QVBoxLayout(right_w)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.addWidget(QLabel("📊 批量转换结果:"))
        self.batch_output = ClearableTextEdit()
        self.batch_output.setReadOnly(True)
        right_l.addWidget(self.batch_output)

        input_splitter.addWidget(left_w)
        input_splitter.addWidget(right_w)
        batch_layout.addWidget(input_splitter)

        # 批量按钮行
        batch_btn_layout = QHBoxLayout()

        self.batch_mode = QComboBox()
        self.batch_mode.addItems(["自动检测", "数字 → 字母", "字母 → 数字"])
        batch_btn_layout.addWidget(self.batch_mode)

        batch_btn_layout.addStretch()
        self.btn_batch = QPushButton("⚡ 批量转换")
        self.btn_batch.setObjectName("primary_btn")
        self.btn_batch.clicked.connect(self._batch_convert)
        batch_btn_layout.addWidget(self.btn_batch)

        self.btn_batch_copy = QPushButton("📋 复制结果")
        self.btn_batch_copy.clicked.connect(
            lambda: self._copy_text(self.batch_output.toPlainText())
        )
        batch_btn_layout.addWidget(self.btn_batch_copy)
        batch_layout.addLayout(batch_btn_layout)

        self.batch_status = QLabel("")
        batch_layout.addWidget(self.batch_status)

        layout.addWidget(batch_group, 1)

    def _col_num_to_letter(self, num):
        if not isinstance(num, int) or num <= 0:
            raise ValueError("列号必须是大于0的正整数")
        letter = ''
        while num > 0:
            num, remainder = divmod(num - 1, 26)
            letter = chr(65 + remainder) + letter
        return letter

    def _col_letter_to_num(self, letter):
        letter = letter.strip().upper()
        if not letter.isalpha():
            raise ValueError("列名只能包含英文字母")
        num = 0
        for char in letter:
            num = num * 26 + (ord(char) - ord('A') + 1)
        return num

    def _num_to_letter(self):
        try:
            val = int(self.num_input.text().strip())
            res = self._col_num_to_letter(val)
            self.num_result.setText(res)
        except ValueError as e:
            self.num_result.setText(f"❌ 错误: {e}")
        except Exception:
            self.num_result.setText("❌ 输入有误")

    def _letter_to_num(self):
        try:
            val = self.letter_input.text().strip()
            if not val:
                return
            res = self._col_letter_to_num(val)
            self.letter_result.setText(str(res))
        except ValueError as e:
            self.letter_result.setText(f"❌ 错误: {e}")

    def _batch_convert(self):
        text = self.batch_input.toPlainText()
        if not text.strip():
            self.batch_status.setText("⚠️ 请输入数据")
            return

        lines = text.splitlines()
        mode = self.batch_mode.currentIndex()
        results = []
        errors = 0

        for line in lines:
            line = line.strip()
            if not line:
                results.append("")
                continue

            try:
                if mode == 0:  # 自动检测
                    if line.isdigit():
                        results.append(self._col_num_to_letter(int(line)))
                    elif line.isalpha():
                        results.append(str(self._col_letter_to_num(line)))
                    else:
                        results.append(f"(无法识别: {line})")
                        errors += 1
                elif mode == 1:  # 数字 -> 字母
                    results.append(self._col_num_to_letter(int(line)))
                elif mode == 2:  # 字母 -> 数字
                    results.append(str(self._col_letter_to_num(line)))
            except Exception:
                results.append(f"(错误: {line})")
                errors += 1

        self.batch_output.setPlainText("\n".join(results))
        self.batch_status.setText(f"✅ 批量转换完成（{len(lines)} 行，{errors} 个错误）")

    def _copy_text(self, text):
        if text:
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "复制成功", "内容已复制到剪贴板！")

# ================================================================
# Tab 13：数据切分
# ================================================================

class DataSplitPanel(QWidget):
    """
    数据切分面板：
    将输入列表按指定数量切分为多个子列表，使用空行分隔。
    """

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        main_splitter = QSplitter(Qt.Vertical)

        # ====== 上半部分（输入 + 控制） ======
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)

        # 1. 输入区域
        self.group_input, self.input_text, _ = _make_input_group(
            "📝 待切分数据", self.controller, self
        )
        top_layout.addWidget(self.group_input, 1)

        # 2. 控制区域
        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel("每组数量:"))
        self.spin_chunk_size = QSpinBox()
        self.spin_chunk_size.setRange(1, 100000)
        self.spin_chunk_size.setValue(3800)
        ctrl_layout.addWidget(self.spin_chunk_size)

        ctrl_layout.addStretch()

        self.btn_run = QPushButton("✂️ 执行切分")
        self.btn_run.setObjectName("primary_btn")
        self.btn_run.clicked.connect(self._perform_split)
        ctrl_layout.addWidget(self.btn_run)
        top_layout.addLayout(ctrl_layout)

        # 3. 结果状态信息
        self.status = QLabel("就绪")
        self.status.setStyleSheet("color: #666; font-weight: bold; margin-top: 5px;")
        top_layout.addWidget(self.status)

        main_splitter.addWidget(top_widget)

        # ====== 下半部分（输出区域） ======
        group_output = QGroupBox("📊 切分结果")
        layout_output = QVBoxLayout(group_output)
        self.output_text = ClearableTextEdit()
        self.output_text.setReadOnly(True)
        btn_copy = QPushButton("📋 复制结果")
        btn_copy.clicked.connect(lambda: self._copy_text(self.output_text.toPlainText()))
        layout_output.addWidget(self.output_text)
        layout_output.addWidget(btn_copy)
        
        main_splitter.addWidget(group_output)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 2)
        
        layout.addWidget(main_splitter)

    def _perform_split(self):
        text = self.input_text.toPlainText()
        if not text.strip():
            self.status.setText("⚠️ 请输入数据")
            return
            
        chunk_size = self.spin_chunk_size.value()
        
        # 清洗数据（去除空行）
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        
        if not lines:
            self.status.setText("⚠️ 没有有效数据")
            return
            
        chunks = []
        for i in range(0, len(lines), chunk_size):
            chunk = lines[i:i + chunk_size]
            chunks.append("\n".join(chunk))
            
        result = "\n\n".join(chunks)
        self.output_text.setPlainText(result)
        
        self.status.setText(f"✅ 切分完成！共 {len(lines)} 行，切分为 {len(chunks)} 组，每组最多 {chunk_size} 行")

    def _copy_text(self, text):
        if text:
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "复制成功", "内容已复制到剪贴板！")

# ================================================================
# Tab 14：批量读取子表
# ================================================================

class _BatchSheetReaderWorker(QThread):
    """后台线程：逐个读取多个 Spreadsheet 的 Sheet 列表"""
    progress = Signal(int, int, str)  # 当前序号, 总数, 消息
    row_ready = Signal(str, str, str, str)  # 原始链接, spreadsheet_id, 表格标题, sheet名
    finished = Signal(int, int)  # 成功数, 失败数
    error_occurred = Signal(str, str)  # 链接, 错误信息

    def __init__(self, links_and_ids):
        """
        Args:
            links_and_ids: [(原始输入行, spreadsheet_id), ...]
        """
        super().__init__()
        self.links_and_ids = links_and_ids
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        from services.sheet_service import SheetService
        total = len(self.links_and_ids)
        success_count = 0
        fail_count = 0

        for idx, (raw_link, sid) in enumerate(self.links_and_ids):
            if self._abort:
                break
            self.progress.emit(idx, total, f"({idx + 1}/{total}) 正在读取: {sid[:20]}...")
            try:
                service = SheetService(sid)
                # 获取表格标题
                title = service.get_spreadsheet_title()
                # 获取所有 Sheet 名称
                sheets = service.list_sheets()
                for sheet_name in sheets:
                    self.row_ready.emit(raw_link, sid, title, sheet_name)
                success_count += 1
            except Exception as e:
                self.error_occurred.emit(raw_link, str(e))
                fail_count += 1

        self.progress.emit(total, total, "读取完成")
        self.finished.emit(success_count, fail_count)


class BatchSheetReaderPanel(QWidget):
    """
    批量读取子表面板：
    输入多个 Google Sheets 链接，自动读取每个表格的所有 Sheet（子表），
    以表格方式展示，支持过滤（名称正则/模糊、链接）、批量复制、导出CSV、右键复制。
    """

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._worker = None
        # 全量数据：[(原始链接, spreadsheet_id, 表格标题, sheet名), ...]
        self._all_rows = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # ---- 输入区 ----
        input_group = QGroupBox("📝 输入表格链接（每行一个链接或 ID）")
        input_layout = QVBoxLayout(input_group)
        input_layout.setSpacing(4)

        self.links_input = ClearableTextEdit()
        self.links_input.setPlaceholderText(
            "粘贴 Google Sheets 链接或 ID，每行一个。例如：\n"
            "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit\n"
            "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit\n"
            "或直接输入 ID"
        )
        self.links_input.setMaximumHeight(120)
        input_layout.addWidget(self.links_input)

        # 按钮行
        btn_row = QHBoxLayout()

        self.btn_start = QPushButton("🚀 开始读取")
        self.btn_start.setObjectName("primary_btn")
        self.btn_start.clicked.connect(self._start_read)
        btn_row.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹ 停止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_read)
        btn_row.addWidget(self.btn_stop)

        self.btn_clear = QPushButton("🗑 清空")
        self.btn_clear.setObjectName("danger_btn")
        self.btn_clear.setMaximumWidth(80)
        self.btn_clear.clicked.connect(self._clear_all)
        btn_row.addWidget(self.btn_clear)

        btn_row.addStretch()
        input_layout.addLayout(btn_row)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        input_layout.addWidget(self.progress_bar)

        layout.addWidget(input_group)

        # ---- 过滤区 ----
        filter_group = QGroupBox("🔍 过滤")
        filter_layout = QHBoxLayout(filter_group)
        filter_layout.setSpacing(6)

        filter_layout.addWidget(QLabel("Sheet名称:"))
        self.filter_name = QLineEdit()
        self.filter_name.setPlaceholderText("模糊搜索或正则表达式...")
        self.filter_name.textChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.filter_name, 2)

        filter_layout.addWidget(QLabel("链接/ID:"))
        self.filter_link = QLineEdit()
        self.filter_link.setPlaceholderText("按链接或ID过滤...")
        self.filter_link.textChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.filter_link, 2)

        self.chk_regex = QCheckBox("正则")
        self.chk_regex.setToolTip("勾选后名称过滤使用正则表达式模式")
        self.chk_regex.stateChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.chk_regex)

        self.btn_clear_filter = QPushButton("✖ 清除过滤")
        self.btn_clear_filter.setMaximumWidth(100)
        self.btn_clear_filter.clicked.connect(self._clear_filter)
        filter_layout.addWidget(self.btn_clear_filter)

        layout.addWidget(filter_group)

        # ---- 操作按钮区 ----
        action_row = QHBoxLayout()

        self.btn_copy_all = QPushButton("📋 批量复制全部")
        self.btn_copy_all.setToolTip("复制当前过滤后显示的全部数据到剪贴板")
        self.btn_copy_all.clicked.connect(self._copy_all)
        action_row.addWidget(self.btn_copy_all)

        self.btn_copy_selected = QPushButton("📋 复制选中行")
        self.btn_copy_selected.setToolTip("复制选中的行到剪贴板")
        self.btn_copy_selected.clicked.connect(self._copy_selected)
        action_row.addWidget(self.btn_copy_selected)

        self.btn_copy_sheet_names = QPushButton("📋 仅复制Sheet名")
        self.btn_copy_sheet_names.setToolTip("仅复制当前过滤后所有 Sheet 名称（每行一个）")
        self.btn_copy_sheet_names.clicked.connect(self._copy_sheet_names_only)
        action_row.addWidget(self.btn_copy_sheet_names)

        self.btn_export = QPushButton("📤 导出 CSV")
        self.btn_export.setToolTip("将当前过滤后的数据导出为 CSV 文件")
        self.btn_export.clicked.connect(self._export_csv)
        action_row.addWidget(self.btn_export)

        action_row.addStretch()

        self.lbl_stats = QLabel("")
        self.lbl_stats.setStyleSheet("color: #666; font-size: 11px;")
        action_row.addWidget(self.lbl_stats)

        layout.addLayout(action_row)

        # ---- 结果表格 ----
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(4)
        self.result_table.setHorizontalHeaderLabels([
            "表格链接", "Spreadsheet ID", "表格标题", "Sheet 名称"
        ])
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.result_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.result_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.result_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self.result_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self.result_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch
        )
        self.result_table.verticalHeader().setDefaultSectionSize(26)
        self.result_table.setSortingEnabled(True)
        # 右键菜单
        self.result_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.result_table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.result_table, 1)

        # ---- 状态栏 ----
        self.status_label = QLabel("就绪。粘贴表格链接后点击「开始读取」。")
        self.status_label.setStyleSheet("color: #888;")
        layout.addWidget(self.status_label)

    # ------ 核心操作 ------

    def _start_read(self):
        """解析输入链接并启动后台线程读取 Sheet 列表"""
        from ui.batch_backup_widget import extract_spreadsheet_id

        text = self.links_input.toPlainText().strip()
        if not text:
            self.status_label.setText("⚠️ 请输入至少一个表格链接或 ID")
            return

        lines = [l.strip() for l in text.split('\n') if l.strip()]
        links_and_ids = []
        invalid = []
        for line in lines:
            sid = extract_spreadsheet_id(line)
            if sid:
                links_and_ids.append((line, sid))
            else:
                invalid.append(line)

        if not links_and_ids:
            self.status_label.setText("⚠️ 未找到有效的表格链接或 ID")
            return

        if invalid:
            self._log(f"⚠️ 跳过 {len(invalid)} 个无效输入: {', '.join(invalid[:3])}...")

        # 清空旧数据
        self._all_rows.clear()
        self.result_table.setRowCount(0)
        self.result_table.setSortingEnabled(False)  # 加载过程中禁用排序防止闪烁

        # 更新 UI 状态
        self.btn_start.setEnabled(False)
        self.btn_start.setText("⏳ 读取中...")
        self.btn_stop.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(links_and_ids))
        self.progress_bar.setValue(0)

        self.status_label.setText(f"正在读取 {len(links_and_ids)} 个表格的子表信息...")
        self._log(f"📖 开始批量读取 {len(links_and_ids)} 个表格的子表")

        # 启动后台线程
        self._worker = _BatchSheetReaderWorker(links_and_ids)
        self._worker.progress.connect(self._on_progress)
        self._worker.row_ready.connect(self._on_row_ready)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _stop_read(self):
        """中止正在进行的读取操作"""
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self.status_label.setText("⏹ 正在停止...")

    def _on_progress(self, current, total, message):
        """进度更新回调"""
        self.progress_bar.setValue(current)
        self.status_label.setText(message)

    def _on_row_ready(self, raw_link, sid, title, sheet_name):
        """收到一行数据（一个 sheet 名称），追加到表格"""
        self._all_rows.append((raw_link, sid, title, sheet_name))
        # 检查是否满足当前过滤条件，满足则添加到表格
        if self._matches_filter(raw_link, sid, title, sheet_name):
            self._append_table_row(raw_link, sid, title, sheet_name)
        self._update_stats()

    def _on_error(self, raw_link, error_msg):
        """某个表格读取失败的回调"""
        self._log(f"❌ 读取失败: {raw_link[:50]}... — {error_msg}")

    def _on_finished(self, success_count, fail_count):
        """全部读取完成的回调"""
        self.btn_start.setEnabled(True)
        self.btn_start.setText("🚀 开始读取")
        self.btn_stop.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.result_table.setSortingEnabled(True)
        self._worker = None

        total_sheets = len(self._all_rows)
        msg = f"✅ 读取完成！成功 {success_count} 个表格，共 {total_sheets} 个子表"
        if fail_count > 0:
            msg += f"，失败 {fail_count} 个"
        self.status_label.setText(msg)
        self._log(msg)
        self._update_stats()

    # ------ 表格操作 ------

    def _append_table_row(self, raw_link, sid, title, sheet_name):
        """向结果表格追加一行"""
        row = self.result_table.rowCount()
        self.result_table.insertRow(row)

        # 表格链接（截断显示，tooltip显示完整）
        link_item = QTableWidgetItem(raw_link)
        link_item.setToolTip(raw_link)
        self.result_table.setItem(row, 0, link_item)

        # Spreadsheet ID
        sid_item = QTableWidgetItem(sid)
        sid_item.setToolTip(sid)
        self.result_table.setItem(row, 1, sid_item)

        # 表格标题
        title_item = QTableWidgetItem(title)
        title_item.setToolTip(title)
        self.result_table.setItem(row, 2, title_item)

        # Sheet 名称
        sheet_item = QTableWidgetItem(sheet_name)
        sheet_item.setToolTip(sheet_name)
        self.result_table.setItem(row, 3, sheet_item)

    def _update_stats(self):
        """更新统计标签"""
        visible = self.result_table.rowCount()
        total = len(self._all_rows)
        if visible == total:
            self.lbl_stats.setText(f"共 {total} 条")
        else:
            self.lbl_stats.setText(f"显示 {visible}/{total} 条")

    # ------ 过滤 ------

    def _matches_filter(self, raw_link, sid, title, sheet_name):
        """判断一行数据是否满足当前过滤条件"""
        # 名称过滤
        name_filter = self.filter_name.text().strip()
        if name_filter:
            if self.chk_regex.isChecked():
                try:
                    if not re.search(name_filter, sheet_name, re.IGNORECASE):
                        return False
                except re.error:
                    # 正则无效时退化为模糊匹配
                    if name_filter.lower() not in sheet_name.lower():
                        return False
            else:
                if name_filter.lower() not in sheet_name.lower():
                    return False

        # 链接/ID 过滤
        link_filter = self.filter_link.text().strip()
        if link_filter:
            combined = f"{raw_link} {sid} {title}".lower()
            if link_filter.lower() not in combined:
                return False

        return True

    def _apply_filter(self):
        """重新应用过滤条件，刷新表格显示"""
        self.result_table.setSortingEnabled(False)
        self.result_table.setRowCount(0)
        for raw_link, sid, title, sheet_name in self._all_rows:
            if self._matches_filter(raw_link, sid, title, sheet_name):
                self._append_table_row(raw_link, sid, title, sheet_name)
        self.result_table.setSortingEnabled(True)
        self._update_stats()

    def _clear_filter(self):
        """清除所有过滤条件"""
        self.filter_name.clear()
        self.filter_link.clear()
        self.chk_regex.setChecked(False)

    # ------ 复制 ------

    def _get_visible_rows(self):
        """获取当前过滤后显示的全部行数据"""
        rows = []
        for i in range(self.result_table.rowCount()):
            row_data = []
            for j in range(self.result_table.columnCount()):
                item = self.result_table.item(i, j)
                row_data.append(item.text() if item else "")
            rows.append(row_data)
        return rows

    def _get_selected_rows(self):
        """获取选中行的数据"""
        selected_indexes = self.result_table.selectionModel().selectedRows()
        if not selected_indexes:
            return []
        rows = []
        for idx in sorted(selected_indexes, key=lambda x: x.row()):
            r = idx.row()
            row_data = []
            for j in range(self.result_table.columnCount()):
                item = self.result_table.item(r, j)
                row_data.append(item.text() if item else "")
            rows.append(row_data)
        return rows

    def _rows_to_tsv(self, rows, include_header=True):
        """将行数据转为 Tab 分隔文本"""
        lines = []
        if include_header:
            headers = []
            for j in range(self.result_table.columnCount()):
                headers.append(self.result_table.horizontalHeaderItem(j).text())
            lines.append("\t".join(headers))
        for row in rows:
            lines.append("\t".join(row))
        return "\n".join(lines)

    def _copy_all(self):
        """复制过滤后的全部数据到剪贴板"""
        rows = self._get_visible_rows()
        if not rows:
            self.status_label.setText("⚠️ 没有数据可复制")
            return
        text = self._rows_to_tsv(rows)
        QApplication.clipboard().setText(text)
        self.status_label.setText(f"✅ 已复制 {len(rows)} 行到剪贴板")

    def _copy_selected(self):
        """复制选中行到剪贴板"""
        rows = self._get_selected_rows()
        if not rows:
            self.status_label.setText("⚠️ 请先选中要复制的行")
            return
        text = self._rows_to_tsv(rows)
        QApplication.clipboard().setText(text)
        self.status_label.setText(f"✅ 已复制选中的 {len(rows)} 行到剪贴板")

    def _copy_sheet_names_only(self):
        """仅复制当前显示的 Sheet 名称（去重，每行一个）"""
        rows = self._get_visible_rows()
        if not rows:
            self.status_label.setText("⚠️ 没有数据可复制")
            return
        # Sheet 名称在第 4 列（索引 3）
        names = []
        seen = set()
        for row in rows:
            name = row[3] if len(row) > 3 else ""
            if name and name not in seen:
                names.append(name)
                seen.add(name)
        text = "\n".join(names)
        QApplication.clipboard().setText(text)
        self.status_label.setText(f"✅ 已复制 {len(names)} 个 Sheet 名称到剪贴板")

    # ------ 导出 ------

    def _export_csv(self):
        """将当前过滤后的数据导出为 CSV 文件"""
        rows = self._get_visible_rows()
        if not rows:
            self.status_label.setText("⚠️ 没有数据可导出")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "导出 CSV", "sheets_list.csv",
            "CSV 文件 (*.csv);;所有文件 (*)"
        )
        if not filepath:
            return

        try:
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                # 写入表头
                headers = []
                for j in range(self.result_table.columnCount()):
                    headers.append(self.result_table.horizontalHeaderItem(j).text())
                writer.writerow(headers)
                # 写入数据
                for row in rows:
                    writer.writerow(row)
            self.status_label.setText(f"✅ 已导出 {len(rows)} 行到 {os.path.basename(filepath)}")
            self._log(f"📤 已导出 CSV: {filepath}")
        except Exception as e:
            self.status_label.setText(f"❌ 导出失败: {e}")

    # ------ 右键菜单 ------

    def _show_context_menu(self, pos):
        """在结果表格上显示右键菜单"""
        menu = QMenu(self)

        # 复制选中行
        act_copy_rows = QAction("📋 复制选中行", self)
        act_copy_rows.triggered.connect(self._copy_selected)
        menu.addAction(act_copy_rows)

        # 复制选中单元格
        act_copy_cell = QAction("📋 复制选中单元格", self)
        act_copy_cell.triggered.connect(self._copy_current_cell)
        menu.addAction(act_copy_cell)

        menu.addSeparator()

        # 复制全部
        act_copy_all = QAction("📋 复制全部数据", self)
        act_copy_all.triggered.connect(self._copy_all)
        menu.addAction(act_copy_all)

        # 仅复制 Sheet 名称
        act_copy_names = QAction("📋 仅复制 Sheet 名称", self)
        act_copy_names.triggered.connect(self._copy_sheet_names_only)
        menu.addAction(act_copy_names)

        menu.addSeparator()

        # 导出
        act_export = QAction("📤 导出为 CSV", self)
        act_export.triggered.connect(self._export_csv)
        menu.addAction(act_export)

        menu.exec(self.result_table.viewport().mapToGlobal(pos))

    def _copy_current_cell(self):
        """复制当前选中的单元格内容"""
        item = self.result_table.currentItem()
        if item:
            QApplication.clipboard().setText(item.text())
            self.status_label.setText(f"✅ 已复制: {item.text()[:50]}")
        else:
            self.status_label.setText("⚠️ 未选中任何单元格")

    # ------ 清空 ------

    def _clear_all(self):
        """清空所有输入和结果"""
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait(2000)
            self._worker = None

        self.links_input.clear()
        self._all_rows.clear()
        self.result_table.setRowCount(0)
        self.filter_name.clear()
        self.filter_link.clear()
        self.chk_regex.setChecked(False)
        self.progress_bar.setVisible(False)
        self.btn_start.setEnabled(True)
        self.btn_start.setText("🚀 开始读取")
        self.btn_stop.setEnabled(False)
        self.lbl_stats.setText("")
        self.status_label.setText("已清空。")

    # ------ 日志辅助 ------

    def _log(self, text):
        """输出日志到主窗口"""
        if self.controller and self.controller.view:
            self.controller.view.log(text)


# ================================================================
# 主组件：表格辅助工具
# ================================================================

class TableUtilsWidget(QWidget):
    """
    表格辅助工具面板，聚合：
    1. 📋 对比差异
    2. 🔤 字符比较
    3. 🔗 字符串拼接
    4. 🔁 文本转换
    5. ✂️ 列拆分/合并
    6. 🧹 数据清洗
    7. 📊 频次统计
    8. 🔄 行列转置
    9. 🕐 时间戳转换
    10. ✂️ 自动切分对比
    11. ⚖️ 双列表对比
    12. 🔢 列号转换
    13. ✂️ 数据切分
    14. 📖 批量读取子表
    """

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 顶部标题栏
        header_layout = QHBoxLayout()
        title = QLabel("🛠 表格辅助工具")
        title.setObjectName("section_title")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self.status_label = QLabel("提示：支持手动输入数据或从已连接表格中读取")
        self.status_label.setStyleSheet("color: #666; font-size: 11px;")
        header_layout.addWidget(self.status_label)
        layout.addLayout(header_layout)

        # 功能选项卡
        self.tabs = QTabWidget()

        self.tabs.addTab(DiffComparePanel(self.controller, self), "📋 对比差异")
        self.tabs.addTab(CharComparePanel(self.controller, self), "🔤 字符比较")
        self.tabs.addTab(StringConcatPanel(self.controller, self), "🔗 字符串拼接")
        self.tabs.addTab(TextTransformPanel(self.controller, self), "🔁 文本转换")
        self.tabs.addTab(ColumnSplitMergePanel(self.controller, self), "✂️ 列拆分/合并")
        self.tabs.addTab(DataCleanPanel(self.controller, self), "🧹 数据清洗")
        self.tabs.addTab(FrequencyPanel(self.controller, self), "📊 频次统计")
        self.tabs.addTab(TransposePanel(self.controller, self), "🔄 行列转置")
        self.tabs.addTab(TimestampPanel(self.controller, self), "🕐 时间戳转换")
        self.tabs.addTab(AutoSplitComparePanel(self.controller, self), "✂️ 自动切分对比")
        self.tabs.addTab(SetComparePanel(self.controller, self), "⚖️ 双列表对比")
        self.tabs.addTab(ColumnConverterPanel(self.controller, self), "🔢 列号转换")
        self.tabs.addTab(DataSplitPanel(self.controller, self), "✂️ 数据切分")
        self.tabs.addTab(BatchSheetReaderPanel(self.controller, self), "📖 批量读取子表")

        layout.addWidget(self.tabs)

    def showEvent(self, event):
        super().showEvent(event)
        if self.controller and self.controller.is_connected:
            if hasattr(self.controller, 'current_spreadsheet_id'):
                sid = self.controller.current_spreadsheet_id[:12]
                self.status_label.setText(f"已连接表格：{sid}...")
            else:
                self.status_label.setText("已连接表格，可使用「从表格读取」功能")

