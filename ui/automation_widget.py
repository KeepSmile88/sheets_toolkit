import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTabWidget, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QSplitter, QCheckBox, QMessageBox
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import Qt, QThread, Signal

logger = logging.getLogger("sheets_toolkit.ui.automation")

class AutomationWorker(QThread):
    finished = Signal(str)
    progress = Signal(str)
    error = Signal(str)

    def __init__(self, service, task_type, **kwargs):
        super().__init__()
        self.service = service
        self.task_type = task_type
        self.kwargs = kwargs

    def run(self):
        try:
            if self.task_type == "create":
                self._run_create()
            elif self.task_type == "rename":
                self._run_rename()
            elif self.task_type == "delete":
                self._run_delete()
        except Exception as e:
            self.error.emit(str(e))
            logger.error(f"自动化任务失败 ({self.task_type}): {e}", exc_info=True)

    def _run_create(self):
        template = self.kwargs.get("template")
        names = self.kwargs.get("names", [])
        
        template_id = self.service.get_sheet_id_by_name(template)
        if template_id is None:
            self.error.emit(f"错误：无法找到模板表 '{template}' 的 ID")
            return
            
        success_count = 0
        for i, name in enumerate(names):
            self.progress.emit(f"正在以模板 '{template}' 创建: {name} ({i+1}/{len(names)})")
            # 复制模板
            new_sheet_info = self.service.copy_sheet(template_id)
            # 谷歌原生 API copy 返回的是类似于 "副本 xxx" 的字样，我们需要把它重命名
            new_sheet_id = new_sheet_info.get("sheetId")
            
            # 构造 batchUpdate 强行重命名
            if new_sheet_id is not None:
                requests = [{
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": new_sheet_id,
                            "title": name
                        },
                        "fields": "title"
                    }
                }]
                self.service.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.service.spreadsheet_id,
                    body={"requests": requests}
                ).execute()
            
            success_count += 1
            
        self.finished.emit(f"成功根据模板批量创建了 {success_count} 个工作表。")

    def _run_rename(self):
        target_sheets = self.kwargs.get("sheets", []) # [(sheetId, currentName), ...]
        prefix = self.kwargs.get("prefix", "")
        suffix = self.kwargs.get("suffix", "")
        find_str = self.kwargs.get("find", "")
        replace_str = self.kwargs.get("replace", "")
        
        requests = []
        for sid, old_name in target_sheets:
            new_name = old_name
            if find_str:
                new_name = new_name.replace(find_str, replace_str)
            new_name = f"{prefix}{new_name}{suffix}"
            
            if new_name != old_name:
                requests.append({
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": sid,
                            "title": new_name
                        },
                        "fields": "title"
                    }
                })
        
        if not requests:
            self.finished.emit("没有表单需要重命名。")
            return
            
        self.progress.emit(f"正在提交批量重命名...")
        self.service.service.spreadsheets().batchUpdate(
            spreadsheetId=self.service.spreadsheet_id,
            body={"requests": requests}
        ).execute()
        
        self.finished.emit(f"批量重命名完成，共修改了 {len(requests)} 个工作表。")

    def _run_delete(self):
        sheet_ids = self.kwargs.get("sheet_ids", [])
        if not sheet_ids:
            self.finished.emit("未选择任何工作表处理。")
            return
            
        requests = [{"deleteSheet": {"sheetId": sid}} for sid in sheet_ids]
        
        self.progress.emit(f"正在进行清理工作...")
        self.service.service.spreadsheets().batchUpdate(
            spreadsheetId=self.service.spreadsheet_id,
            body={"requests": requests}
        ).execute()
        
        self.finished.emit(f"批量清理完成，共删除了 {len(requests)} 个工作表。")


class BatchCreatePanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.worker = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        desc = QLabel("💡 <b>批量模板建表：</b>请在左侧选择连接并在此刷新后，选择需要作为母版的工作表，然后在输入框中提供新表单名称列表即可高速批量建表。")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("① 选定模板工作表:"))
        self.template_combo = QComboBox()
        self.template_combo.setMinimumWidth(150)
        ctrl.addWidget(self.template_combo)
        
        self.btn_refresh = QPushButton("🔄 刷新表单列表")
        self.btn_refresh.clicked.connect(self.load_sheets)
        ctrl.addWidget(self.btn_refresh)
        ctrl.addStretch()
        layout.addLayout(ctrl)
        
        layout.addWidget(QLabel("② 输入新生成的表单组名称 (每行一个):"))
        self.names_input = ClearableTextEdit()
        self.names_input.setPlaceholderText("部门A-汇总\n部门B-汇总\n部门C-汇总...")
        layout.addWidget(self.names_input)
        
        self.btn_execute = QPushButton("🔨 一键批量建表")
        self.btn_execute.setObjectName("primary_btn")
        self.btn_execute.clicked.connect(self.execute)
        layout.addWidget(self.btn_execute)
        
        self.status = QLabel("待机中。")
        self.status.setStyleSheet("color: #666;")
        layout.addWidget(self.status)

    def load_sheets(self):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 未连接服务")
            return
        sheets = self.controller.service.list_sheets()
        self.template_combo.clear()
        self.template_combo.addItems(sheets)
        self.status.setText("✅ 列表已更新")

    def execute(self):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 未连接服务")
            return
            
        template = self.template_combo.currentText()
        if not template:
            self.status.setText("⚠️ 请选择一个模板工作表")
            return
            
        names_text = self.names_input.toPlainText()
        names = [n.strip() for n in names_text.split('\n') if n.strip()]
        if not names:
            self.status.setText("⚠️ 请输入至少一个新表名称")
            return
            
        self.btn_execute.setEnabled(False)
        self.status.setText("⏳ 准备生成...")
        
        self.worker = AutomationWorker(
            self.controller.service, 
            task_type="create", 
            template=template, 
            names=names
        )
        self.worker.progress.connect(self.status.setText)
        self.worker.finished.connect(self.on_success)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_success(self, msg):
        self.btn_execute.setEnabled(True)
        self.status.setText(f"✅ {msg}")
        self.names_input.clear()

    def on_error(self, err):
        self.btn_execute.setEnabled(True)
        self.status.setText(f"❌ 失败: {err}")


class BatchRenamePanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.worker = None
        self._current_sheets = []
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        desc = QLabel("💡 <b>批量重命名：</b>勾选目标表单，并在下方规则区域填写替换规则。点击执行以快速应用到所有勾选的表单。")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        top = QHBoxLayout()
        self.btn_load = QPushButton("🔄 加载目标表格结构")
        self.btn_load.clicked.connect(self.load_sheets)
        top.addWidget(self.btn_load)
        
        self.btn_sel_all = QPushButton("☑️ 全选")
        self.btn_sel_all.clicked.connect(lambda: self._set_all_checked(True))
        top.addWidget(self.btn_sel_all)
        
        self.btn_sel_none = QPushButton("☐ 清空选择")
        self.btn_sel_none.clicked.connect(lambda: self._set_all_checked(False))
        top.addWidget(self.btn_sel_none)
        top.addStretch()
        layout.addLayout(top)
        
        # 列表展示
        self.table = QTableWidget(0, 1)
        self.table.horizontalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, stretch=1)
        
        # 参数配置区
        form = QHBoxLayout()
        
        fg1 = QVBoxLayout()
        fg1.addWidget(QLabel("增加前缀:"))
        self.in_prefix = QLineEdit()
        self.in_prefix.setPlaceholderText("如: [归档]")
        fg1.addWidget(self.in_prefix)
        
        fg1.addWidget(QLabel("增加后缀:"))
        self.in_suffix = QLineEdit()
        self.in_suffix.setPlaceholderText("如: _2026")
        fg1.addWidget(self.in_suffix)
        form.addLayout(fg1)
        
        fg2 = QVBoxLayout()
        fg2.addWidget(QLabel("查找文本 (替换):"))
        self.in_find = QLineEdit()
        self.in_find.setPlaceholderText("如: 原命名")
        fg2.addWidget(self.in_find)
        
        fg2.addWidget(QLabel("替换为:"))
        self.in_replace = QLineEdit()
        self.in_replace.setPlaceholderText("如: 新命名")
        fg2.addWidget(self.in_replace)
        form.addLayout(fg2)
        
        layout.addLayout(form)
        
        self.btn_execute = QPushButton("📝 提交批量改名")
        self.btn_execute.setObjectName("primary_btn")
        self.btn_execute.clicked.connect(self.execute)
        layout.addWidget(self.btn_execute)
        
        self.status = QLabel("待机中。")
        self.status.setStyleSheet("color: #666;")
        layout.addWidget(self.status)

    def _set_all_checked(self, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item:
                item.setCheckState(state)

    def load_sheets(self):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 未连接服务")
            return
        
        self.status.setText("⏳ 正在拉取元数据...")
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
            
            # 使用 Spreadsheet API 一次拉取全部元数据 (包含 id 和 name)
            spreadsheet = self.controller.service.service.spreadsheets().get(
                spreadsheetId=self.controller.service.spreadsheet_id
            ).execute()
            
            sheets = spreadsheet.get("sheets", [])
            self.table.setRowCount(0)
            self._current_sheets = []
            
            for s in sheets:
                props = s.get("properties", {})
                sid = props.get("sheetId")
                title = props.get("title")
                
                self._current_sheets.append((sid, title))
                
                r = self.table.rowCount()
                self.table.insertRow(r)
                
                item = QTableWidgetItem(f"[{sid}] {title}")
                item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Unchecked)
                item.setData(Qt.UserRole, sid)
                item.setData(Qt.UserRole + 1, title)
                self.table.setItem(r, 0, item)
                
            self.status.setText(f"✅ 成功提取了 {len(sheets)} 个工作表。")
        except Exception as e:
            self.status.setText(f"❌ 拉取失败: {e}")

    def execute(self):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 未连接服务")
            return
            
        targets = []
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item and item.checkState() == Qt.Checked:
                sid = item.data(Qt.UserRole)
                title = item.data(Qt.UserRole + 1)
                targets.append((sid, title))
                
        if not targets:
            self.status.setText("⚠️ 请勾选至少一个表单")
            return
            
        prefix = self.in_prefix.text()
        suffix = self.in_suffix.text()
        find_str = self.in_find.text()
        replace = self.in_replace.text()
        
        if not (prefix or suffix or find_str):
            self.status.setText("⚠️ 请至少配置一项命名规则")
            return
            
        self.btn_execute.setEnabled(False)
        self.status.setText("⏳ 处理中...")
        
        self.worker = AutomationWorker(
            self.controller.service, 
            task_type="rename", 
            sheets=targets,
            prefix=prefix,
            suffix=suffix,
            find=find_str,
            replace=replace
        )
        self.worker.progress.connect(self.status.setText)
        self.worker.finished.connect(self.on_success)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_success(self, msg):
        self.btn_execute.setEnabled(True)
        self.status.setText(f"✅ {msg}")
        self.load_sheets() # 操作完自动刷新

    def on_error(self, err):
        self.btn_execute.setEnabled(True)
        self.status.setText(f"❌ 失败: {err}")


class BatchDeletePanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.worker = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        desc = QLabel("💡 <b>批量安全清理：</b>勾选所有不再需要的工作表，并一键完成批量删除清理（注意！删除工作版无法轻易撤销，建议操作前开启在主界面的批量备份功能）。")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #d32f2f;")
        layout.addWidget(desc)
        
        top = QHBoxLayout()
        self.btn_load = QPushButton("🔄 加载当前表格")
        self.btn_load.clicked.connect(self.load_sheets)
        top.addWidget(self.btn_load)
        
        self.btn_sel_all = QPushButton("☑️ 全选")
        self.btn_sel_all.clicked.connect(lambda: self._set_all_checked(True))
        top.addWidget(self.btn_sel_all)
        
        self.btn_sel_none = QPushButton("☐ 清空选择")
        self.btn_sel_none.clicked.connect(lambda: self._set_all_checked(False))
        top.addWidget(self.btn_sel_none)
        top.addStretch()
        layout.addLayout(top)
        
        self.table = QTableWidget(0, 1)
        self.table.horizontalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, stretch=1)
        
        self.btn_execute = QPushButton("🗑️ 警告：一键批量销毁勾选表单")
        self.btn_execute.setObjectName("danger_btn")
        self.btn_execute.clicked.connect(self.execute)
        layout.addWidget(self.btn_execute)
        
        self.status = QLabel("待机中。")
        self.status.setStyleSheet("color: #666;")
        layout.addWidget(self.status)

    def _set_all_checked(self, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item:
                item.setCheckState(state)

    def load_sheets(self):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 未连接服务")
            return
        
        self.status.setText("⏳ 正在拉取...")
        try:
            # 同样直接拉取 meta 确保拿到 sheetId 用于精准销毁
            spreadsheet = self.controller.service.service.spreadsheets().get(
                spreadsheetId=self.controller.service.spreadsheet_id
            ).execute()
            
            sheets = spreadsheet.get("sheets", [])
            self.table.setRowCount(0)
            
            for s in sheets:
                props = s.get("properties", {})
                sid = props.get("sheetId")
                title = props.get("title")
                
                r = self.table.rowCount()
                self.table.insertRow(r)
                item = QTableWidgetItem(f"[{sid}] {title}")
                item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Unchecked)
                item.setData(Qt.UserRole, sid)
                self.table.setItem(r, 0, item)
                
            self.status.setText(f"✅ 成功提取了 {len(sheets)} 个工作表，防误删注意。")
        except Exception as e:
            self.status.setText(f"❌ 拉取失败: {e}")

    def execute(self):
        if not self.controller.is_connected or not self.controller.service:
            self.status.setText("⚠️ 未连接服务")
            return
            
        targets = []
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item and item.checkState() == Qt.Checked:
                targets.append(item.data(Qt.UserRole))
                
        if not targets:
            self.status.setText("⚠️ 请勾选至少一个表单")
            return
            
        # 即使只剩一个表也可能删掉导致失败，需二次确认
        reply = QMessageBox.warning(
            self, "确认批量清理", 
            f"您选中了 {len(targets)} 个工作表即将销毁，该操作极其危险。是否仍然继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_execute.setEnabled(False)
        self.status.setText("⏳ 清理中...")
        
        self.worker = AutomationWorker(
            self.controller.service, 
            task_type="delete", 
            sheet_ids=targets
        )
        self.worker.progress.connect(self.status.setText)
        self.worker.finished.connect(self.on_success)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_success(self, msg):
        self.btn_execute.setEnabled(True)
        self.status.setText(f"✅ {msg}")
        self.load_sheets()

    def on_error(self, err):
        self.btn_execute.setEnabled(True)
        self.status.setText(f"❌ 失败: {err}")


class AutomationWidget(QWidget):
    """
    自动化综合处理面板：替代旧版“自动化”，
    提供完整的：1.批量模板克隆建表 2.批量命名组合 3.批量清理中心
    """
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("⚙️ 自动化综合处理中心")
        title.setObjectName("section_title")
        layout.addWidget(title)

        self.tabs = QTabWidget()
        
        self.create_tab = BatchCreatePanel(self.controller, self)
        self.tabs.addTab(self.create_tab, "📄 批量克隆建表")
        
        self.rename_tab = BatchRenamePanel(self.controller, self)
        self.tabs.addTab(self.rename_tab, "📝 批量整理重命名")
        
        self.delete_tab = BatchDeletePanel(self.controller, self)
        self.tabs.addTab(self.delete_tab, "🗑️ 安全批量清理")

        layout.addWidget(self.tabs)
