import time
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QProgressBar, QMessageBox, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QApplication, QMenu
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from services.sheet_service import SheetService

logger = logging.getLogger("sheets_toolkit.ui.data_driven_template_widget")


# 根据表格 ID 生成 Google Sheets 链接
def _make_sheet_url(sheet_id):
    """根据表格 ID 生成 Google Sheets 链接"""
    if not sheet_id:
        return ""
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"


class TemplateEngineWorker(QThread):
    """后台引擎：执行数据读取、克隆模板、查找替换与授权"""
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, data_source_id, sheet_name, template_id, name_template, email_col, role, folder_id):
        super().__init__()
        self.data_source_id = data_source_id
        self.sheet_name = sheet_name
        self.template_id = template_id
        self.name_template = name_template
        self.email_col = email_col
        self.role = role
        self.folder_id = folder_id

    def run(self):
        try:
            self.progress.emit(0, 100, "正在拉取数据源...")
            data_service = SheetService(self.data_source_id)
            
            # 读取数据
            data = data_service.read_data(self.sheet_name if self.sheet_name else None)
            if not data or len(data) < 2:
                self.error.emit("数据源中没有足够的数据（至少需要表头和一行数据）。")
                return
                
            headers = [str(h).strip() for h in data[0]]
            rows = data[1:]
            total = len(rows)
            results = []
            
            template_service = SheetService(self.template_id)
            
            for i, row in enumerate(rows):
                try:
                    # 补齐长度
                    row_data = row + [""] * (len(headers) - len(row))
                    
                    # 构造替换字典: {"{{表头名}}": "实际值"}
                    replacements = {}
                    for col_idx, header in enumerate(headers):
                        if header:
                            replacements[f"{{{{{header}}}}}"] = str(row_data[col_idx])
                            
                    # 计算新表格名称
                    new_name = self.name_template
                    for search_text, replace_text in replacements.items():
                        new_name = new_name.replace(search_text, replace_text)
                        
                    self.progress.emit(i, total, f"({i+1}/{total}) 正在克隆: {new_name}...")
                    
                    # 1. 克隆表格
                    clone_res = template_service.create_from_template(new_name, self.folder_id)
                    new_id = clone_res.get("id")
                    
                    if not new_id:
                        raise Exception("克隆模板失败")
                        
                    # 2. 占位符替换
                    self.progress.emit(i, total, f"({i+1}/{total}) 正在替换占位符...")
                    new_service = SheetService(new_id)
                    new_service.find_and_replace_batch(replacements)
                    
                    # 3. 执行授权分享
                    email_to_share = ""
                    if self.email_col and self.email_col in headers:
                        email_idx = headers.index(self.email_col)
                        email_to_share = str(row_data[email_idx]).strip()
                        if email_to_share and "@" in email_to_share:
                            self.progress.emit(i, total, f"({i+1}/{total}) 正在授权给: {email_to_share}...")
                            new_service.share_with_email(email_to_share, self.role)
                            
                    results.append({
                        "name": new_name,
                        "id": new_id,
                        "shared_with": email_to_share,
                        "status": "success"
                    })
                    
                    # 避免触发 API 限流，稍作延时
                    time.sleep(1)
                    
                except Exception as e:
                    logger.error(f"处理第 {i+2} 行数据时失败: {e}")
                    results.append({
                        "name": new_name if 'new_name' in locals() else f"Row {i+2}",
                        "id": None,
                        "shared_with": "",
                        "status": "error",
                        "error": str(e)
                    })
                    
            self.finished.emit(results)
            
        except Exception as e:
            self.error.emit(str(e))


class DataDrivenTemplateWidget(QWidget):
    """
    数据驱动的模板生成器 (Mail Merge) 面板
    """
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self._headers = []
        self._results = []  # 保存结果供批量复制使用
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("📑 数据模板引擎 (邮件合并)")
        title.setObjectName("section_title")
        layout.addWidget(title)
        
        desc = QLabel(
            "基于数据总表，为每行数据自动克隆一个模板并填充数据。模板中需使用 <b>{{表头名}}</b> 作为占位符。"
        )
        desc.setStyleSheet("color: gray; margin-bottom: 4px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # ======= 数据源 =======
        data_group = QGroupBox("1. 数据源配置")
        data_layout = QVBoxLayout(data_group)
        
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("🗄️ 数据源链接/ID:"))
        self.source_input = QLineEdit()
        self.source_input.setPlaceholderText("填入包含员工信息/数据记录的 Google Sheet")
        r1.addWidget(self.source_input, 1)
        data_layout.addLayout(r1)
        
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("📋 工作表名称:"))
        self.sheet_name_input = QLineEdit()
        self.sheet_name_input.setPlaceholderText("留空默认第一页")
        self.sheet_name_input.setMaximumWidth(150)
        r2.addWidget(self.sheet_name_input)
        
        r2.addStretch()
        self.btn_fetch_headers = QPushButton("🔄 拉取表头字段")
        self.btn_fetch_headers.clicked.connect(self._fetch_headers)
        r2.addWidget(self.btn_fetch_headers)
        data_layout.addLayout(r2)
        
        layout.addWidget(data_group)

        # ======= 模板配置 =======
        tmpl_group = QGroupBox("2. 模板配置")
        tmpl_layout = QVBoxLayout(tmpl_group)
        
        t1 = QHBoxLayout()
        t1.addWidget(QLabel("📋 模板链接/ID:"))
        self.template_input = QLineEdit()
        self.template_input.setPlaceholderText("填入需要被克隆的模板表格")
        t1.addWidget(self.template_input, 1)
        tmpl_layout.addLayout(t1)
        
        t2 = QHBoxLayout()
        t2.addWidget(QLabel("📁 目标文件夹ID:"))
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("可选，留空则存在 Drive 根目录")
        t2.addWidget(self.folder_input, 1)
        tmpl_layout.addLayout(t2)
        
        layout.addWidget(tmpl_group)

        # ======= 动态规则 =======
        rule_group = QGroupBox("3. 生成规则")
        rule_layout = QVBoxLayout(rule_group)
        
        ru1 = QHBoxLayout()
        ru1.addWidget(QLabel("📝 命名规则:"))
        self.naming_input = QLineEdit("{{姓名}} - 个人报表")
        self.naming_input.setToolTip("使用 {{表头名}} 动态组合新表格的文件名")
        ru1.addWidget(self.naming_input, 1)
        rule_layout.addLayout(ru1)
        
        ru2 = QHBoxLayout()
        ru2.addWidget(QLabel("✉️ 授权指定邮箱列:"))
        self.email_col_combo = QComboBox()
        self.email_col_combo.addItem("无 (不自动授权)")
        self.email_col_combo.setToolTip("选择包含邮箱的列，系统会自动把生成的表格分享给该邮箱")
        ru2.addWidget(self.email_col_combo)
        
        ru2.addWidget(QLabel("  角色:"))
        self.role_combo = QComboBox()
        self.role_combo.addItems(["reader", "writer", "commenter"])
        ru2.addWidget(self.role_combo)
        ru2.addStretch()
        rule_layout.addLayout(ru2)
        
        layout.addWidget(rule_group)

        # ======= 执行 =======
        action_layout = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        action_layout.addWidget(self.progress, 1)
        
        self.status_label = QLabel("准备就绪")
        action_layout.addWidget(self.status_label)
        
        self.btn_start = QPushButton("🚀 开始批量生成")
        self.btn_start.setObjectName("primary_btn")
        self.btn_start.setMinimumHeight(40)
        self.btn_start.clicked.connect(self._start_engine)
        action_layout.addWidget(self.btn_start)

        # 批量复制按钮
        self.copy_btn = QPushButton("📋 批量复制")
        self.copy_btn.setToolTip("复制创建结果中的名称、ID 或链接到剪贴板")
        self.copy_btn.setEnabled(False)
        self.copy_btn.setMinimumHeight(40)
        copy_menu = QMenu(self)
        copy_menu.addAction("📝 复制全部名称", self._copy_names)
        copy_menu.addAction("🔑 复制全部 ID", self._copy_ids)
        copy_menu.addAction("🔗 复制全部链接", self._copy_links)
        copy_menu.addSeparator()
        copy_menu.addAction("📊 复制全部（名称 + ID + 链接）", self._copy_all)
        self.copy_btn.setMenu(copy_menu)
        action_layout.addWidget(self.copy_btn)
        
        layout.addLayout(action_layout)

        # ======= 结果展示 =======
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["生成文件名称", "文件 ID", "链接", "授权分享", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        # 单击单元格即可复制内容
        self.table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self.table, 1)

    def _fetch_headers(self):
        """拉取数据源表头以填充下拉框"""
        from ui.batch_backup_widget import extract_spreadsheet_id
        
        source_raw = self.source_input.text().strip()
        source_id = extract_spreadsheet_id(source_raw)
        
        if not source_id:
            QMessageBox.warning(self, "提示", "请输入有效的数据源链接/ID")
            return
            
        self.btn_fetch_headers.setEnabled(False)
        self.btn_fetch_headers.setText("⏳ 拉取中...")
        
        try:
            service = SheetService(source_id)
            sheet_name = self.sheet_name_input.text().strip() or None
            
            # 读取第一行
            range_name = f"'{sheet_name}'!1:1" if sheet_name else "1:1"
            data = service.read_data(range_name)
            
            if data and len(data) > 0:
                self._headers = [str(h).strip() for h in data[0] if str(h).strip()]
                self.email_col_combo.clear()
                self.email_col_combo.addItem("无 (不自动授权)")
                self.email_col_combo.addItems(self._headers)
                
                # 尝试自动选中可能的邮箱列
                for i, h in enumerate(self._headers):
                    if "邮箱" in h or "email" in h.lower():
                        self.email_col_combo.setCurrentIndex(i + 1)
                        break
                        
                QMessageBox.information(self, "成功", f"拉取到 {len(self._headers)} 个表头字段，您可以在命名规则中使用 {{{{字段名}}}}。")
            else:
                QMessageBox.warning(self, "警告", "未能读取到表头数据，请检查表格是否为空。")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"拉取表头失败:\n{e}")
            
        finally:
            self.btn_fetch_headers.setEnabled(True)
            self.btn_fetch_headers.setText("🔄 拉取表头字段")

    def _start_engine(self):
        from ui.batch_backup_widget import extract_spreadsheet_id
        
        source_id = extract_spreadsheet_id(self.source_input.text().strip())
        template_id = extract_spreadsheet_id(self.template_input.text().strip())
        
        if not source_id or not template_id:
            QMessageBox.warning(self, "提示", "请正确填写数据源和模板的链接/ID。")
            return
            
        name_tmpl = self.naming_input.text().strip()
        if not name_tmpl:
            QMessageBox.warning(self, "提示", "请填写命名规则。")
            return
            
        sheet_name = self.sheet_name_input.text().strip()
        folder_id = self.folder_input.text().strip()
        
        email_col = None
        if self.email_col_combo.currentIndex() > 0:
            email_col = self.email_col_combo.currentText()
            
        role = self.role_combo.currentText()
        
        reply = QMessageBox.question(
            self, "确认生成",
            "该操作将基于数据源行数，批量创建大量表格。可能会耗费一定时间。\n是否继续执行？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_start.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.table.setRowCount(0)
        self.status_label.setText("🚀 引擎启动中...")
        
        self._worker = TemplateEngineWorker(
            source_id, sheet_name, template_id, name_tmpl, email_col, role, folder_id
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, val, total, msg):
        self.progress.setMaximum(total)
        self.progress.setValue(val)
        self.status_label.setText(msg)

    def _on_finished(self, results):
        self.progress.setVisible(False)
        self.btn_start.setEnabled(True)
        self._results = results
        
        self.table.setRowCount(len(results))
        success_count = 0
        for i, res in enumerate(results):
            # 名称
            self.table.setItem(i, 0, QTableWidgetItem(res.get("name", "")))
            # ID
            sheet_id = res.get("id", "") or ""
            self.table.setItem(i, 1, QTableWidgetItem(sheet_id))
            # 链接
            link = _make_sheet_url(sheet_id)
            link_item = QTableWidgetItem(link)
            link_item.setToolTip("单击复制链接")
            if link:
                link_item.setForeground(QColor("#4A90D9"))
            self.table.setItem(i, 2, link_item)
            # 授权分享
            self.table.setItem(i, 3, QTableWidgetItem(res.get("shared_with", "未分享")))
            # 状态
            status = "✅ 成功" if res["status"] == "success" else f"❌ {res.get('error', '')}"
            self.table.setItem(i, 4, QTableWidgetItem(status))
            if res["status"] == "success":
                success_count += 1
                
        self.status_label.setText(f"✅ 执行完成！成功创建 {success_count}/{len(results)} 份报表。")
        self.copy_btn.setEnabled(bool(results))
        QMessageBox.information(self, "任务完成", f"批量生成完毕。\n成功: {success_count}\n失败: {len(results)-success_count}")

    def _on_error(self, err):
        self.progress.setVisible(False)
        self.btn_start.setEnabled(True)
        self.status_label.setText("❌ 引擎异常")
        QMessageBox.critical(self, "错误", f"发生严重异常，任务中止:\n{err}")

    # ========== 复制功能 ==========

    def _on_cell_clicked(self, row, col):
        """单击单元格时将内容复制到剪贴板"""
        item = self.table.item(row, col)
        if item and item.text():
            QApplication.clipboard().setText(item.text())
            self.status_label.setText(f"📋 已复制: {item.text()[:60]}{'…' if len(item.text()) > 60 else ''}")

    def _get_success_results(self):
        """获取成功的结果列表"""
        return [r for r in self._results if r.get("status") == "success" and r.get("id")]

    def _copy_names(self):
        """复制全部表格名称"""
        items = self._get_success_results()
        if not items:
            self.status_label.setText("⚠️ 没有可复制的成功结果")
            return
        text = "\n".join(r.get("name", "") for r in items)
        QApplication.clipboard().setText(text)
        self.status_label.setText(f"📋 已复制 {len(items)} 个表格名称")

    def _copy_ids(self):
        """复制全部表格 ID"""
        items = self._get_success_results()
        if not items:
            self.status_label.setText("⚠️ 没有可复制的成功结果")
            return
        text = "\n".join(r.get("id", "") for r in items)
        QApplication.clipboard().setText(text)
        self.status_label.setText(f"📋 已复制 {len(items)} 个表格 ID")

    def _copy_links(self):
        """复制全部表格链接"""
        items = self._get_success_results()
        if not items:
            self.status_label.setText("⚠️ 没有可复制的成功结果")
            return
        text = "\n".join(_make_sheet_url(r.get("id", "")) for r in items)
        QApplication.clipboard().setText(text)
        self.status_label.setText(f"📋 已复制 {len(items)} 个表格链接")

    def _copy_all(self):
        """复制全部信息（名称 + ID + 链接，以制表符分隔，可直接粘贴到表格）"""
        items = self._get_success_results()
        if not items:
            self.status_label.setText("⚠️ 没有可复制的成功结果")
            return
        lines = ["名称\tID\t链接"]  # 表头
        for r in items:
            name = r.get("name", "")
            sid = r.get("id", "")
            link = _make_sheet_url(sid)
            lines.append(f"{name}\t{sid}\t{link}")
        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
        self.status_label.setText(f"📋 已复制 {len(items)} 条完整信息（可粘贴到表格）")
