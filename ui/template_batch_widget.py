# 模板批量创建 UI 组件 — 包含两个功能标签页：
# 1. 批量创建新表格：从一个模板表格批量生成多个新表格
# 2. 批量复制工作表：将工作表复制到多个已有表格中并重命名
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar,
    QApplication, QMenu, QMessageBox, QTabWidget,
    QComboBox, QGroupBox
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QColor

logger = logging.getLogger("sheets_toolkit.ui.template_batch")


# 根据表格 ID 生成 Google Sheets 链接
def _make_sheet_url(sheet_id):
    """根据表格 ID 生成 Google Sheets 链接"""
    if not sheet_id:
        return ""
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"


# ================================================================
# Worker 线程：批量创建新表格
# ================================================================

class TemplateBatchWorker(QThread):
    """模板批量创建工作线程"""
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, template_id, names, folder_id):
        super().__init__()
        self.template_id = template_id
        self.names = names
        self.folder_id = folder_id

    def run(self):
        try:
            from services.sheet_service import SheetService
            results = SheetService.batch_create_from_template(
                self.template_id, self.names,
                self.folder_id or None,
                progress_callback=self._on_progress
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, c, t, m):
        self.progress.emit(c, t, m)


# ================================================================
# Worker 线程：批量复制工作表到已有表格
# ================================================================

class CopySheetWorker(QThread):
    """批量复制工作表到多个目标表格的工作线程"""
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, source_sid, sheet_name, targets):
        super().__init__()
        self.source_sid = source_sid
        self.sheet_name = sheet_name
        self.targets = targets

    def run(self):
        try:
            from services.sheet_service import SheetService
            results = SheetService.batch_copy_sheet_to_targets(
                self.source_sid, self.sheet_name, self.targets,
                progress_callback=self._on_progress
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, c, t, m):
        self.progress.emit(c, t, m)


# ================================================================
# 主面板：双 Tab 布局
# ================================================================

class TemplateBatchWidget(QWidget):
    """模板批量面板 — 包含"批量创建新表格"和"批量复制工作表"两个功能"""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._worker = None
        self._copy_worker = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        title = QLabel("📑 模板批量")
        title.setObjectName("section_title")
        layout.addWidget(title)

        # 双 Tab 布局
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_create_tab(), "📄 模板克隆")
        self.tabs.addTab(self._build_copy_tab(), "📋 工作表分发")
        layout.addWidget(self.tabs)

    # ================================================================
    # Tab 1: 批量创建新表格（原有功能）
    # ================================================================

    def _build_create_tab(self):
        """构建"批量创建新表格"标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(8)

        help_label = QLabel(
            "选择一个模板表格，一键基于模板批量生成多个新表格。\n"
            "新表格将保留模板的所有格式、公式和数据。"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        # 模板 ID
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("📋 模板表格 ID/链接："))
        self.template_input = QLineEdit()
        self.template_input.setPlaceholderText("输入模板表格的 ID 或链接")
        r1.addWidget(self.template_input)
        layout.addLayout(r1)

        # 目标文件夹
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("📁 目标文件夹 ID（可选）："))
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("留空则创建在 My Drive 根目录")
        r2.addWidget(self.folder_input)
        layout.addLayout(r2)

        # 新表格名称
        layout.addWidget(QLabel("📝 新表格名称（每行一个）："))
        self.names_input = ClearableTextEdit()
        self.names_input.setPlaceholderText(
            "输入要创建的新表格名称，每行一个\n"
            "例如：\n"
            "一月销售报表\n"
            "二月销售报表\n"
            "三月销售报表"
        )
        self.names_input.setMaximumHeight(120)
        layout.addWidget(self.names_input)

        # 按钮
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("🚀 批量创建")
        self.start_btn.clicked.connect(self.start_create)
        btn_row.addWidget(self.start_btn)

        btn_row.addStretch()

        # 批量复制按钮
        self.copy_btn = QPushButton("📋 批量复制")
        self.copy_btn.setToolTip("复制创建结果中的名称、ID 或链接到剪贴板")
        self.copy_btn.setEnabled(False)
        copy_menu = QMenu(self)
        copy_menu.addAction("📝 复制全部名称", self._copy_names)
        copy_menu.addAction("🔑 复制全部 ID", self._copy_ids)
        copy_menu.addAction("🔗 复制全部链接", self._copy_links)
        copy_menu.addSeparator()
        copy_menu.addAction("📊 复制全部（名称 + ID + 链接）", self._copy_all)
        self.copy_btn.setMenu(copy_menu)
        btn_row.addWidget(self.copy_btn)

        layout.addLayout(btn_row)

        # 进度
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # 结果
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(4)
        self.result_table.setHorizontalHeaderLabels(["表格名称", "Spreadsheet ID", "链接", "状态"])
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.result_table.setColumnWidth(3, 50)
        # 单击单元格即可复制内容
        self.result_table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self.result_table)

        # 保存结果供批量复制使用
        self._results = []

        return tab

    # ================================================================
    # Tab 2: 批量复制工作表到已有表格（新功能）
    # ================================================================

    def _build_copy_tab(self):
        """构建"批量复制工作表到已有表格"标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(8)

        help_label = QLabel(
            "将源表格中的某个工作表（sheet tab）同时复制到多个已有的目标表格中，"
            "并可为每个目标中的新工作表指定名称。\n"
            "例如：把 Sheet1 同时复制到表格 A/B/C 中，分别命名为 Sheet1_A, Sheet1_B, Sheet1_C。"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        # === 源表格配置 ===
        source_group = QGroupBox("📄 源表格配置")
        source_layout = QVBoxLayout(source_group)

        s1 = QHBoxLayout()
        s1.addWidget(QLabel("📄 源表格 ID/链接："))
        self.cs_source_input = QLineEdit()
        self.cs_source_input.setPlaceholderText("输入包含要复制工作表的源表格 ID 或链接")
        s1.addWidget(self.cs_source_input, 1)
        self.cs_refresh_btn = QPushButton("🔄 刷新工作表")
        self.cs_refresh_btn.clicked.connect(self._cs_load_sheets)
        s1.addWidget(self.cs_refresh_btn)
        source_layout.addLayout(s1)

        s2 = QHBoxLayout()
        s2.addWidget(QLabel("📋 选择工作表："))
        self.cs_sheet_combo = QComboBox()
        self.cs_sheet_combo.setMinimumWidth(200)
        self.cs_sheet_combo.setPlaceholderText("请先刷新工作表列表")
        s2.addWidget(self.cs_sheet_combo, 1)
        s2.addStretch()
        source_layout.addLayout(s2)

        layout.addWidget(source_group)

        # === 目标配置 ===
        target_group = QGroupBox("🎯 目标表格配置")
        target_layout = QVBoxLayout(target_group)

        target_layout.addWidget(QLabel(
            "📝 每行一个目标，格式：<b>目标表格ID或链接 | 新工作表名称</b>\n"
            "如果不指定新名称（省略 | 后面的部分），则使用源工作表的原始名称。"
        ))
        self.cs_targets_input = ClearableTextEdit()
        self.cs_targets_input.setPlaceholderText(
            "每行一个目标，格式：目标表格ID或链接 | 新工作表名称\n"
            "例如：\n"
            "https://docs.google.com/spreadsheets/d/abc123/edit | Sheet1_客户A\n"
            "def456 | Sheet1_客户B\n"
            "ghi789 | Sheet1_客户C\n\n"
            "也可以只填 ID/链接（不指定名称）：\n"
            "abc123\n"
            "def456"
        )
        self.cs_targets_input.setMaximumHeight(150)
        target_layout.addWidget(self.cs_targets_input)

        layout.addWidget(target_group)

        # === 操作按钮 ===
        btn_row = QHBoxLayout()
        self.cs_start_btn = QPushButton("🚀 开始批量复制")
        self.cs_start_btn.setObjectName("primary_btn")
        self.cs_start_btn.clicked.connect(self._cs_start)
        btn_row.addWidget(self.cs_start_btn)

        btn_row.addStretch()

        # 批量复制结果按钮
        self.cs_copy_btn = QPushButton("📋 批量复制")
        self.cs_copy_btn.setToolTip("复制结果中的表格名称、ID 或链接到剪贴板")
        self.cs_copy_btn.setEnabled(False)
        cs_copy_menu = QMenu(self)
        cs_copy_menu.addAction("📝 复制目标表格名称", self._cs_copy_names)
        cs_copy_menu.addAction("🔑 复制目标表格 ID", self._cs_copy_ids)
        cs_copy_menu.addAction("🔗 复制目标表格链接", self._cs_copy_links)
        cs_copy_menu.addSeparator()
        cs_copy_menu.addAction("📊 复制全部（名称 + ID + 链接 + 工作表名）", self._cs_copy_all)
        self.cs_copy_btn.setMenu(cs_copy_menu)
        btn_row.addWidget(self.cs_copy_btn)

        layout.addLayout(btn_row)

        # === 进度 ===
        self.cs_progress = QProgressBar()
        self.cs_progress.setVisible(False)
        layout.addWidget(self.cs_progress)
        self.cs_status = QLabel("")
        layout.addWidget(self.cs_status)

        # === 结果表格 ===
        self.cs_result_table = QTableWidget()
        self.cs_result_table.setColumnCount(5)
        self.cs_result_table.setHorizontalHeaderLabels([
            "目标表格", "Spreadsheet ID", "链接", "新工作表名", "状态"
        ])
        self.cs_result_table.setAlternatingRowColors(True)
        self.cs_result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        cs_header = self.cs_result_table.horizontalHeader()
        cs_header.setSectionResizeMode(0, QHeaderView.Stretch)
        cs_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        cs_header.setSectionResizeMode(2, QHeaderView.Stretch)
        cs_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        cs_header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.cs_result_table.setColumnWidth(4, 50)
        self.cs_result_table.cellClicked.connect(self._cs_on_cell_clicked)
        layout.addWidget(self.cs_result_table)

        # 保存结果供批量复制使用
        self._cs_results = []

        return tab

    # ================================================================
    # Tab 1: 逻辑方法
    # ================================================================

    def start_create(self):
        from ui.batch_backup_widget import extract_spreadsheet_id

        template_text = self.template_input.text().strip()
        template_id = extract_spreadsheet_id(template_text) if template_text else None
        if not template_id:
            self.status_label.setText("⚠️ 请输入有效的模板表格 ID 或链接")
            return

        names_text = self.names_input.toPlainText().strip()
        names = [n.strip() for n in names_text.split('\n') if n.strip()]
        if not names:
            self.status_label.setText("⚠️ 请输入至少一个新表格名称")
            return

        folder_id = self.folder_input.text().strip()

        self.start_btn.setEnabled(False)
        self.start_btn.setText("⏳ 创建中...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(names))
        self.progress_bar.setValue(0)
        self.result_table.setRowCount(0)

        self._log(f"🚀 从模板创建 {len(names)} 个表格")

        self._worker = TemplateBatchWorker(template_id, names, folder_id)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, c, t, m):
        self.progress_bar.setValue(c)
        self.status_label.setText(m)

    def _on_finished(self, results):
        self._results = results
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.progress_bar.setVisible(False)
        self.result_table.setRowCount(len(results))
        for i, r in enumerate(results):
            # 名称
            self.result_table.setItem(i, 0, QTableWidgetItem(r.get("name", "")))
            # ID
            sheet_id = r.get("id", "") or ""
            self.result_table.setItem(i, 1, QTableWidgetItem(sheet_id))
            # 链接
            link = _make_sheet_url(sheet_id)
            link_item = QTableWidgetItem(link)
            link_item.setToolTip("单击复制链接")
            if link:
                link_item.setForeground(QColor("#4A90D9"))
            self.result_table.setItem(i, 2, link_item)
            # 状态
            status = "✅" if r["status"] == "success" else "❌"
            item = QTableWidgetItem(status)
            if r["status"] == "error":
                item.setToolTip(r.get("error", ""))
            self.result_table.setItem(i, 3, item)

        s = sum(1 for r in results if r["status"] == "success")
        msg = f"✅ 完成: {s}/{len(results)} 个表格创建成功"
        self.status_label.setText(msg)
        self._log(msg)
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 批量创建")
        self.copy_btn.setEnabled(bool(results))
        self._worker = None

    def _on_error(self, msg):
        self.status_label.setText(f"❌ {msg}")
        self._log(f"❌ 批量创建失败: {msg}")
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 批量创建")
        self.progress_bar.setVisible(False)
        self._results = []
        self._worker = None

    # ================================================================
    # Tab 2: 逻辑方法
    # ================================================================

    def _cs_load_sheets(self):
        """刷新源表格的工作表列表"""
        from ui.batch_backup_widget import extract_spreadsheet_id

        raw = self.cs_source_input.text().strip()
        source_id = extract_spreadsheet_id(raw) if raw else None
        if not source_id:
            QMessageBox.warning(self, "提示", "请输入有效的源表格 ID 或链接")
            return

        self.cs_refresh_btn.setEnabled(False)
        self.cs_refresh_btn.setText("⏳ 加载中...")

        try:
            from services.sheet_service import SheetService
            service = SheetService(source_id)
            sheets = service.list_sheets()
            self.cs_sheet_combo.clear()
            self.cs_sheet_combo.addItems(sheets)
            self.cs_status.setText(f"✅ 已加载 {len(sheets)} 个工作表")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载工作表失败:\n{e}")
        finally:
            self.cs_refresh_btn.setEnabled(True)
            self.cs_refresh_btn.setText("🔄 刷新工作表")

    def _cs_parse_targets(self):
        """解析目标配置文本，返回 targets 列表"""
        from ui.batch_backup_widget import extract_spreadsheet_id

        text = self.cs_targets_input.toPlainText().strip()
        if not text:
            return []

        targets = []
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue

            # 支持 | 或 \t 分隔
            if '|' in line:
                parts = line.split('|', 1)
            elif '\t' in line:
                parts = line.split('\t', 1)
            else:
                parts = [line]

            raw_id = parts[0].strip()
            new_name = parts[1].strip() if len(parts) > 1 else ""

            dest_id = extract_spreadsheet_id(raw_id) if raw_id else None
            if dest_id:
                targets.append({"dest_id": dest_id, "new_name": new_name})

        return targets

    def _cs_start(self):
        """开始批量复制工作表"""
        from ui.batch_backup_widget import extract_spreadsheet_id

        # 验证源表格
        raw = self.cs_source_input.text().strip()
        source_id = extract_spreadsheet_id(raw) if raw else None
        if not source_id:
            self.cs_status.setText("⚠️ 请输入有效的源表格 ID 或链接")
            return

        # 验证工作表选择
        sheet_name = self.cs_sheet_combo.currentText()
        if not sheet_name:
            self.cs_status.setText("⚠️ 请先刷新并选择要复制的工作表")
            return

        # 验证目标配置
        targets = self._cs_parse_targets()
        if not targets:
            self.cs_status.setText("⚠️ 请输入至少一个目标表格")
            return

        # 确认
        reply = QMessageBox.question(
            self, "确认批量复制",
            f"将工作表 「{sheet_name}」 复制到 {len(targets)} 个目标表格中。\n是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 开始执行
        self.cs_start_btn.setEnabled(False)
        self.cs_start_btn.setText("⏳ 复制中...")
        self.cs_progress.setVisible(True)
        self.cs_progress.setMaximum(len(targets))
        self.cs_progress.setValue(0)
        self.cs_result_table.setRowCount(0)

        self._log(f"🚀 开始将 '{sheet_name}' 复制到 {len(targets)} 个目标表格")

        self._copy_worker = CopySheetWorker(source_id, sheet_name, targets)
        self._copy_worker.progress.connect(self._cs_on_progress)
        self._copy_worker.finished.connect(self._cs_on_finished)
        self._copy_worker.error.connect(self._cs_on_error)
        self._copy_worker.start()

    def _cs_on_progress(self, c, t, m):
        self.cs_progress.setValue(c)
        self.cs_status.setText(m)

    def _cs_on_finished(self, results):
        self._cs_results = results
        self.cs_progress.setValue(self.cs_progress.maximum())
        self.cs_progress.setVisible(False)
        self.cs_result_table.setRowCount(len(results))

        for i, r in enumerate(results):
            # 目标表格名称
            self.cs_result_table.setItem(i, 0, QTableWidgetItem(r.get("dest_title", "")))
            # 目标表格 ID
            dest_id = r.get("dest_id", "")
            self.cs_result_table.setItem(i, 1, QTableWidgetItem(dest_id))
            # 链接
            link = _make_sheet_url(dest_id)
            link_item = QTableWidgetItem(link)
            link_item.setToolTip("单击复制链接")
            if link:
                link_item.setForeground(QColor("#4A90D9"))
            self.cs_result_table.setItem(i, 2, link_item)
            # 新工作表名
            self.cs_result_table.setItem(i, 3, QTableWidgetItem(r.get("new_sheet_name", "")))
            # 状态
            status = "✅" if r["status"] == "success" else "❌"
            status_item = QTableWidgetItem(status)
            if r["status"] == "error":
                status_item.setToolTip(r.get("error", ""))
            self.cs_result_table.setItem(i, 4, status_item)

        s = sum(1 for r in results if r["status"] == "success")
        msg = f"✅ 完成: {s}/{len(results)} 个目标表格复制成功"
        self.cs_status.setText(msg)
        self._log(msg)
        self.cs_start_btn.setEnabled(True)
        self.cs_start_btn.setText("🚀 开始批量复制")
        self.cs_copy_btn.setEnabled(bool(results))
        self._copy_worker = None

    def _cs_on_error(self, msg):
        self.cs_status.setText(f"❌ {msg}")
        self._log(f"❌ 批量复制工作表失败: {msg}")
        self.cs_start_btn.setEnabled(True)
        self.cs_start_btn.setText("🚀 开始批量复制")
        self.cs_progress.setVisible(False)
        self._cs_results = []
        self._copy_worker = None

    # ================================================================
    # 公共日志方法
    # ================================================================

    def _log(self, text):
        if self.controller and self.controller.view:
            self.controller.view.log(text)

    # ================================================================
    # Tab 1: 复制功能
    # ================================================================

    def _on_cell_clicked(self, row, col):
        """单击单元格时将内容复制到剪贴板"""
        item = self.result_table.item(row, col)
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

    # ================================================================
    # Tab 2: 复制功能
    # ================================================================

    def _cs_on_cell_clicked(self, row, col):
        """单击 Tab2 结果表格单元格时将内容复制到剪贴板"""
        item = self.cs_result_table.item(row, col)
        if item and item.text():
            QApplication.clipboard().setText(item.text())
            self.cs_status.setText(f"📋 已复制: {item.text()[:60]}{'…' if len(item.text()) > 60 else ''}")

    def _cs_get_success_results(self):
        """获取 Tab2 中成功的结果列表"""
        return [r for r in self._cs_results if r.get("status") == "success"]

    def _cs_copy_names(self):
        """复制目标表格名称"""
        items = self._cs_get_success_results()
        if not items:
            self.cs_status.setText("⚠️ 没有可复制的成功结果")
            return
        text = "\n".join(r.get("dest_title", "") for r in items)
        QApplication.clipboard().setText(text)
        self.cs_status.setText(f"📋 已复制 {len(items)} 个目标表格名称")

    def _cs_copy_ids(self):
        """复制目标表格 ID"""
        items = self._cs_get_success_results()
        if not items:
            self.cs_status.setText("⚠️ 没有可复制的成功结果")
            return
        text = "\n".join(r.get("dest_id", "") for r in items)
        QApplication.clipboard().setText(text)
        self.cs_status.setText(f"📋 已复制 {len(items)} 个目标表格 ID")

    def _cs_copy_links(self):
        """复制目标表格链接"""
        items = self._cs_get_success_results()
        if not items:
            self.cs_status.setText("⚠️ 没有可复制的成功结果")
            return
        text = "\n".join(_make_sheet_url(r.get("dest_id", "")) for r in items)
        QApplication.clipboard().setText(text)
        self.cs_status.setText(f"📋 已复制 {len(items)} 个目标表格链接")

    def _cs_copy_all(self):
        """复制全部信息（名称 + ID + 链接 + 工作表名，以制表符分隔）"""
        items = self._cs_get_success_results()
        if not items:
            self.cs_status.setText("⚠️ 没有可复制的成功结果")
            return
        lines = ["目标表格名称\t目标表格ID\t链接\t新工作表名"]  # 表头
        for r in items:
            name = r.get("dest_title", "")
            sid = r.get("dest_id", "")
            link = _make_sheet_url(sid)
            sheet_name = r.get("new_sheet_name", "")
            lines.append(f"{name}\t{sid}\t{link}\t{sheet_name}")
        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
        self.cs_status.setText(f"📋 已复制 {len(items)} 条完整信息（可粘贴到表格）")
