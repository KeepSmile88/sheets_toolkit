# 表格库 UI 组件 — 独立窗口，多账号 Tab 管理 + 分组 + 搜索 + 批量导入 + 批量打开
import logging
import webbrowser
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QGroupBox, QComboBox,
    QCheckBox, QMessageBox, QTreeWidget,
    QTreeWidgetItem, QInputDialog, QProgressBar, QTabWidget,
    QAbstractItemView, QMenu, QFileDialog, QToolButton, QTabBar
)
from ui.clearable_text_edit import ClearableTextEdit
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QAction

from services.spreadsheet_library import SpreadsheetLibrary, AccountManager
from ui.note_viewer_dialog import NoteViewerDialog
from ui.permission_manager_dialog import PermissionManagerDialog

logger = logging.getLogger("sheets_toolkit.ui.spreadsheet_library")


class DraggableGroupTree(QTreeWidget):
    """支持拖放移动分组的树控件。
    拖放完成后发射 group_dropped 信号，由 AccountPanel 处理持久化。
    """
    group_dropped = Signal(str, str)  # (group_id, new_full_path)

    def __init__(self, parent=None):
        super().__init__(parent)
        # 启用拖放
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)

    def startDrag(self, supportedActions):
        """限制特殊节点不可拖动"""
        item = self.currentItem()
        if item:
            gid = item.data(0, Qt.UserRole)
            if gid in ("__all__", "default", "__virtual_parent__"):
                return  # 禁止拖动
        super().startDrag(supportedActions)

    def dropEvent(self, event):
        """处理拖放结束事件 — 计算新路径并发射信号"""
        dragged_item = self.currentItem()
        if not dragged_item:
            event.ignore()
            return

        dragged_gid = dragged_item.data(0, Qt.UserRole)
        if dragged_gid in ("__all__", "default", "__virtual_parent__"):
            event.ignore()
            return

        # 获取拖拽目标位置
        target_item = self.itemAt(event.position().toPoint())
        drop_indicator = self.dropIndicatorPosition()

        # 不允许放到 "全部" 节点的子级
        if target_item and target_item.data(0, Qt.UserRole) == "__all__":
            if drop_indicator == QAbstractItemView.OnItem:
                event.ignore()
                return

        # 提取被拖拽节点的短名称（去掉 emoji 前缀）
        dragged_text = dragged_item.text(0)
        # 去除 📁/📄 图标前缀
        for prefix in ("📁 ", "📄 "):
            if dragged_text.startswith(prefix):
                dragged_text = dragged_text[len(prefix):]
                break
        dragged_short_name = dragged_text.strip()

        # 执行默认的 drop 操作（移动树节点）
        super().dropEvent(event)

        # drop 完成后，根据树节点的新位置计算完整路径
        new_path = self._build_path_for_item(dragged_item, dragged_short_name)
        if new_path and dragged_gid:
            self.group_dropped.emit(dragged_gid, new_path)

    def _build_path_for_item(self, item, short_name):
        """根据节点在树中的当前位置构建完整路径"""
        parts = [short_name]
        parent = item.parent()
        while parent:
            parent_gid = parent.data(0, Qt.UserRole)
            # 跳过 "全部" 根节点
            if parent_gid == "__all__":
                break
            parent_text = parent.text(0)
            for prefix in ("📁 ", "📄 "):
                if parent_text.startswith(prefix):
                    parent_text = parent_text[len(prefix):]
                    break
            parts.insert(0, parent_text.strip())
            parent = parent.parent()
        return "->".join(parts)


class HealthCheckWorker(QThread):
    """健康巡检工作线程 — 多线程并发扫描表格健康状态"""
    entry_checked = Signal(str, str, str)  # entry_id, status, detail
    progress = Signal(int, int, str)       # current, total, message
    all_done = Signal()

    def __init__(self, entries):
        super().__init__()
        self.entries = entries  # [{"id": ..., "spreadsheet_id": ..., "name": ...}, ...]

    def run(self):
        import concurrent.futures
        from services.sheet_service import SheetService

        total = len(self.entries)
        completed = 0

        def check_one(entry):
            sid = entry.get("spreadsheet_id", "")
            eid = entry.get("id", "")
            name = entry.get("name", sid[:15])
            if not sid:
                return eid, "error", "缺少 Spreadsheet ID"
            try:
                service = SheetService(sid)
                report = service.health_check()
                errors = report.get("errors_found", 0)
                empty = report.get("empty_sheets", 0)
                total_rows = report.get("total_rows", 0)

                if errors > 0:
                    status = "error"
                    detail = f"{errors} 个公式错误, {total_rows} 行数据"
                elif empty > 0:
                    status = "warning"
                    detail = f"{empty} 个空工作表, {total_rows} 行数据"
                else:
                    status = "ok"
                    detail = f"{report.get('sheet_count', 0)} 个工作表, {total_rows} 行数据"

                return eid, status, detail
            except Exception as e:
                return eid, "error", f"访问失败: {str(e)[:60]}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(check_one, e): e for e in self.entries
            }
            for future in concurrent.futures.as_completed(futures):
                eid, status, detail = future.result()
                completed += 1
                entry = futures[future]
                name = entry.get("name", "")
                self.entry_checked.emit(eid, status, detail)
                self.progress.emit(completed, total, f"({completed}/{total}) {name}")

        self.all_done.emit()


class BatchImportWorker(QThread):
    """批量导入工作线程 — 自动从 Google API 获取表格标题"""
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, links, group_name, notes):
        super().__init__()
        self.links = links
        self.group_name = group_name
        self.notes = notes

    def run(self):
        try:
            from services.sheet_service import SheetService
            from ui.batch_backup_widget import extract_spreadsheet_id
            results = []
            total = len(self.links)

            for i, link in enumerate(self.links):
                link = link.strip()
                if not link:
                    continue

                sid = extract_spreadsheet_id(link)
                if not sid:
                    results.append({
                        "link": link, "name": "", "sid": "",
                        "status": "error", "error": "无法提取 ID"
                    })
                    continue

                self.progress.emit(i, total, f"({i+1}/{total}) 获取标题: {sid[:15]}...")
                try:
                    service = SheetService(sid)
                    title = service.get_spreadsheet_title()
                    results.append({
                        "link": link, "name": title, "sid": sid,
                        "status": "success"
                    })
                except Exception as e:
                    results.append({
                        "link": link, "name": sid[:20], "sid": sid,
                        "status": "error", "error": str(e)
                    })

            self.progress.emit(total, total, "完成")
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class AccountPanel(QWidget):
    """
    单个账号的管理面板 — 分组管理 + 搜索 + 批量导入 + 批量打开。
    作为 SpreadsheetLibraryDialog 中每个 Tab 的内容。
    """

    def __init__(self, library, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.library = library
        self._selected_entry_id = None
        self._import_worker = None
        self._health_worker = None
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._do_search)
        self.setup_ui()
        self.refresh_all()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Horizontal)

        # ======= 左侧：分组树 =======
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 4, 0)

        ll.addWidget(QLabel("📁 分组"))

        self.group_tree = DraggableGroupTree(self)
        self.group_tree.setHeaderLabels(["分组", "数量"])
        self.group_tree.setColumnWidth(0, 130)
        self.group_tree.currentItemChanged.connect(self._on_group_select)
        self.group_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.group_tree.customContextMenuRequested.connect(self._show_group_context_menu)
        self.group_tree.group_dropped.connect(self._on_group_dropped)
        ll.addWidget(self.group_tree)

        # 分组操作按钮
        grp_btns = QHBoxLayout()
        add_grp = QPushButton("➕ 新增")
        add_grp.clicked.connect(self._add_group)
        grp_btns.addWidget(add_grp)
        rename_grp = QPushButton("✏️ 重命名")
        rename_grp.clicked.connect(self._rename_group)
        grp_btns.addWidget(rename_grp)
        del_grp = QPushButton("🗑 删除")
        del_grp.setObjectName("danger_btn")
        # del_grp.clicked.connect(self._delete_group)
        del_grp.clicked.connect(self._delete_group)
        grp_btns.addWidget(del_grp)
        ll.addLayout(grp_btns)

        # ======= 右侧：标签页 =======
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 0, 0, 0)

        self.tabs = QTabWidget()

        # --- Tab 1: 管理 ---
        manage_tab = QWidget()
        ml = QVBoxLayout(manage_tab)
        ml.setContentsMargins(4, 4, 4, 4)

        # 搜索区
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索表格（名称/链接/备注）...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(self._do_search)  # 支持回车搜索
        self.search_input.textChanged.connect(self._on_search_text_changed)  # 支持清空和输入自动搜索
        search_row.addWidget(self.search_input)

        self.search_btn = QPushButton("🔍 搜索")
        self.search_btn.clicked.connect(self._do_search)
        search_row.addWidget(self.search_btn)

        self.regex_check = QCheckBox("正则")
        self.regex_check.stateChanged.connect(self._on_search_text_changed)
        search_row.addWidget(self.regex_check)

        self.search_count = QLabel("")
        self.search_count.setMinimumWidth(80)
        search_row.addWidget(self.search_count)
        ml.addLayout(search_row)

        # 表格列表（支持多选）
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["⭐", "名称", "分组", "标签", "链接/ID", "备注", "状态", "更新时间"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(7, 130)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.currentCellChanged.connect(self._on_entry_select)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
        ml.addWidget(self.table)

        # 操作按钮行（批量打开等）
        action_row = QHBoxLayout()
        self.open_btn = QPushButton("🌐 在浏览器中打开选中项")
        self.open_btn.clicked.connect(self._open_selected_in_browser)
        action_row.addWidget(self.open_btn)

        connect_sel_btn = QPushButton("🔗 连接选中表格")
        connect_sel_btn.clicked.connect(self._quick_connect_selected)
        action_row.addWidget(connect_sel_btn)

        action_row.addStretch()

        self.health_btn = QPushButton("⏱️ 巡检全部")
        self.health_btn.clicked.connect(self._start_health_check_all)
        action_row.addWidget(self.health_btn)

        export_btn = QPushButton("📤 导出")
        export_btn.clicked.connect(self._export_data)
        action_row.addWidget(export_btn)

        import_btn = QPushButton("📥 导入")
        import_btn.clicked.connect(self._import_data)
        action_row.addWidget(import_btn)

        select_all_btn = QPushButton("全选")
        select_all_btn.setMaximumWidth(50)
        select_all_btn.clicked.connect(self.table.selectAll)
        action_row.addWidget(select_all_btn)
        ml.addLayout(action_row)

        # 编辑区
        edit_group = QGroupBox("条目详情")
        el = QVBoxLayout(edit_group)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("表格名称:"))
        self.edit_name = QLineEdit()
        r1.addWidget(self.edit_name)
        r1.addWidget(QLabel("分组:"))
        self.edit_group = QComboBox()
        self.edit_group.setMinimumWidth(100)
        r1.addWidget(self.edit_group)
        el.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("表格链接:"))
        self.edit_link = QLineEdit()
        self.edit_link.setPlaceholderText("粘贴完整链接或 ID")
        r2.addWidget(self.edit_link)
        el.addLayout(r2)

        r3 = QHBoxLayout()
        r3.addWidget(QLabel("标签:"))
        self.edit_tags = QLineEdit()
        self.edit_tags.setPlaceholderText("多个标签用逗号隔开 (例如: 研发, 2024)")
        r3.addWidget(self.edit_tags)
        
        r3.addWidget(QLabel("备注:"))
        self.edit_notes = QLineEdit()
        r3.addWidget(self.edit_notes)
        
        self.edit_star = QCheckBox("🌟 置顶星标")
        r3.addWidget(self.edit_star)
        el.addLayout(r3)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("➕ 新增条目")
        add_btn.clicked.connect(self._add_entry)
        btn_row.addWidget(add_btn)
        save_btn = QPushButton("💾 保存修改")
        save_btn.setObjectName("secondary_btn")
        save_btn.clicked.connect(self._save_entry)
        btn_row.addWidget(save_btn)
        del_btn = QPushButton("🗑 删除选中")
        del_btn.setObjectName("danger_btn")
        del_btn.clicked.connect(self._delete_selected_entries)
        btn_row.addWidget(del_btn)
        el.addLayout(btn_row)

        ml.addWidget(edit_group)

        self.info_label = QLabel("")
        ml.addWidget(self.info_label)

        self.tabs.addTab(manage_tab, "📋 管理")

        # --- Tab 2: 批量导入 ---
        import_tab = QWidget()
        il = QVBoxLayout(import_tab)
        il.setContentsMargins(4, 4, 4, 4)

        il.addWidget(QLabel("📥 批量导入 — 粘贴多个表格链接，自动获取标题并添加到指定分组"))

        il.addWidget(QLabel("📄 表格链接（每行一个）："))
        self.import_links = ClearableTextEdit()
        self.import_links.setPlaceholderText(
            "粘贴表格链接或 ID，每行一个\n\n"
            "例如：\n"
            "https://docs.google.com/spreadsheets/d/xxx/edit\n"
            "https://docs.google.com/spreadsheets/d/yyy/edit"
        )
        il.addWidget(self.import_links)

        opt_row = QHBoxLayout()
        opt_row.addWidget(QLabel("导入到分组:"))
        self.import_group = QComboBox()
        self.import_group.setMinimumWidth(120)
        self.import_group.setEditable(True)
        self.import_group.setToolTip("选择已有分组或输入新分组名称")
        opt_row.addWidget(self.import_group)

        opt_row.addWidget(QLabel("备注:"))
        self.import_notes = QLineEdit()
        self.import_notes.setPlaceholderText("可选，统一备注")
        opt_row.addWidget(self.import_notes)
        il.addLayout(opt_row)

        import_btns = QHBoxLayout()
        self.import_btn = QPushButton("🚀 批量导入")
        self.import_btn.clicked.connect(self._start_batch_import)
        import_btns.addWidget(self.import_btn)

        bookmark_btn = QPushButton("🔖 从书签导入")
        bookmark_btn.setToolTip(
            "从浏览器导出的书签文件（HTML）中提取 Google Sheets 链接")
        bookmark_btn.clicked.connect(self._import_from_bookmarks)
        import_btns.addWidget(bookmark_btn)

        clear_btn = QPushButton("🧹 清空")
        clear_btn.clicked.connect(lambda: (
            self.import_links.clear(), self.import_result.setRowCount(0),
            self.import_status.setText("")
        ))
        clear_btn.setMaximumWidth(80)
        import_btns.addWidget(clear_btn)
        il.addLayout(import_btns)

        self.import_progress = QProgressBar()
        self.import_progress.setVisible(False)
        il.addWidget(self.import_progress)
        self.import_status = QLabel("")
        il.addWidget(self.import_status)

        # 导入结果
        self.import_result = QTableWidget()
        self.import_result.setColumnCount(4)
        self.import_result.setHorizontalHeaderLabels(
            ["名称", "ID", "状态", "说明"]
        )
        self.import_result.setAlternatingRowColors(True)
        self.import_result.setEditTriggers(QTableWidget.NoEditTriggers)
        self.import_result.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.import_result.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.import_result.setColumnWidth(2, 50)
        self.import_result.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        il.addWidget(self.import_result)

        self.tabs.addTab(import_tab, "📥 批量导入")

        rl.addWidget(self.tabs)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([180, 750])
        layout.addWidget(splitter)

    # ========================
    # 搜索
    # ========================

    def _on_search_text_changed(self, *args):
        """搜索输入改变时触发防抖计时器"""
        self._search_timer.start()

    def _do_search(self):
        """执行搜索"""
        keyword = self.search_input.text().strip()
        use_regex = self.regex_check.isChecked()

        if keyword:
            # 搜索所有条目（忽略当前选中的分组）
            results = self.library.search(keyword, use_regex)
            self._refresh_table(results)
            self.search_count.setText(f"找到 {len(results)} 条")
        else:
            self.search_count.setText("")
            # 无搜索关键词时，显示当前分组
            current = self.group_tree.currentItem()
            if current:
                gid = current.data(0, Qt.UserRole)
                if gid == "__all__":
                    self._refresh_table()
                else:
                    self._refresh_table(self.library.get_entries_by_group(gid))
            else:
                self._refresh_table()

    # ========================
    # 批量打开浏览器
    # ========================

    def _get_selected_entries(self):
        """获取所有选中行对应的条目"""
        entries = []
        seen = set()
        for item in self.table.selectedItems():
            row = item.row()
            if row in seen:
                continue
            seen.add(row)
            name_item = self.table.item(row, 0)
            if name_item:
                eid = name_item.data(Qt.UserRole)
                entry = self.library.get_entry(eid)
                if entry:
                    entries.append(entry)
        return entries

    def _open_selected_in_browser(self):
        """在浏览器中批量打开选中的表格"""
        entries = self._get_selected_entries()
        if not entries:
            self.info_label.setText("⚠️ 请先选择要打开的表格")
            return

        if len(entries) > 10:
            if QMessageBox.question(
                self, "确认",
                f"即将打开 {len(entries)} 个表格？\n打开过多标签页可能影响浏览器性能。",
                QMessageBox.Yes | QMessageBox.No
            ) != QMessageBox.Yes:
                return

        opened = 0
        for entry in entries:
            link = entry.get("link", "")
            sid = entry.get("spreadsheet_id", "")
            if link and link.startswith("http"):
                webbrowser.open(link)
                opened += 1
            elif sid:
                url = f"https://docs.google.com/spreadsheets/d/{sid}/edit"
                webbrowser.open(url)
                opened += 1

        self.info_label.setText(f"🌐 已在浏览器中打开 {opened} 个表格")

    def _quick_connect_selected(self):
        """快速连接选中的第一个表格"""
        entries = self._get_selected_entries()
        if not entries:
            self.info_label.setText("⚠️ 请先选择要连接的表格")
            return

        entry = entries[0]
        link = entry.get("link", "") or entry.get("spreadsheet_id", "")
        if link and self.controller and self.controller.view:
            self.controller.view.input_id.setText(link)
            self.controller.view.connect_sheet()
            self.info_label.setText(f"🔗 已连接: {entry.get('name', '')}")

    # ========================
    # 批量导入
    # ========================

    def _start_batch_import(self):
        text = self.import_links.toPlainText().strip()
        if not text:
            self.import_status.setText("⚠️ 请输入表格链接")
            return

        links = [l.strip() for l in text.split('\n') if l.strip()]
        if not links:
            self.import_status.setText("⚠️ 未检测到有效链接")
            return

        group_name = self.import_group.currentText().strip() or "默认"
        notes = self.import_notes.text().strip()

        self.import_btn.setEnabled(False)
        self.import_btn.setText("⏳ 导入中...")
        self.import_progress.setVisible(True)
        self.import_progress.setMaximum(len(links))
        self.import_progress.setValue(0)
        self.import_result.setRowCount(0)

        self._import_worker = BatchImportWorker(links, group_name, notes)
        self._import_worker.progress.connect(
            lambda c, t, m: (
                self.import_progress.setValue(c),
                self.import_status.setText(m)
            )
        )
        self._import_worker.finished.connect(
            lambda results: self._on_import_finished(results, group_name, notes)
        )
        self._import_worker.error.connect(self._on_import_error)
        self._import_worker.start()

    def _on_import_finished(self, results, group_name, notes):
        self.import_progress.setValue(self.import_progress.maximum())
        self.import_result.setRowCount(len(results))

        ok_count = 0
        for i, r in enumerate(results):
            self.import_result.setItem(i, 0, QTableWidgetItem(r.get("name", "—")))
            self.import_result.setItem(i, 1, QTableWidgetItem(r.get("sid", "")[:25]))
            status = "✅" if r["status"] == "success" else "❌"
            self.import_result.setItem(i, 2, QTableWidgetItem(status))

            if r["status"] == "success":
                ok_count += 1
                self.library.add_entry(r["name"], r["link"], group_name, notes)
                self.import_result.setItem(i, 3, QTableWidgetItem("已添加"))
            else:
                err_item = QTableWidgetItem(r.get("error", ""))
                err_item.setToolTip(r.get("error", ""))
                self.import_result.setItem(i, 3, err_item)

        self.import_status.setText(f"✅ 导入完成: {ok_count}/{len(results)} 成功")
        self.import_btn.setEnabled(True)
        self.import_btn.setText("🚀 批量导入")
        self.import_progress.setVisible(False)
        self._import_worker = None
        self.refresh_all()

    def _on_import_error(self, msg):
        self.import_status.setText(f"❌ {msg}")
        self.import_btn.setEnabled(True)
        self.import_btn.setText("🚀 批量导入")
        self.import_progress.setVisible(False)
        self._import_worker = None

    def _import_from_bookmarks(self):
        """从浏览器导出的书签 HTML 文件中批量导入 Google Sheets 链接。
        保留原始目录结构作为分组（用 '->' 连接层级），保留书签名称作为条目名称。
        """
        import re as _re
        from html.parser import HTMLParser

        path, _ = QFileDialog.getOpenFileName(
            self, "选择书签文件", "",
            "书签文件 (*.html *.htm);;所有文件 (*.*)"
        )
        if not path:
            return

        try:
            # 尝试多种编码读取书签文件
            content = None
            for enc in ('utf-8', 'gbk', 'latin-1'):
                try:
                    with open(path, 'r', encoding=enc) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue

            if not content:
                self.import_status.setText("❌ 无法读取书签文件（编码不支持）")
                return

            # ---- 用 HTMLParser 解析书签的目录结构 ----
            # 浏览器书签 HTML 结构:
            #   <DL><p>
            #     <DT><H3>文件夹名</H3>
            #     <DL><p>
            #       <DT><A HREF="url">书签名</A>
            #     </DL>
            #   </DL>

            class BookmarkParser(HTMLParser):
                """解析书签 HTML，提取目录层级和 Google Sheets 链接"""
                def __init__(self):
                    super().__init__()
                    self.folder_stack = []   # 当前目录栈
                    self.results = []        # [{name, link, folder_path, sid}]
                    self._current_tag = None
                    self._current_href = None
                    self._in_h3 = False
                    self._pending_folder = None
                    self._dl_depth = 0       # <DL> 嵌套深度追踪

                def handle_starttag(self, tag, attrs):
                    tag_lower = tag.lower()
                    self._current_tag = tag_lower

                    if tag_lower == 'dl':
                        self._dl_depth += 1
                        # 如果有待入栈的文件夹名，在进入新 <DL> 时入栈
                        if self._pending_folder is not None:
                            self.folder_stack.append(self._pending_folder)
                            self._pending_folder = None

                    elif tag_lower == 'h3':
                        self._in_h3 = True

                    elif tag_lower == 'a':
                        attrs_dict = dict(attrs)
                        self._current_href = attrs_dict.get('href', '') or attrs_dict.get('HREF', '')

                def handle_endtag(self, tag):
                    tag_lower = tag.lower()
                    if tag_lower == 'dl':
                        self._dl_depth -= 1
                        if self.folder_stack:
                            self.folder_stack.pop()
                    elif tag_lower == 'h3':
                        self._in_h3 = False
                    elif tag_lower == 'a':
                        self._current_href = None
                    self._current_tag = None

                def handle_data(self, data):
                    text = data.strip()
                    if not text:
                        return

                    if self._in_h3:
                        # 文件夹名称 — 暂存，等下一个 <DL> 出现时再入栈
                        self._pending_folder = text

                    elif self._current_href and self._current_tag == 'a':
                        href = self._current_href
                        folder_path = '->'.join(self.folder_stack) if self.folder_stack else ''
                        sid = ""

                        from urllib.parse import urlparse
                        parsed_href = urlparse(href if '://' in href else 'http://' + href)
                        domain = parsed_href.netloc.lower()

                        # 1. Google Docs / Sheets / Slides (提取文件 ID)
                        if domain.endswith('google.com') or domain.endswith('google.com.hk'):
                            sid_match = _re.search(r'/d/([a-zA-Z0-9_-]+)', href)
                            if sid_match:
                                sid = sid_match.group(1)

                        # 2. YouTube (提取视频 ID)
                        elif domain.endswith('youtube.com') or domain == 'youtu.be':
                            v_match = _re.search(r'(?:v=|\/)([a-zA-Z0-9_-]{11})', href)
                            if v_match:
                                sid = v_match.group(1)

                        # 3. PDF 或其他链接 (提取文件名作为 sid，或者保留为 None/空)
                        elif href.lower().endswith('.pdf'):
                            # 提取文件名如 'view1' 作为 sid
                            pdf_match = _re.search(r'/([^/]+)\.pdf', href, _re.I)
                            if pdf_match:
                                sid = pdf_match.group(1)

                        if not sid:
                            html_match = _re.search(r'/([^/]+)\.html', href, _re.I)
                            if html_match:
                                sid = html_match.group(1)
                            else:
                                clean_url = _re.sub(r'^https?://', '', href).strip('/')
                                sid = _re.sub(r'[\./]', '_', clean_url)

                        # 只要有链接，就存入结果（保持原有结构：name, link, folder_path, sid）
                        if sid:  
                            self.results.append({
                                'name': text,
                                'link': href,
                                'folder_path': folder_path,
                                'sid': sid, # 如果没匹配到特定 ID，此处为 None
                        })

            parser = BookmarkParser()
            parser.feed(content)
            bookmarks = parser.results

            if not bookmarks:
                self.import_status.setText(
                    "⚠️ 未在书签文件中找到 Google Sheets 链接"
                )
                QMessageBox.information(
                    self, "提示",
                    "未在书签文件中找到任何 Google Sheets 链接。\n\n"
                    "请确认：\n"
                    "1. 书签文件是从浏览器导出的 HTML 格式\n"
                    "2. 书签中包含 Google Sheets 的链接\n"
                    "   (docs.google.com/spreadsheets/d/...)"
                )
                return

            # 按 Spreadsheet ID 去重
            seen_sids = set()
            unique_bookmarks = []
            for bm in bookmarks:
                if bm['sid'] not in seen_sids:
                    seen_sids.add(bm['sid'])
                    unique_bookmarks.append(bm)

            # ---- 弹出预览对话框让用户确认 ----
            preview_dlg = QDialog(self)
            preview_dlg.setWindowTitle("🔖 书签导入预览")
            preview_dlg.setMinimumSize(750, 450)
            preview_dlg.resize(800, 500)
            dlg_layout = QVBoxLayout(preview_dlg)

            dlg_layout.addWidget(QLabel(
                f"从书签文件中找到 {len(unique_bookmarks)} 个 Google Sheets 链接，"
                f"涉及 {len(set(b['folder_path'] for b in unique_bookmarks if b['folder_path']))} 个文件夹。\n"
                "文件夹结构将自动映射为分组（用 '->' 表示层级）。取消勾选可跳过不需要导入的项。"
            ))

            # 预览表格
            preview_table = QTableWidget()
            preview_table.setColumnCount(4)
            preview_table.setHorizontalHeaderLabels(
                ["✅", "书签名称", "书签目录 → 分组", "链接/ID"])
            preview_table.setRowCount(len(unique_bookmarks))
            preview_table.setAlternatingRowColors(True)
            preview_table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeToContents)
            preview_table.horizontalHeader().setSectionResizeMode(
                1, QHeaderView.Stretch)
            preview_table.horizontalHeader().setSectionResizeMode(
                2, QHeaderView.Stretch)
            preview_table.horizontalHeader().setSectionResizeMode(
                3, QHeaderView.Stretch)
            preview_table.verticalHeader().setDefaultSectionSize(26)

            check_items = []
            for i, bm in enumerate(unique_bookmarks):
                # 勾选框
                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk.setCheckState(Qt.Checked)
                preview_table.setItem(i, 0, chk)
                check_items.append(chk)

                # 书签名称
                preview_table.setItem(i, 1, QTableWidgetItem(bm['name']))

                # 文件夹路径
                folder_display = bm['folder_path'] or "(根目录)"
                preview_table.setItem(i, 2, QTableWidgetItem(folder_display))

                # 链接 ID
                id_item = QTableWidgetItem(bm['sid'][:30])
                id_item.setToolTip(bm['link'])
                preview_table.setItem(i, 3, id_item)

            dlg_layout.addWidget(preview_table)

            # 选项行：根目录的书签归入哪个分组
            opt_row = QHBoxLayout()
            opt_row.addWidget(QLabel("无目录的书签归入分组:"))
            root_group_combo = QComboBox()
            root_group_combo.setEditable(True)
            root_group_combo.setMinimumWidth(120)
            root_group_combo.addItems(self.library.get_group_names())
            root_group_combo.setCurrentText("书签导入")
            opt_row.addWidget(root_group_combo)

            opt_row.addStretch()

            select_all_btn = QPushButton("全选")
            select_all_btn.setMaximumWidth(60)
            select_all_btn.clicked.connect(
                lambda: [c.setCheckState(Qt.Checked) for c in check_items])
            opt_row.addWidget(select_all_btn)

            deselect_all_btn = QPushButton("全不选")
            deselect_all_btn.setMaximumWidth(60)
            deselect_all_btn.clicked.connect(
                lambda: [c.setCheckState(Qt.Unchecked) for c in check_items])
            opt_row.addWidget(deselect_all_btn)

            dlg_layout.addLayout(opt_row)

            # 按钮行
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            import_confirm_btn = QPushButton("🚀 确认导入")
            import_confirm_btn.clicked.connect(preview_dlg.accept)
            btn_row.addWidget(import_confirm_btn)
            cancel_btn = QPushButton("取消")
            cancel_btn.clicked.connect(preview_dlg.reject)
            btn_row.addWidget(cancel_btn)
            dlg_layout.addLayout(btn_row)

            if preview_dlg.exec() != QDialog.Accepted:
                return

            # ---- 执行导入 ----
            root_group = root_group_combo.currentText().strip() or "默认"
            imported = 0
            skipped = 0

            for i, bm in enumerate(unique_bookmarks):
                if check_items[i].checkState() != Qt.Checked:
                    skipped += 1
                    continue

                # 确定分组名：有文件夹路径用路径，否则用根分组
                group_name = bm['folder_path'] if bm['folder_path'] else root_group

                self.library.add_entry(
                    name=bm['name'],
                    link=bm['link'],
                    group_name=group_name,
                    notes=f"从书签导入",
                )
                imported += 1

            self.refresh_all()

            # 更新导入结果表
            self.import_result.setRowCount(imported + skipped)
            row = 0
            for i, bm in enumerate(unique_bookmarks):
                checked = check_items[i].checkState() == Qt.Checked
                self.import_result.setItem(row, 0, QTableWidgetItem(bm['name']))
                self.import_result.setItem(row, 1, QTableWidgetItem(bm['sid'][:25]))
                self.import_result.setItem(
                    row, 2, QTableWidgetItem("✅" if checked else "⏭️"))
                detail = bm['folder_path'] or root_group if checked else "已跳过"
                self.import_result.setItem(row, 3, QTableWidgetItem(detail))
                row += 1

            self.import_status.setText(
                f"🔖 书签导入完成: {imported} 条已导入, {skipped} 条已跳过"
            )

        except Exception as e:
            self.import_status.setText(f"❌ 读取书签文件失败: {str(e)}")
            logger.error(f"书签导入失败: {e}", exc_info=True)

    # ========================
    # 数据刷新
    # ========================

    def refresh_all(self):
        self._refresh_groups()
        self._refresh_table()
        self._refresh_group_combo()
        self._refresh_import_group_combo()

    def _refresh_groups(self):
        self.group_tree.clear()

        all_item = QTreeWidgetItem(self.group_tree)
        all_item.setText(0, "📁 全部")
        all_item.setData(0, Qt.UserRole, "__all__")
        all_item.setText(1, str(len(self.library.entries)))

        # 构建无限极树结构
        # tree = { "node_name": { "_gid": gid/None, "_full_path": "A->B", "children": { ... } } }
        tree_struct = {}

        for gid, g in self.library.groups.items():
            full_name = g['name']
            parts = [p.strip() for p in full_name.split("->")]
            
            curr_level = tree_struct
            current_path = ""
            for i, part in enumerate(parts):
                current_path = f"{current_path}->{part}" if current_path else part
                is_leaf = (i == len(parts) - 1)
                
                if part not in curr_level:
                    curr_level[part] = {
                        "_gid": gid if is_leaf else None,
                        "_full_path": current_path,
                        "children": {}
                    }
                else:
                    if is_leaf:
                        curr_level[part]["_gid"] = gid
                
                curr_level = curr_level[part]["children"]

        # 递归构建 QTreeWidgetItem
        def build_nodes(parent_widget, children_dict):
            for name, data in sorted(children_dict.items(), key=lambda x: x[0]):
                node = QTreeWidgetItem(parent_widget)
                
                gid = data["_gid"]
                has_children = len(data["children"]) > 0
                
                # 图标：有子节点是 📁，否则是 📄
                icon = "📁" if has_children else "📄"
                node.setText(0, f"{icon} {name}")
                
                if gid:
                    node.setData(0, Qt.UserRole, gid)
                    node.setText(1, str(len(self.library.get_entries_by_group(gid))))
                else:
                    node.setData(0, Qt.UserRole, "__virtual_parent__")
                    node.setText(1, "")
                
                # 保存完整路径以备右键操作使用
                node.setData(0, Qt.UserRole + 1, data["_full_path"])
                
                if has_children:
                    build_nodes(node, data["children"])

        build_nodes(self.group_tree, tree_struct)
        self.group_tree.expandAll()

    def _refresh_table(self, entries=None):
        items = entries if entries is not None else self.library.entries
        # 排序：星标置顶，然后按分组，最后按时间倒序
        items = sorted(
            items,
            key=lambda x: (
                not x.get("is_starred", False),
                self.library.get_group_name(x.get("group_id", "default")),
                x.get("updated", "")
            ),
            reverse=False
        )
        
        self.table.setRowCount(len(items))

        for i, e in enumerate(items):
            # ⭐
            star_text = "⭐" if e.get("is_starred", False) else ""
            star_item = QTableWidgetItem(star_text)
            star_item.setTextAlignment(Qt.AlignCenter)
            star_item.setData(Qt.UserRole, e.get("id"))
            self.table.setItem(i, 0, star_item)
            
            # 名称
            name_item = QTableWidgetItem(e.get("name", ""))
            self.table.setItem(i, 1, name_item)

            # 分组
            group_name = self.library.get_group_name(e.get("group_id", "default"))
            self.table.setItem(i, 2, QTableWidgetItem(group_name))

            # 标签
            tags_str = ", ".join(e.get("tags", []))
            self.table.setItem(i, 3, QTableWidgetItem(tags_str))

            # 链接/ID
            sid = e.get("spreadsheet_id", "")
            link_item = QTableWidgetItem(sid or e.get("link", ""))
            link_item.setToolTip(e.get("link", ""))
            self.table.setItem(i, 4, link_item)

            # 备注
            self.table.setItem(i, 5, QTableWidgetItem(e.get("notes", "")))

            # 健康状态
            health = e.get("health_status", "unknown")
            status_map = {
                "ok": "🟢",
                "warning": "🟡",
                "error": "🔴",
                "unknown": "⚪"
            }
            status_icon = status_map.get(health, "⚪")
            health_item = QTableWidgetItem(status_icon)
            health_item.setTextAlignment(Qt.AlignCenter)
            health_item.setToolTip(e.get("health_detail", ""))
            self.table.setItem(i, 6, health_item)

            # 更新时间
            updated = e.get("updated", "")[:16].replace("T", " ")
            self.table.setItem(i, 7, QTableWidgetItem(updated))

        self.info_label.setText(f"📊 共 {len(items)} 条记录")

    def _refresh_group_combo(self):
        cur = self.edit_group.currentText()
        self.edit_group.blockSignals(True)
        self.edit_group.clear()
        self.edit_group.addItems(self.library.get_group_names())
        idx = self.edit_group.findText(cur)
        if idx >= 0:
            self.edit_group.setCurrentIndex(idx)
        elif self.edit_group.count() > 0:
            self.edit_group.setCurrentIndex(0)
        self.edit_group.blockSignals(False)

    def _refresh_import_group_combo(self):
        cur = self.import_group.currentText()
        self.import_group.blockSignals(True)
        self.import_group.clear()
        self.import_group.addItems(self.library.get_group_names())
        idx = self.import_group.findText(cur)
        if idx >= 0:
            self.import_group.setCurrentIndex(idx)
        elif self.import_group.count() > 0:
            self.import_group.setCurrentIndex(0)
        self.import_group.blockSignals(False)

    # ========================
    # 分组操作
    # ========================

    def _on_group_select(self, current, previous):
        if not current:
            return
        gid = current.data(0, Qt.UserRole)
        # 忽略虚拟父节点点击
        if gid == "__virtual_parent__":
            return

        # 切换分组时清空搜索
        if self.search_input.text().strip():
            return  # 搜索模式下不跟随分组

        if gid == "__all__":
            self._refresh_table()
        else:
            self._refresh_table(self.library.get_entries_by_group(gid))

    def _add_group(self):
        name, ok = QInputDialog.getText(self, "新增一级分组", "分组名称:")
        if ok and name.strip():
            self.library.add_group(name.strip())
            self.refresh_all()

    def _add_sub_group(self, item):
        self.group_tree.setCurrentItem(item)
        parent_full_name = item.data(0, Qt.UserRole + 1)
        
        name, ok = QInputDialog.getText(self, "添加子分组", f"在【{parent_full_name}】下添加子分组:")
        if ok and name.strip():
            new_full_name = f"{parent_full_name}->{name.strip()}"
            self.library.add_group(new_full_name)
            self.refresh_all()

    def _show_group_context_menu(self, pos):
        item = self.group_tree.itemAt(pos)
        menu = QMenu(self)

        add_main_action = QAction("➕ 新增一级分组", self)
        add_main_action.triggered.connect(self._add_group)
        menu.addAction(add_main_action)

        if item:
            gid = item.data(0, Qt.UserRole)
            if gid not in ("__all__", "default"):
                menu.addSeparator()

                add_sub_action = QAction("📂 添加子分组", self)
                add_sub_action.triggered.connect(lambda: self._add_sub_group(item))
                menu.addAction(add_sub_action)

                if gid != "__virtual_parent__":
                    rename_action = QAction("✏️ 重命名", self)
                    rename_action.triggered.connect(self._rename_group)
                    del_action = QAction("🗑 删除", self)
                    del_action.triggered.connect(self._delete_group)
                    
                    menu.addSeparator()
                    menu.addAction(rename_action)
                    menu.addAction(del_action)

        menu.exec_(self.group_tree.mapToGlobal(pos))

    def _rename_group(self):
        current = self.group_tree.currentItem()
        if not current:
            return
        gid = current.data(0, Qt.UserRole)
        if gid in ("__all__", "__virtual_parent__"):
            return
        old_name = self.library.groups.get(gid, {}).get("name", "")
        new_name, ok = QInputDialog.getText(self, "重命名分组", "新名称(可用'->'创建层级):", text=old_name)
        if ok and new_name.strip():
            self.library.rename_group(gid, new_name.strip())
            self.refresh_all()

    def _delete_group(self):
        current = self.group_tree.currentItem()
        if not current:
            return
        gid = current.data(0, Qt.UserRole)
        if gid in ("__all__", "default", "__virtual_parent__"):
            return
        name = self.library.groups.get(gid, {}).get("name", "")
        if QMessageBox.question(
            self, "确认", f"删除分组「{name}」？\n其中的条目将移至「默认」分组。",
            QMessageBox.Yes | QMessageBox.No
        ) == QMessageBox.Yes:
            self.library.delete_group(gid)
            self.refresh_all()

    def _on_group_dropped(self, group_id: str, new_path: str):
        logger.info(f"Group moved: ID={group_id}, NewPath={new_path}")
        self.library.move_group(group_id, new_path)
        self.refresh_all()


    # ========================
    # 条目操作
    # ========================

    def _show_table_context_menu(self, pos):
        """表格右键菜单"""
        entries = self._get_selected_entries()
        if not entries:
            return

        menu = QMenu(self)

        open_action = QAction("🌐 在浏览器中打开", self)
        open_action.triggered.connect(self._open_selected_in_browser)
        menu.addAction(open_action)

        connect_action = QAction("🔗 快速连接首个表格", self)
        connect_action.triggered.connect(self._quick_connect_selected)
        menu.addAction(connect_action)
        menu.addSeparator()

        star_action = QAction("🌟 切换星标状态", self)
        star_action.triggered.connect(self._toggle_star_selected)
        menu.addAction(star_action)
        menu.addSeparator()

        note_action = QAction("📝 查看批注", self)
        note_action.triggered.connect(self._open_note_viewer)
        menu.addAction(note_action)

        perm_action = QAction("🔐 协作者管理", self)
        perm_action.triggered.connect(self._open_permission_manager)
        menu.addAction(perm_action)

        health_action = QAction("⏱️ 巡检选中表格", self)
        health_action.triggered.connect(self._start_health_check_selected)
        menu.addAction(health_action)
        menu.addSeparator()

        del_action = QAction("🗑 删除选中表格", self)
        del_action.triggered.connect(self._delete_selected_entries)
        menu.addAction(del_action)

        menu.exec_(self.table.viewport().mapToGlobal(pos))

    def _toggle_star_selected(self):
        """切换选中表格的星标状态"""
        entries = self._get_selected_entries()
        if not entries:
            return

        # 如果选中的第一个是有星标的，则全部取消，否则全部打星标
        target_star = not entries[0].get("is_starred", False)
        
        for entry in entries:
            self.library.update_entry(entry["id"], is_starred=target_star)
        
        self.refresh_all()
        status = "已置顶" if target_star else "已取消星标"
        self.info_label.setText(f"🌟 {status} {len(entries)} 个表格")

    def _open_note_viewer(self):
        """打开批注查看器"""
        entries = self._get_selected_entries()
        if not entries:
            self.info_label.setText("⚠️ 请先选择要查看批注的表格")
            return

        entry = entries[0]
        sid = entry.get("spreadsheet_id", "")
        name = entry.get("name", "")
        if not sid:
            self.info_label.setText("⚠️ 选中的表格缺少 Spreadsheet ID")
            return

        dlg = NoteViewerDialog(sid, name, parent=self)
        dlg.exec()

    def _open_permission_manager(self):
        """打开协作者权限管理对话框"""
        entries = self._get_selected_entries()
        if not entries:
            self.info_label.setText("⚠️ 请先选择要管理权限的表格")
            return

        # 过滤出有 spreadsheet_id 的条目
        valid = [e for e in entries if e.get("spreadsheet_id")]
        if not valid:
            self.info_label.setText("⚠️ 选中的表格缺少 Spreadsheet ID")
            return

        dlg = PermissionManagerDialog(valid, parent=self)
        dlg.exec()

    def _on_entry_select(self, row, col, prev_row, prev_col):
        if row < 0:
            return
        item = self.table.item(row, 0)
        if not item:
            return
        eid = item.data(Qt.UserRole)
        entry = self.library.get_entry(eid)
        if not entry:
            return

        self._selected_entry_id = eid
        self.edit_name.setText(entry.get("name", ""))
        self.edit_link.setText(entry.get("link", ""))
        self.edit_notes.setText(entry.get("notes", ""))
        self.edit_tags.setText(", ".join(entry.get("tags", [])))
        self.edit_star.setChecked(entry.get("is_starred", False))

        group_name = self.library.get_group_name(entry.get("group_id", "default"))
        idx = self.edit_group.findText(group_name)
        if idx >= 0:
            self.edit_group.setCurrentIndex(idx)

    def _add_entry(self):
        name = self.edit_name.text().strip()
        link = self.edit_link.text().strip()
        if not name or not link:
            self.info_label.setText("⚠️ 请输入表格名称和链接")
            return

        group_name = self.edit_group.currentText()
        notes = self.edit_notes.text().strip()
        
        tags_raw = self.edit_tags.text().strip()
        tags = [t.strip() for t in tags_raw.split(',')] if tags_raw else []
        is_starred = self.edit_star.isChecked()

        self.library.add_entry(name, link, group_name, notes, is_starred=is_starred, tags=tags)
        self.refresh_all()
        self._clear_edit()
        self.info_label.setText(f"✅ 已添加: {name}")

    def _save_entry(self):
        if not self._selected_entry_id:
            self.info_label.setText("⚠️ 请先选择要修改的条目")
            return

        tags_raw = self.edit_tags.text().strip()
        tags = [t.strip() for t in tags_raw.split(',')] if tags_raw else []

        self.library.update_entry(
            self._selected_entry_id,
            name=self.edit_name.text().strip(),
            link=self.edit_link.text().strip(),
            notes=self.edit_notes.text().strip(),
            group_name=self.edit_group.currentText(),
            tags=tags,
            is_starred=self.edit_star.isChecked()
        )
        self.refresh_all()
        self.info_label.setText("💾 已保存修改")

    def _delete_selected_entries(self):
        """删除所有选中的条目"""
        entries = self._get_selected_entries()
        if not entries:
            self.info_label.setText("⚠️ 请先选择要删除的条目")
            return

        if len(entries) == 1:
            name = entries[0].get("name", "")
            msg = f"删除表格「{name}」？"
        else:
            msg = f"删除选中的 {len(entries)} 个表格？"

        if QMessageBox.question(
            self, "确认", msg, QMessageBox.Yes | QMessageBox.No
        ) == QMessageBox.Yes:
            for entry in entries:
                self.library.delete_entry(entry["id"])
            self._selected_entry_id = None
            self.refresh_all()
            self._clear_edit()
            self.info_label.setText(f"🗑 已删除 {len(entries)} 条记录")

    def _clear_edit(self):
        self.edit_name.clear()
        self.edit_link.clear()
        self.edit_notes.clear()
        self.edit_tags.clear()
        self.edit_star.setChecked(False)
        self._selected_entry_id = None

    # ========================
    # 健康巡检
    # ========================

    def _start_health_check_all(self):
        """巡检全部表格"""
        entries = self.library.entries
        if not entries:
            self.info_label.setText("⚠️ 表格库无数据")
            return
        self._run_health_check(entries)

    def _start_health_check_selected(self):
        """巡检选中表格"""
        entries = self._get_selected_entries()
        if not entries:
            self.info_label.setText("⚠️ 请先选择要巡检的表格")
            return
        self._run_health_check(entries)

    def _run_health_check(self, entries):
        """启动健康巡检"""
        if self._health_worker and self._health_worker.isRunning():
            self.info_label.setText("⚠️ 巡检正在进行中...")
            return

        self.health_btn.setEnabled(False)
        self.health_btn.setText("⏳ 巡检中...")
        self.info_label.setText(f"⏱️ 正在巡检 {len(entries)} 个表格...")

        self._health_worker = HealthCheckWorker(entries)
        self._health_worker.entry_checked.connect(self._on_entry_health_checked)
        self._health_worker.progress.connect(
            lambda c, t, m: self.info_label.setText(f"⏱️ {m}")
        )
        self._health_worker.all_done.connect(self._on_health_done)
        self._health_worker.start()

    def _on_entry_health_checked(self, entry_id, status, detail):
        """单个条目巡检完成 — 更新持久化状态并刷新表格行"""
        self.library.update_health(entry_id, status, detail)
        # 尝试在当前表格中找到并更新对应行
        status_map = {"ok": "🟢", "warning": "🟡", "error": "🔴", "unknown": "⚪"}
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == entry_id:
                icon = status_map.get(status, "⚪")
                health_item = QTableWidgetItem(icon)
                health_item.setTextAlignment(Qt.AlignCenter)
                health_item.setToolTip(detail)
                self.table.setItem(row, 6, health_item)
                break

    def _on_health_done(self):
        """全部巡检完成"""
        self.health_btn.setEnabled(True)
        self.health_btn.setText("⏱️ 巡检全部")
        self.info_label.setText("✅ 健康巡检完成")
        self._health_worker = None

    # ========================
    # 导出 / 导入
    # ========================

    def _export_data(self):
        """导出表格库数据为 JSON 文件"""
        # 判断是否有选中分组
        current = self.group_tree.currentItem()
        group_id = None
        if current:
            gid = current.data(0, Qt.UserRole)
            if gid not in ("__all__", "__virtual_parent__"):
                group_id = gid

        data = self.library.export_data(group_id)

        # 默认文件名
        import json
        from datetime import datetime
        default_name = f"表格库导出_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        path, _ = QFileDialog.getSaveFileName(
            self, "导出表格库", default_name,
            "JSON 文件 (*.json)"
        )
        if not path:
            return

        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            count = len(data.get("entries", []))
            self.info_label.setText(f"📤 已导出 {count} 条记录到 {path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _import_data(self):
        """从 JSON 文件导入表格库数据"""
        import json

        path, _ = QFileDialog.getOpenFileName(
            self, "导入表格库", "",
            "JSON 文件 (*.json)"
        )
        if not path:
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "读取失败", f"无法解析 JSON 文件:\n{e}")
            return

        # 确认格式
        if "entries" not in data:
            QMessageBox.warning(self, "格式错误", "文件中缺少 entries 字段，不是有效的表格库导出文件")
            return

        count = len(data.get("entries", []))

        # 询问合并还是覆盖
        reply = QMessageBox.question(
            self, "导入方式",
            f"该文件包含 {count} 条记录。\n\n"
            "选择导入方式：\n"
            "【Yes】合并 — 按 Spreadsheet ID 去重，保留现有数据\n"
            "【No】覆盖 — 替换全部现有数据",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
        )

        if reply == QMessageBox.Cancel:
            return

        merge = (reply == QMessageBox.Yes)
        stats = self.library.import_data(data, merge=merge)

        self.refresh_all()
        mode = "合并" if merge else "覆盖"
        self.info_label.setText(
            f"📥 {mode}导入完成: "
            f"新增 {stats['added']}, 跳过 {stats['skipped']}, "
            f"新增分组 {stats['groups_added']}"
        )


class SpreadsheetLibraryDialog(QDialog):
    """
    表格库独立窗口 — 多账号 Tab 管理。
    每个 Tab 是一个 AccountPanel，对应一个独立账号。
    """

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.account_mgr = AccountManager()
        self._panels = {}  # acc_id -> AccountPanel
        self._setup_ui()
        self._load_tabs()

    def _setup_ui(self):
        self.setWindowTitle("📂 表格库管理器")
        self.setMinimumSize(950, 650)
        self.resize(1050, 720)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 6, 6, 6)

        # ======== 账号 Tab ========
        self.account_tabs = QTabWidget()
        self.account_tabs.setTabsClosable(False)
        self.account_tabs.setMovable(True)
        self.account_tabs.currentChanged.connect(self._on_tab_changed)

        # Tab 栏右键菜单
        self.account_tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.account_tabs.tabBar().customContextMenuRequested.connect(
            self._show_tab_context_menu)

        # 右上角"+"按钮
        add_btn = QToolButton()
        add_btn.setText("＋")
        add_btn.setToolTip("添加新账号")
        add_btn.clicked.connect(self._add_account)
        self.account_tabs.setCornerWidget(add_btn, Qt.TopRightCorner)

        layout.addWidget(self.account_tabs)

        # ======== 底部全局搜索 ========
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("🔍 全局搜索:"))
        self._global_search = QLineEdit()
        self._global_search.setPlaceholderText(
            "跨所有账号搜索表格（名称/链接/备注）...")
        self._global_search.setClearButtonEnabled(True)
        self._global_search.returnPressed.connect(self._do_global_search)
        search_row.addWidget(self._global_search)

        global_btn = QPushButton("🔍 搜索")
        global_btn.clicked.connect(self._do_global_search)
        global_btn.setMaximumWidth(80)
        search_row.addWidget(global_btn)

        self._global_count = QLabel("")
        self._global_count.setMinimumWidth(80)
        search_row.addWidget(self._global_count)
        layout.addLayout(search_row)

        # 全局搜索结果表
        self._global_table = QTableWidget()
        self._global_table.setColumnCount(5)
        self._global_table.setHorizontalHeaderLabels(
            ["账号", "⭐", "名称", "分组", "链接/ID"])
        self._global_table.setAlternatingRowColors(True)
        self._global_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._global_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._global_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self._global_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents)
        self._global_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self._global_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents)
        self._global_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.Stretch)
        self._global_table.setMaximumHeight(180)
        self._global_table.setVisible(False)
        self._global_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._global_table.customContextMenuRequested.connect(
            self._show_global_result_menu)
        layout.addWidget(self._global_table)

        # ======== 底部备份/恢复按钮 ========
        backup_row = QHBoxLayout()
        backup_row.addStretch()

        self._backup_status = QLabel("")
        backup_row.addWidget(self._backup_status)

        backup_export_btn = QPushButton("💾 备份全部数据")
        backup_export_btn.setToolTip(
            "将所有账号的表格库数据打包备份为 ZIP 文件")
        backup_export_btn.clicked.connect(self._backup_all_data)
        backup_row.addWidget(backup_export_btn)

        backup_restore_btn = QPushButton("📂 从备份恢复")
        backup_restore_btn.setToolTip(
            "从之前导出的 ZIP 备份文件中恢复所有账号数据")
        backup_restore_btn.clicked.connect(self._restore_from_backup)
        backup_row.addWidget(backup_restore_btn)

        layout.addLayout(backup_row)

    def _load_tabs(self):
        """根据 AccountManager 中的账号列表创建 Tab"""
        self.account_tabs.blockSignals(True)
        for acc in self.account_mgr.accounts:
            lib = self.account_mgr.get_library(acc["id"])
            panel = AccountPanel(lib, self.controller, self)
            self._panels[acc["id"]] = panel
            self.account_tabs.addTab(panel, acc["name"])
        # 定位到上次的活动 Tab
        if self.account_mgr.active_index < self.account_tabs.count():
            self.account_tabs.setCurrentIndex(
                self.account_mgr.active_index)
        self.account_tabs.blockSignals(False)

    def _on_tab_changed(self, idx):
        if idx >= 0:
            self.account_mgr.active_index = idx

    # ======== 账号操作 ========

    def _add_account(self):
        name, ok = QInputDialog.getText(
            self, "新增账号", "账号名称:")
        if ok and name.strip():
            acc_id = self.account_mgr.add_account(name.strip())
            lib = self.account_mgr.get_library(acc_id)
            panel = AccountPanel(lib, self.controller, self)
            self._panels[acc_id] = panel
            self.account_tabs.addTab(panel, name.strip())
            self.account_tabs.setCurrentIndex(
                self.account_tabs.count() - 1)

    def _show_tab_context_menu(self, pos):
        idx = self.account_tabs.tabBar().tabAt(pos)
        if idx < 0:
            return

        accounts = self.account_mgr.accounts
        if idx >= len(accounts):
            return
        acc = accounts[idx]

        menu = QMenu(self)

        rename_act = QAction("✏️ 重命名", self)
        rename_act.triggered.connect(lambda: self._rename_account(idx, acc))
        menu.addAction(rename_act)

        if len(accounts) > 1:
            del_act = QAction("🗑 删除此账号", self)
            del_act.triggered.connect(
                lambda: self._delete_account(idx, acc))
            menu.addAction(del_act)

        menu.addSeparator()
        add_act = QAction("＋ 添加新账号", self)
        add_act.triggered.connect(self._add_account)
        menu.addAction(add_act)

        menu.exec(self.account_tabs.tabBar().mapToGlobal(pos))

    def _rename_account(self, idx, acc):
        new_name, ok = QInputDialog.getText(
            self, "重命名账号", "新名称:", text=acc["name"])
        if ok and new_name.strip():
            self.account_mgr.rename_account(acc["id"], new_name.strip())
            self.account_tabs.setTabText(idx, new_name.strip())

    def _delete_account(self, idx, acc):
        if QMessageBox.question(
            self, "确认",
            f"删除账号「{acc['name']}」？\n该账号下的所有数据将被永久删除！",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        self.account_mgr.delete_account(acc["id"])
        self._panels.pop(acc["id"], None)
        self.account_tabs.removeTab(idx)

    # ======== 全局搜索 ========

    def _do_global_search(self):
        keyword = self._global_search.text().strip()
        if not keyword:
            self._global_table.setVisible(False)
            self._global_count.setText("")
            return

        results = self.account_mgr.search_all(keyword)
        self._global_table.setRowCount(len(results))
        self._global_table.setVisible(True)

        for i, r in enumerate(results):
            e = r["entry"]
            self._global_table.setItem(
                i, 0, QTableWidgetItem(r["account_name"]))
            star = "⭐" if e.get("is_starred") else ""
            si = QTableWidgetItem(star)
            si.setTextAlignment(Qt.AlignCenter)
            self._global_table.setItem(i, 1, si)
            self._global_table.setItem(
                i, 2, QTableWidgetItem(e.get("name", "")))

            # 获取对应 library 查分组名
            lib = self.account_mgr.get_library(r["account_id"])
            gname = lib.get_group_name(
                e.get("group_id", "default")) if lib else ""
            self._global_table.setItem(i, 3, QTableWidgetItem(gname))

            sid = e.get("spreadsheet_id", "")
            link_item = QTableWidgetItem(sid or e.get("link", ""))
            link_item.setToolTip(e.get("link", ""))
            # 存储完整信息以备右键使用
            link_item.setData(Qt.UserRole, r)
            self._global_table.setItem(i, 4, link_item)

        self._global_count.setText(f"找到 {len(results)} 条")

    def _show_global_result_menu(self, pos):
        row = self._global_table.currentRow()
        if row < 0:
            return
        item = self._global_table.item(row, 4)
        if not item:
            return
        r = item.data(Qt.UserRole)
        if not r:
            return

        e = r["entry"]
        menu = QMenu(self)

        open_act = QAction(
            f"🌐 打开: {e.get('name', '')[:25]}", self)
        open_act.triggered.connect(lambda: self._open_global_entry(e))
        menu.addAction(open_act)

        copy_act = QAction("📋 复制链接", self)
        copy_act.triggered.connect(
            lambda: self._copy_global_entry(e))
        menu.addAction(copy_act)

        menu.exec(self._global_table.viewport().mapToGlobal(pos))

    def _open_global_entry(self, entry):
        link = entry.get("link", "")
        sid = entry.get("spreadsheet_id", "")
        if link and link.startswith("http"):
            webbrowser.open(link)
        elif sid:
            webbrowser.open(
                f"https://docs.google.com/spreadsheets/d/{sid}/edit")

    def _copy_global_entry(self, entry):
        from PySide6.QtWidgets import QApplication
        link = entry.get("link", "")
        sid = entry.get("spreadsheet_id", "")
        text = link if link else (
            f"https://docs.google.com/spreadsheets/d/{sid}/edit"
            if sid else "")
        if text:
            QApplication.clipboard().setText(text)

    # ======== 备份 / 恢复 ========

    def _backup_all_data(self):
        """将所有账号数据打包为 ZIP 备份文件"""
        import json
        import zipfile
        import shutil
        from datetime import datetime

        accounts = self.account_mgr.accounts
        if not accounts:
            self._backup_status.setText("⚠️ 没有账号数据可备份")
            return

        # 统计条目总数
        total_entries = 0
        for acc in accounts:
            lib = self.account_mgr.get_library(acc["id"])
            if lib:
                total_entries += len(lib.entries)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        default_name = f"表格库全量备份_{timestamp}.zip"

        path, _ = QFileDialog.getSaveFileName(
            self, "备份全部数据", default_name,
            "ZIP 压缩文件 (*.zip)"
        )
        if not path:
            return

        try:
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
                # 1. 写入账号元数据
                meta = {
                    "version": "2.0",
                    "backup_type": "full",
                    "backup_at": datetime.now().isoformat(),
                    "account_count": len(accounts),
                    "total_entries": total_entries,
                    "accounts": accounts,
                    "active_index": self.account_mgr.active_index,
                }
                zf.writestr(
                    "backup_meta.json",
                    json.dumps(meta, ensure_ascii=False, indent=2)
                )

                # 2. 将每个账号的数据导出为 JSON 并打包
                for acc in accounts:
                    lib = self.account_mgr.get_library(acc["id"])
                    if not lib:
                        continue
                    data = lib.export_data()
                    data["account_id"] = acc["id"]
                    data["account_name"] = acc["name"]
                    filename = f"account_{acc['id']}.json"
                    zf.writestr(
                        filename,
                        json.dumps(data, ensure_ascii=False, indent=2)
                    )

            self._backup_status.setText(
                f"💾 备份成功: {len(accounts)} 个账号, "
                f"{total_entries} 条记录"
            )
            QMessageBox.information(
                self, "备份成功",
                f"已备份 {len(accounts)} 个账号、{total_entries} 条记录\n\n"
                f"文件: {path}"
            )
        except Exception as e:
            QMessageBox.warning(self, "备份失败", f"备份过程中发生错误:\n{e}")
            logger.error(f"备份失败: {e}", exc_info=True)

    def _restore_from_backup(self):
        """从 ZIP 备份文件恢复所有账号数据"""
        import json
        import zipfile

        path, _ = QFileDialog.getOpenFileName(
            self, "选择备份文件", "",
            "ZIP 压缩文件 (*.zip)"
        )
        if not path:
            return

        try:
            with zipfile.ZipFile(path, 'r') as zf:
                # 1. 读取元数据
                if "backup_meta.json" not in zf.namelist():
                    QMessageBox.warning(
                        self, "格式错误",
                        "所选文件不是有效的表格库备份文件。\n"
                        "（缺少 backup_meta.json）"
                    )
                    return

                meta = json.loads(zf.read("backup_meta.json").decode('utf-8'))
                acc_count = meta.get("account_count", 0)
                entry_count = meta.get("total_entries", 0)
                backup_time = meta.get("backup_at", "未知")[:19].replace("T", " ")

                # 2. 确认恢复
                reply = QMessageBox.warning(
                    self, "确认恢复",
                    f"即将从备份文件恢复数据：\n\n"
                    f"📅 备份时间: {backup_time}\n"
                    f"👤 账号数量: {acc_count}\n"
                    f"📊 条目总数: {entry_count}\n\n"
                    f"⚠️ 恢复方式：\n"
                    f"【Yes】合并 — 新增备份中的账号和条目，保留现有数据\n"
                    f"【No】覆盖 — 清除现有数据并完全替换为备份内容\n",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
                )

                if reply == QMessageBox.Cancel:
                    return

                merge_mode = (reply == QMessageBox.Yes)

                # 3. 读取所有账号数据文件
                account_data_list = []
                backup_accounts = meta.get("accounts", [])
                for acc in backup_accounts:
                    filename = f"account_{acc['id']}.json"
                    if filename in zf.namelist():
                        data = json.loads(zf.read(filename).decode('utf-8'))
                        account_data_list.append({
                            "account": acc,
                            "data": data,
                        })

            # 4. 执行恢复
            stats = {"accounts_added": 0, "entries_added": 0,
                     "entries_skipped": 0}

            if not merge_mode:
                # 覆盖模式：删除所有现有账号，重新创建
                existing_ids = [a["id"] for a in self.account_mgr.accounts]
                # 先清除缓存的 library 实例
                self.account_mgr._libraries.clear()
                self.account_mgr._accounts.clear()

                for item in account_data_list:
                    acc = item["account"]
                    data = item["data"]
                    acc_id = self.account_mgr.add_account(acc["name"])
                    lib = self.account_mgr.get_library(acc_id)
                    if lib:
                        import_stats = lib.import_data(data, merge=False)
                        stats["entries_added"] += import_stats["added"]
                    stats["accounts_added"] += 1

                self.account_mgr._save_accounts()
            else:
                # 合并模式：按账号名匹配，已有账号合并条目，新账号创建
                existing_names = {
                    a["name"]: a["id"] for a in self.account_mgr.accounts
                }
                for item in account_data_list:
                    acc = item["account"]
                    data = item["data"]
                    acc_name = acc["name"]

                    if acc_name in existing_names:
                        # 已有账号 — 合并条目
                        acc_id = existing_names[acc_name]
                    else:
                        # 新账号 — 创建
                        acc_id = self.account_mgr.add_account(acc_name)
                        stats["accounts_added"] += 1

                    lib = self.account_mgr.get_library(acc_id)
                    if lib:
                        import_stats = lib.import_data(data, merge=True)
                        stats["entries_added"] += import_stats["added"]
                        stats["entries_skipped"] += import_stats["skipped"]

            # 5. 重载 UI
            self._panels.clear()
            self.account_tabs.blockSignals(True)
            while self.account_tabs.count() > 0:
                self.account_tabs.removeTab(0)
            self.account_tabs.blockSignals(False)
            self._load_tabs()

            mode = "合并" if merge_mode else "覆盖"
            msg = (
                f"📂 {mode}恢复完成:\n"
                f"新增账号 {stats['accounts_added']} 个, "
                f"新增条目 {stats['entries_added']} 条"
            )
            if merge_mode:
                msg += f", 跳过 {stats['entries_skipped']} 条"

            self._backup_status.setText(msg.replace('\n', ' '))
            QMessageBox.information(self, "恢复完成", msg)

        except zipfile.BadZipFile:
            QMessageBox.warning(
                self, "文件错误",
                "所选文件不是有效的 ZIP 文件，请检查文件是否损坏。"
            )
        except Exception as e:
            QMessageBox.warning(self, "恢复失败", f"恢复过程中发生错误:\n{e}")
            logger.error(f"备份恢复失败: {e}", exc_info=True)

