import re
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem,
    QProgressBar, QMessageBox, QGroupBox, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QScrollArea, QSplitter
)
from PySide6.QtCore import Qt, QThread, Signal
from services.spreadsheet_library import AccountManager
from services.sheet_service import SheetService

logger = logging.getLogger("sheets_toolkit.ui.global_search_widget")


def check_condition(row_data, headers, col_key, rule, target_val):
    """
    检查单行数据是否满足指定条件
    """
    if not row_data:
        return False
        
    # 尝试解析 col_key，如果是纯数字则视为列号(1-based)，否则视为表头名
    col_idx = -1
    if col_key.isdigit():
        col_idx = int(col_key) - 1
    elif headers and col_key in headers:
        col_idx = headers.index(col_key)
        
    if col_idx < 0 or col_idx >= len(row_data):
        return False  # 该列不存在，不匹配
        
    cell_val = str(row_data[col_idx])
    target_val_str = str(target_val)
    
    if rule == "包含":
        return target_val_str.lower() in cell_val.lower()
    elif rule == "不包含":
        return target_val_str.lower() not in cell_val.lower()
    elif rule == "等于":
        return target_val_str.lower() == cell_val.lower()
    elif rule == "不等于":
        return target_val_str.lower() != cell_val.lower()
    elif rule == "大于":
        # 尝试转数字比较，否则字典序
        try:
            return float(cell_val) > float(target_val_str)
        except ValueError:
            return cell_val > target_val_str
    elif rule == "小于":
        try:
            return float(cell_val) < float(target_val_str)
        except ValueError:
            return cell_val < target_val_str
    elif rule == "正则匹配":
        try:
            return bool(re.search(target_val_str, cell_val, re.IGNORECASE))
        except re.error:
            return False
            
    return False


class GlobalSearchWorker(QThread):
    """后台线程：执行跨表搜索过滤逻辑"""
    progress = Signal(int, int, str)  # curr, total, msg
    finished = Signal(list)           # 搜索结果列表
    error = Signal(str)

    def __init__(self, sources, conditions):
        """
        sources: list of dict {"sid": ..., "name": ...}
        conditions: list of dict {"col": ..., "rule": ..., "val": ...}
        """
        super().__init__()
        self.sources = sources
        self.conditions = conditions

    def run(self):
        try:
            results = []
            total = len(self.sources)
            
            for i, src in enumerate(self.sources):
                sid = src["sid"]
                spreadsheet_name = src["name"]
                
                self.progress.emit(i, total, f"正在检索: {spreadsheet_name}...")
                
                try:
                    service = SheetService(sid)
                    # 为了获得更准确的名称，可不依赖库中缓存的名称，但在 worker 中为了提速直接用传入的
                    sheets = service.list_sheets()
                    
                    for sheet_name in sheets:
                        data = service.read_data(sheet_name)
                        if not data or len(data) == 0:
                            continue
                            
                        # 假设第一行为表头
                        headers = [str(h).strip() for h in data[0]]
                        
                        # 从第二行开始遍历数据
                        for row_idx, row_data in enumerate(data[1:], start=2):
                            # 如果没有条件，视为全匹配
                            match_all = True
                            for cond in self.conditions:
                                if not check_condition(row_data, headers, cond["col"], cond["rule"], cond["val"]):
                                    match_all = False
                                    break
                                    
                            if match_all:
                                results.append({
                                    "spreadsheet_name": spreadsheet_name,
                                    "sheet_name": sheet_name,
                                    "row_number": row_idx,
                                    "data": row_data
                                })
                except Exception as e:
                    logger.error(f"检索表格 {spreadsheet_name}({sid}) 失败: {e}")
                    # 继续查下一个
                    
            self.finished.emit(results)
            
        except Exception as e:
            logger.error(f"全局搜索失败: {e}")
            self.error.emit(str(e))


class ConditionWidget(QWidget):
    """单条过滤条件组件"""
    remove_requested = Signal(QWidget)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.col_input = QLineEdit()
        self.col_input.setPlaceholderText("列号(如1)或列名(如姓名)")
        layout.addWidget(self.col_input)
        
        self.rule_combo = QComboBox()
        self.rule_combo.addItems(["包含", "等于", "不包含", "不等于", "大于", "小于", "正则匹配"])
        layout.addWidget(self.rule_combo)
        
        self.val_input = QLineEdit()
        self.val_input.setPlaceholderText("匹配值...")
        layout.addWidget(self.val_input, 1)
        
        self.btn_remove = QPushButton("❌")
        self.btn_remove.setMaximumWidth(40)
        self.btn_remove.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(self.btn_remove)

    def get_condition(self):
        col = self.col_input.text().strip()
        rule = self.rule_combo.currentText()
        val = self.val_input.text().strip()
        if not col or not val:
            return None
        return {"col": col, "rule": rule, "val": val}


class GlobalSearchWidget(QWidget):
    """
    全局跨表搜索与筛选面板
    """
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.account_mgr = AccountManager()
        self._worker = None
        self._results = []
        self._setup_ui()
        self._load_library_entries()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("🔍 全局搜索与筛选")
        title.setObjectName("section_title")
        layout.addWidget(title)
        
        main_splitter = QSplitter(Qt.Vertical)
        
        # 顶层控制面板容器
        top_container = QWidget()
        top_vlayout = QVBoxLayout(top_container)
        top_vlayout.setContentsMargins(0, 0, 0, 0)

        # ======= 上半区：水平分割 =======
        top_layout = QHBoxLayout()

        # 1. 数据源选择
        source_group = QGroupBox("1. 搜索范围 (从表格库选择)")
        source_layout = QVBoxLayout(source_group)
        
        acc_layout = QHBoxLayout()
        self.account_combo = QComboBox()
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        acc_layout.addWidget(self.account_combo, 1)
        self.btn_select_all = QPushButton("全选")
        self.btn_select_all.clicked.connect(lambda: self._set_all_checked(True))
        acc_layout.addWidget(self.btn_select_all)
        self.btn_deselect_all = QPushButton("全不选")
        self.btn_deselect_all.clicked.connect(lambda: self._set_all_checked(False))
        acc_layout.addWidget(self.btn_deselect_all)
        source_layout.addLayout(acc_layout)

        self.source_list = QListWidget()
        self.source_list.setAlternatingRowColors(True)
        source_layout.addWidget(self.source_list)
        
        top_layout.addWidget(source_group, 1)

        # 2. 过滤条件
        cond_group = QGroupBox("2. 筛选条件 (多条件同时满足)")
        cond_layout = QVBoxLayout(cond_group)
        
        self.cond_container = QVBoxLayout()
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_widget.setLayout(self.cond_container)
        scroll.setWidget(scroll_widget)
        cond_layout.addWidget(scroll)
        
        btn_add_cond = QPushButton("➕ 添加过滤条件")
        btn_add_cond.clicked.connect(self._add_condition_row)
        cond_layout.addWidget(btn_add_cond)
        
        # 默认添加一行条件
        self._add_condition_row()

        top_layout.addWidget(cond_group, 1)
        
        top_vlayout.addLayout(top_layout, 1)

        # ======= 状态栏与操作 =======
        action_layout = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        action_layout.addWidget(self.progress, 1)
        
        self.status_label = QLabel("配置条件后点击开始搜索")
        action_layout.addWidget(self.status_label)
        
        self.btn_export = QPushButton("📤 导出结果至表格")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export_results)
        action_layout.addWidget(self.btn_export)

        self.btn_search = QPushButton("🚀 开始全局搜索")
        self.btn_search.setObjectName("primary_btn")
        self.btn_search.setMinimumHeight(40)
        self.btn_search.clicked.connect(self._start_search)
        action_layout.addWidget(self.btn_search)

        top_vlayout.addLayout(action_layout)
        
        main_splitter.addWidget(top_container)

        # ======= 结果展示区 =======
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["来源表格", "工作表名", "行号", "行数据摘要"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        
        main_splitter.addWidget(self.table)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        
        layout.addWidget(main_splitter, 1)

    def _add_condition_row(self):
        cond_w = ConditionWidget()
        cond_w.remove_requested.connect(self._remove_condition_row)
        self.cond_container.addWidget(cond_w)
        
    def _remove_condition_row(self, widget):
        if self.cond_container.count() > 1:
            self.cond_container.removeWidget(widget)
            widget.deleteLater()
        else:
            QMessageBox.information(self, "提示", "至少保留一条过滤条件，否则请直接点击汇总。")

    # ============================
    # 列表加载
    # ============================

    def _load_library_entries(self):
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        for acc in self.account_mgr.accounts:
            self.account_combo.addItem(acc["name"], userData=acc["id"])
        self.account_combo.blockSignals(False)
        
        active_idx = self.account_mgr.active_index
        if 0 <= active_idx < self.account_combo.count():
            self.account_combo.setCurrentIndex(active_idx)
            self._load_entries_for_account(self.account_combo.itemData(active_idx))
        elif self.account_combo.count() > 0:
            self.account_combo.setCurrentIndex(0)
            self._load_entries_for_account(self.account_combo.itemData(0))

    def _on_account_changed(self, index):
        if index < 0:
            return
        self._load_entries_for_account(self.account_combo.itemData(index))

    def _load_entries_for_account(self, acc_id):
        self.source_list.clear()
        lib = self.account_mgr.get_library(acc_id)
        if not lib:
            return
            
        for entry in lib.entries:
            name = entry.get("name", "未命名")
            group_name = lib.get_group_name(entry.get("group_id"))
            sid = entry.get("spreadsheet_id", "")
            if sid:
                item = QListWidgetItem(f"[{group_name}] {name}")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                # 将 name 和 sid 都存下来
                item.setData(Qt.UserRole, {"sid": sid, "name": name})
                self.source_list.addItem(item)
                
    def _set_all_checked(self, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        for i in range(self.source_list.count()):
            self.source_list.item(i).setCheckState(state)

    # ============================
    # 执行搜索
    # ============================

    def _start_search(self):
        # 1. 获取源
        sources = []
        for i in range(self.source_list.count()):
            item = self.source_list.item(i)
            if item.checkState() == Qt.Checked:
                sources.append(item.data(Qt.UserRole))
                
        if not sources:
            QMessageBox.warning(self, "提示", "请至少勾选一个要搜索的表格。")
            return
            
        # 2. 获取条件
        conditions = []
        for i in range(self.cond_container.count()):
            w = self.cond_container.itemAt(i).widget()
            if isinstance(w, ConditionWidget):
                c = w.get_condition()
                if c:
                    conditions.append(c)
                    
        if not conditions:
            reply = QMessageBox.question(self, "无条件警告", "未输入任何有效过滤条件，这将直接导出所有数据。是否继续？", QMessageBox.Yes|QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
                
        self.btn_search.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.table.setRowCount(0)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(sources))
        self.progress.setValue(0)
        self.status_label.setText("准备开始检索...")
        self._results = []

        self._worker = GlobalSearchWorker(sources, conditions)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, val, total, msg):
        self.progress.setValue(val)
        self.status_label.setText(msg)

    def _on_finished(self, results):
        self.progress.setVisible(False)
        self.btn_search.setEnabled(True)
        self._results = results
        
        if not results:
            self.status_label.setText("✅ 检索完成，未找到符合条件的数据。")
            QMessageBox.information(self, "完成", "未找到符合条件的数据。")
            return
            
        self.status_label.setText(f"✅ 检索完成，共找到 {len(results)} 行符合条件的数据。")
        self.btn_export.setEnabled(True)
        self._populate_table()

    def _on_error(self, err):
        self.progress.setVisible(False)
        self.btn_search.setEnabled(True)
        self.status_label.setText("❌ 检索失败")
        QMessageBox.critical(self, "错误", f"检索过程出错: {err}")

    def _populate_table(self):
        """将检索结果渲染到表格"""
        self.table.setRowCount(len(self._results))
        for i, res in enumerate(self._results):
            self.table.setItem(i, 0, QTableWidgetItem(res["spreadsheet_name"]))
            self.table.setItem(i, 1, QTableWidgetItem(res["sheet_name"]))
            self.table.setItem(i, 2, QTableWidgetItem(str(res["row_number"])))
            
            # 将原始行数据合并为一个字符串展示，方便预览
            data_str = " | ".join([str(x) for x in res["data"]])
            self.table.setItem(i, 3, QTableWidgetItem(data_str))

    # ============================
    # 导出结果
    # ============================

    def _export_results(self):
        """将检索结果连带原始列导出到新的 Google Sheet（通过提取逻辑）"""
        if not self._results:
            return
            
        from ui.drive_folder_widget import ExportToSheetWorker
        from ui.batch_backup_widget import extract_spreadsheet_id
        from PySide6.QtWidgets import QInputDialog
        
        target_raw, ok = QInputDialog.getText(
            self, "导出结果", "请输入用于接收搜索结果的 Google Sheet 链接或 ID:\n(导出将完全覆盖该表的第一页)"
        )
        if not ok or not target_raw.strip():
            return
            
        target_sid = extract_spreadsheet_id(target_raw.strip())
        if not target_sid:
            QMessageBox.warning(self, "错误", "无法解析有效的表格 ID。")
            return
            
        # 构造导出数据：表头 + 动态列展开
        export_data = []
        
        # 为了美观，找出结果中最长的数据列数
        max_cols = max(len(res["data"]) for res in self._results) if self._results else 0
        headers = ["来源表格", "工作表名", "原行号"] + [f"列 {i+1}" for i in range(max_cols)]
        export_data.append(headers)
        
        for res in self._results:
            row = [
                res["spreadsheet_name"],
                res["sheet_name"],
                str(res["row_number"])
            ]
            row.extend([str(x) for x in res["data"]])
            export_data.append(row)
            
        self.status_label.setText("📤 正在导出搜索结果...")
        self.btn_export.setEnabled(False)
        
        self._export_worker = ExportToSheetWorker(target_sid, "搜索结果", export_data)
        self._export_worker.finished.connect(lambda msg: self._export_finished(msg, True))
        self._export_worker.error.connect(lambda msg: self._export_finished(msg, False))
        self._export_worker.start()

    def _export_finished(self, msg, success):
        self.btn_export.setEnabled(True)
        if success:
            self.status_label.setText("✅ 导出成功")
            QMessageBox.information(self, "导出成功", msg)
        else:
            self.status_label.setText("❌ 导出失败")
            QMessageBox.warning(self, "导出失败", msg)
