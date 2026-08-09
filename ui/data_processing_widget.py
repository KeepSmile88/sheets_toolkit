# 数据处理功能 — 聚合高级查找、动态筛选、统计分析、批量匹配等强大功能
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QLineEdit,
    QComboBox, QCheckBox, QHeaderView, QMessageBox, QMenu, QSplitter,
    QGridLayout
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction

logger = logging.getLogger("sheets_toolkit.ui.data_processing")


class DataProcessingWidget(QWidget):
    """
    数据处理高级工具面板，聚合：
    1. 🔍 批量查找
    2. 📌 高级筛选
    3. 🧮 统计分析
    4. 🔄 批量匹配 (Multi-XLOOKUP)
    5. 🖼️ 链接转图片
    6. 🎨 快捷格式化
    """

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 顶部标题栏
        header_layout = QHBoxLayout()
        title = QLabel("📊 数据处理")
        title.setObjectName("section_title")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self.status_label = QLabel("提示：连接表格后即可使用高级数据处理功能")
        self.status_label.setStyleSheet("color: #666; font-size: 11px;")
        header_layout.addWidget(self.status_label)
        layout.addLayout(header_layout)

        # 功能选项卡
        self.tabs = QTabWidget()
        
        # 1. 批量查找模块
        self.search_tab = SearchPanel(self.controller, self)
        self.tabs.addTab(self.search_tab, "🔍 批量查找")

        # 2. 高级筛选模块
        self.filter_tab = FilterPanel(self.controller, self)
        self.tabs.addTab(self.filter_tab, "📌 高级筛选")

        # 3. 统计分析模块
        self.stats_tab = StatsPanel(self.controller, self)
        self.tabs.addTab(self.stats_tab, "🧮 统计分析")

        # 4. 批量匹配 (VLOOKUP) 模块
        self.match_tab = MatchPanel(self.controller, self)
        self.tabs.addTab(self.match_tab, "🔄 批量匹配")
        
        # 5. 原位链接转图片工具
        self.url_image_tab = UrlToImagePanel(self.controller, self)
        self.tabs.addTab(self.url_image_tab, "🖼️ 链接转图片")

        # 6. 快捷区域格式化小面板
        self.quick_format_tab = QuickFormatPanel(self.controller, self)
        self.tabs.addTab(self.quick_format_tab, "🎨 快捷格式化")
        
        # 7. 批量查重与高亮
        self.duplicate_finder_tab = DuplicateFinderPanel(self.controller, self)
        self.tabs.addTab(self.duplicate_finder_tab, "👯 查重定位")
        
        # 8. 批量翻译面板
        self.translate_tab = TranslatePanel(self.controller, self)
        self.tabs.addTab(self.translate_tab, "🌐 批量翻译")

        # 9. 多表合并与去重
        self.merge_unique_tab = MergeUniquePanel(self.controller, self)
        self.tabs.addTab(self.merge_unique_tab, "🧲 合并去重")

        layout.addWidget(self.tabs)

    def showEvent(self, event):
        super().showEvent(event)
        if self.controller.is_connected:
            self.status_label.setText(f"已连接表格：{self.controller.current_spreadsheet_id[:12]}...")


class SearchWorker(QThread):
    """后台批量查找线程"""
    progress = Signal(str)
    result_found = Signal(str, int, int, str)  # sheet_name, row, col, content
    finished = Signal(int) # total_found
    error = Signal(str)

    def __init__(self, service, keyword, match_case, exact_match, search_all, target_col_idx=-1):
        super().__init__()
        self.service = service
        self.keyword = keyword
        self.match_case = match_case
        self.exact_match = exact_match
        self.search_all = search_all
        self.target_col_idx = target_col_idx

    def run(self):
        try:
            total_found = 0
            sheets_to_search = []
            
            if self.search_all:
                sheets_to_search = self.service.list_sheets()
            else:
                view = self.service.controller.view  # type: ignore
                current_sheet = view.sheet_list.currentText()
                if not current_sheet:
                    self.error.emit("请先在左侧选择一个当前工作表")
                    return
                sheets_to_search = [current_sheet]

            self.progress.emit(f"准备检索 {len(sheets_to_search)} 个工作表...")

            search_kw = self.keyword if self.match_case else self.keyword.lower()

            for sheet_name in sheets_to_search:
                self.progress.emit(f"正在读取: {sheet_name} ...")
                # 读取该工作表所有使用中的数据
                data = self.service.read_data(sheet_name)
                
                for r, row in enumerate(data):
                    for c, cell_val in enumerate(row):
                        if self.target_col_idx >= 0 and c != self.target_col_idx:
                            continue
                        
                        val_str = str(cell_val)
                        cmp_str = val_str if self.match_case else val_str.lower()
                        
                        match = False
                        if self.exact_match:
                            if cmp_str == search_kw:
                                match = True
                        else:
                            if search_kw in cmp_str:
                                match = True
                                
                        if match:
                            total_found += 1
                            self.result_found.emit(sheet_name, r, c, val_str)
                            
            self.finished.emit(total_found)
            
        except Exception as e:
            self.error.emit(str(e))
            logger.error(f"批量查找失败: {e}", exc_info=True)


class SearchPanel(QWidget):
    """批量查找功能面板"""
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.worker = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # 搜索输入控制区
        ctrl_layout = QHBoxLayout()
        self.kw_input = QLineEdit()
        self.kw_input.setPlaceholderText("在此输入你想在表格中批量寻找的关键词...")
        self.kw_input.returnPressed.connect(self.perform_search)
        
        self.btn_search = QPushButton("🔍 立即检索")
        self.btn_search.setObjectName("secondary_btn")
        self.btn_search.clicked.connect(self.perform_search)

        ctrl_layout.addWidget(QLabel("关键词:"))
        ctrl_layout.addWidget(self.kw_input)
        ctrl_layout.addWidget(self.btn_search)
        layout.addLayout(ctrl_layout)

        # 搜索选项
        opt_layout = QHBoxLayout()
        self.chk_case = QCheckBox("区分大小写")
        self.chk_exact = QCheckBox("全字匹配")
        self.chk_all_sheets = QCheckBox("检索所有工作表 (默认仅当前表)")
        
        opt_layout.addWidget(self.chk_case)
        opt_layout.addWidget(self.chk_exact)
        opt_layout.addWidget(self.chk_all_sheets)
        opt_layout.addStretch()

        # 新增目标列选择
        col_layout = QHBoxLayout()
        self.btn_load_cols = QPushButton("🔄 加载当前表列头")
        self.btn_load_cols.clicked.connect(self.load_columns)
        self.col_combo = QComboBox()
        self.col_combo.addItem("★ 搜索全部列", -1)
        self.col_combo.setMinimumWidth(150)
        
        col_layout.addWidget(self.btn_load_cols)
        col_layout.addWidget(QLabel("限定目标列:"))
        col_layout.addWidget(self.col_combo)
        col_layout.addStretch()
        
        opt_layout_container = QVBoxLayout()
        opt_layout_container.addLayout(col_layout)
        opt_layout_container.addLayout(opt_layout)
        layout.addLayout(opt_layout_container)

        # 结果表格
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["工作表", "位置", "列(字母)", "单元格内容"])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        
        # 结果表增加右键菜单用于复制
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        layout.addWidget(self.table)

        # 底部状态
        self.status = QLabel("就绪。请输入关键词开始检索。")
        layout.addWidget(self.status)

    def load_columns(self):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 请先在左侧连接 Google Sheet")
            return

        try:
            view = self.controller.view
            current_sheet = view.sheet_list.currentText()
            if not current_sheet:
                self.status.setText("⚠️ 未选择任何工作表")
                return

            self.status.setText("⏳ 正在拉取表头...")
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()

            data = self.controller.service.read_data(f"{current_sheet}!1:1")
            
            self.col_combo.clear()
            self.col_combo.addItem("★ 搜索全部列", -1)
            if data and data[0]:
                for i, name in enumerate(data[0]):
                    letter = self._col_num_to_letter(i)
                    self.col_combo.addItem(f"{letter} - {name}", i)
                self.status.setText(f"✅ 成功加载 {len(data[0])} 个列头")
            else:
                self.status.setText("⚠️ 当前工作表第一行为空")
                
        except Exception as e:
            self.status.setText(f"❌ 加载列表头失败: {str(e)}")

    def perform_search(self):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 请先在左侧连接 Google Sheet")
            return

        kw = self.kw_input.text().strip()
        if not kw:
            self.status.setText("⚠️ 请输入关键词")
            return

        if self.worker and self.worker.isRunning():
            self.status.setText("⏳ 正在检索中，请稍后再试...")
            return

        self.table.setRowCount(0)
        self.status.setText("⏳ 正在启动检索线程...")
        self.btn_search.setEnabled(False)

        # 伪装控制器的 view 以传递 current sheet (简化设计，依赖 main_window)
        self.controller.service.controller = self.controller

        target_col_idx = self.col_combo.currentData()
        if target_col_idx is None:
            target_col_idx = -1

        self.worker = SearchWorker(
            self.controller.service,
            kw,
            self.chk_case.isChecked(),
            self.chk_exact.isChecked(),
            self.chk_all_sheets.isChecked(),
            target_col_idx
        )
        self.worker.progress.connect(lambda msg: self.status.setText(f"⏳ {msg}"))
        self.worker.result_found.connect(self.add_result_row)
        self.worker.finished.connect(self.on_search_finished)
        self.worker.error.connect(self.on_search_error)
        self.worker.start()

    def add_result_row(self, sheet_name, r, c, content):
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)
        
        # 转换列数字为字母，例如 0->A, 1->B
        col_letter = self._col_num_to_letter(c)
        pos_str = f"R{r+1}C{c+1}"
        
        self.table.setItem(row_idx, 0, QTableWidgetItem(sheet_name))
        self.table.setItem(row_idx, 1, QTableWidgetItem(pos_str))
        self.table.setItem(row_idx, 2, QTableWidgetItem(f"{col_letter}{r+1}"))
        self.table.setItem(row_idx, 3, QTableWidgetItem(content))
        
        # 滚动到底部
        self.table.scrollToBottom()

    def on_search_finished(self, total):
        self.btn_search.setEnabled(True)
        self.status.setText(f"✅ 检索完成！共找到 {total} 条结果。")
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def on_search_error(self, err_msg):
        self.btn_search.setEnabled(True)
        self.status.setText(f"❌ 检索失败: {err_msg}")
        QMessageBox.critical(self, "检索错误", str(err_msg))

    def _col_num_to_letter(self, n):
        string = ""
        n += 1
        while n > 0:
            n, remainder = divmod(n - 1, 26)
            string = chr(65 + remainder) + string
        return string

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)
        
        copy_cell_act = QAction("📋 复制本单元格内容", self)
        copy_cell_act.triggered.connect(lambda: self._copy_text(item.text()))
        menu.addAction(copy_cell_act)

        menu.addSeparator()
        
        row_idx = item.row()
        copy_row_act = QAction("📋 复制整行结果", self)
        copy_row_act.triggered.connect(lambda: self._copy_row(row_idx))
        menu.addAction(copy_row_act)

        menu.exec_(self.table.mapToGlobal(pos))

    def _copy_text(self, text):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        self.status.setText("✅ 已复制到剪贴板")

    def _copy_row(self, r):
        cols = []
        for c in range(self.table.columnCount()):
            it = self.table.item(r, c)
            cols.append(it.text() if it else "")
        self._copy_text("\t".join(cols))


class FilterWorker(QThread):
    """后台筛选线程"""
    finished = Signal(list, list)  # header, matched_rows
    error = Signal(str)

    def __init__(self, service, col_idx, op, target_val, match_case):
        super().__init__()
        self.service = service
        self.col_idx = col_idx
        self.op = op
        self.target_val = target_val
        self.match_case = match_case

    def run(self):
        try:
            view = self.service.controller.view  # type: ignore
            current_sheet = view.sheet_list.currentText()
            if not current_sheet:
                self.error.emit("无可用的工作表")
                return

            data = self.service.read_data(current_sheet)
            if not data:
                self.error.emit("工作表内无数据")
                return

            header = data[0]
            if len(data) == 1:
                self.finished.emit(header, [])
                return

            target = str(self.target_val)
            if not self.match_case:
                target = target.lower()

            results = []
            for row in data[1:]:
                # 防止由于每行长度不等导致的索引越界，补齐空值
                val = str(row[self.col_idx]) if self.col_idx < len(row) else ""
                cmp_val = val if self.match_case else val.lower()

                match = False
                if self.op == "包含":
                    match = target in cmp_val
                elif self.op == "等于":
                    match = cmp_val == target
                elif self.op == "不等于":
                    match = cmp_val != target
                elif self.op == "大于" or self.op == "小于":
                    try:
                        v1 = float(cmp_val.replace(',', ''))
                        v2 = float(target.replace(',', ''))
                        match = (v1 > v2) if self.op == "大于" else (v1 < v2)
                    except ValueError:
                        pass # 如果无法转为数字则匹配失败

                if match:
                    results.append(row)

            self.finished.emit(header, results)

        except Exception as e:
            self.error.emit(str(e))
            logger.error(f"筛选失败: {e}", exc_info=True)


class FilterPanel(QWidget):
    """高级筛选功能面板"""
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.worker = None
        self._current_header = []
        self._filtered_data = [] # 缓存结果数据，用于导出
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # 控制区
        ctrl_layout = QHBoxLayout()
        
        self.btn_load_cols = QPushButton("🔄 加载当前表列头")
        self.btn_load_cols.clicked.connect(self.load_columns)
        
        self.col_combo = QComboBox()
        self.col_combo.setMinimumWidth(120)
        
        self.op_combo = QComboBox()
        self.op_combo.addItems(["包含", "等于", "不等于", "大于", "小于"])
        
        self.val_input = QLineEdit()
        self.val_input.setPlaceholderText("比较值")
        self.val_input.returnPressed.connect(self.perform_filter)

        self.btn_filter = QPushButton("📌 立即筛选")
        self.btn_filter.setObjectName("secondary_btn")
        self.btn_filter.clicked.connect(self.perform_filter)

        ctrl_layout.addWidget(self.btn_load_cols)
        ctrl_layout.addWidget(QLabel("选择列:"))
        ctrl_layout.addWidget(self.col_combo)
        ctrl_layout.addWidget(self.op_combo)
        ctrl_layout.addWidget(self.val_input)
        ctrl_layout.addWidget(self.btn_filter)
        layout.addLayout(ctrl_layout)

        # 选项区
        opt_layout = QHBoxLayout()
        self.chk_case = QCheckBox("区分大小写")
        opt_layout.addWidget(self.chk_case)
        opt_layout.addStretch()

        self.btn_export = QPushButton("📤 导出结果为CSV")
        self.btn_export.clicked.connect(self.export_csv)
        self.btn_export.setEnabled(False)
        opt_layout.addWidget(self.btn_export)

        layout.addLayout(opt_layout)

        # 结果表格
        self.table = QTableWidget(0, 0)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        
        # 底部状态
        self.status = QLabel("请先连接表格并“加载列头”。")
        layout.addWidget(self.status)

    def load_columns(self):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 请先在左侧连接 Google Sheet")
            return

        try:
            view = self.controller.view
            current_sheet = view.sheet_list.currentText()
            if not current_sheet:
                self.status.setText("⚠️ 未选择任何工作表")
                return

            self.status.setText("⏳ 正在拉取表头...")
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()

            data = self.controller.service.read_data(f"{current_sheet}!1:1")
            
            self.col_combo.clear()
            self._current_header = []
            if data and data[0]:
                self._current_header = data[0]
                items = [f"{self._col_num_to_letter(i)} - {name}" for i, name in enumerate(data[0])]
                self.col_combo.addItems(items)
                self.status.setText(f"✅ 成功加载 {len(items)} 个列头")
            else:
                self.status.setText("⚠️ 当前工作表第一行为空")
                
        except Exception as e:
            self.status.setText(f"❌ 加载列表头失败: {str(e)}")

    def perform_filter(self):
        if self.col_combo.count() == 0:
            self.status.setText("⚠️ 请先加载列头")
            return

        target_val = self.val_input.text().strip()
        if not target_val and self.op_combo.currentText() not in ["不等于"]:
            self.status.setText("⚠️ 请输入比较值")
            return

        self.btn_filter.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.status.setText("⏳ 正在拉取并筛选数据...")

        col_idx = self.col_combo.currentIndex()
        op = self.op_combo.currentText()
        case_sensitive = self.chk_case.isChecked()

        self.controller.service.controller = self.controller
        self.worker = FilterWorker(self.controller.service, col_idx, op, target_val, case_sensitive)
        self.worker.finished.connect(self.on_filter_finished)
        self.worker.error.connect(self.on_filter_error)
        self.worker.start()

    def on_filter_finished(self, header, matched_rows):
        self.btn_filter.setEnabled(True)
        self._current_header = header
        self._filtered_data = matched_rows
        
        num_cols = len(header)
        self.table.setColumnCount(num_cols)
        self.table.setHorizontalHeaderLabels([str(x) for x in header])
        
        self.table.setRowCount(len(matched_rows))
        
        for r, row_data in enumerate(matched_rows):
            for c in range(num_cols):
                val = str(row_data[c]) if c < len(row_data) else ""
                self.table.setItem(r, c, QTableWidgetItem(val))

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

        if len(matched_rows) > 0:
            self.btn_export.setEnabled(True)
        
        self.status.setText(f"✅ 筛选完毕！找到 {len(matched_rows)} 行匹配数据。")

    def on_filter_error(self, err_msg):
        self.btn_filter.setEnabled(True)
        self.status.setText(f"❌ 筛选失败: {err_msg}")

    def export_csv(self):
        if not self._filtered_data:
            return
            
        import csv
        from PySide6.QtWidgets import QFileDialog
        
        path, _ = QFileDialog.getSaveFileName(
            self, "导出筛选结果", "筛选结果.csv", "CSV 文件 (*.csv)"
        )
        if not path:
            return
            
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                if self._current_header:
                    writer.writerow(self._current_header)
                writer.writerows(self._filtered_data)
            self.status.setText(f"📤 已成功导出至 {path}")
        except Exception as e:
            self.status.setText(f"❌ 导出失败: {e}")

    def _col_num_to_letter(self, n):
        string = ""
        n += 1
        while n > 0:
            n, remainder = divmod(n - 1, 26)
            string = chr(65 + remainder) + string
        return string


class StatsWorker(QThread):
    """后台统计分析线程"""
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, service, col_idx):
        super().__init__()
        self.service = service
        self.col_idx = col_idx

    def run(self):
        try:
            view = self.service.controller.view  # type: ignore
            current_sheet = view.sheet_list.currentText()
            if not current_sheet:
                self.error.emit("无可用的工作表")
                return

            data = self.service.read_data(current_sheet)
            if not data or len(data) <= 1:
                self.error.emit("工作表内无有效数据行")
                return

            nums = []
            empty_count = 0
            invalid_count = 0

            # 从第二行开始统计
            for row in data[1:]:
                val = str(row[self.col_idx]).strip() if self.col_idx < len(row) else ""
                
                if not val:
                    empty_count += 1
                    continue
                    
                # 尝试清洗为数字
                try:
                    v = float(val.replace(',', ''))
                    nums.append(v)
                except ValueError:
                    invalid_count += 1
                    
            if not nums:
                res = {
                    "count": 0, "sum": 0, "avg": 0, "max": 0, "min": 0,
                    "empty": empty_count, "invalid": invalid_count
                }
            else:
                res = {
                    "count": len(nums),
                    "sum": sum(nums),
                    "avg": sum(nums) / len(nums),
                    "max": max(nums),
                    "min": min(nums),
                    "empty": empty_count,
                    "invalid": invalid_count
                }
                
            self.finished.emit(res)

        except Exception as e:
            self.error.emit(str(e))
            logger.error(f"统计失败: {e}", exc_info=True)


class StatsPanel(QWidget):
    """统计分析面板"""
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.worker = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # 控制区
        ctrl_layout = QHBoxLayout()
        self.btn_load_cols = QPushButton("🔄 加载当前表列头")
        self.btn_load_cols.clicked.connect(self.load_columns)
        
        self.col_combo = QComboBox()
        self.col_combo.setMinimumWidth(120)
        
        self.btn_calc = QPushButton("🧮 一键生成统计")
        self.btn_calc.setObjectName("primary_btn")
        self.btn_calc.clicked.connect(self.perform_calc)

        ctrl_layout.addWidget(self.btn_load_cols)
        ctrl_layout.addWidget(QLabel("从工作表选择列:"))
        ctrl_layout.addWidget(self.col_combo)
        ctrl_layout.addWidget(self.btn_calc)
        ctrl_layout.addStretch()
        layout.addLayout(ctrl_layout)

        # 结果显示区 (用大字体标签展示)
        grid_layout = QVBoxLayout()
        grid_layout.setContentsMargins(20, 20, 20, 20)
        grid_layout.setSpacing(15)

        title = QLabel("💡 统计分析报告")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #4CAF50;")
        grid_layout.addWidget(title)

        self.lbl_sum = self._make_stat_lbl("总和 (Sum):", "-")
        self.lbl_avg = self._make_stat_lbl("平均值 (Average):", "-")
        self.lbl_max = self._make_stat_lbl("最大值 (Max):", "-")
        self.lbl_min = self._make_stat_lbl("最小值 (Min):", "-")
        self.lbl_cnt = self._make_stat_lbl("有效数字计数:", "-")
        self.lbl_oth = self._make_stat_lbl("空值 / 非数字:", "-")

        grid_layout.addWidget(self.lbl_sum)
        grid_layout.addWidget(self.lbl_avg)
        grid_layout.addWidget(self.lbl_max)
        grid_layout.addWidget(self.lbl_min)
        grid_layout.addWidget(self.lbl_cnt)
        grid_layout.addWidget(self.lbl_oth)
        grid_layout.addStretch()

        # 添加边框包围结果
        frame = QWidget()
        frame.setLayout(grid_layout)
        frame.setStyleSheet("QWidget { background: #f9f9f9; border-radius: 8px; border: 1px solid #ddd; }")
        
        layout.addWidget(frame)
        
        # 底部状态
        self.status = QLabel("自动过滤文本，仅对数字安全求和。")
        layout.addWidget(self.status)

    def _make_stat_lbl(self, title, val):
        lbl = QLabel(f"<b>{title}</b><br><span style='font-size: 18px; color: #333;'>{val}</span>")
        lbl.setStyleSheet("background: transparent; border: none;")
        return lbl

    def _update_stat_lbl(self, lbl, title, val):
        lbl.setText(f"<b>{title}</b><br><span style='font-size: 18px; color: #1976D2;'>{val}</span>")

    def load_columns(self):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 请先在左侧连接 Google Sheet")
            return

        try:
            view = self.controller.view
            current_sheet = view.sheet_list.currentText()
            if not current_sheet:
                self.status.setText("⚠️ 未选择任何工作表")
                return

            self.status.setText("⏳ 正在拉取表头...")
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()

            data = self.controller.service.read_data(f"{current_sheet}!1:1")
            
            self.col_combo.clear()
            if data and data[0]:
                self._col_num_to_letter = lambda n: chr(65 + (n % 26)) if n < 26 else chr(65 + n // 26 - 1) + chr(65 + n % 26)
                items = [f"{self._col_num_to_letter(i)} - {name}" for i, name in enumerate(data[0])]
                self.col_combo.addItems(items)
                self.status.setText(f"✅ 成功加载 {len(items)} 个列头")
            else:
                self.status.setText("⚠️ 当前工作表第一行为空")
                
        except Exception as e:
            self.status.setText(f"❌ 加载列表头失败: {str(e)}")

    def perform_calc(self):
        if self.col_combo.count() == 0:
            self.status.setText("⚠️ 请先加载列头")
            return

        self.btn_calc.setEnabled(False)
        self.status.setText("⏳ 正在拉取数据与计算...")

        col_idx = self.col_combo.currentIndex()
        self.controller.service.controller = self.controller
        
        self.worker = StatsWorker(self.controller.service, col_idx)
        self.worker.finished.connect(self.on_calc_finished)
        self.worker.error.connect(self.on_calc_error)
        self.worker.start()

    def on_calc_finished(self, res):
        self.btn_calc.setEnabled(True)
        
        # 格式化输出
        fmt = "{:,.2f}"
        self._update_stat_lbl(self.lbl_sum, "总和 (Sum):", fmt.format(res['sum']) if res['count'] > 0 else "0")
        self._update_stat_lbl(self.lbl_avg, "平均值 (Average):", fmt.format(res['avg']) if res['count'] > 0 else "0")
        self._update_stat_lbl(self.lbl_max, "最大值 (Max):", fmt.format(res['max']) if res['count'] > 0 else "0")
        self._update_stat_lbl(self.lbl_min, "最小值 (Min):", fmt.format(res['min']) if res['count'] > 0 else "0")
        self._update_stat_lbl(self.lbl_cnt, "有效数字计数:", f"{res['count']} 行")
        self._update_stat_lbl(self.lbl_oth, "空值 / 非数字:", f"空: {res['empty']} 行 | 非数字文本: {res['invalid']} 行")
        
        self.status.setText(f"✅ 计算完成")

    def on_calc_error(self, err_msg):
        self.btn_calc.setEnabled(True)
        self.status.setText(f"❌ 计算失败: {err_msg}")


class MatchWorker(QThread):
    """后台批量匹配线程 (类似于强化的多列返回 VLOOKUP)"""
    finished = Signal(list, list) # header, results
    progress = Signal(str)
    error = Signal(str)

    def __init__(self, service, keys_text, query_col_idx, result_col_indices, match_case, exact_match):
        super().__init__()
        self.service = service
        self.keys = [k.strip() for k in keys_text.split('\n') if k.strip()]
        self.query_col_idx = query_col_idx
        self.result_col_indices = result_col_indices  # id 列表[]
        self.match_case = match_case
        self.exact_match = exact_match

    def run(self):
        try:
            if not self.keys:
                self.error.emit("关键词列表为空")
                return

            view = self.service.controller.view  # type: ignore
            current_sheet = view.sheet_list.currentText()
            if not current_sheet:
                self.error.emit("无可用的工作表")
                return

            self.progress.emit(f"正在拉取工作表 '{current_sheet}' 的全量数据...")
            data = self.service.read_data(current_sheet)
            
            if not data or len(data) <= 1:
                self.error.emit("工作表内无有效数据行")
                return
                
            original_headers = data[0]
            
            # 生成结果的 Header：[关键字表头] + [匹配工作表/行] + [结果列1, 2...]
            out_header = ["搜索关键字", "匹配位置"]
            for c_idx in self.result_col_indices:
                col_name = original_headers[c_idx] if c_idx < len(original_headers) else f"列{c_idx+1}"
                out_header.append(col_name)

            out_results = []
            
            # 预处理搜索关键词（如果不区分大小写，可全转小写提升速度）
            search_keys = self.keys if self.match_case else [k.lower() for k in self.keys]

            total_rows = len(data) - 1
            for i, kw in enumerate(search_keys):
                if i % 50 == 0:
                    self.progress.emit(f"正在匹配进度: {i}/{len(search_keys)} ...")
                    
                original_kw = self.keys[i]
                found_match_for_kw = False

                for r_idx, row in enumerate(data[1:]):
                    val = str(row[self.query_col_idx]) if self.query_col_idx < len(row) else ""
                    cmp_val = val if self.match_case else val.lower()

                    match = False
                    if self.exact_match:
                        match = (cmp_val == kw)
                    else:
                        match = (kw in cmp_val)

                    if match:
                        found_match_for_kw = True
                        # 组装这行请求的字段
                        res_row = [original_kw, f"{current_sheet}!行{r_idx + 2}"]
                        for c_idx in self.result_col_indices:
                            c_val = str(row[c_idx]) if c_idx < len(row) else ""
                            res_row.append(c_val)
                        
                        out_results.append(res_row)
                
                # 如果这个关键词一次也没匹配到，加入一条空记录以提示用户
                if not found_match_for_kw:
                    empty_row = [original_kw, "未找到匹配项"] + [""] * len(self.result_col_indices)
                    out_results.append(empty_row)

            self.finished.emit(out_header, out_results)

        except Exception as e:
            self.error.emit(str(e))
            logger.error(f"批量匹配失败: {e}", exc_info=True)


class MatchPanel(QWidget):
    """批量匹配特性面板"""
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.worker = None
        self._current_header = []
        self._match_results = []
        self._col_mapping = [] # 保存加载下拉列表框的数据 mapping: (idx, name)
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)

        # 顶部操作栏
        top_layout = QHBoxLayout()
        self.btn_load_cols = QPushButton("🔄 加载当前表列头")
        self.btn_load_cols.clicked.connect(self.load_columns)
        top_layout.addWidget(self.btn_load_cols)
        
        top_layout.addWidget(QLabel("① 选定查询列(源):"))
        self.query_col_combo = QComboBox()
        self.query_col_combo.setMinimumWidth(100)
        top_layout.addWidget(self.query_col_combo)
        
        top_layout.addStretch()
        main_layout.addLayout(top_layout)

        # 主分屏区：左侧配置 和 右侧结果
        splitter = QSplitter(Qt.Horizontal)
        
        # --- 左侧：配置区 ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 10, 0)
        
        left_layout.addWidget(QLabel("② 输入批量查询关键词 (每行一个):"))
        self.kw_text = ClearableTextEdit()
        self.kw_text.setPlaceholderText("例如批量粘贴 100 个订单号或用户名\nuser01\nuser02...")
        left_layout.addWidget(self.kw_text)

        left_layout.addWidget(QLabel("③ 选择要返回的结果列 (多选):"))
        self.result_cols_list = QTableWidget(0, 1)
        self.result_cols_list.horizontalHeader().setVisible(False)
        self.result_cols_list.horizontalHeader().setStretchLastSection(True)
        self.result_cols_list.setSelectionMode(QTableWidget.NoSelection)
        self.result_cols_list.setAlternatingRowColors(True)
        left_layout.addWidget(self.result_cols_list, stretch=1)

        # 选项
        opt_layout = QHBoxLayout()
        self.chk_case = QCheckBox("区分大小写")
        self.chk_exact = QCheckBox("全字匹配(推荐)")
        self.chk_exact.setChecked(True)
        opt_layout.addWidget(self.chk_case)
        opt_layout.addWidget(self.chk_exact)
        left_layout.addLayout(opt_layout)

        self.btn_match = QPushButton("🔄 开始批量智能匹配")
        self.btn_match.setObjectName("primary_btn")
        self.btn_match.clicked.connect(self.perform_match)
        left_layout.addWidget(self.btn_match)
        
        # --- 右侧：结果区 ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 0, 0)
        
        res_header_layout = QHBoxLayout()
        res_header_layout.addWidget(QLabel("匹配结果:"))
        res_header_layout.addStretch()
        self.btn_export = QPushButton("📤 导出全部结果")
        self.btn_export.clicked.connect(self.export_csv)
        self.btn_export.setEnabled(False)
        res_header_layout.addWidget(self.btn_export)
        right_layout.addLayout(res_header_layout)

        self.table = QTableWidget(0, 0)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        
        # 右键辅助菜单
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        right_layout.addWidget(self.table)
        
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([350, 650])
        main_layout.addWidget(splitter)
        
        # 底部状态
        self.status = QLabel("请先连接表格并加载列头。")
        main_layout.addWidget(self.status)

    def load_columns(self):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 请先在左侧连接 Google Sheet")
            return

        try:
            view = self.controller.view
            current_sheet = view.sheet_list.currentText()
            if not current_sheet:
                self.status.setText("⚠️ 未选择任何工作表")
                return

            self.status.setText("⏳ 正在拉取表头...")
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()

            data = self.controller.service.read_data(f"{current_sheet}!1:1")
            
            self.query_col_combo.clear()
            self.result_cols_list.setRowCount(0)
            self._col_mapping = []
            
            if data and data[0]:
                self._current_header = data[0]
                
                for i, name in enumerate(data[0]):
                    letter = self._col_num_to_letter(i)
                    display_name = f"{letter} - {name}"
                    
                    self.query_col_combo.addItem(display_name, i) # userData = idx
                    
                    # 添进多选列表
                    row_idx = self.result_cols_list.rowCount()
                    self.result_cols_list.insertRow(row_idx)
                    item = QTableWidgetItem(display_name)
                    item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                    item.setCheckState(Qt.Unchecked)
                    item.setData(Qt.UserRole, i)
                    self.result_cols_list.setItem(row_idx, 0, item)
                    
                self.status.setText(f"✅ 成功加载 {len(data[0])} 个列头")
            else:
                self.status.setText("⚠️ 当前工作表第一行为空")
                
        except Exception as e:
            self.status.setText(f"❌ 加载列表头失败: {str(e)}")

    def perform_match(self):
        kw_text = self.kw_text.toPlainText().strip()
        if not kw_text:
            self.status.setText("⚠️ 请输入至少一个查询关键词")
            return
            
        if self.query_col_combo.count() == 0:
            self.status.setText("⚠️ 请先加载列头")
            return

        query_col_idx = self.query_col_combo.currentData()
        
        # 收集选中的目标列
        result_cols = []
        for i in range(self.result_cols_list.rowCount()):
            item = self.result_cols_list.item(i, 0)
            if item.checkState() == Qt.Checked:
                result_cols.append(item.data(Qt.UserRole))
                
        if not result_cols:
            self.status.setText("⚠️ 请在左侧列表中至少勾选一个【结果列】")
            return

        self.btn_match.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.status.setText("⏳ 正在启动智能多列匹配...")

        self.controller.service.controller = self.controller
        self.worker = MatchWorker(
            self.controller.service, 
            kw_text, 
            query_col_idx, 
            result_cols, 
            self.chk_case.isChecked(),
            self.chk_exact.isChecked()
        )
        self.worker.progress.connect(lambda msg: self.status.setText(f"⏳ {msg}"))
        self.worker.finished.connect(self.on_match_finished)
        self.worker.error.connect(self.on_match_error)
        self.worker.start()

    def on_match_finished(self, out_header, results):
        self.btn_match.setEnabled(True)
        self._match_results = results
        self._current_header = out_header
        
        num_cols = len(out_header)
        self.table.setColumnCount(num_cols)
        self.table.setHorizontalHeaderLabels(out_header)
        
        self.table.setRowCount(len(results))
        for r, row_data in enumerate(results):
            for c in range(num_cols):
                val = str(row_data[c]) if c < len(row_data) else ""
                
                item = QTableWidgetItem(val)
                # 为未找到的项将背景设为淡红色警示
                if c == 1 and val == "未找到匹配项":
                    item.setForeground(Qt.red)
                    
                self.table.setItem(r, c, item)

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

        if len(results) > 0:
            self.btn_export.setEnabled(True)
        
        self.status.setText(f"✅ 批量匹配完毕！共生成 {len(results)} 行结果（包括多重匹配项）。")

    def on_match_error(self, err_msg):
        self.btn_match.setEnabled(True)
        self.status.setText(f"❌ 批量匹配失败: {err_msg}")

    def export_csv(self):
        if not self._match_results:
            return
            
        import csv
        from PySide6.QtWidgets import QFileDialog
        
        path, _ = QFileDialog.getSaveFileName(
            self, "导出查询结果", "匹配查询结果.csv", "CSV 文件 (*.csv)"
        )
        if not path:
            return
            
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                if self._current_header:
                    writer.writerow(self._current_header)
                writer.writerows(self._match_results)
            self.status.setText(f"📤 已成功导出至 {path}")
        except Exception as e:
            self.status.setText(f"❌ 导出失败: {e}")

    def _col_num_to_letter(self, n):
        string = ""
        n += 1
        while n > 0:
            n, remainder = divmod(n - 1, 26)
            string = chr(65 + remainder) + string
        return string

    # --- 右键菜单与复制功能 ---
    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)
        copy_cell_act = QAction("📋 复制本单元格内容", self)
        copy_cell_act.triggered.connect(lambda: self._copy_text(item.text()))
        menu.addAction(copy_cell_act)

        menu.addSeparator()
        row_idx = item.row()
        copy_row_act = QAction("📋 复制整行结果", self)
        copy_row_act.triggered.connect(lambda: self._copy_row(row_idx))
        menu.addAction(copy_row_act)
        menu.exec_(self.table.mapToGlobal(pos))

    def _copy_text(self, text):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        self.status.setText("✅ 已复制到剪贴板")

    def _copy_row(self, r):
        cols = []
        for c in range(self.table.columnCount()):
            it = self.table.item(r, c)
            cols.append(it.text() if it else "")
        self._copy_text("\t".join(cols))


class UrlToImageWorker(QThread):
    """提取图片链接并转换为=IMAGE()公式的后台线程"""
    finished = Signal(int, int) # count_total, count_converted
    progress = Signal(str)
    error = Signal(str)

    def __init__(self, service, sheet_name, range_a1, controller):
        super().__init__()
        self.service = service
        self.sheet_name = sheet_name
        self.range_a1 = range_a1
        self.controller = controller

    def run(self):
        try:
            full_range = f"{self.sheet_name}!{self.range_a1}" if "!" not in self.range_a1 else self.range_a1
            self.progress.emit(f"正在读取区域: {full_range}")
            
            data = self.service.read_data(full_range)
            if not data:
                self.error.emit("目标区域无数据")
                return

            import re
            img_ext_pattern = re.compile(r'\.(png|jpg|jpeg|gif|webp)(\?.*)?$', re.IGNORECASE)
            
            updates = []
            count_total = 0
            count_converted = 0

            # data 是二维数组
            for r_idx, row in enumerate(data):
                for c_idx, val in enumerate(row):
                    val_str = str(val).strip()
                    if not val_str:
                        continue
                    
                    count_total += 1
                    
                    # 简单判断是否是 http 开头并且似乎像是个图片链接
                    if val_str.startswith('http') and img_ext_pattern.search(val_str):
                        # 如果它目前还不是公式，我们才转换它
                        if not val_str.startswith('='):
                            formula = f'=IMAGE("{val_str}")'
                            
                            updates.append({
                                'row': r_idx,
                                'col': c_idx,
                                'formula': formula
                            })
                            count_converted += 1

            if count_converted == 0:
                self.finished.emit(count_total, 0)
                return

            self.progress.emit(f"发现 {count_converted} 个图片链接，正在提交公式转换...")
            
            # 使用 Controller 的 Command 进行封装，支持撤销
            from services.command.batch_update_command import BatchUpdateCommand
            update_data_list = []
            
            for u in updates:
                cell_a1 = self._get_absolute_cell_range(self.range_a1, u['row'], u['col'])
                update_data_list.append({
                    "range": f"{self.sheet_name}!{cell_a1}",
                    "values": [[u['formula']]]
                })
                
            cmd = BatchUpdateCommand(self.service, update_data_list)
            self.controller.run_command(cmd)

            self.finished.emit(count_total, count_converted)

        except Exception as e:
            self.error.emit(str(e))
            logger.error(f"链接转图片失败: {e}", exc_info=True)

    def _get_absolute_cell_range(self, a1_notation, r_offset, c_offset):
        import re
        # 解析如 C2 或 C:C（取第一部分的字母，如果有数字则作为起始行，否则默认为1）
        range_parts = a1_notation.split(':')
        start_part = range_parts[0]
        match = re.search(r'([a-zA-Z]+)(\d*)', start_part)
        
        if match:
            start_col_str = match.group(1).upper()
            start_row = int(match.group(2)) if match.group(2) else 1
            
            start_col_num = 0
            for char in start_col_str:
                start_col_num = start_col_num * 26 + (ord(char) - ord('A') + 1)
                
            target_col_num = start_col_num + c_offset
            target_row = start_row + r_offset
            
            def n2a(n):
                string = ""
                while n > 0:
                    n, remainder = divmod(n - 1, 26)
                    string = chr(65 + remainder) + string
                return string
                
            return f"{n2a(target_col_num)}{target_row}"
        else:
            return f"{chr(65+c_offset)}{r_offset+1}"


class UrlToImagePanel(QWidget):
    """链接转图片小工具面板"""
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.worker = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        desc = QLabel("💡 <b>用法：</b>在连接有效表格后，框选下方的目标范围（如 <code>C2:C100</code>）。<br>该功能会自动把该范围内所有形似图片的 <code>http...png</code> 链接文本替换为可以直接显示图片的 <code>=IMAGE(...)</code> 公式。")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #444; margin-bottom: 10px;")
        layout.addWidget(desc)

        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel("选择工作表:"))
        self.sheet_combo = QComboBox()
        self.sheet_combo.setMinimumWidth(150)
        ctrl_layout.addWidget(self.sheet_combo)
        
        self.btn_refresh_sheets = QPushButton("🔄 刷新表单")
        self.btn_refresh_sheets.clicked.connect(self.load_sheets)
        ctrl_layout.addWidget(self.btn_refresh_sheets)

        ctrl_layout.addWidget(QLabel("处理区域:"))
        self.range_input = QLineEdit()
        self.range_input.setPlaceholderText("例如: B2:B100 或 C:C")
        self.range_input.setText("A1:Z100")
        ctrl_layout.addWidget(self.range_input)

        self.btn_convert = QPushButton("🪄 一键原位转换为图片")
        self.btn_convert.setObjectName("primary_btn")
        self.btn_convert.clicked.connect(self.perform_conversion)
        ctrl_layout.addWidget(self.btn_convert)
        ctrl_layout.addStretch()

        layout.addLayout(ctrl_layout)
        
        self.status = QLabel("待机中。")
        self.status.setStyleSheet("font-size: 14px; margin-top: 20px; color: #1976D2;")
        layout.addWidget(self.status)
        layout.addStretch()

    def load_sheets(self):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 请先在左侧连接 Google Sheet")
            return
        try:
            sheets = self.controller.service.list_sheets()
            self.sheet_combo.clear()
            self.sheet_combo.addItems(sheets)
            self.status.setText("✅ 工作表列表已更新")
        except Exception as e:
            self.status.setText(f"❌ 获取工作表失败: {e}")

    def perform_conversion(self):
        sheet_name = self.sheet_combo.currentText()
        if not sheet_name:
            self.status.setText("⚠️ 请先加载并选择工作表")
            return
            
        range_a1 = self.range_input.text().strip()
        if not range_a1:
            self.status.setText("⚠️ 请输入要处理的区域，如 B2:B100")
            return

        self.btn_convert.setEnabled(False)
        self.status.setText("⏳ 提取链接并转换中...")

        self.controller.service.controller = self.controller
        self.worker = UrlToImageWorker(self.controller.service, sheet_name, range_a1, self.controller)
        self.worker.progress.connect(lambda msg: self.status.setText(f"⏳ {msg}"))
        self.worker.finished.connect(self.on_conversion_finished)
        self.worker.error.connect(self.on_conversion_error)
        self.worker.start()

    def on_conversion_finished(self, total, converted):
        self.btn_convert.setEnabled(True)
        if converted > 0:
            self.status.setText(f"🎉 转换成功！<br><br>共检查了 {total} 个单元格。<br>发现了 <b>{converted}</b> 个图片链接，已全部原地转换为 =IMAGE() 图片。<br>如果不满意，可点击主界面的撤销按钮。")
        else:
            self.status.setText(f"ℹ️ 扫描完成。<br><br>共检查了 {total} 个单元格。<br>未发现任何纯图片链接文本（需为 http 开头且具有 jpg/png 等后缀）。")

    def on_conversion_error(self, err_msg):
        self.btn_convert.setEnabled(True)
        self.status.setText(f"❌ 转换错误: {err_msg}")


class QuickFormatPanel(QWidget):
    """快捷区域格式化面板"""
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        desc = QLabel("💡 <b>用法：</b>在下方输入目前想快速调整的 <code>选定区域</code>，然后点击相应按钮。所有操作均支持点击主界面的撤销按钮还原。")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #444; margin-bottom: 20px;")
        layout.addWidget(desc)

        # 区域选择
        r_layout = QHBoxLayout()
        r_layout.addWidget(QLabel("要格式化的区域范围:"))
        self.range_input = QLineEdit()
        self.range_input.setPlaceholderText("例如 Sheet1!A1:D5 或 A1:F1")
        r_layout.addWidget(self.range_input)
        
        self.btn_get_current = QPushButton("📍 填入当前选中表与区域")
        self.btn_get_current.clicked.connect(self.fill_current_range)
        r_layout.addWidget(self.btn_get_current)
        r_layout.addStretch()
        layout.addLayout(r_layout)

        # 快捷按钮排版 (网格或流式)
        btn_layout = QHBoxLayout()
        
        # 1. 颜色区
        color_widget = QWidget()
        cl = QVBoxLayout(color_widget)
        cl.addWidget(QLabel("🎨 背景高亮"))
        self.btn_color_yellow = QPushButton("🟡 黄色高亮")
        self.btn_color_red = QPushButton("🔴 红色高亮")
        self.btn_color_green = QPushButton("🟢 绿色高亮")
        self.btn_color_clear = QPushButton("⚪ 清除背景色")
        
        self.btn_color_yellow.clicked.connect(lambda: self.apply_format({"backgroundColor": {"red": 1.0, "green": 0.9, "blue": 0.6}}))
        self.btn_color_red.clicked.connect(lambda: self.apply_format({"backgroundColor": {"red": 1.0, "green": 0.8, "blue": 0.8}}))
        self.btn_color_green.clicked.connect(lambda: self.apply_format({"backgroundColor": {"red": 0.8, "green": 1.0, "blue": 0.8}}))
        self.btn_color_clear.clicked.connect(lambda: self.apply_format({"backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0, "alpha": 0}}))
        
        cl.addWidget(self.btn_color_yellow)
        cl.addWidget(self.btn_color_red)
        cl.addWidget(self.btn_color_green)
        cl.addWidget(self.btn_color_clear)
        cl.addStretch()
        btn_layout.addWidget(color_widget)
        
        # 2. 字体区
        font_widget = QWidget()
        fl = QVBoxLayout(font_widget)
        fl.addWidget(QLabel("A 字体强调"))
        self.btn_bold = QPushButton("𝐁 粗体")
        self.btn_bold_clear = QPushButton("取消粗体")
        
        self.btn_bold.clicked.connect(lambda: self.apply_format({"textFormat": {"bold": True}}))
        self.btn_bold_clear.clicked.connect(lambda: self.apply_format({"textFormat": {"bold": False}}))
        
        fl.addWidget(self.btn_bold)
        fl.addWidget(self.btn_bold_clear)
        fl.addStretch()
        btn_layout.addWidget(font_widget)
        
        # 3. 对齐区
        align_widget = QWidget()
        al = QVBoxLayout(align_widget)
        al.addWidget(QLabel("⇹ 快速对齐"))
        self.btn_align_center = QPushButton("居中对齐 (水平+垂直)")
        self.btn_align_left = QPushButton("靠左对齐")
        
        self.btn_align_center.clicked.connect(lambda: self.apply_format({"horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"}))
        self.btn_align_left.clicked.connect(lambda: self.apply_format({"horizontalAlignment": "LEFT"}))
        
        al.addWidget(self.btn_align_center)
        al.addWidget(self.btn_align_left)
        al.addStretch()
        btn_layout.addWidget(align_widget)
        
        layout.addLayout(btn_layout)
        
        self.status = QLabel("就绪。请设定范围并点击对应格式按钮。")
        self.status.setStyleSheet("color: #666; margin-top: 15px;")
        layout.addWidget(self.status)
        layout.addStretch()

    def fill_current_range(self):
        if not self.controller.is_connected:
            return
        curr_range = self.controller.get_current_range()
        self.range_input.setText(curr_range)
        self.status.setText("✅ 已同步主窗口当前选中的区域。")

    def apply_format(self, format_dict):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 请先连接 Google Sheet")
            return
            
        range_str = self.range_input.text().strip()
        if not range_str:
            self.status.setText("⚠️ 请求执行操作前请输入格式化区域")
            return
            
        try:
            from services.command.batch_update_command import BatchUpdateFormatCommand
            cmd = BatchUpdateFormatCommand(self.controller.service, range_str, format_dict)
            self.controller.run_command(cmd)
            self.status.setText(f"✅ 格式已应用至 {range_str}！可点击撤销还原。")
        except Exception as e:
            self.status.setText(f"❌ 应用格式出错: {e}")
            logger.error(f"快捷格式化失败: {e}", exc_info=True)


class DuplicateFinderWorker(QThread):
    """跨表批量查重工作线程"""
    finished = Signal(list, list)  # results, highlight_count
    progress = Signal(str)
    error = Signal(str)
    
    def __init__(self, service, keys_text, query_col_idx, match_case, exact_match, search_all):
        super().__init__()
        self.service = service
        self.keys = set([k.strip() for k in keys_text.split('\n') if k.strip()])
        self.query_col_idx = query_col_idx
        self.match_case = match_case
        self.exact_match = exact_match
        self.search_all = search_all
        
    def run(self):
        try:
            if not self.keys:
                self.error.emit("关键词列表为空")
                return

            view = self.service.controller.view
            current_sheet = view.sheet_list.currentText()
            
            self.progress.emit("正在拉取工作表基础属性...")
            # 获取所有工作表的 meta（包含 sheetId），用于后续的发包高亮
            spreadsheet_meta = self.service.service.spreadsheets().get(
                spreadsheetId=self.service.spreadsheet_id
            ).execute()
            
            sheets_data = spreadsheet_meta.get("sheets", [])
            sheet_map = {} # sheet_name -> sheet_id
            for s in sheets_data:
                props = s.get("properties", {})
                sheet_map[props.get("title", "")] = props.get("sheetId")
            
            sheets_to_search = []
            if self.search_all:
                sheets_to_search = list(sheet_map.keys())
            else:
                if not current_sheet:
                    self.error.emit("无可用的当前工作表进行查询")
                    return
                sheets_to_search = [current_sheet]

            self.progress.emit(f"准备在 {len(sheets_to_search)} 个工作表中查找对应数据。")
            
            out_results = []
            highlight_requests = []
            
            search_keys = self.keys if self.match_case else set(k.lower() for k in self.keys)
            
            # 使用略带显眼的红色系高亮查重结果：淡红色 (Red: 1.0, Green: 0.85, Blue: 0.85)
            highlight_color = {"red": 1.0, "green": 0.85, "blue": 0.85}

            for s_name in sheets_to_search:
                self.progress.emit(f"正在读取并比对: {s_name} ...")
                data = self.service.read_data(s_name)
                
                sid = sheet_map.get(s_name)
                if sid is None or not data:
                    continue

                for r_idx, row in enumerate(data):
                    # 如果未指定列 (query_col_idx == -1)，检查所有单元格；否则查对应列
                    found_in_row = False
                    col_index_found = -1
                    content_found = ""
                    matched_key = ""
                    
                    if self.query_col_idx >= 0:
                        val = str(row[self.query_col_idx]) if self.query_col_idx < len(row) else ""
                        cmp_val = val if self.match_case else val.lower()
                        for kw in search_keys:
                            if self.exact_match and cmp_val == kw:
                                found_in_row = True; matched_key = kw; break
                            elif not self.exact_match and kw in cmp_val:
                                found_in_row = True; matched_key = kw; break
                        
                        if found_in_row:
                            content_found = val
                            col_index_found = self.query_col_idx
                    else:
                        for c_idx, cell_val in enumerate(row):
                            val_str = str(cell_val)
                            cmp_str = val_str if self.match_case else val_str.lower()
                            for kw in search_keys:
                                if self.exact_match and cmp_str == kw:
                                    found_in_row = True; matched_key = kw; col_index_found = c_idx; break
                                elif not self.exact_match and kw in cmp_str:
                                    found_in_row = True; matched_key = kw; col_index_found = c_idx; break
                            if found_in_row:
                                content_found = val_str
                                break
                    
                    if found_in_row:
                        # 组装结果: [关键词，工作表，行号(直观)，单元格位置，内容]
                        col_letter = self._col_num_to_letter(col_index_found) if col_index_found >= 0 else "?"
                        pos_str = f"{col_letter}{r_idx + 1}"
                        # 注意这里恢复原始大小写的 key（可选），不过简单处理就用匹配到的 kw
                        out_results.append([
                            matched_key,
                            s_name,
                            str(r_idx + 1),
                            pos_str,
                            content_found
                        ])
                        
                        # 把整行都加入高亮队列
                        highlight_requests.append({
                            "repeatCell": {
                                "range": {
                                    "sheetId": sid,
                                    "startRowIndex": r_idx,
                                    "endRowIndex": r_idx + 1
                                    # 未限制列即为整行高亮
                                },
                                "cell": {
                                    "userEnteredFormat": {
                                        "backgroundColor": highlight_color
                                    }
                                },
                                "fields": "userEnteredFormat.backgroundColor"
                            }
                        })
            
            highlight_count = len(highlight_requests)
            
            if highlight_count > 0:
                self.progress.emit(f"比对完成，发现 {highlight_count} 条重复数据！正在将表格底色标红高亮...")
                self.service.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.service.spreadsheet_id,
                    body={"requests": highlight_requests}
                ).execute()
            
            out_header = ["触发关键词", "工作表名称", "行号", "单元格位置", "原始数据内容"]
            self.finished.emit([out_header] + out_results if out_results else [], highlight_count)

        except Exception as e:
            self.error.emit(str(e))
            logger.error(f"批量查重失败: {e}", exc_info=True)

    def _col_num_to_letter(self, n):
        string = ""
        n += 1
        while n > 0:
            n, remainder = divmod(n - 1, 26)
            string = chr(65 + remainder) + string
        return string


class DuplicateFinderPanel(QWidget):
    """跨表数据去重与高亮查询面板"""
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.worker = None
        self._match_results = []
        self._current_header = []
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)

        desc = QLabel("💡 <b>功能：</b>输入一批已知数据（比如刚从别处复制来的 ID名单），自动探查并找出表格内是否已有这些数据及其重复散落的位置。<br>查重引擎将自动把<b>存在重复源数据的关联整行</b>全部标为显眼的浅红色，并在下方反馈明细报表（高亮暂不支持撤销保护）。")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #444; margin-bottom: 5px;")
        main_layout.addWidget(desc)

        # 顶部操作栏
        top_layout = QHBoxLayout()
        self.btn_load_cols = QPushButton("🔄 加载当前表列头")
        self.btn_load_cols.clicked.connect(self.load_columns)
        top_layout.addWidget(self.btn_load_cols)
        
        top_layout.addWidget(QLabel("限定查重检索列:"))
        self.query_col_combo = QComboBox()
        self.query_col_combo.setMinimumWidth(150)
        self.query_col_combo.addItem("★ 检索全表各列", -1)
        top_layout.addWidget(self.query_col_combo)
        top_layout.addStretch()
        main_layout.addLayout(top_layout)

        # 布局
        splitter = QSplitter(Qt.Horizontal)
        
        # --- 左侧：待查数据录入 ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 10, 0)
        
        left_layout.addWidget(QLabel("输入待审查的一批核心数据 (每行一个):"))
        self.kw_text = ClearableTextEdit()
        self.kw_text.setPlaceholderText("粘贴例如 001、002、Tom、Jerry 这样的去重探针数据，每行一个...")
        left_layout.addWidget(self.kw_text, stretch=1)

        # 选项
        opt_layout = QVBoxLayout()
        self.chk_case = QCheckBox("区分大小写")
        self.chk_exact = QCheckBox("🎯 全字匹配严格查重 (推荐)")
        self.chk_exact.setChecked(True)
        self.chk_all_sheets = QCheckBox("🌐 跨全部工作表查重 (默认仅当前)")
        opt_layout.addWidget(self.chk_case)
        opt_layout.addWidget(self.chk_exact)
        opt_layout.addWidget(self.chk_all_sheets)
        left_layout.addLayout(opt_layout)

        self.btn_execute = QPushButton("🚨 执行去审查重并全行高亮标红")
        self.btn_execute.setObjectName("danger_btn")
        self.btn_execute.clicked.connect(self.perform_check)
        self.btn_execute.setToolTip("警告：对查重找到的所有表格对应行进行原地背景色覆盖不可撤销，请谨慎！")
        left_layout.addWidget(self.btn_execute)
        
        # --- 右侧：高亮详情结果区 ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 0, 0)
        
        res_header_layout = QHBoxLayout()
        res_header_layout.addWidget(QLabel("重复项暴露详情:"))
        res_header_layout.addStretch()
        self.btn_export = QPushButton("📤 导出异常表")
        self.btn_export.clicked.connect(self.export_csv)
        self.btn_export.setEnabled(False)
        res_header_layout.addWidget(self.btn_export)
        right_layout.addLayout(res_header_layout)

        self.table = QTableWidget(0, 0)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        right_layout.addWidget(self.table)
        
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([260, 540])
        main_layout.addWidget(splitter)
        
        self.status = QLabel("就绪。输入数据后点击查重引擎。")
        main_layout.addWidget(self.status)

    def load_columns(self):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 请先在主界面左侧连接 Google Sheet")
            return

        try:
            view = self.controller.view
            current_sheet = view.sheet_list.currentText()
            if not current_sheet:
                self.status.setText("⚠️ 未选择任何工作表")
                return

            self.status.setText("⏳ 正在拉取表头...")
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()

            data = self.controller.service.read_data(f"{current_sheet}!1:1")
            
            self.query_col_combo.clear()
            self.query_col_combo.addItem("★ 检索全表各列", -1)
            if data and data[0]:
                for i, name in enumerate(data[0]):
                    letter = self._col_num_to_letter(i)
                    self.query_col_combo.addItem(f"{letter} - {name}", i)
                self.status.setText(f"✅ 成功加载 {len(data[0])} 个列头")
            else:
                self.status.setText("⚠️ 当前工作表第一行为空")
                
        except Exception as e:
            self.status.setText(f"❌ 加载列表头失败: {str(e)}")

    def perform_check(self):
        kw_text = self.kw_text.toPlainText().strip()
        if not kw_text:
            self.status.setText("⚠️ 未填入任何用于查重比对的数据")
            return

        query_col_idx = self.query_col_combo.currentData()
        if query_col_idx is None:
            query_col_idx = -1

        reply = QMessageBox.warning(
            self, "高亮警告", 
            "本查重引擎为了强化您的视觉效果，将直接向云端发起行背景色红光高亮接口（该直接格式化不受底层库单一事务撤销保护）。\n\n您是否确认已做好备份或其他准备，继续执行数据去重标红任务？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_execute.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.status.setText("⏳ 查重矩阵发动中，高速匹配与云端着色进行中...")

        self.controller.service.controller = self.controller
        self.worker = DuplicateFinderWorker(
            self.controller.service, 
            kw_text, 
            query_col_idx, 
            self.chk_case.isChecked(),
            self.chk_exact.isChecked(),
            self.chk_all_sheets.isChecked()
        )
        self.worker.progress.connect(lambda msg: self.status.setText(f"⏳ {msg}"))
        self.worker.finished.connect(self.on_check_finished)
        self.worker.error.connect(self.on_check_error)
        self.worker.start()

    def on_check_finished(self, results_with_header, highlight_count):
        self.btn_execute.setEnabled(True)
        if not results_with_header or len(results_with_header) <= 1:
            # 意味着就算有header也没数据，或者连header都没有直接空数组
            self.status.setText("🛡️ 太棒了！在您指定的范畴内完全没有发生任何数据重复。")
            return

        out_header = results_with_header[0]
        results = results_with_header[1:]
        
        self._current_header = out_header
        self._match_results = results
        
        num_cols = len(out_header)
        self.table.setColumnCount(num_cols)
        self.table.setHorizontalHeaderLabels(out_header)
        
        self.table.setRowCount(len(results))
        for r, row_data in enumerate(results):
            for c in range(num_cols):
                val = str(row_data[c]) if c < len(row_data) else ""
                item = QTableWidgetItem(val)
                # 为行号或者重复项添加醒目标注
                item.setForeground(Qt.black)
                self.table.setItem(r, c, item)

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

        self.btn_export.setEnabled(True)
        self.status.setText(f"🚨 查重警报！共发现散布在 {highlight_count} 处的重复行记录。云端着色已生效。请观察表格与上方明细面板。")

    def on_check_error(self, err_msg):
        self.btn_execute.setEnabled(True)
        self.status.setText(f"❌ 查重引擎崩溃或中断: {err_msg}")

    def export_csv(self):
        if not self._match_results:
            return
        import csv
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "导出重复明细", "高危查重记录.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                if self._current_header:
                    writer.writerow(self._current_header)
                writer.writerows(self._match_results)
            self.status.setText(f"📤 异常数据详情已归档至 {path}")
        except Exception as e:
            self.status.setText(f"❌ 导出写盘失败: {e}")

    def _col_num_to_letter(self, n):
        string = ""
        n += 1
        while n > 0:
            n, remainder = divmod(n - 1, 26)
            string = chr(65 + remainder) + string
        return string

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item: return
        menu = QMenu(self)
        
        copy_cell_act = QAction("📋 复制本单元格内容", self)
        copy_cell_act.triggered.connect(lambda: self._copy_text(item.text()))
        menu.addAction(copy_cell_act)

        menu.addSeparator()
        row_idx = item.row()
        copy_row_act = QAction("📋 带走这条明细 (复制整行)", self)
        copy_row_act.triggered.connect(lambda: self._copy_row(row_idx))
        menu.addAction(copy_row_act)
        menu.exec_(self.table.mapToGlobal(pos))

    def _copy_text(self, text):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        self.status.setText("✅ 分析信息已提取进剪贴板")

    def _copy_row(self, r):
        cols = []
        for c in range(self.table.columnCount()):
            it = self.table.item(r, c)
            cols.append(it.text() if it else "")
        self._copy_text("\t".join(cols))


class TranslateWorker(QThread):
    """异步批量翻译与固化工作线程"""
    progress = Signal(str)
    finished = Signal(str)
    error = Signal(str)
    
    def __init__(self, service, sheet_name, src_col_letter, tar_col_letter, start_row, end_row, src_lang, tar_lang):
        super().__init__()
        self.service = service
        self.sheet_name = sheet_name
        self.src_col_letter = src_col_letter
        self.tar_col_letter = tar_col_letter
        self.start_row = start_row
        self.end_row = end_row
        self.src_lang = src_lang
        self.tar_lang = tar_lang
        
    def run(self):
        try:
            num_rows = self.end_row - self.start_row + 1
            if num_rows <= 0:
                self.error.emit("行数范围无效")
                return

            self.progress.emit("🚀 阶段一：正在生成翻译公式矩阵...")
            
            # 准备写入目标列的 formulas
            # 格式：=GOOGLETRANSLATE(C5, "en", "zh-cn")
            values = []
            for r in range(self.start_row, self.end_row + 1):
                src_cell = f"{self.src_col_letter}{r}"
                formula = f'=IF(ISBLANK({src_cell}), "", GOOGLETRANSLATE({src_cell}, "{self.src_lang}", "{self.tar_lang}"))'
                values.append([formula])
                
            tar_range = f"{self.sheet_name}!{self.tar_col_letter}{self.start_row}:{self.tar_col_letter}{self.end_row}"
            
            # 使用 USER_ENTERED 写入公式
            self.progress.emit("🔌 阶段一：正在将云端公式推入 Google Sheets...")
            self.service.service.spreadsheets().values().update(
                spreadsheetId=self.service.spreadsheet_id,
                range=tar_range,
                valueInputOption="USER_ENTERED",
                body={"values": values}
            ).execute()
            
            # 阶段二：轮询等待计算完毕
            import time
            max_retries = 20
            poll_interval = 2
            
            self.progress.emit("⏳ 阶段二：等待 Google 云端集群进行语言转换计算...")
            
            final_values = []
            success = False
            for attempt in range(max_retries):
                time.sleep(poll_interval)
                self.progress.emit(f"🔄 阶段二：正在获取计算结果 (第 {attempt + 1}/{max_retries} 次尝试)...")
                
                # 获取格式化的结果，如果不含 Loading 等状态且正常则认为完毕
                result = self.service.service.spreadsheets().values().get(
                    spreadsheetId=self.service.spreadsheet_id,
                    range=tar_range,
                    valueRenderOption="FORMATTED_VALUE"
                ).execute()
                
                rows = result.get("values", [])
                
                # 检查是否还有正在计算的（如 "#N/A", "Loading..."等常见未决标记）
                pending = False
                for row in rows:
                    val = str(row[0]).strip() if row else ""
                    # 公式未计算完会返回空、Error 或 Loading
                    if val in ("Loading...", "加载中..."):
                        pending = True
                        break
                        
                if not pending:
                    # 即使返回了 #VALUE! 等也是计算完了，退出轮询
                    final_values = rows
                    success = True
                    break
                    
            if not success:
                self.error.emit("⚠️ 警告：等待翻译结果超时，云端可能拥塞。公式已保留在表格中，您可以稍后在表格内直接查看。")
                return
                
            # 阶段三：固化为实文本
            self.progress.emit("🔨 阶段三：获取成功，正在剥离公式，粉碎为纯静态实数据并覆盖写回...")
            
            # 补齐长度避免因为空单元格导致写入错位
            write_back_values = []
            for r in range(num_rows):
                if r < len(final_values) and final_values[r]:
                    val = final_values[r][0]
                    # 处理可能留下的错误占位文本
                    if str(val).startswith("#"):
                        val = "" # 发生错误时写空
                    write_back_values.append([val])
                else:
                    write_back_values.append([""])
                    
            self.service.service.spreadsheets().values().update(
                spreadsheetId=self.service.spreadsheet_id,
                range=tar_range,
                valueInputOption="RAW",  # 关键：RAW 模式不会被解析为公式，直接写入字符串内容
                body={"values": write_back_values}
            ).execute()

            self.finished.emit(f"🎉 翻译并固化完成！共处理了 {num_rows} 单元格数据。")

        except Exception as e:
            self.error.emit(str(e))
            logger.error(f"批量翻译失败: {e}", exc_info=True)


class TranslatePanel(QWidget):
    """批量翻译面板 UI"""
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.worker = None
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)

        desc = QLabel("💡 <b>功能：</b>基于 <code>GOOGLETRANSLATE</code> 原生公式的超强驱动力！将指定列的内容极速批量翻译，并<b>自动在后台提取翻译成果</b>，帮您把那些耗性能的公式粉碎，原位留下的全是<b>纯净清爽的纯文本数据</b>！")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #444; margin-bottom: 5px;")
        main_layout.addWidget(desc)

        # 顶部操作栏
        top_layout = QHBoxLayout()
        self.btn_load_cols = QPushButton("🔄 载入当前表列头以供拾取")
        self.btn_load_cols.clicked.connect(self.load_columns)
        top_layout.addWidget(self.btn_load_cols)
        top_layout.addStretch()
        main_layout.addLayout(top_layout)

        form_layout = QGridLayout()
        
        # 行1：列选取
        form_layout.addWidget(QLabel("① 原始语言文本所在列:"), 0, 0)
        self.src_col_combo = QComboBox()
        self.src_col_combo.setMinimumWidth(120)
        form_layout.addWidget(self.src_col_combo, 0, 1)

        form_layout.addWidget(QLabel("② 翻译结果输出的目标列:"), 0, 2)
        self.tar_col_combo = QComboBox()
        self.tar_col_combo.setMinimumWidth(120)
        form_layout.addWidget(self.tar_col_combo, 0, 3)

        # 行2：行围
        form_layout.addWidget(QLabel("起始行号 (含):"), 1, 0)
        self.in_start_row = QLineEdit()
        self.in_start_row.setPlaceholderText("2")
        self.in_start_row.setText("2")
        form_layout.addWidget(self.in_start_row, 1, 1)

        form_layout.addWidget(QLabel("结束行号 (含):"), 1, 2)
        self.in_end_row = QLineEdit()
        self.in_end_row.setPlaceholderText("100")
        self.in_end_row.setText("100")
        form_layout.addWidget(self.in_end_row, 1, 3)
        
        # 行3：语言代码
        form_layout.addWidget(QLabel("源语言代码 (如 auto, en, zh-cn):"), 2, 0)
        self.in_src_lang = QLineEdit()
        self.in_src_lang.setText("auto")
        form_layout.addWidget(self.in_src_lang, 2, 1)

        form_layout.addWidget(QLabel("目标语言代码 (如 zh-cn, en, fr):"), 2, 2)
        self.in_tar_lang = QLineEdit()
        self.in_tar_lang.setText("zh-cn")
        form_layout.addWidget(self.in_tar_lang, 2, 3)

        main_layout.addLayout(form_layout)

        self.btn_execute = QPushButton("⚡ 一键发车：批量极速翻译与固化引擎")
        self.btn_execute.setObjectName("primary_btn")
        self.btn_execute.clicked.connect(self.perform_translation)
        
        act_layout = QHBoxLayout()
        act_layout.addWidget(self.btn_execute)
        act_layout.addStretch()
        main_layout.addLayout(act_layout)

        main_layout.addStretch()

        self.status = QLabel("待机中。使用前请先『🔄载入列头』。")
        self.status.setWordWrap(True)
        main_layout.addWidget(self.status)

    def load_columns(self):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 请先在主界面左侧连接 Google Sheet")
            return

        try:
            view = self.controller.view
            current_sheet = view.sheet_list.currentText()
            if not current_sheet:
                self.status.setText("⚠️ 未选择任何工作表")
                return

            self.status.setText("⏳ 正在拉取表头...")
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()

            data = self.controller.service.read_data(f"{current_sheet}!1:1")
            
            self.src_col_combo.clear()
            self.tar_col_combo.clear()
            
            # 手工补充一些长列 A-Z
            for i in range(26):
                letter = chr(65 + i)
                name = f"未命名列 ({letter})"
                if data and data[0] and i < len(data[0]):
                    name = str(data[0][i])
                
                # Combo 存 (展示名, 列字母)
                display_text = f"{letter} - {name}"
                self.src_col_combo.addItem(display_text, letter)
                self.tar_col_combo.addItem(display_text, letter)
                
            self.status.setText("✅ 列头读取完毕！现在请选择您的流转区域。")
                
        except Exception as e:
            self.status.setText(f"❌ 加载列表头失败: {str(e)}")

    def perform_translation(self):
        view = self.controller.view
        current_sheet = view.sheet_list.currentText()
        if not current_sheet:
            self.status.setText("⚠️ 未选择操作的工作表")
            return
            
        src_col_letter = self.src_col_combo.currentData()
        tar_col_letter = self.tar_col_combo.currentData()
        
        if not src_col_letter or not tar_col_letter:
            self.status.setText("⚠️ 请确保来源列与目标列已被正确选取")
            return
            
        try:
            start_r = int(self.in_start_row.text().strip())
            end_r = int(self.in_end_row.text().strip())
            if start_r < 1 or end_r < start_r:
                raise ValueError
        except ValueError:
            self.status.setText("⚠️ 行号数字非法 (起点必须大于0，终点必须不小于起点)")
            return
            
        src_lang = self.in_src_lang.text().strip()
        tar_lang = self.in_tar_lang.text().strip()
        
        if not src_lang or not tar_lang:
            self.status.setText("⚠️ 语言代码不可为空。若不清楚原语言可填入 auto")
            return

        reply = QMessageBox.warning(
            self, "确认覆盖目标列", 
            f"引爆翻译引擎后，程序将以迅雷之势将 {current_sheet} 表 {tar_col_letter}列 第 {start_r} 至 {end_r} 行的内容**彻底覆写**为翻译结果，原本在目标列该区段的数据将不复存在（防呆提示不支持底层撤销）。\n\n您确定目标列是安全且空的吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_execute.setEnabled(False)
        self.status.setText("⏳ 系统预热完毕。启动翻译引擎。")

        self.worker = TranslateWorker(
            self.controller.service, 
            current_sheet,
            src_col_letter, tar_col_letter, 
            start_r, end_r, 
            src_lang, tar_lang
        )
        self.worker.progress.connect(lambda msg: self.status.setText(msg))
        self.worker.finished.connect(self.on_check_finished)
        self.worker.error.connect(self.on_check_error)
        self.worker.start()

    def on_check_finished(self, msg):
        self.btn_execute.setEnabled(True)
        self.status.setText(msg)

    def on_check_error(self, err_msg):
        self.btn_execute.setEnabled(True)
        self.status.setText(f"❌ 翻译崩溃或中断: {err_msg}")


class MergeUniqueWorker(QThread):
    """异步多表合并去重与固化写入线程"""
    progress = Signal(str)
    finished = Signal(str)
    error = Signal(str)
    
    def __init__(self, service, sources, target_sheet, start_cell, do_unique):
        super().__init__()
        self.service = service
        self.sources = sources      # List of string like "Sheet1!A:D" or "https://...edit, Sheet!A:D"
        self.target_sheet = target_sheet
        self.start_cell = start_cell  # e.g. "A1"
        self.do_unique = do_unique
        
    def run(self):
        import re
        try:
            self.progress.emit(f"🚀 阶段一：准备从 {len(self.sources)} 个数据源拉取数据...")
            
            all_merged_rows = []
            
            for idx, source in enumerate(self.sources):
                self.progress.emit(f"⏳ 正在拉取第 {idx+1}/{len(self.sources)} 个源: {source[:30]}...")
                
                # Parsing logic for sources
                source = source.strip()
                target_spreadsheet_id = self.service.spreadsheet_id
                target_range = source
                
                # Check if it's an external URL
                # format: https://docs.google.com/spreadsheets/d/{ID}/edit, Sheet1!A1:D
                from urllib.parse import urlparse
                parsed_source = urlparse(source if '://' in source else 'http://' + source)
                domain = parsed_source.netloc.lower()
                
                is_google = domain == 'docs.google.com' or domain.endswith('.docs.google.com') or domain == 'google.com' or domain.endswith('.google.com')

                if is_google:
                    parts = source.split(",", 1)
                    if len(parts) != 2:
                        self.error.emit(f"数据源格式错误 (缺少逗号分隔): {source}")
                        return
                    url_part = parts[0].strip()
                    target_range = parts[1].strip()
                    
                    # Extract ID from URL
                    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url_part)
                    if match:
                        target_spreadsheet_id = match.group(1)
                    else:
                        self.error.emit(f"无法从 URL 提取 Spreadsheet ID: {url_part}")
                        return
                
                # Fetch data with FORMULA render option to preserve =IMAGE() etc.
                result = self.service.service.spreadsheets().values().get(
                    spreadsheetId=target_spreadsheet_id,
                    range=target_range,
                    valueRenderOption="FORMULA"
                ).execute()
                
                rows = result.get("values", [])
                
                # Strip entirely empty trailing rows from this chunk if needed (helps clean up A:D selects)
                cleaned_rows = []
                for row in rows:
                    if any(str(cell).strip() for cell in row):
                        cleaned_rows.append(row)
                
                all_merged_rows.extend(cleaned_rows)
            
            self.progress.emit(f"✅ 阶段一完毕：共吸入 {len(all_merged_rows)} 行非空原始数据。")
            
            # Phase 2: Deduplication (UNIQUE)
            final_rows = all_merged_rows
            if self.do_unique:
                self.progress.emit("🔨 阶段二：正在本地执行全量哈希运算与行级去重 (UNIQUE)...")
                seen = set()
                deduped_rows = []
                for row in all_merged_rows:
                    # Convert row array to a stable tuple for hashing
                    # We might have uneven row lengths; pad or just tuple-ize as is
                    tup = tuple(str(x).strip() for x in row)
                    if tup not in seen:
                        seen.add(tup)
                        deduped_rows.append(row)
                final_rows = deduped_rows
                self.progress.emit(f"✨ 阶段二完毕：去重后保留了 {len(final_rows)} 行唯一独立数据。")
            else:
                self.progress.emit("⏭️ 阶段二跳过：用户选择了不进行去重。")
                
            if not final_rows:
                self.finished.emit("⚠️ 所有数据源均为空，合并中止。")
                return
                
            # Normalize array dimensions (make all rows have the same number of cols)
            max_cols = max(len(row) for row in final_rows)
            normalized_rows = []
            for row in final_rows:
                normalized = list(row)
                while len(normalized) < max_cols:
                    normalized.append("")
                normalized_rows.append(normalized)
            
            # Phase 3: Write back
            self.progress.emit("🔌 阶段三：正在将纯实数据(保留原厂公式)全量覆写至目标表...")
            
            # Reconstruct the exact write target A1 notation
            target_write_range = f"{self.target_sheet}!{self.start_cell}"
            
            # Clear old potential data around the starting cell might be needed, 
            # but usually USER_ENTERED updates. If user wants a clean sheet, they should use Structure Clear first.
            
            self.service.service.spreadsheets().values().update(
                spreadsheetId=self.service.spreadsheet_id,
                range=target_write_range,
                valueInputOption="USER_ENTERED", # Evaluates formulas natively 
                body={"values": normalized_rows}
            ).execute()
            
            stat_msg = f"去重合并完成并下发！共向 {self.target_sheet} 写入 {len(normalized_rows)} 行物理实数据。"
            self.finished.emit(f"🎉 {stat_msg}")
            
        except Exception as e:
            self.error.emit(str(e))
            logger.error(f"合并去重失败: {e}", exc_info=True)


class MergeUniquePanel(QWidget):
    """多表合并与去重面板 UI"""
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.worker = None
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)

        desc = QLabel("💡 <b>功能：</b>强大的本机数据总线收集器！将分布在<b>当前大表或跨表格（指定URL）</b>中的多路片段提取回本地沙盒，像 <code>VSTACK</code> 加 <code>UNIQUE</code> 那样清洗去重，最后只把<b>脱水的纯静态实数据和合法函数（如 =IMAGE()）</b>一拳打进目标表汇聚点！")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #444; margin-bottom: 5px;")
        main_layout.addWidget(desc)

        # 1. 数据源区域
        source_label = QLabel("📥 <b>步骤一：请贴入数据源清单（一行一个源）</b>\n - 若为当前表的片段直接写：`Sheet1!A1:D`\n - 若为跨表数据请连同网络链接：`https://.../edit, 源总表!A2:E`")
        source_label.setWordWrap(True)
        main_layout.addWidget(source_label)

        self.in_sources = ClearableTextEdit()
        self.in_sources.setPlaceholderText("例如：\nSheet1!A2:D\nSheet2!A2:D\nhttps://docs.google.com/spreadsheets/d/xxx/edit, 其他表!A2:D")
        self.in_sources.setMinimumHeight(150)
        main_layout.addWidget(self.in_sources)

        # 2. 目标输出区域
        target_layout = QGridLayout()
        target_layout.addWidget(QLabel("📤 <b>步骤二：设定固化倾泻点 (当前连接库)</b>"), 0, 0, 1, 2)
        
        target_layout.addWidget(QLabel("目标工作表名称:"), 1, 0)
        self.target_sheet_combo = QComboBox()
        self.target_sheet_combo.setMinimumWidth(150)
        target_layout.addWidget(self.target_sheet_combo, 1, 1)
        
        btn_refresh = QPushButton("🔄 载入表名")
        btn_refresh.clicked.connect(self.load_sheets)
        target_layout.addWidget(btn_refresh, 1, 2)

        target_layout.addWidget(QLabel("写入锚点左上角:"), 2, 0)
        self.in_anchor = QLineEdit()
        self.in_anchor.setPlaceholderText("A1")
        self.in_anchor.setText("A1")
        target_layout.addWidget(self.in_anchor, 2, 1)

        main_layout.addLayout(target_layout)

        # 3. 操作与开关
        act_layout = QHBoxLayout()
        self.chk_unique = QCheckBox("🔥 执行本地级行哈希全量去重 (类似 UNIQUE)")
        self.chk_unique.setChecked(True)
        act_layout.addWidget(self.chk_unique)
        
        act_layout.addStretch()

        self.btn_execute = QPushButton("⚡ 执行本地沙盒抽取与脱水合并")
        self.btn_execute.setObjectName("primary_btn")
        self.btn_execute.clicked.connect(self.perform_merge)
        act_layout.addWidget(self.btn_execute)

        main_layout.addLayout(act_layout)

        main_layout.addStretch()

        self.status = QLabel("待机中。")
        self.status.setWordWrap(True)
        main_layout.addWidget(self.status)

    def load_sheets(self):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 请先连接 Google Sheet")
            return
            
        try:
            view = self.controller.view
            sheets = [view.sheet_list.itemText(i) for i in range(view.sheet_list.count())]
            self.target_sheet_combo.clear()
            self.target_sheet_combo.addItems(sheets)
            self.status.setText("✅ 输出候选表已更新。")
        except Exception as e:
            self.status.setText(f"❌ 加载工作表失败: {str(e)}")

    def perform_merge(self):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 未连接表格服务")
            return

        sources_text = self.in_sources.toPlainText().strip()
        if not sources_text:
            self.status.setText("⚠️ 数据源列表不可为空")
            return
            
        sources = [s.strip() for s in sources_text.split("\n") if s.strip()]
        target_sheet = self.target_sheet_combo.currentText()
        anchor = self.in_anchor.text().strip()
        
        if not target_sheet or not anchor:
            self.status.setText("⚠️ 目标表或锚点未设定")
            return

        reply = QMessageBox.warning(
            self, "确认覆盖", 
            f"引擎即将由本地汇聚 {len(sources)} 条源线列的数据，并在本地去重后，整体暴力轰盖到 {target_sheet} 的 {anchor} 坐标网格处。\n如果目标区域原先有数据会无情覆盖！\n\n确认推进合并固化？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_execute.setEnabled(False)
        self.status.setText("⏳ 合并机器开始运转，派发网络蛛丝抽拉数据...")

        self.worker = MergeUniqueWorker(
            self.controller.service,
            sources,
            target_sheet,
            anchor,
            self.chk_unique.isChecked()
        )
        self.worker.progress.connect(lambda msg: self.status.setText(msg))
        self.worker.finished.connect(self.on_check_finished)
        self.worker.error.connect(self.on_check_error)
        self.worker.start()

    def on_check_finished(self, msg):
        self.btn_execute.setEnabled(True)
        self.status.setText(msg)

    def on_check_error(self, err_msg):
        self.btn_execute.setEnabled(True)
        self.status.setText(f"❌ 合并失败: {err_msg}")
