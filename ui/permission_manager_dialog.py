# 协作者权限管理对话框 — 批量查看/修改/添加/移除表格协作者权限
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QGroupBox, QProgressBar, QMessageBox,
    QAbstractItemView, QCheckBox
)
from PySide6.QtCore import Qt, QThread, Signal
import re

logger = logging.getLogger("sheets_toolkit.ui.permission_manager_dialog")

class MultiEmailDialog(QDialog):
    def __init__(self, initial_text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量输入协作者邮箱")
        self.setMinimumSize(400, 300)
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("每行输入一个邮箱地址，或直接粘贴带逗号/空格分隔的邮箱列表："))
        
        from PySide6.QtWidgets import QTextEdit
        self.text_edit = QTextEdit()
        # 将逗号转换为换行以便于查看
        initial_text = initial_text.replace(",", "\n")
        self.text_edit.setPlainText(initial_text)
        layout.addWidget(self.text_edit)
        
        btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton("确定")
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)
        
    def get_emails_str(self):
        text = self.text_edit.toPlainText()
        # 按照空白字符（空格、换行等）或逗号分割
        raw_emails = re.split(r'[\s,]+', text)
        valid_emails = []
        for e in raw_emails:
            e = e.strip()
            if e and e not in valid_emails:
                valid_emails.append(e)
        return ",".join(valid_emails)

class MultiEmailLineEdit(QLineEdit):
    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        dlg = MultiEmailDialog(self.text(), self.parent())
        if dlg.exec():
            self.setText(dlg.get_emails_str())



class PermissionFetchWorker(QThread):
    """后台线程 — 批量拉取选中表格的协作者列表"""
    progress = Signal(int, int, str)
    entry_done = Signal(str, str, list)  # entry_id, title, permissions
    all_done = Signal()
    error = Signal(str)

    def __init__(self, entries):
        super().__init__()
        self.entries = entries  # [{"id": ..., "spreadsheet_id": ..., "name": ...}, ...]

    def run(self):
        try:
            from services.sheet_service import SheetService
            total = len(self.entries)
            for i, entry in enumerate(self.entries):
                sid = entry.get("spreadsheet_id", "")
                name = entry.get("name", sid[:20])
                eid = entry.get("id", "")
                if not sid:
                    continue
                self.progress.emit(i, total, f"({i+1}/{total}) 获取: {name}")
                try:
                    service = SheetService(sid)
                    perms = service.list_permissions()
                    self.entry_done.emit(eid, name, perms)
                except Exception as e:
                    logger.error(f"获取 {name} 权限失败: {e}")
                    self.entry_done.emit(eid, name, [])

            self.progress.emit(total, total, "完成")
            self.all_done.emit()
        except Exception as e:
            self.error.emit(str(e))


class PermissionActionWorker(QThread):
    """后台线程 — 执行权限操作（添加/修改/移除）"""
    progress = Signal(int, int, str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, action, spreadsheet_ids, **kwargs):
        super().__init__()
        self.action = action  # "add" / "update" / "remove"
        self.spreadsheet_ids = spreadsheet_ids
        self.kwargs = kwargs

    def run(self):
        try:
            from services.sheet_service import SheetService
            
            # 处理递归展开
            actual_sids = set()
            if self.kwargs.get("recursive_down", False):
                for sid in self.spreadsheet_ids:
                    actual_sids.add(sid)
                    try:
                        self.progress.emit(0, 0, f"正在递归获取 {sid[:10]}... 下的文件列表")
                        child_ids = SheetService.list_all_files_in_folder_recursive(sid)
                        actual_sids.update(child_ids)
                    except Exception as e:
                        logger.error(f"递归获取 {sid} 失败: {e}")
            else:
                actual_sids = set(self.spreadsheet_ids)
                
            actual_sids = list(actual_sids)
            total = len(actual_sids)
            success = 0

            for i, sid in enumerate(actual_sids):
                self.progress.emit(i, total, f"({i+1}/{total}) 处理中...")
                try:
                    service = SheetService(sid)
                    if self.action == "add":
                        emails = [e.strip() for e in self.kwargs["email"].split(",") if e.strip()]
                        for email in emails:
                            service.set_permission(
                                email,
                                self.kwargs.get("role", "writer")
                            )
                    elif self.action == "update":
                        service.update_permission(
                            self.kwargs["permission_id"],
                            self.kwargs["role"]
                        )
                    elif self.action == "set_secure":
                        service.set_copy_requires_writer_permission(self.kwargs.get("enable", True))
                    elif self.action == "set_owners_only":
                        service.set_writers_can_share_permission(not self.kwargs.get("enable", True))
                    elif self.action == "remove_all_secure":
                        service.set_copy_requires_writer_permission(False)
                        service.set_writers_can_share_permission(True)
                    elif self.action == "remove_all_permissions":
                        service.remove_all_permissions(recursive=self.kwargs.get("recursive_up", False))
                    elif self.action == "sync_permissions":
                        emails = [e.strip() for e in self.kwargs["email"].split(",") if e.strip()]
                        service.sync_permissions(emails, self.kwargs.get("role", "writer"), recursive_remove=self.kwargs.get("recursive_up", False))
                    elif self.action == "remove_anyone_permission":
                        service.remove_anyone_permission()
                    success += 1
                except Exception as e:
                    logger.error(f"权限操作失败 [{sid}]: {e}")

            self.finished.emit(f"完成: {success}/{total} 成功")
        except Exception as e:
            self.error.emit(str(e))


class PermissionManagerDialog(QDialog):
    """
    协作者权限管理对话框。

    显示选中表格的所有协作者权限，支持：
    - 批量添加新协作者
    - 修改协作者角色
    - 移除协作者
    """

    def __init__(self, entries, parent=None):
        """
        Args:
            entries: 选中的表格条目列表
                     [{"id": ..., "spreadsheet_id": ..., "name": ...}, ...]
        """
        super().__init__(parent)
        self.entries = entries
        self._worker = None
        self._action_worker = None
        # 缓存：{entry_id: {"name": ..., "sid": ..., "perms": [...]}}
        self._perm_cache = {}
        self._setup_ui()
        self._start_fetch()

    def _setup_ui(self):
        self.setWindowTitle(f"🔐 协作者权限管理 — {len(self.entries)} 个表格")
        self.setMinimumSize(850, 550)
        self.resize(950, 650)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ======= 表格列表 =======
        layout.addWidget(QLabel(f"📊 当前管理: {len(self.entries)} 个表格"))

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["表格名称", "协作者邮箱", "角色", "类型", "权限 ID"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setColumnHidden(4, True)  # 隐藏权限 ID
        self.table.verticalHeader().setDefaultSectionSize(28)
        layout.addWidget(self.table)

        # ======= 操作区 =======
        ops_group = QGroupBox("操作")
        ol = QVBoxLayout(ops_group)

        # 添加协作者
        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("📧 邮箱:"))
        self.email_input = MultiEmailLineEdit()
        self.email_input.setPlaceholderText("协作者邮箱地址 (可逗号分隔，双击批量输入)")
        add_row.addWidget(self.email_input)

        add_row.addWidget(QLabel("角色:"))
        self.role_combo = QComboBox()
        self.role_combo.addItems(["writer", "reader"])
        add_row.addWidget(self.role_combo)

        self.apply_all_check = QCheckBox("应用到全部表格")
        self.apply_all_check.setChecked(True)
        add_row.addWidget(self.apply_all_check)

        self.apply_recursive_check = QCheckBox("递归应用到所有子文件(对文件夹有效)")
        self.apply_recursive_check.setChecked(False)
        add_row.addWidget(self.apply_recursive_check)

        self.add_btn = QPushButton("➕ 添加协作者")
        self.add_btn.clicked.connect(self._add_collaborator)
        add_row.addWidget(self.add_btn)
        
        self.sync_btn = QPushButton("🔄 一键同步权限")
        self.sync_btn.setStyleSheet("background-color: #f39c12; color: white;")
        self.sync_btn.setToolTip("将选中表格的权限完全替换为上述输入框中的邮箱，并统一设置为左侧选定的角色。")
        self.sync_btn.clicked.connect(self._sync_permissions)
        add_row.addWidget(self.sync_btn)
        
        ol.addLayout(add_row)

        # 修改/移除
        action_row = QHBoxLayout()

        self.change_role_combo = QComboBox()
        self.change_role_combo.addItems(["writer", "reader"])
        action_row.addWidget(QLabel("🔄 修改选中为:"))
        action_row.addWidget(self.change_role_combo)

        self.update_btn = QPushButton("🔄 修改角色")
        self.update_btn.clicked.connect(self._update_selected_role)
        action_row.addWidget(self.update_btn)

        action_row.addStretch()
        
        self.remove_parent_recursive_check = QCheckBox("同时从父文件夹中移除该用户的访问权 (高危)")
        self.remove_parent_recursive_check.setStyleSheet("color: red; font-weight: bold;")
        action_row.addWidget(self.remove_parent_recursive_check)

        self.remove_btn = QPushButton("🗑 移除选中")
        self.remove_btn.setObjectName("danger_btn")
        self.remove_btn.clicked.connect(self._remove_selected)
        action_row.addWidget(self.remove_btn)

        self.accept_owner_btn = QPushButton("📥 接收选中(所有者)")
        self.accept_owner_btn.setStyleSheet("background-color: #2e7d32; color: white;")
        self.accept_owner_btn.clicked.connect(self._accept_selected_ownership)
        action_row.addWidget(self.accept_owner_btn)

        self.remove_all_btn = QPushButton("💣 移除所有人(保留所有者)")
        self.remove_all_btn.setStyleSheet("background-color: #d32f2f; color: white;")
        self.remove_all_btn.clicked.connect(self._remove_all_permissions)
        action_row.addWidget(self.remove_all_btn)

        self.remove_anyone_btn = QPushButton("🚫 取消公开访问 (转受限)")
        self.remove_anyone_btn.setStyleSheet("background-color: #795548; color: white;")
        self.remove_anyone_btn.clicked.connect(self._remove_anyone_permission)
        action_row.addWidget(self.remove_anyone_btn)

        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self._start_fetch)
        action_row.addWidget(self.refresh_btn)
        ol.addLayout(action_row)

        sec_layout = QHBoxLayout()
        sec_layout.addWidget(QLabel("🛡️ **高阶工作簿级安全限制**:"))
        
        self.btn_secure_on = QPushButton("🔒 防盗版全封锁 (禁止下载/复制)")
        self.btn_secure_on.setStyleSheet("background-color: #6a1b9a; color: white; border-radius: 4px; padding: 5px;")
        self.btn_secure_on.clicked.connect(lambda: self._set_secure_mode(True))
        sec_layout.addWidget(self.btn_secure_on)
        
        self.btn_owner_only_on = QPushButton("👑 独占分享权 (仅所有者可分享)")
        self.btn_owner_only_on.setStyleSheet("background-color: #1565c0; color: white; border-radius: 4px; padding: 5px;")
        self.btn_owner_only_on.clicked.connect(lambda: self._set_owner_only_mode(True))
        sec_layout.addWidget(self.btn_owner_only_on)
        
        self.btn_secure_off = QPushButton("🔓 抹除全部高级锁定")
        self.btn_secure_off.clicked.connect(lambda: self._remove_all_secure_modes())
        sec_layout.addWidget(self.btn_secure_off)
        sec_layout.addStretch()
        
        ol.addLayout(sec_layout)

        layout.addWidget(ops_group)

        # ======= 状态栏 =======
        bottom = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        bottom.addWidget(self.progress)
        self.status_label = QLabel("")
        bottom.addWidget(self.status_label)
        layout.addLayout(bottom)

    # ========================
    # 拉取权限
    # ========================

    def _start_fetch(self):
        """启动后台扫描协作者"""
        self.table.setRowCount(0)
        self._perm_cache.clear()
        self.progress.setVisible(True)
        self.progress.setMaximum(len(self.entries))
        self.progress.setValue(0)
        self.status_label.setText("⏳ 正在扫描协作者...")

        self._worker = PermissionFetchWorker(self.entries)
        self._worker.progress.connect(
            lambda c, t, m: (self.progress.setValue(c), self.status_label.setText(m))
        )
        self._worker.entry_done.connect(self._on_entry_perms)
        self._worker.all_done.connect(self._on_fetch_done)
        self._worker.error.connect(self._on_error)
        
        # 安全释放资源
        self._worker.all_done.connect(self._worker.deleteLater)
        self._worker.error.connect(lambda msg: self._worker.deleteLater())
        
        self._worker.start()

    def _on_entry_perms(self, entry_id, title, perms):
        """收到某个表格的权限列表 — 追加到表格"""
        # 找到对应条目的 sid
        sid = ""
        for e in self.entries:
            if e.get("id") == entry_id:
                sid = e.get("spreadsheet_id", "")
                break

        self._perm_cache[entry_id] = {
            "name": title, "sid": sid, "perms": perms
        }

        for p in perms:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # 表格名称（携带 sid 数据）
            name_item = QTableWidgetItem(title)
            name_item.setData(Qt.UserRole, sid)
            name_item.setData(Qt.UserRole + 1, entry_id)
            self.table.setItem(row, 0, name_item)

            # 邮箱
            email = p.get("emailAddress", p.get("displayName", "—"))
            self.table.setItem(row, 1, QTableWidgetItem(email))

            # 角色
            role = p.get("role", "—")
            role_display = {
                "owner": "👑 所有者",
                "writer": "✏️ 编辑者",
                "reader": "👁 阅读者",
                "commenter": "💬 评论者"
            }.get(role, role)
            
            if p.get("pendingOwner"):
                role_display = "⌛ 待接收 (所有者)"
                
            self.table.setItem(row, 2, QTableWidgetItem(role_display))

            # 类型
            ptype = p.get("type", "—")
            self.table.setItem(row, 3, QTableWidgetItem(ptype))

            # 权限 ID（隐藏列）
            self.table.setItem(row, 4, QTableWidgetItem(p.get("id", "")))

    def _on_fetch_done(self):
        """扫描完成"""
        self.progress.setVisible(False)
        total = self.table.rowCount()
        self.status_label.setText(f"✅ 扫描完成: 共 {total} 条权限记录")
        self._worker = None

    def _on_error(self, msg):
        self.progress.setVisible(False)
        self.status_label.setText(f"❌ {msg}")
        self._worker = None

    # ========================
    # 权限操作
    # ========================

    def _get_selected_permission_rows(self):
        """获取选中行的 (sid, permission_id, role, email) 列表"""
        results = []
        seen = set()
        for item in self.table.selectedItems():
            row = item.row()
            if row in seen:
                continue
            seen.add(row)
            name_item = self.table.item(row, 0)
            pid_item = self.table.item(row, 4)
            email_item = self.table.item(row, 1)
            role_item = self.table.item(row, 2)
            if name_item and pid_item:
                sid = name_item.data(Qt.UserRole)
                pid = pid_item.text()
                email = email_item.text() if email_item else ""
                role_text = role_item.text() if role_item else ""
                # 跳过所有者
                if "所有者" in role_text:
                    continue
                results.append({
                    "sid": sid, "permission_id": pid,
                    "email": email, "role": role_text
                })
        return results

    def _add_collaborator(self):
        """添加新协作者"""
        email = self.email_input.text().strip()
        if not email:
            QMessageBox.warning(self, "提示", "请输入至少一个协作者邮箱。")
            return

        role = self.role_combo.currentText()

        if self.apply_all_check.isChecked():
            sids = [e.get("spreadsheet_id", "") for e in self.entries if e.get("spreadsheet_id")]
        else:
            # 仅对表格中当前选中行对应的表格操作
            selected = self._get_selected_permission_rows()
            sids = list(set(r["sid"] for r in selected if r["sid"]))
            if not sids:
                sids = [e.get("spreadsheet_id", "") for e in self.entries if e.get("spreadsheet_id")]

        if not sids:
            self.status_label.setText("⚠️ 没有可操作的表格")
            return

        self._run_action("add", sids, email=email, role=role, recursive_down=self.apply_recursive_check.isChecked())

    def _update_selected_role(self):
        """修改选中协作者的角色"""
        selected = self._get_selected_permission_rows()
        if not selected:
            self.status_label.setText("⚠️ 请先在表格中选中要修改的协作者")
            return

        new_role = self.change_role_combo.currentText()

        # 逐个修改（每个权限需要各自的 sid 和 permission_id）
        self._batch_permission_ops(selected, "update", role=new_role)

    def _remove_selected(self):
        """移除选中的协作者"""
        selected = self._get_selected_permission_rows()
        if not selected:
            self.status_label.setText("⚠️ 请先在表格中选中要移除的协作者")
            return

        if QMessageBox.question(
            self, "确认",
            f"确定移除 {len(selected)} 个协作者的权限？",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        self._batch_permission_ops(selected, "remove")

    def _accept_selected_ownership(self):
        """接收选中的待接收的所有者权限"""
        selected = self._get_selected_permission_rows()
        # 仅过滤出处于“待接收”状态的权限，或尝试全部发送让API判断
        # 这里为了友好，筛选一下
        pending_selected = [s for s in selected if "待接收" in s["role"]]
        if not pending_selected:
            self.status_label.setText("⚠️ 选中的行中没有处于 '待接收 (所有者)' 状态的记录")
            return

        if QMessageBox.question(
            self, "确认",
            f"确定接收 {len(pending_selected)} 个表格的所有者权限吗？\n接收后，您将成为这些表格的所有者。",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        self._batch_permission_ops(pending_selected, "accept_ownership")

    def _set_secure_mode(self, enable):
        """开启或关闭整体防盗版模式"""
        selected = self._get_selected_permission_rows()
        if not selected:
            # 如果没有勾选任何行，就在当前所见全部表格上下发生效
            sids = list(set([e.get("spreadsheet_id", "") for e in self.entries if e.get("spreadsheet_id")]))
        else:
            sids = list(set(r["sid"] for r in selected if r["sid"]))
            
        if not sids:
            self.status_label.setText("⚠️ 没有选定可操作的表格")
            return
            
        action_name = "开启防泄漏封锁" if enable else "解除锁定"
        if QMessageBox.question(
            self, "确认应用超级安全策略",
            f"确定对选中的 {len(sids)} 个表格 {action_name} 吗？\n开启后，所有具有“仅查看”和“可评论”权限的用户\n将无法复制任何单元格、无法打印，且无法建立副本下载源数据！",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        self._run_action("set_secure", sids, enable=enable, recursive_down=self.apply_recursive_check.isChecked())

    def _set_owner_only_mode(self, enable):
        """开启或关闭所有者独占分享权"""
        selected = self._get_selected_permission_rows()
        if not selected:
            sids = list(set([e.get("spreadsheet_id", "") for e in self.entries if e.get("spreadsheet_id")]))
        else:
            sids = list(set(r["sid"] for r in selected if r["sid"]))
            
        if not sids:
            self.status_label.setText("⚠️ 没有选定可操作的表格")
            return
            
        action_name = "开启独占分享权" if enable else "解除独占限制"
        if QMessageBox.question(
            self, "确认应用超级安全策略",
            f"确定对选中的 {len(sids)} 个表格 {action_name} 吗？\n开启后，现有的编辑者（Writer）将彻底失去邀请新用户、修改其他人权限的能力！\n唯有您（所有者）可以掌控该表格的授权生死大权。",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        self._run_action("set_owners_only", sids, enable=enable, recursive_down=self.apply_recursive_check.isChecked())

    def _remove_all_permissions(self):
        """一键移除选中表格或当前所有表格的所有协作者（保留所有者）"""
        selected = self._get_selected_permission_rows()
        if not selected:
            sids = list(set([e.get("spreadsheet_id", "") for e in self.entries if e.get("spreadsheet_id")]))
        else:
            sids = list(set(r["sid"] for r in selected if r["sid"]))
            
        if not sids:
            self.status_label.setText("⚠️ 没有选定可操作的表格")
            return
            
        if QMessageBox.question(
            self, "危险操作确认",
            f"⚠️ 确定要移除这 {len(sids)} 个表格的所有协作者吗？\n该操作会清除除所有者外的所有人权限，且无法撤销！",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        self._run_action("remove_all_permissions", sids, recursive_down=self.apply_recursive_check.isChecked(), recursive_up=self.remove_parent_recursive_check.isChecked())

    def _remove_all_secure_modes(self):
        """一键解除所有由高阶安全模式引发的限制"""
        selected = self._get_selected_permission_rows()
        if not selected:
            sids = list(set([e.get("spreadsheet_id", "") for e in self.entries if e.get("spreadsheet_id")]))
        else:
            sids = list(set(r["sid"] for r in selected if r["sid"]))
            
        if not sids:
            self.status_label.setText("⚠️ 没有选定可操作的表格")
            return
            
        if QMessageBox.question(
            self, "解除高级锁定确认",
            f"确定要为 {len(sids)} 个表格解除所有高阶安全限制吗？\n(包含允许复制/下载 和 允许编辑者分享)",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        self._run_action("remove_all_secure", sids, recursive_down=self.apply_recursive_check.isChecked())
            
    def _sync_permissions(self):
        """一键同步权限：用输入的邮箱完全替换现有的权限"""
        emails_str = self.email_input.text().strip()
        if not emails_str:
            self.status_label.setText("⚠️ 请输入要同步保留/添加的协作者邮箱")
            return
        
        role = self.role_combo.currentText()
        selected = self._get_selected_permission_rows()
        if not selected:
            sids = list(set([e.get("spreadsheet_id", "") for e in self.entries if e.get("spreadsheet_id")]))
        else:
            sids = list(set(r["sid"] for r in selected if r["sid"]))
            
        if not sids:
            self.status_label.setText("⚠️ 没有选定可操作的表格")
            return
            
        if QMessageBox.question(
            self, "一键同步确认",
            f"确定要将 {len(sids)} 个表格的权限同步为如下邮箱吗？\n{emails_str}\n\n注意：这会赋予上述邮箱 {role} 角色，同时移除其他所有协作者（保留所有者）。此操作不可撤销！",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        self._run_action("sync_permissions", sids, email=emails_str, role=role, recursive_down=self.apply_recursive_check.isChecked(), recursive_up=self.remove_parent_recursive_check.isChecked())

    def _remove_anyone_permission(self):
        """取消公开访问权限 (知道链接的任何人)"""
        selected = self._get_selected_permission_rows()
        if not selected:
            sids = list(set([e.get("spreadsheet_id", "") for e in self.entries if e.get("spreadsheet_id")]))
        else:
            sids = list(set(r["sid"] for r in selected if r["sid"]))
            
        if not sids:
            self.status_label.setText("⚠️ 没有选定可操作的表格")
            return
            
        if QMessageBox.question(
            self, "取消公开访问确认",
            f"确定要将这 {len(sids)} 个表格的“知道链接的任何人”权限取消吗？\n取消后，仅受邀用户才可访问。",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        self._run_action("remove_anyone_permission", sids, recursive_down=self.apply_recursive_check.isChecked())


    def _batch_permission_ops(self, selected, action, **kwargs):
        """批量执行权限操作（逐个调用）"""
        from services.sheet_service import SheetService
        total = len(selected)
        success = 0
        errors = []

        self.progress.setVisible(True)
        self.progress.setMaximum(total)

        for i, item in enumerate(selected):
            self.progress.setValue(i)
            self.status_label.setText(f"({i+1}/{total}) 处理: {item['email']}")
            try:
                service = SheetService(item["sid"])
                if action == "update":
                    service.update_permission(item["permission_id"], kwargs["role"])
                elif action == "remove":
                    # 调用递归移除逻辑，传入当前的 checkbox 状态
                    service.remove_permission(
                        permission_id=item["permission_id"], 
                        recursive=self.remove_parent_recursive_check.isChecked(),
                        email=item["email"]
                    )
                elif action == "accept_ownership":
                    service.accept_ownership(item["permission_id"])
                success += 1
            except Exception as e:
                errors.append(f"{item['email']}: {e}")
                logger.error(f"权限操作失败: {e}")

        self.progress.setVisible(False)
        self.status_label.setText(f"✅ 完成: {success}/{total} 成功")

        if errors:
            QMessageBox.warning(
                self, "部分失败",
                f"有 {len(errors)} 个操作失败：\n" + "\n".join(errors[:5])
            )

        # 刷新列表
        self._start_fetch()

    def _run_action(self, action, sids, **kwargs):
        """执行权限操作"""
        self._action_worker = PermissionActionWorker(action, sids, **kwargs)
        self.progress.setVisible(True)
        self.progress.setMaximum(len(sids))
        self.status_label.setText("⏳ 执行中...")

        self._action_worker.progress.connect(
            lambda c, t, m: (self.progress.setValue(c), self.status_label.setText(m))
        )
        self._action_worker.finished.connect(self._on_action_done)
        self._action_worker.error.connect(self._on_error)
        
        # 安全释放资源
        self._action_worker.finished.connect(lambda _: self._action_worker.deleteLater())
        self._action_worker.error.connect(lambda _: self._action_worker.deleteLater())
        
        self._action_worker.start()

    def _on_action_done(self, msg):
        """操作完成"""
        self.progress.setVisible(False)
        self.status_label.setText(f"✅ {msg}")
        self._action_worker = None
        self.email_input.clear()
        # 刷新权限列表
        self._start_fetch()
