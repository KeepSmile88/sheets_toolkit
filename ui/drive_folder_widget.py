# Drive 文件夹浏览器组件 — 输入文件夹链接后展示所有文件，支持右键修改权限
# 支持用户名过滤（精准/模糊/正则）和双击进入子文件夹递归浏览
import re
import logging
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QMenu, QAbstractItemView, QMessageBox,
    QComboBox, QGroupBox, QCheckBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor

logger = logging.getLogger("sheets_toolkit.ui.drive_folder_widget")


def extract_folder_id(url_or_id):
    """
    从 Google Drive 文件夹链接中提取 folder_id。
    支持格式：
    - https://drive.google.com/drive/folders/<ID>
    - https://drive.google.com/drive/u/0/folders/<ID>
    - https://drive.google.com/drive/u/0/folders/<ID>?...
    - 纯 folder_id 字符串
    """
    if not url_or_id:
        return None
    url_or_id = url_or_id.strip()

    if url_or_id == "/":
        return "root"

    # 尝试从 URL 提取
    match = re.search(r'folders/([a-zA-Z0-9_-]+)', url_or_id)
    if match:
        return match.group(1)

    # 如果看起来像纯 ID（无特殊符号），直接返回
    if re.match(r'^[a-zA-Z0-9_-]+$', url_or_id):
        return url_or_id

    return None


def format_file_size(size_bytes):
    """将字节大小格式化为可读字符串"""
    if size_bytes is None:
        return "—"
    try:
        size = int(size_bytes)
    except (ValueError, TypeError):
        return "—"

    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"


def format_permissions_summary(permissions):
    """将权限列表格式化为简短摘要"""
    if not permissions:
        return "—"

    role_map = {
        "owner": "👑所有者",
        "writer": "✏️编辑",
        "reader": "👁阅读",
        "commenter": "💬评论"
    }

    parts = []
    for p in permissions:
        role = p.get("role", "")
        ptype = p.get("type", "")
        if ptype == "anyone":
            parts.append(f"{role_map.get(role, role)}(所有人)")
        elif ptype == "domain":
            parts.append(f"{role_map.get(role, role)}(域)")
        else:
            email = p.get("emailAddress", "")
            short = email.split("@")[0] if email else p.get("displayName", "?")
            parts.append(f"{role_map.get(role, role)}:{short}")

    # 限制显示数量
    if len(parts) > 3:
        return ", ".join(parts[:3]) + f" +{len(parts) - 3}"
    return ", ".join(parts)


def get_file_icon(mime_type):
    """根据 MIME 类型返回文件图标前缀"""
    mime = mime_type or ""
    if "folder" in mime:
        return "📁"
    elif "spreadsheet" in mime:
        return "📊"
    elif "document" in mime:
        return "📄"
    elif "presentation" in mime:
        return "📽️"
    elif "image" in mime:
        return "🖼️"
    elif "pdf" in mime:
        return "📕"
    elif "video" in mime:
        return "🎬"
    elif "audio" in mime:
        return "🎵"
    elif "zip" in mime or "compressed" in mime or "archive" in mime:
        return "📦"
    return "📎"


def file_matches_filter(file_data, keyword, match_mode, filter_target):
    """
    检查文件是否匹配过滤条件。

    Args:
        file_data: 文件数据字典（含 permissions, name 等）
        keyword: 过滤关键词
        match_mode: 匹配模式 — "精准匹配" / "模糊匹配" / "正则匹配"
        filter_target: 过滤目标 — "按用户名/邮箱" / "按文件名"

    Returns:
        bool: 是否匹配
    """
    if not keyword:
        return True

    targets = []
    
    if filter_target == "按文件名":
        name = file_data.get("name", "")
        if name:
            targets.append(name)
    elif filter_target == "按归属":
        owned = file_data.get("ownedByMe", False)
        owner_str = "我的" if owned else "别人共享"
        targets.append(owner_str)
        targets.append("👤 我的" if owned else "🤝 别人共享")
    else:
        # 按用户名/邮箱
        permissions = file_data.get("permissions", [])
        if not permissions:
            return False
            
        for p in permissions:
            email = p.get("emailAddress", "")
            display_name = p.get("displayName", "")
            if email:
                targets.append(email)
                targets.append(email.split("@")[0])  # 用户名部分
            if display_name:
                targets.append(display_name)

    if not targets:
        return False

    for target in targets:
        if match_mode == "精准匹配":
            if keyword == target:
                return True
        elif match_mode == "模糊匹配":
            if keyword.lower() in target.lower():
                return True
        elif match_mode == "正则匹配":
            try:
                if re.search(keyword, target, re.IGNORECASE):
                    return True
            except re.error:
                # 正则语法错误时退化为模糊匹配
                if keyword.lower() in target.lower():
                    return True

    return False


class DriveFolderFetchWorker(QThread):
    """后台线程 — 异步获取文件夹中的文件列表"""
    progress = Signal(str)
    finished = Signal(str, list)  # (folder_id, 文件列表)
    error = Signal(str)

    def __init__(self, folder_id, recursive=False, include_shared=True, supported_mime_types=None):
        super().__init__()
        self.folder_id = folder_id
        self.recursive = recursive
        self.include_shared = include_shared
        self.supported_mime_types = supported_mime_types

    def run(self):
        try:
            from services.sheet_service import SheetService
            if self.recursive:
                self.progress.emit("⏳ 正在递归遍历所有子文件夹...")
                files = SheetService.list_all_files_with_path(
                    self.folder_id, 
                    self.progress.emit,
                    include_shared=self.include_shared,
                    check_cancelled=self.isInterruptionRequested,
                    supported_mime_types=self.supported_mime_types
                )
            else:
                self.progress.emit("⏳ 正在获取文件夹内容...")
                files = SheetService.list_folder_files(
                    self.folder_id,
                    check_cancelled=self.isInterruptionRequested,
                    supported_mime_types=self.supported_mime_types
                )
            if self.isInterruptionRequested():
                self.error.emit("已取消加载")
                return
            self.finished.emit(self.folder_id, files)
        except Exception as e:
            logger.error(f"获取文件夹内容失败: {e}")
            self.error.emit(str(e))


class DriveFolderWidget(QWidget):
    """
    Google Drive 文件夹浏览器组件。

    输入文件夹链接后以表格展示所有文件信息：
    - 文件名、文件链接、文件权限、修改日期、文件大小
    - 右键点击文件名可打开权限管理对话框
    - 支持用户名过滤（精准/模糊/正则）
    - 双击文件夹可递归进入子目录
    """

    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self._worker = None
        self._files_cache = []  # 缓存当前加载的文件列表（未过滤）
        self._folder_stack = []  # 导航栈：[(folder_id, folder_name), ...]
        self._current_folder_id = None  # 当前浏览的文件夹 ID
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ======= 标题 =======
        title = QLabel("📂 网盘文件夹浏览器")
        title.setObjectName("section_title")
        layout.addWidget(title)

        desc = QLabel(
            "输入 Google Drive 文件夹链接，浏览其中的所有文件。"
            "右键点击文件名可修改访问权限，双击文件夹可进入子目录。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: gray; margin-bottom: 4px;")
        layout.addWidget(desc)

        # ======= 输入区 =======
        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("📎 文件夹链接:"))

        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText(
            "粘贴 Google Drive 文件夹链接或 ID，如 https://drive.google.com/drive/folders/xxxxx"
        )
        self.folder_input.returnPressed.connect(self._on_load_clicked)
        input_row.addWidget(self.folder_input, 1)

        self.load_btn = QPushButton("📂 加载文件夹")
        self.load_btn.clicked.connect(self._toggle_load)
        input_row.addWidget(self.load_btn)

        self.recursive_fetch_check = QCheckBox("递归获取所有表格 (附带路径)")
        self.recursive_fetch_check.setToolTip("开启后，将深入遍历所有子文件夹并只返回表格文件")
        input_row.addWidget(self.recursive_fetch_check)

        self.include_shared_check = QCheckBox("包含'与我共享'")
        self.include_shared_check.setChecked(True)
        self.include_shared_check.setToolTip("开启后，在使用根目录('/')全局检索时，包含别人分享给您的文件")
        input_row.addWidget(self.include_shared_check)
        
        # 文件类型过滤
        self.mime_menu = QMenu(self)
        self.mime_actions = {}
        try:
            from modules.mime import DRIVE_MIME_TYPES
            mime_types = DRIVE_MIME_TYPES
        except ImportError:
            mime_types = {
                "表格 (Sheets)": "application/vnd.google-apps.spreadsheet",
                "文档 (Docs)": "application/vnd.google-apps.document",
                "幻灯片 (Slides)": "application/vnd.google-apps.presentation",
                "表单 (Forms)": "application/vnd.google-apps.form",
                "PDF文件": "application/pdf",
                "图片 (Image)": "image/",
                "视频 (Video)": "video/"
            }
        
        from PySide6.QtWidgets import QWidgetAction
        for label, mime in mime_types.items():
            action = QWidgetAction(self.mime_menu)
            cb = QCheckBox(label)
            cb.setStyleSheet("QCheckBox { padding: 4px 15px; margin: 2px 0px; } QCheckBox:hover { background-color: #f0f0f0; }")
            if "spreadsheet" in mime:
                cb.setChecked(True)
            cb.setProperty("mime", mime)
            action.setDefaultWidget(cb)
            self.mime_menu.addAction(action)
            self.mime_actions[label] = cb

        self.mime_btn = QPushButton("📄 文件类型...")
        self.mime_btn.setMenu(self.mime_menu)
        input_row.addWidget(self.mime_btn)

        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self._refresh_current)
        input_row.addWidget(self.refresh_btn)

        layout.addLayout(input_row)

        # ======= 导航栏（面包屑 + 返回按钮）=======
        nav_row = QHBoxLayout()

        self.back_btn = QPushButton("⬅️ 返回上级")
        self.back_btn.clicked.connect(self._go_back)
        self.back_btn.setEnabled(False)
        self.back_btn.setMaximumWidth(120)
        nav_row.addWidget(self.back_btn)

        self.breadcrumb_label = QLabel("")
        self.breadcrumb_label.setStyleSheet(
            "color: #1565C0; font-size: 12px; padding: 2px 6px;"
        )
        self.breadcrumb_label.setWordWrap(True)
        nav_row.addWidget(self.breadcrumb_label, 1)

        layout.addLayout(nav_row)

        # ======= 过滤区 =======
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("🔍 过滤:"))
        
        self.filter_target_combo = QComboBox()
        self.filter_target_combo.addItems(["按用户名/邮箱", "按文件名", "按归属"])
        self.filter_target_combo.currentTextChanged.connect(self._apply_filter)
        filter_row.addWidget(self.filter_target_combo)

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("输入关键词进行过滤...")
        self.filter_input.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.filter_input, 1)

        self.filter_mode = QComboBox()
        self.filter_mode.addItems(["模糊匹配", "精准匹配", "正则匹配"])
        self.filter_mode.setToolTip(
            "模糊匹配：包含关键词即可（不区分大小写）\n"
            "精准匹配：必须完全一致\n"
            "正则匹配：使用正则表达式（不区分大小写）"
        )
        self.filter_mode.currentTextChanged.connect(self._apply_filter)
        self.filter_mode.setMaximumWidth(120)
        filter_row.addWidget(self.filter_mode)

        self.clear_filter_btn = QPushButton("✖ 清除过滤")
        self.clear_filter_btn.clicked.connect(self._clear_filter)
        self.clear_filter_btn.setMaximumWidth(100)
        filter_row.addWidget(self.clear_filter_btn)

        layout.addLayout(filter_row)

        # ======= 文件表格 =======
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["文件名", "归属", "文件路径", "文件链接", "文件权限", "修改日期", "文件大小"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        # 列宽设置 — 全部使用 Interactive 模式，支持用户拖拽调整
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        # 设置合理的默认列宽
        self.table.setColumnWidth(0, 220)  # 文件名
        self.table.setColumnWidth(1, 80)   # 归属 (我的/共享)
        self.table.setColumnWidth(2, 150)  # 文件路径
        self.table.setColumnWidth(3, 180)  # 文件链接
        self.table.setColumnWidth(4, 200)  # 文件权限
        self.table.setColumnWidth(5, 140)  # 修改日期
        # 第 6 列（文件大小）由 stretchLastSection 自动填充
        self.table.verticalHeader().setDefaultSectionSize(30)

        # 启用右键菜单
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        # 双击进入子文件夹
        self.table.doubleClicked.connect(self._on_double_click)

        layout.addWidget(self.table, 1)

        # ======= 导出到 Google Sheet =======
        export_group = QGroupBox("📤 导出到 Google Sheet")
        export_layout = QHBoxLayout(export_group)

        export_layout.addWidget(QLabel("📄 目标表格链接/ID:"))
        self.export_sid_input = QLineEdit()
        self.export_sid_input.setPlaceholderText("输入要导出到的 Google Sheet 链接或 ID")
        export_layout.addWidget(self.export_sid_input, 1)

        export_layout.addWidget(QLabel("📋 工作表名:"))
        self.export_sheet_input = QLineEdit("Sheet1")
        self.export_sheet_input.setMaximumWidth(120)
        export_layout.addWidget(self.export_sheet_input)

        self.export_btn = QPushButton("📤 导出当前数据")
        self.export_btn.clicked.connect(self._export_to_sheet)
        export_layout.addWidget(self.export_btn)

        layout.addWidget(export_group)

        # ======= 状态栏 =======
        bottom = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)  # 不确定进度模式
        self.progress.setMaximumWidth(200)
        bottom.addWidget(self.progress)

        self.status_label = QLabel("请输入文件夹链接并点击加载")
        bottom.addWidget(self.status_label)
        bottom.addStretch()

        self.file_count_label = QLabel("")
        bottom.addWidget(self.file_count_label)

        layout.addLayout(bottom)

    # ========================
    # 面包屑导航
    # ========================

    def _get_supported_mime_types(self):
        selected = []
        for cb in self.mime_actions.values():
            if cb.isChecked():
                selected.append(cb.property("mime"))
        return selected if selected else None

    def _update_breadcrumb(self):
        """更新面包屑导航显示"""
        if not self._folder_stack:
            self.breadcrumb_label.setText("")
            self.back_btn.setEnabled(False)
            return

        parts = []
        for _, name in self._folder_stack:
            parts.append(name)

        path = " ▸ ".join(parts)
        self.breadcrumb_label.setText(f"📍 {path}")
        self.back_btn.setEnabled(len(self._folder_stack) > 1)

    def _go_back(self):
        """返回上级文件夹"""
        if len(self._folder_stack) <= 1:
            return

        # 弹出当前层
        self._folder_stack.pop()
        # 加载上一层
        parent_id, parent_name = self._folder_stack[-1]
        self._load_folder_by_id(parent_id)

    # ========================
    # 加载文件夹
    # ========================

    def _toggle_load(self):
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
            self.load_btn.setText("⏳ 正在停止...")
            self.load_btn.setEnabled(False)
            self.status_label.setText("正在终止操作，请稍候...")
        else:
            self._on_load_clicked()

    def _on_load_clicked(self):
        """从输入框解析并加载文件夹（作为根级导航）"""
        raw = self.folder_input.text().strip()
        if not raw:
            self.status_label.setText("⚠️ 请输入文件夹链接或 ID")
            return

        folder_id = extract_folder_id(raw)
        if not folder_id:
            self.status_label.setText("❌ 无法识别有效的文件夹 ID，请检查链接格式")
            return

        # 重置导航栈，作为新的根目录
        self._folder_stack = [(folder_id, f"根目录 ({folder_id[:12]}...)")]
        self._load_folder_by_id(folder_id)

    def _refresh_current(self):
        """刷新当前文件夹"""
        if self._current_folder_id:
            self._load_folder_by_id(self._current_folder_id)
        else:
            self._on_load_clicked()

    def _load_folder_by_id(self, folder_id):
        """根据 folder_id 加载文件夹内容"""
        self._current_folder_id = folder_id
        self.status_label.setText(f"⏳ 正在加载文件夹 ({folder_id[:20]}...)...")
        self.progress.setVisible(True)
        self.load_btn.setText("🛑 停止加载")
        self.load_btn.setEnabled(True)
        self.refresh_btn.setEnabled(False)
        self.back_btn.setEnabled(False)
        self.table.setRowCount(0)

        self._worker = DriveFolderFetchWorker(
            folder_id, 
            recursive=self.recursive_fetch_check.isChecked(),
            include_shared=self.include_shared_check.isChecked(),
            supported_mime_types=self._get_supported_mime_types()
        )
        self._worker.progress.connect(lambda msg: self.status_label.setText(msg))
        self._worker.finished.connect(self._on_files_loaded)
        self._worker.error.connect(self._on_load_error)
        # 确保线程执行完毕后安全释放资源，防止僵尸线程导致 C++ 底层崩溃
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.error.connect(lambda msg: self._worker.deleteLater())
        self._worker.start()

    def _on_files_loaded(self, folder_id, files):
        """文件列表加载完成"""
        self.progress.setVisible(False)
        self.load_btn.setText("📂 加载文件夹")
        self.load_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self._worker = None
        self._files_cache = files

        self._update_breadcrumb()
        self._apply_filter()  # 渲染表格（通过过滤逻辑统一处理）

        if not files:
            self.status_label.setText("📭 文件夹为空或无访问权限")
            self.file_count_label.setText("")

    def _on_load_error(self, msg):
        """加载失败"""
        self.progress.setVisible(False)
        self.load_btn.setText("📂 加载文件夹")
        self.load_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self._update_breadcrumb()
        self._worker = None
        self.status_label.setText(f"❌ 加载失败: {msg}")
        self.file_count_label.setText("")

    # ========================
    # 用户名过滤
    # ========================

    def _apply_filter(self):
        """根据当前过滤条件筛选并渲染文件列表"""
        keyword = self.filter_input.text().strip()
        mode = self.filter_mode.currentText()
        target = self.filter_target_combo.currentText()

        if keyword:
            filtered = [
                f for f in self._files_cache
                if file_matches_filter(f, keyword, mode, target)
            ]
        else:
            filtered = self._files_cache

        self._populate_table(filtered)

        # 更新状态
        total = len(self._files_cache)
        shown = len(filtered)
        if keyword:
            self.status_label.setText(
                f"🔍 过滤结果: 显示 {shown}/{total} 个文件 "
                f"(模式: {mode}, 关键词: \"{keyword}\")"
            )
        elif total > 0:
            self.status_label.setText("✅ 加载完成")
        self.file_count_label.setText(f"共 {shown}/{total} 个文件" if keyword else f"共 {total} 个文件")

    def _clear_filter(self):
        """清除过滤条件"""
        self.filter_input.clear()
        # _apply_filter 会自动通过 textChanged 触发

    # ========================
    # 表格渲染
    # ========================

    def _populate_table(self, files):
        """将文件列表渲染到表格中"""
        self.table.setRowCount(0)

        if not files:
            return

        for f in files:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # 文件名（存储文件 ID 和 mimeType 到 UserRole）
            raw_name = f.get("name", "—")
            mime = f.get("mimeType", "")
            icon = get_file_icon(mime)

            name_item = QTableWidgetItem(f"{icon} {raw_name}")
            name_item.setData(Qt.UserRole, f.get("id", ""))
            name_item.setData(Qt.UserRole + 1, mime)
            name_item.setData(Qt.UserRole + 2, raw_name)  # 存储原始名称

            # 文件夹行加粗显示
            if "folder" in mime:
                font = name_item.font()
                font.setBold(True)
                name_item.setFont(font)
                name_item.setForeground(QColor("#1565C0"))

            self.table.setItem(row, 0, name_item)

            # 归属
            owned = f.get("ownedByMe", False)
            if "folder" in mime:
                owner_text = "—" # 文件夹不太好严格区分或者没必要
            else:
                owner_text = "👤 我的" if owned else "🤝 别人共享"
            self.table.setItem(row, 1, QTableWidgetItem(owner_text))

            # 文件路径
            path = f.get("path", "—")
            self.table.setItem(row, 2, QTableWidgetItem(path))

            # 文件链接
            link = f.get("webViewLink", "—")
            link_item = QTableWidgetItem(link)
            link_item.setToolTip(link)
            self.table.setItem(row, 3, link_item)

            # 文件权限摘要
            perms = f.get("permissions", [])
            perm_text = format_permissions_summary(perms)
            perm_item = QTableWidgetItem(perm_text)
            perm_item.setToolTip(perm_text)
            self.table.setItem(row, 4, perm_item)

            # 修改日期
            mod_time = f.get("modifiedTime", "")
            if mod_time:
                try:
                    dt = datetime.fromisoformat(mod_time.replace("Z", "+00:00"))
                    mod_display = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    mod_display = mod_time[:19]
            else:
                mod_display = "—"
            self.table.setItem(row, 5, QTableWidgetItem(mod_display))

            # 文件大小
            size_text = format_file_size(f.get("size"))
            self.table.setItem(row, 6, QTableWidgetItem(size_text))

    # ========================
    # 双击进入子文件夹
    # ========================

    def _on_double_click(self, index):
        """双击表格行 — 如果是文件夹则进入"""
        row = index.row()
        name_item = self.table.item(row, 0)
        if not name_item:
            return

        mime = name_item.data(Qt.UserRole + 1) or ""
        if "folder" not in mime:
            return  # 不是文件夹，忽略

        folder_id = name_item.data(Qt.UserRole)
        folder_name = name_item.data(Qt.UserRole + 2) or name_item.text()

        if not folder_id:
            return

        # 推入导航栈
        self._folder_stack.append((folder_id, folder_name))
        # 清除过滤条件（进入新文件夹时重置）
        self.filter_input.clear()
        # 加载子文件夹
        self._load_folder_by_id(folder_id)

        logger.info(f"进入子文件夹: {folder_name} ({folder_id})")

    # ========================
    # 右键菜单
    # ========================

    def _show_context_menu(self, pos):
        """在文件名上右键弹出权限管理菜单"""
        item = self.table.itemAt(pos)
        if not item:
            return

        row = item.row()
        name_item = self.table.item(row, 0)
        if not name_item:
            return

        file_id = name_item.data(Qt.UserRole)
        file_name = name_item.text()
        mime = name_item.data(Qt.UserRole + 1) or ""

        if not file_id:
            return

        menu = QMenu(self)

        # 复制选中数据（多选/连选）
        selected_rows = self._get_selected_rows()
        if selected_rows:
            copy_data_action = menu.addAction(
                f"📋 复制选中数据 ({len(selected_rows)} 行)"
            )
            copy_data_action.triggered.connect(self._copy_selected_data)
            menu.addSeparator()

            # 检查选中的文件是否包含 Google Sheets (表格)
            has_spreadsheet = False
            for r in selected_rows:
                n_item = self.table.item(r, 0)
                if n_item and "spreadsheet" in (n_item.data(Qt.UserRole + 1) or ""):
                    has_spreadsheet = True
                    break
            
            if has_spreadsheet:
                save_lib_action = menu.addAction("📥 保存选中表格到表格库")
                save_lib_action.triggered.connect(self._save_selected_to_library)
                menu.addSeparator()

                trash_action = menu.addAction("🗑 将选中表格移到垃圾桶")
                trash_action.triggered.connect(lambda: self._delete_selected_spreadsheets("trash"))
                
                perm_delete_action = menu.addAction("💀 彻底永久删除选中表格")
                perm_delete_action.triggered.connect(lambda: self._delete_selected_spreadsheets("permanent"))
                menu.addSeparator()

        # 修改权限
        if len(selected_rows) > 1:
            perm_action = menu.addAction(f"🔐 批量修改访问权限 ({len(selected_rows)} 个文件)")
            perm_action.triggered.connect(self._open_batch_permission_dialog)
        else:
            perm_action = menu.addAction("🔐 修改访问权限")
            perm_action.triggered.connect(
                lambda: self._open_permission_dialog(file_id, file_name)
            )

        # 如果是文件夹，添加"进入文件夹"选项
        if "folder" in mime:
            folder_name = name_item.data(Qt.UserRole + 2) or file_name
            enter_action = menu.addAction("📂 进入此文件夹")
            enter_action.triggered.connect(
                lambda: self._enter_folder(file_id, folder_name)
            )

        # 打开/复制链接
        link_item = self.table.item(row, 3)
        if link_item and link_item.text() != "—":
            import webbrowser
            open_action = menu.addAction("🌐 在浏览器中打开")
            open_action.triggered.connect(
                lambda: webbrowser.open(link_item.text())
            )
            
            copy_link_action = menu.addAction("🔗 复制文件链接")
            copy_link_action.triggered.connect(
                lambda: self._copy_to_clipboard(link_item.text())
            )

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _enter_folder(self, folder_id, folder_name):
        """通过右键菜单进入子文件夹"""
        self._folder_stack.append((folder_id, folder_name))
        self.filter_input.clear()
        self._load_folder_by_id(folder_id)

    def _open_permission_dialog(self, file_id, file_name):
        """打开权限管理对话框（复用 PermissionManagerDialog）"""
        try:
            from ui.permission_manager_dialog import PermissionManagerDialog

            # 将文件信息组装成 PermissionManagerDialog 所需的格式
            # 该对话框接受 entries 列表，每个 entry 含 id、spreadsheet_id、name
            # 这里 spreadsheet_id 实际上就是 Drive 文件的 ID（Drive API 通用）
            entries = [{
                "id": file_id,
                "spreadsheet_id": file_id,
                "name": file_name
            }]

            dlg = PermissionManagerDialog(entries, parent=self)
            dlg.setWindowTitle(f"🔐 权限管理 — {file_name}")
            dlg.exec()

            # 对话框关闭后刷新文件列表以反映权限变更
            self._refresh_current()

        except Exception as e:
            logger.error(f"打开权限管理失败: {e}")
            QMessageBox.warning(
                self, "错误",
                f"无法打开权限管理面板:\n{e}"
            )

    def _open_batch_permission_dialog(self):
        """打开批量权限管理对话框"""
        selected_rows = self._get_selected_rows()
        if not selected_rows:
            return
            
        try:
            from ui.permission_manager_dialog import PermissionManagerDialog
            
            entries = []
            for r in selected_rows:
                name_item = self.table.item(r, 0)
                if not name_item: continue
                fid = name_item.data(Qt.UserRole)
                fname = name_item.data(Qt.UserRole + 2) or name_item.text()
                if fid:
                    entries.append({
                        "id": fid,
                        "spreadsheet_id": fid,
                        "name": fname
                    })
            
            if not entries:
                return

            dlg = PermissionManagerDialog(entries, parent=self)
            dlg.exec()
            self._refresh_current()
        except Exception as e:
            logger.error(f"打开批量权限管理失败: {e}")
            QMessageBox.warning(self, "错误", f"无法打开批量权限管理面板:\n{e}")

    def _copy_to_clipboard(self, text):
        """复制文本到剪贴板"""
        try:
            from PySide6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self.status_label.setText("📋 已复制到剪贴板")
        except Exception as e:
            self.status_label.setText(f"❌ 复制失败: {e}")

    # ========================
    # 保存到表格库
    # ========================

    def _save_selected_to_library(self):
        """将选中的表格文件批量保存到表格库"""
        rows = self._get_selected_rows()
        if not rows:
            return
            
        # 筛选出表格类型的文件
        spreadsheets = []
        for r in rows:
            name_item = self.table.item(r, 0)
            link_item = self.table.item(r, 1)
            if not name_item or not link_item:
                continue
                
            mime = name_item.data(Qt.UserRole + 1) or ""
            if "spreadsheet" in mime:
                # 原始文件名
                raw_name = name_item.data(Qt.UserRole + 2) or name_item.text()
                link = link_item.text()
                if link and link != "—":
                    spreadsheets.append((raw_name, link))
                    
        if not spreadsheets:
            QMessageBox.information(self, "提示", "选中的行中没有 Google 表格文件。")
            return
            
        try:
            from ui.save_to_library_dialog import SaveToLibraryDialog
            dlg = SaveToLibraryDialog(self)
            if dlg.exec():
                acc_id, group_name, notes = dlg.get_selection()
                
                # 获取该账号的 Library 实例
                from services.spreadsheet_library import AccountManager
                mgr = AccountManager()
                lib = mgr.get_library(acc_id)
                if not lib:
                    QMessageBox.warning(self, "错误", "无法获取目标表格库。")
                    return
                    
                # 批量添加
                count = 0
                for name, link in spreadsheets:
                    lib.add_entry(
                        name=name,
                        link=link,
                        group_name=group_name,
                        notes=notes
                    )
                    count += 1
                    
                acc_name = mgr.get_account_name(acc_id)
                QMessageBox.information(
                    self, "保存成功", 
                    f"成功将 {count} 个表格存入 [{acc_name}] 账号的 [{group_name}] 分组！"
                )
        except Exception as e:
            logger.error(f"保存到表格库失败: {e}")
            QMessageBox.critical(self, "错误", f"保存到表格库时发生错误:\n{e}")

    # ========================
    # 复制选中数据
    # ========================

    def _get_selected_rows(self):
        """获取所有选中的行号（去重并排序）"""
        rows = set()
        for item in self.table.selectedItems():
            rows.add(item.row())
        return sorted(rows)

    def _copy_selected_data(self):
        """
        复制选中行的数据到剪贴板。
        支持多选（Ctrl+点击）和连选（Shift+点击）。
        格式为制表符分隔的文本（可直接粘贴到 Excel/Sheets）。
        """
        rows = self._get_selected_rows()
        if not rows:
            self.status_label.setText("⚠️ 请先选择要复制的行")
            return

        # 表头
        headers = []
        for col in range(self.table.columnCount()):
            h = self.table.horizontalHeaderItem(col)
            headers.append(h.text() if h else f"列{col}")

        lines = ["\t".join(headers)]

        # 数据行
        for row in rows:
            line_data = []
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                line_data.append(item.text() if item else "")
            lines.append("\t".join(line_data))

        try:
            from PySide6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText("\n".join(lines))
            self.status_label.setText(f"📋 已复制 {len(rows)} 行数据到剪贴板")
        except Exception as e:
            self.status_label.setText(f"❌ 复制失败: {e}")

    # ========================
    # 删除选中表格
    # ========================

    def _delete_selected_spreadsheets(self, mode):
        """删除选中的 Google Sheets 表格"""
        rows = self._get_selected_rows()
        if not rows:
            return

        spreadsheets = []
        for r in rows:
            name_item = self.table.item(r, 0)
            if not name_item:
                continue
            mime = name_item.data(Qt.UserRole + 1) or ""
            if "spreadsheet" in mime:
                file_id = name_item.data(Qt.UserRole)
                if file_id:
                    spreadsheets.append(file_id)

        if not spreadsheets:
            QMessageBox.information(self, "提示", "选中的行中没有 Google 表格文件。")
            return

        if mode == "permanent":
            reply = QMessageBox.warning(
                self, "⚠️ 彻底删除确认",
                f"确定要彻底永久删除 {len(spreadsheets)} 个工作簿吗？\n\n此操作不可恢复！",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
        else:
            reply = QMessageBox.question(
                self, "移到垃圾桶",
                f"确定要将 {len(spreadsheets)} 个工作簿移到垃圾桶吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

        if reply != QMessageBox.Yes: return

        # 我们复用 BatchDeleteSheetsWidget 里的 DeleteSpreadsheetWorker
        from ui.batch_delete_sheets_widget import DeleteSpreadsheetWorker
        self.progress.setVisible(True)
        self.progress.setRange(0, len(spreadsheets))
        self.progress.setValue(0)
        self.status_label.setText("⏳ 删除中...")
        
        self._delete_worker = DeleteSpreadsheetWorker(spreadsheets, mode)
        self._delete_worker.progress.connect(self._on_delete_progress)
        self._delete_worker.finished.connect(self._on_delete_finished)
        self._delete_worker.error.connect(self._on_delete_error)
        self._delete_worker.start()

    def _on_delete_progress(self, current, total, message):
        self.progress.setValue(current)
        self.status_label.setText(message)

    def _on_delete_finished(self, results):
        self.progress.setVisible(False)
        success = sum(1 for r in results if r.get("status") == "success")
        QMessageBox.information(self, "删除完成", f"删除完成: 成功 {success} / {len(results)}")
        self.status_label.setText(f"✅ 删除完成: 成功 {success} 个表格")
        self._delete_worker = None
        # 操作完刷新页面
        self._refresh_current()

    def _on_delete_error(self, error_msg):
        self.progress.setVisible(False)
        self.status_label.setText(f"❌ 删除失败: {error_msg}")
        QMessageBox.warning(self, "删除失败", f"批量删除失败:\n{error_msg}")
        self._delete_worker = None




    # ========================
    # 导出到 Google Sheet
    # ========================

    def _get_table_data_for_export(self):
        """
        将当前表格中的所有可见数据（含表头）提取为二维列表。
        """
        data = []

        # 表头
        headers = []
        for col in range(self.table.columnCount()):
            h = self.table.horizontalHeaderItem(col)
            headers.append(h.text() if h else f"列{col}")
        data.append(headers)

        # 数据行
        for row in range(self.table.rowCount()):
            row_data = []
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                row_data.append(item.text() if item else "")
            data.append(row_data)

        return data

    def _export_to_sheet(self):
        """将当前文件列表导出到指定的 Google Sheet"""
        raw_sid = self.export_sid_input.text().strip()
        if not raw_sid:
            QMessageBox.warning(self, "提示", "请输入目标 Google Sheet 的链接或 ID")
            return

        # 提取 Spreadsheet ID
        from ui.batch_backup_widget import extract_spreadsheet_id
        sid = extract_spreadsheet_id(raw_sid)
        if not sid:
            QMessageBox.warning(self, "错误", "无法识别有效的 Spreadsheet ID")
            return

        sheet_name = self.export_sheet_input.text().strip()
        if not sheet_name:
            sheet_name = "Sheet1"

        if self.table.rowCount() == 0:
            QMessageBox.warning(self, "提示", "当前没有可导出的数据")
            return

        data = self._get_table_data_for_export()

        # 确认导出
        reply = QMessageBox.question(
            self, "确认导出",
            f"将导出 {len(data) - 1} 行数据到:\n"
            f"表格 ID: {sid[:30]}...\n"
            f"工作表: {sheet_name}\n\n"
            "数据将从 A1 开始写入，是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 执行导出
        self.export_btn.setEnabled(False)
        self.status_label.setText("📤 正在导出...")
        self.progress.setVisible(True)

        self._export_worker = ExportToSheetWorker(sid, sheet_name, data)
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.error.connect(self._on_export_error)
        self._export_worker.start()

    def _on_export_finished(self, msg):
        """导出完成"""
        self.progress.setVisible(False)
        self.export_btn.setEnabled(True)
        self.status_label.setText(f"✅ {msg}")
        QMessageBox.information(self, "导出成功", msg)

    def _on_export_error(self, msg):
        """导出失败"""
        self.progress.setVisible(False)
        self.export_btn.setEnabled(True)
        self.status_label.setText(f"❌ 导出失败: {msg}")
        QMessageBox.warning(self, "导出失败", msg)


class ExportToSheetWorker(QThread):
    """后台线程 — 将数据导出到 Google Sheet"""
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, spreadsheet_id, sheet_name, data):
        super().__init__()
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.data = data

    def run(self):
        try:
            from services.sheet_service import SheetService
            service = SheetService(self.spreadsheet_id)

            # 计算写入范围
            num_rows = len(self.data)
            num_cols = max(len(r) for r in self.data) if self.data else 1
            # 列号转字母
            end_col_letter = chr(ord('A') + num_cols - 1) if num_cols <= 26 else 'Z'
            cell_range = f"A1:{end_col_letter}{num_rows}"

            # 写入数据
            service.write_data(self.sheet_name, cell_range, self.data)

            title = service.get_spreadsheet_title()
            self.finished.emit(
                f"已成功导出 {num_rows - 1} 行数据到 \"{title}\" 的 {self.sheet_name} 工作表"
            )
        except Exception as e:
            logger.error(f"导出到 Google Sheet 失败: {e}")
            self.error.emit(str(e))
