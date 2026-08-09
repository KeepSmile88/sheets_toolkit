# 主窗口 — 应用程序的入口界面
# 所有业务操作通过 Controller 执行，不直接调用 modules
import os
import logging
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QLineEdit, QComboBox, QFileDialog, QStackedWidget,
    QSplitter, QListWidget, QStatusBar, QMenuBar, QMenu, QProgressBar,
    QSizePolicy
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

from ui.controller import SheetController
from ui.task_form import TaskForm
from ui.task_queue_view import TaskQueueView
from ui.data_preview import DataPreviewWidget
from ui.history_view import HistoryView
from ui.batch_backup_widget import BatchBackupWidget
from ui.clean_rows_widget import CleanRowsWidget
from ui.batch_formula_widget import BatchFormulaWidget
from ui.batch_note_widget import BatchNoteWidget
from ui.formula_library_widget import FormulaLibraryWidget
from ui.health_check_widget import HealthCheckWidget
from ui.template_batch_widget import TemplateBatchWidget
from ui.batch_format_widget import BatchFormatWidget
from ui.dashboard_widget import DashboardWidget
from ui.batch_validation_widget import BatchValidationWidget
from ui.color_scheme_widget import ColorSchemeWidget
from ui.spreadsheet_library_widget import SpreadsheetLibraryDialog
from ui.mini_library_widget import MiniLibraryWindow
from ui.drive_folder_widget import DriveFolderWidget
from ui.data_consolidation_widget import DataConsolidationWidget
from ui.global_search_widget import GlobalSearchWidget
from ui.data_driven_template_widget import DataDrivenTemplateWidget
from ui.batch_delete_sheets_widget import BatchDeleteSheetsWidget
from ui.table_utils_widget import TableUtilsWidget
from ui.ui_utils import info, error, confirm

from services.command.export_command import ExportCommand
from services.command.read_command import ReadCommand
from services.command.backup_command import BackupCommand
from services.command.permission_command import (
    InviteEditorCommand, RemoveAllPermissionsCommand
)

logger = logging.getLogger("sheets_toolkit.ui.main_window")


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self, theme_manager=None, role="admin", username=""):
        super().__init__()
        title_suffix = f" - {role} [{username}]"
        self.setWindowTitle(f"📊 Google Sheets 工具箱{title_suffix}")
        self.setMinimumSize(1100, 750)
        self.theme_manager = theme_manager
        self.role = role
        self.username = username
        self.controller = SheetController(self)
        self._mini_library = None  # 迷你表格库窗口单例
        self.setup_menu()
        self.setup_ui()
        self.setup_statusbar()

    # ========================
    # 账户方法
    # ========================
    def open_change_password(self):
        from ui.change_password_dialog import ChangePasswordDialog
        dlg = ChangePasswordDialog(self.username, parent=self)
        dlg.exec()

    # ========================
    # 菜单栏
    # ========================

    def setup_menu(self):
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("📁 文件")

        connect_action = QAction("🔗 连接表格", self)
        connect_action.triggered.connect(self.connect_sheet)
        file_menu.addAction(connect_action)

        export_action = QAction("📤 导出 Excel", self)
        export_action.triggered.connect(self.export_excel)
        file_menu.addAction(export_action)

        backup_action = QAction("💾 备份表格", self)
        backup_action.triggered.connect(self.backup_sheet)
        file_menu.addAction(backup_action)

        file_menu.addSeparator()

        quit_action = QAction("❌ 退出", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # 编辑菜单
        edit_menu = menubar.addMenu("✏️ 编辑")

        undo_action = QAction("↩️ 撤销", self)
        undo_action.triggered.connect(lambda: self.controller.undo_last())
        edit_menu.addAction(undo_action)

        # 视图菜单
        view_menu = menubar.addMenu("👁 视图")

        if self.theme_manager:
            theme_action = QAction("🌓 切换主题", self)
            theme_action.triggered.connect(self.toggle_theme)
            view_menu.addAction(theme_action)
            
        # 账户菜单
        account_menu = menubar.addMenu("👤 账户")
        
        change_pwd_action = QAction("🔑 修改密码...", self)
        change_pwd_action.triggered.connect(self.open_change_password)
        account_menu.addAction(change_pwd_action)

        # 认证菜单
        auth_menu = menubar.addMenu("🔑 认证")

        select_creds_action = QAction("📂 选择凭据文件...", self)
        select_creds_action.triggered.connect(self.select_credentials_file)
        auth_menu.addAction(select_creds_action)

        auth_status_action = QAction("ℹ️ 查看认证状态", self)
        auth_status_action.triggered.connect(self.show_auth_status)
        auth_menu.addAction(auth_status_action)

        auth_menu.addSeparator()

        logout_action = QAction("🚪 注销", self)
        logout_action.triggered.connect(self.logout_auth)
        auth_menu.addAction(logout_action)

        # 表格库菜单
        lib_menu = menubar.addMenu("📂 表格库")

        lib_action = QAction("📂 表格库管理器", self)
        lib_action.triggered.connect(self.open_sheet_library)
        lib_menu.addAction(lib_action)

        mini_lib_action = QAction("📌 迷你浮动窗口", self)
        mini_lib_action.triggered.connect(self.open_mini_library)
        lib_menu.addAction(mini_lib_action)

    # ========================
    # 主界面布局
    # ========================

    def setup_ui(self):
        # 顶部参数输入区
        self.input_id = QLineEdit()
        self.input_id.setPlaceholderText("输入 Google Sheet ID...")
        self.sheet_list = QComboBox()
        self.range_input = QLineEdit("A1:B10")
        self.range_input.setPlaceholderText("如 A1:B10")
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("搜索关键词...")

        # 加载最近使用的 Spreadsheet ID
        try:
            from core.config import AppConfig
            config = AppConfig()
            default_id = config.get("default_spreadsheet_id", "")
            if default_id:
                self.input_id.setText(default_id)
        except Exception:
            pass

        # 日志区
        self.log_box = ClearableTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(60)

        # 连接日志信号
        from core.logger import get_log_emitter
        get_log_emitter().log_signal.connect(self.log)

        # 参数面板
        form = QVBoxLayout()
        form.setSpacing(6)

        form.addWidget(QLabel("📄 Google Sheet ID"))
        form.addWidget(self.input_id)

        connect_btn = QPushButton("🔗 连接")
        connect_btn.clicked.connect(self.connect_sheet)
        form.addWidget(connect_btn)

        form.addWidget(QLabel("📋 工作表"))
        form.addWidget(self.sheet_list)
        form.addWidget(QLabel("📍 区域范围"))
        form.addWidget(self.range_input)
        form.addWidget(QLabel("🔍 搜索关键词"))
        form.addWidget(self.keyword_input)
        form.addStretch()

        sidebar = QWidget()
        sidebar.setLayout(form)
        sidebar.setMaximumWidth(260)
        sidebar.setMinimumWidth(200)

        # 左侧导航菜单与页面映射
        pages = [
            ("📄 表格结构", self.page_structure),          # 0
            ("📊 数据处理", self.page_data),               # 1
            ("👁 数据预览", self.page_preview),            # 2
            ("🔐 权限协作", self.page_collab),             # 3
            ("⚙️ 自动化", self.page_auto),                 # 4
            ("📦 批量备份", self.page_batch_backup),       # 5
            ("🧹 清理行", self.page_clean_rows),           # 6
            ("📝 批量公式", self.page_batch_formula),       # 7
            ("💬 批量备注", self.page_batch_note),         # 8
            ("📚 公式库", self.page_formula_lib),          # 9
            ("🏥 健康检查", self.page_health_check),       # 10
            ("📑 模板批量", self.page_template_batch),     # 11
            ("🎨 批量格式化", self.page_batch_format),       # 12
            ("📋 仪表盘", self.page_dashboard),            # 13
            ("✅ 数据验证", self.page_validation),         # 14
            ("🎨 配色库", self.page_color_scheme),         # 15
            ("👁‍🗨 单元格监控", self.page_cell_monitor),       # 16
            ("📅 调度任务", self.page_schedule),           # 17
            ("📜 操作历史", self.page_history),            # 18
            ("📂 网盘文件夹", self.page_drive_folder),        # 19
            ("🔗 跨表汇总", self.page_data_consolidation), # 20
            ("🔍 全局搜索", self.page_global_search),        # 21
            ("📑 数据模板引擎", self.page_data_driven_template), # 22
            ("🗑 批量删除", self.page_batch_delete_sheets),  # 23
            ("🛠 表格辅助工具", self.page_table_utils)             # 24
        ]

        if getattr(self, "role", "admin") == "user":
            # 普通用户只保留部分功能
            allowed_pages = ["🔐 权限协作", "📂 网盘文件夹"]
            pages = [p for p in pages if p[0] in allowed_pages]

        self.menu = QListWidget()
        self.stack = QStackedWidget()
        
        self.page_mapping = []
        for i, (title, func) in enumerate(pages):
            self.menu.addItem(title)
            self.stack.addWidget(func())
            self.page_mapping.append(i)

        self.menu.setMaximumWidth(150)
        self.menu.setMinimumWidth(130)
        self.menu.setSpacing(4)
        
        def on_page_switch(index):
            if 0 <= index < len(self.page_mapping):
                self.stack.setCurrentIndex(index)
                
        self.menu.currentRowChanged.connect(on_page_switch)

        # 右侧：功能区 + 日志
        right_split = QSplitter(Qt.Vertical)
        right_split.addWidget(self.stack)
        right_split.addWidget(self.log_box)
        right_split.setStretchFactor(0, 4)
        right_split.setStretchFactor(1, 1)
        right_split.setCollapsible(0, False)  # 防止功能区被折叠导致往上拉时反而变小
        right_split.setCollapsible(1, False)  # 防止日志框被完全折叠
        right_split.setOpaqueResize(False)    # 禁用实时重绘，根除拖拽闪烁
        # 设置日志区域最小高度，防止拉伸时变得过小
        self.log_box.setMinimumHeight(80)
        self.stack.setMinimumHeight(300)

        # 中间内容区：导航 + 功能
        content = QSplitter()
        content.addWidget(self.menu)
        content.addWidget(right_split)

        # 总布局：参数区 + 内容区
        final_layout = QSplitter()
        final_layout.addWidget(sidebar)
        final_layout.addWidget(content)

        self.setCentralWidget(final_layout)
        self.menu.setCurrentRow(0)

    # ========================
    # 状态栏
    # ========================

    def setup_statusbar(self):
        self.statusBar().showMessage("就绪 — 请输入 Sheet ID 并连接")
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress_bar)

        # 持久显示认证用户名（左下角）
        self.user_label = QLabel("🔒 未认证")
        self.user_label.setStyleSheet("color: gray; padding: 0 8px;")
        self.statusBar().addPermanentWidget(self.user_label)

        # 如果已有 token，尝试显示用户
        self._update_auth_label()

    # ========================
    # 功能页面
    # ========================

    def page_structure(self):
        """表格结构页"""
        from ui.structure_widget import StructureWidget
        self.structure_widget = StructureWidget(self.controller)
        return self.structure_widget

    def page_data(self):
        """数据处理页"""
        from ui.data_processing_widget import DataProcessingWidget
        self.data_processing = DataProcessingWidget(self.controller)
        return self.data_processing

    def page_preview(self):
        """数据预览页"""
        self.data_preview = DataPreviewWidget(self.controller)
        return self.data_preview

    def page_collab(self):
        """权限协作页"""
        return self._make_page("🔐 权限协作", [
            ("🔐 打开高级权限管理面板 (当前连接表格)", self.open_permission_manager),
            ("🔗 手动批量输入表格链接进行权限管理", self.open_batch_url_input),
        ])

    def page_auto(self):
        """自动化页"""
        from ui.automation_widget import AutomationWidget
        self.automation_widget = AutomationWidget(self.controller)
        return self.automation_widget

    def page_batch_backup(self):
        """批量备份页"""
        self.batch_backup = BatchBackupWidget(self.controller)
        return self.batch_backup

    def page_clean_rows(self):
        """清理行页"""
        self.clean_rows = CleanRowsWidget(self.controller)
        return self.clean_rows

    def page_batch_formula(self):
        """批量公式页"""
        self.batch_formula = BatchFormulaWidget(self.controller)
        return self.batch_formula

    def page_batch_note(self):
        """批量备注页"""
        self.batch_note = BatchNoteWidget(self.controller)
        return self.batch_note

    def page_formula_lib(self):
        """公式库页"""
        self.formula_lib = FormulaLibraryWidget(self.controller)
        return self.formula_lib

    def page_health_check(self):
        """健康检查页"""
        self.health_check = HealthCheckWidget(self.controller)
        return self.health_check

    def page_template_batch(self):
        """模板批量页"""
        self.template_batch = TemplateBatchWidget(self.controller)
        return self.template_batch

    def page_batch_format(self):
        """批量格式化页"""
        self.batch_format = BatchFormatWidget(self.controller)
        return self.batch_format

    def page_dashboard(self):
        """仪表盘页"""
        self.dashboard = DashboardWidget(self.controller)
        return self.dashboard

    def page_validation(self):
        """数据验证页"""
        self.validation = BatchValidationWidget(self.controller)
        return self.validation

    def page_color_scheme(self):
        """配色库页"""
        self.color_scheme = ColorSchemeWidget(self.controller)
        return self.color_scheme

    def page_cell_monitor(self):
        """单元格监控页"""
        from ui.cell_monitor_widget import CellMonitorWidget
        self.cell_monitor = CellMonitorWidget(self.controller)
        return self.cell_monitor

    def page_schedule(self):
        """调度任务页"""
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        title = QLabel("📅 调度任务")
        title.setObjectName("section_title")
        layout.addWidget(title)

        self.task_view = TaskQueueView(self.controller)
        self.task_form = TaskForm(self.controller, self.task_view, self.log)
        layout.addWidget(self.task_form)
        layout.addWidget(self.task_view)
        return wrap

    def page_history(self):
        """操作历史页"""
        self.history_view = HistoryView(self.controller)
        return self.history_view

    def page_drive_folder(self):
        """网盘文件夹浏览页"""
        from ui.drive_folder_widget import DriveFolderWidget
        self.drive_folder = DriveFolderWidget(self.controller)
        return self.drive_folder

    # ========================
    # 页面构造工具
    # ========================

    def _make_page(self, title_text, items):
        """批量生成功能按钮页"""
        layout = QVBoxLayout()
        title = QLabel(title_text)
        title.setObjectName("section_title")
        layout.addWidget(title)

        for item in items:
            label = item[0]
            func = item[1]
            obj_name = item[2] if len(item) > 2 else None

            btn = QPushButton(label)
            btn.setToolTip(label)
            if obj_name:
                btn.setObjectName(obj_name)
            btn.clicked.connect(lambda *args, f=func: self.safe_exec(f))
            layout.addWidget(btn)

        layout.addStretch()
        wrap = QWidget()
        wrap.setLayout(layout)
        return wrap

    # ========================
    # 业务操作 — 全部通过 Controller 命令执行
    # ========================

    def connect_sheet(self):
        """连接到 Spreadsheet（支持输入链接或 ID）"""
        raw = self.input_id.text().strip()
        if not raw:
            error(self, "错误", "请输入 Google Sheet ID 或链接")
            return

        # 从 URL 中提取 Spreadsheet ID
        from ui.batch_backup_widget import extract_spreadsheet_id
        sid = extract_spreadsheet_id(raw)
        if not sid:
            error(self, "错误", "无法识别有效的 Spreadsheet ID。\n请输入完整链接或纯 ID。")
            return

        # 将提取出的纯 ID 回写到输入框
        if sid != raw:
            self.input_id.setText(sid)
            self.log(f"📋 已从链接中提取 ID: {sid}")

        self.statusBar().showMessage(f"正在连接...")
        self.controller.connect_sheet(sid)

        # 连接成功后显示信息
        if self.controller.is_connected:
            # 连接成功说明认证已完成，更新认证状态标签
            self._update_auth_label()
            try:
                title = self.controller.service.get_spreadsheet_title()
                sheets = self.controller.service.list_sheets()
                self.statusBar().showMessage(f"已连接: {title} ({len(sheets)} 个工作表)")
                self.log(f"📊 表格标题: {title}")
                self.log(f"📋 工作表: {', '.join(sheets)}")
            except Exception:
                self.statusBar().showMessage(f"已连接: {sid[:20]}...")



    def export_excel(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "保存 Excel 文件", "", "Excel (*.xlsx)"
        )
        if filename:
            cmd = ExportCommand(filename)
            self.controller.run_command(cmd)

    def backup_sheet(self):
        cmd = BackupCommand()
        self.controller.run_command(cmd)


    def open_permission_manager(self):
        """调出高级权限协作面板（复用表格库模块）"""
        if not self.controller.is_connected or not self.controller.service:
            error(self, "未连接", "请先在左侧输入表格 ID 并点击「连接」")
            return

        sid = self.controller.service.spreadsheet_id
        try:
            title = self.controller.service.get_spreadsheet_title()
        except:
            title = sid[:20]

        # 组装成 PermissionManagerDialog 能解析的格式
        entries = [{"id": "current", "spreadsheet_id": sid, "name": title}]

        from ui.permission_manager_dialog import PermissionManagerDialog
        dlg = PermissionManagerDialog(entries, parent=self)
        dlg.exec()

    def open_batch_url_input(self):
        """打开批量导入表格链接窗口"""
        from ui.batch_url_input_dialog import BatchUrlInputDialog
        input_dlg = BatchUrlInputDialog(self)
        if input_dlg.exec():
            entries = input_dlg.get_entries()
            if entries:
                from ui.permission_manager_dialog import PermissionManagerDialog
                dlg = PermissionManagerDialog(entries, parent=self)
                dlg.exec()


    # ========================
    # 辅助方法
    # ========================

    def switch_page(self, index):
        if hasattr(self, "page_mapping") and 0 <= index < len(self.page_mapping):
            self.stack.setCurrentIndex(self.page_mapping[index])
        else:
            self.stack.setCurrentIndex(index)

    def update_sheet_list(self, names):
        self.sheet_list.clear()
        self.sheet_list.addItems(names)

    def toggle_theme(self):
        if self.theme_manager:
            new_theme = self.theme_manager.toggle_theme()
            self.statusBar().showMessage(f"已切换到 {'深色' if new_theme == 'dark' else '浅色'} 主题")

    def log(self, text):
        self.log_box.append(str(text))

    def safe_exec(self, func):
        try:
            result = func() if callable(func) else func
            if result:
                self.log(str(result))
        except Exception as e:
            error(self, "错误", str(e))
            logger.error(f"操作执行失败: {e}")

    def _update_auth_label(self):
        """更新状态栏的认证标签，确保显示准确"""
        try:
            from core.auth import AuthManager
            auth = AuthManager()
            if auth.is_authenticated:
                # 已认证且 creds 有效
                display_name = auth.user_email or "已认证"
                self.user_label.setText(f"👤 {display_name}")
                self.user_label.setStyleSheet(
                    "color: #4CAF50; padding: 0 8px; font-weight: bold;"
                )
            elif auth._creds is not None:
                # 有 creds 但可能过期（后续操作会自动刷新）
                display_name = auth.user_email or "已认证 (凭据待刷新)"
                self.user_label.setText(f"👤 {display_name}")
                self.user_label.setStyleSheet(
                    "color: #FF9800; padding: 0 8px; font-weight: bold;"
                )
            elif hasattr(auth, '_token_path') and os.path.exists(auth._token_path):
                # token 文件存在但尚未加载（可能启动时加载失败）
                self.user_label.setText("🔑 已有凭据 (待验证)")
                self.user_label.setStyleSheet(
                    "color: #FF9800; padding: 0 8px;"
                )
            else:
                self.user_label.setText("🔒 未认证")
                self.user_label.setStyleSheet("color: gray; padding: 0 8px;")
        except Exception:
            pass

    # ========================
    # 认证操作
    # ========================

    def select_credentials_file(self):
        """打开文件对话框选择 credentials.json 并认证"""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Google API 凭据文件",
            "", "JSON 文件 (*.json);;所有文件 (*)"
        )
        if not path:
            return

        self.log(f"🔑 已选择凭据文件: {path}")
        self.log("🌐 正在启动浏览器进行 OAuth 认证...")
        self.statusBar().showMessage("正在进行 OAuth 认证...")

        try:
            from core.auth import AuthManager
            auth = AuthManager()
            auth.authenticate_with_file(path)

            if auth.is_authenticated:
                email = auth.user_email
                display_name = email or "已认证"
                msg = f"✅ 认证成功！\n\n当前用户: {email}" if email else "✅ 认证成功！"
                self.log(f"✅ 认证成功: {display_name}")
                self.statusBar().showMessage(f"已认证: {display_name}")

                # 更新持久用户名 QLabel
                if hasattr(self, 'user_label'):
                    self.user_label.setText(f"👤 {display_name}")
                    self.user_label.setStyleSheet(
                        "color: #4CAF50; padding: 0 8px; font-weight: bold;"
                    )

                info(self, "认证成功", msg)
            else:
                self.log("❌ 认证失败")
                self.statusBar().showMessage("认证失败")
                error(self, "认证失败", "OAuth 认证未能完成，请重试。")

        except Exception as e:
            self.log(f"❌ 认证失败: {e}")
            self.statusBar().showMessage("认证失败")
            error(self, "认证失败", str(e))

    def show_auth_status(self):
        """显示当前认证状态"""
        from PySide6.QtWidgets import QMessageBox
        try:
            from core.auth import AuthManager
            auth = AuthManager()
            status = auth.auth_status

            if status["authenticated"]:
                msg = (
                    f"✅ 已认证\n\n"
                    f"👤 用户: {status['email'] or '未知'}\n"
                    f"📂 凭据文件: {status['creds_path']}\n"
                    f"🔒 Token: {'已保存' if status['token_exists'] else '未保存'}"
                )
            else:
                msg = (
                    f"❌ 未认证\n\n"
                    f"📂 凭据文件: {status['creds_path']}\n"
                    f"🔒 Token: {'已保存' if status['token_exists'] else '未保存'}\n\n"
                    "请通过菜单 🔑 认证 → 📂 选择凭据文件 进行认证。"
                )
            QMessageBox.information(self, "认证状态", msg)
        except Exception as e:
            QMessageBox.warning(self, "认证状态", f"获取状态失败: {e}")

    def open_sheet_library(self):
        """打开表格库独立窗口"""
        try:
            from ui.spreadsheet_library_widget import SpreadsheetLibraryDialog
            dialog = SpreadsheetLibraryDialog(self.controller, self)
            dialog.exec_()
            # 关闭后刷新迷你窗口（如果已打开）
            if self._mini_library and self._mini_library.isVisible():
                self._mini_library._refresh()
        except Exception as e:
            error(self, "错误", f"无法打开表格库: {e}")

    def open_mini_library(self):
        """打开表格库迷你浮动窗口（单例）"""
        try:
            if self._mini_library is None:
                self._mini_library = MiniLibraryWindow(self.controller)
            self._mini_library.show()
            self._mini_library.raise_()
            self._mini_library.activateWindow()
            self._mini_library._refresh()
        except Exception as e:
            error(self, "错误", f"无法打开迷你表格库: {e}")

    def logout_auth(self):
        """注销认证"""
        if not confirm(self, "确认注销", "注销后将清除已保存的 Token，需要重新认证。\n确定要注销吗？"):
            return

        try:
            from core.auth import AuthManager
            auth = AuthManager()
            auth.logout()
            self.log("🚪 已注销认证")
            self.statusBar().showMessage("已注销")

            # 重置用户名显示
            if hasattr(self, 'user_label'):
                self.user_label.setText("🔒 未认证")
                self.user_label.setStyleSheet("color: gray; padding: 0 8px;")

            info(self, "已注销", "认证信息已清除。\n下次操作时需要重新选择凭据文件认证。")
        except Exception as e:
            error(self, "注销失败", str(e))

    def closeEvent(self, event):
        """关闭窗口时清理资源"""
        self.controller.shutdown()
        super().closeEvent(event)

    # ========================
    # 新增高级页面
    # ========================

    def page_data_consolidation(self):
        return DataConsolidationWidget(self.controller)

    def page_global_search(self):
        return GlobalSearchWidget(self.controller)

    def page_data_driven_template(self):
        return DataDrivenTemplateWidget(self.controller)

    def page_batch_delete_sheets(self):
        """批量删除页（工作簿 + 子工作表）"""
        self.batch_delete_sheets = BatchDeleteSheetsWidget(self.controller)
        return self.batch_delete_sheets

    def page_table_utils(self):
        """表格辅助工具页"""
        self.table_utils = TableUtilsWidget(self.controller)
        return self.table_utils

