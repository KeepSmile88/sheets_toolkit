import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QCheckBox,
    QProgressBar, QMessageBox, QGroupBox, QRadioButton, QButtonGroup,
    QComboBox, QTabWidget, )
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import Qt, QThread, Signal
from services.spreadsheet_library import AccountManager
from services.sheet_service import SheetService

logger = logging.getLogger("sheets_toolkit.ui.data_consolidation_widget")


class ConsolidationWorker(QThread):
    """后台线程：执行跨表合并逻辑"""
    progress = Signal(int, int, str)  # 当前进度，总进度，状态文本
    finished = Signal(int, int)       # 处理表数，总写入行数
    error = Signal(str)

    def __init__(self, source_configs, target_sid, target_sheet, skip_header, write_mode, specified_sheets=None, raw_mode=True):
        super().__init__()
        self.source_configs = source_configs
        self.target_sid = target_sid
        self.target_sheet = target_sheet
        self.skip_header = skip_header
        self.write_mode = write_mode
        self.specified_sheets = specified_sheets or []
        self.raw_mode = raw_mode

    def run(self):
        try:
            total_sources = len(self.source_configs)
            sheets_processed = 0
            total_rows_written = 0
            is_first_valid_data = True
            
            target_service = SheetService(self.target_sid)
            
            # 确保目标工作表存在，不存在则创建
            target_sheets = target_service.list_sheets()
            if self.target_sheet not in target_sheets:
                target_service.create_sheet(self.target_sheet)
                
            if self.write_mode == "overwrite":
                # 覆盖模式，先清空旧数据
                target_service.clear_data(f"'{self.target_sheet}'")
                
            # 将批次大小调高至 10000 行，以减少 API 请求次数，防止触发频率限制
            CHUNK_SIZE = 10000
            
            # 第一步：遍历所有选定的工作簿
            for i, config in enumerate(self.source_configs):
                sid = config['sid']
                gid = config.get('gid')
                try:
                    service = SheetService(sid)
                    
                    if gid is not None:
                        meta = service.get_metadata()
                        sheets = []
                        for s in meta.get('sheets', []):
                            if s.get('properties', {}).get('sheetId') == gid:
                                sheets = [s['properties']['title']]
                                break
                    else:
                        sheets = service.list_sheets()
                    
                    # 遍历该工作簿下的所有工作表
                    for sheet_name in sheets:
                        if gid is None and self.specified_sheets and sheet_name not in self.specified_sheets:
                            continue
                            
                        self.progress.emit(i, total_sources, f"正在拉取表格: {sheet_name} ...")
                        data = service.read_data(sheet_name)
                        if not data:
                            continue
                            
                        # 过滤掉完全为空的无效行
                        filtered_data = []
                        for row in data:
                            if row and any(str(cell).strip() for cell in row):
                                filtered_data.append(row)
                                
                        if not filtered_data:
                            continue
                            
                        # 如果不是本次处理的第一个有效数据集且要求跳过表头，则去掉第一行
                        if self.skip_header and not is_first_valid_data and len(filtered_data) > 0:
                            filtered_data = filtered_data[1:]
                            
                        if filtered_data:
                            # 采用流式写入，立刻分批将该表数据写入目标表，释放内存
                            for chunk_start in range(0, len(filtered_data), CHUNK_SIZE):
                                chunk = filtered_data[chunk_start:chunk_start + CHUNK_SIZE]
                                self.progress.emit(i, total_sources, f"正在写入 {sheet_name} ({min(chunk_start + CHUNK_SIZE, len(filtered_data))}/{len(filtered_data)})...")
                                input_option = "RAW" if self.raw_mode else "USER_ENTERED"
                                target_service.append_data(self.target_sheet, "A1", chunk, value_input_option=input_option)
                                total_rows_written += len(chunk)
                                
                            is_first_valid_data = False
                        sheets_processed += 1
                        
                except Exception as e:
                    logger.error(f"读取或写入表格 {sid} 失败: {e}")
                    # 继续处理下一个表格
            
            if total_rows_written == 0:
                self.error.emit("未从所选表格中拉取到任何有效数据。")
                return
                
            self.finished.emit(sheets_processed, total_rows_written)
            
        except Exception as e:
            logger.error(f"数据合并失败: {e}")
            self.error.emit(str(e))


class DataConsolidationWidget(QWidget):
    """
    跨表数据汇总面板
    """
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.account_mgr = AccountManager()
        self._worker = None
        self._setup_ui()
        self._load_library_entries()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ======= 标题 =======
        title = QLabel("🔗 跨表数据汇总")
        title.setObjectName("section_title")
        layout.addWidget(title)
        
        desc = QLabel(
            "选择多个表格或输入多个表格链接，提取其中所有工作表的数据并垂直合并为一张总表。"
        )
        desc.setStyleSheet("color: gray; margin-bottom: 4px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # ======= 数据源选择 =======
        source_group = QGroupBox("1. 选择数据源")
        source_layout = QVBoxLayout(source_group)
        
        self.source_tabs = QTabWidget()
        
        # --- Tab 1: 手动输入 ---
        self.tab_manual = QWidget()
        manual_layout = QVBoxLayout(self.tab_manual)
        manual_layout.addWidget(QLabel("每行输入一个 Google Sheet 链接或 ID:"))
        self.manual_links_edit = ClearableTextEdit()
        self.manual_links_edit.setPlaceholderText("https://docs.google.com/spreadsheets/d/...\\n...")
        manual_layout.addWidget(self.manual_links_edit)
        self.source_tabs.addTab(self.tab_manual, "手动输入")
        
        # --- Tab 2: 表格库选择 ---
        self.tab_library = QWidget()
        library_layout = QVBoxLayout(self.tab_library)
        
        # 账号选择
        acc_layout = QHBoxLayout()
        acc_layout.addWidget(QLabel("选择账号:"))
        self.account_combo = QComboBox()
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        acc_layout.addWidget(self.account_combo, 1)
        
        self.btn_select_all = QPushButton("全选")
        self.btn_select_all.clicked.connect(lambda: self._set_all_checked(True))
        acc_layout.addWidget(self.btn_select_all)
        
        self.btn_deselect_all = QPushButton("全不选")
        self.btn_deselect_all.clicked.connect(lambda: self._set_all_checked(False))
        acc_layout.addWidget(self.btn_deselect_all)
        
        library_layout.addLayout(acc_layout)

        # 搜索框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索表格名称...")
        self.search_input.textChanged.connect(self._on_search_text_changed)
        library_layout.addWidget(self.search_input)

        self.source_list = QListWidget()
        self.source_list.setAlternatingRowColors(True)
        library_layout.addWidget(self.source_list)
        
        self.source_tabs.addTab(self.tab_library, "从表格库选择")
        
        source_layout.addWidget(self.source_tabs)

        # 指定工作表名称
        self.specify_sheets_input = QLineEdit()
        self.specify_sheets_input.setPlaceholderText("指定要提取的工作表名称 (选填，多个用逗号分隔，留空则提取所有工作表)")
        source_layout.addWidget(self.specify_sheets_input)

        # 跳过表头选项
        self.skip_header_cb = QCheckBox("保留第一个表头，其余表格跳过第 1 行 (适用于结构完全一致的数据)")
        self.skip_header_cb.setChecked(True)
        source_layout.addWidget(self.skip_header_cb)

        layout.addWidget(source_group, 1)

        # ======= 目标配置 =======
        target_group = QGroupBox("2. 目标表配置")
        target_layout = QVBoxLayout(target_group)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("🎯 目标表格链接/ID:"))
        self.target_sid_input = QLineEdit()
        self.target_sid_input.setPlaceholderText("填入用于接收汇总数据的 Google Sheet 链接")
        row1.addWidget(self.target_sid_input, 1)
        target_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("📋 目标工作表名称:"))
        self.target_sheet_input = QLineEdit("合并总表")
        self.target_sheet_input.setMaximumWidth(150)
        row2.addWidget(self.target_sheet_input)
        row2.addStretch()
        target_layout.addLayout(row2)
        
        # 原格式保留选项
        self.raw_mode_cb = QCheckBox("强制保留纯文本格式（防止日期变数字等问题）")
        self.raw_mode_cb.setChecked(True)
        target_layout.addWidget(self.raw_mode_cb)

        # 写入模式
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("📝 写入模式:"))
        self.mode_group = QButtonGroup(self)
        self.radio_append = QRadioButton("追加写入 (在原数据下方继续添加)")
        self.radio_overwrite = QRadioButton("覆盖写入 (清空原工作表并写入)")
        self.radio_overwrite.setChecked(True)
        self.mode_group.addButton(self.radio_append)
        self.mode_group.addButton(self.radio_overwrite)
        mode_layout.addWidget(self.radio_overwrite)
        mode_layout.addWidget(self.radio_append)
        mode_layout.addStretch()
        target_layout.addLayout(mode_layout)

        layout.addWidget(target_group)

        # ======= 执行区 =======
        bottom_layout = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        bottom_layout.addWidget(self.progress, 1)
        
        self.status_label = QLabel("")
        bottom_layout.addWidget(self.status_label)
        
        self.btn_start = QPushButton("🚀 开始汇总合并")
        self.btn_start.setObjectName("primary_btn")
        self.btn_start.setMinimumHeight(40)
        self.btn_start.setMinimumWidth(150)
        self.btn_start.clicked.connect(self._start_consolidation)
        bottom_layout.addWidget(self.btn_start)

        layout.addLayout(bottom_layout)

    # ============================
    # 列表加载
    # ============================

    def _load_library_entries(self):
        """加载表格库账号和条目"""
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
        acc_id = self.account_combo.itemData(index)
        self._load_entries_for_account(acc_id)

    def _load_entries_for_account(self, acc_id):
        self.source_list.clear()
        lib = self.account_mgr.get_library(acc_id)
        if not lib:
            return
            
        for entry in lib.entries:
            name = entry.get("name", "未命名")
            group_id = entry.get("group_id")
            group_name = lib.get_group_name(group_id)
            sid = entry.get("spreadsheet_id", "")
            
            if sid:
                item = QListWidgetItem(f"[{group_name}] {name}")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                item.setData(Qt.UserRole, sid)
                self.source_list.addItem(item)
                
    def _on_search_text_changed(self, text):
        search_text = text.lower()
        for i in range(self.source_list.count()):
            item = self.source_list.item(i)
            if search_text in item.text().lower():
                item.setHidden(False)
            else:
                item.setHidden(True)

    def _set_all_checked(self, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        for i in range(self.source_list.count()):
            item = self.source_list.item(i)
            if not item.isHidden():
                item.setCheckState(state)

    # ============================
    # 执行汇总
    # ============================

    def _start_consolidation(self):
        # 1. 获取选中的源表格
        source_configs = []
        from ui.batch_backup_widget import extract_spreadsheet_id
        import re
        
        if self.source_tabs.currentWidget() == self.tab_manual:
            # 手动输入模式
            text = self.manual_links_edit.toPlainText().strip()
            if text:
                for line in text.split('\n'):
                    line = line.strip()
                    if line:
                        sid = extract_spreadsheet_id(line)
                        if sid:
                            match = re.search(r'[#&?]gid=([0-9]+)', line)
                            gid = int(match.group(1)) if match else None
                            source_configs.append({"sid": sid, "gid": gid})
        else:
            # 表格库选择模式
            for i in range(self.source_list.count()):
                item = self.source_list.item(i)
                if item.checkState() == Qt.Checked:
                    source_configs.append({"sid": item.data(Qt.UserRole), "gid": None})
                
        if not source_configs:
            QMessageBox.warning(self, "提示", "请提供至少一个有效的源表格。")
            return
            
        # 2. 检查目标表
        target_raw = self.target_sid_input.text().strip()
        target_sid = extract_spreadsheet_id(target_raw)
        
        if not target_sid:
            QMessageBox.warning(self, "提示", "请输入有效的目标表格链接或 ID。")
            return
            
        target_sheet = self.target_sheet_input.text().strip()
        if not target_sheet:
            QMessageBox.warning(self, "提示", "请输入目标工作表名称。")
            return
            
        skip_header = self.skip_header_cb.isChecked()
        write_mode = "append" if self.radio_append.isChecked() else "overwrite"
        raw_mode = self.raw_mode_cb.isChecked()
        
        raw_specified_sheets = self.specify_sheets_input.text().strip()
        specified_sheets = [s.strip() for s in raw_specified_sheets.split(',')] if raw_specified_sheets else []
        
        sheet_msg = f"（仅提取指定工作表：{', '.join(specified_sheets)}）" if specified_sheets else "（提取所有工作表）"
        
        reply = QMessageBox.question(
            self, "确认汇总",
            f"将合并 {len(source_configs)} 个工作簿中的数据 {sheet_msg} 到目标表，确定执行？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_start.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(source_configs))
        self.progress.setValue(0)
        self.status_label.setText("准备开始...")
        
        self._worker = ConsolidationWorker(
            source_configs, target_sid, target_sheet, skip_header, write_mode, specified_sheets, raw_mode
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, val, total, msg):
        self.progress.setMaximum(total)
        self.progress.setValue(val)
        self.status_label.setText(msg)

    def _on_finished(self, sheets_processed, total_rows):
        self.btn_start.setEnabled(True)
        self.progress.setVisible(False)
        msg = f"合并成功！从 {sheets_processed} 个工作表中提取了 {total_rows} 行数据。"
        self.status_label.setText(f"✅ {msg}")
        QMessageBox.information(self, "汇总完成", msg)

    def _on_error(self, err):
        self.btn_start.setEnabled(True)
        self.progress.setVisible(False)
        self.status_label.setText("❌ 合并失败")
        QMessageBox.critical(self, "错误", f"汇总过程中出现错误:\n{err}")
