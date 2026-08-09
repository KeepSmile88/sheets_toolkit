# 单元格值监控面板 — 支持多组监控任务，定时获取值并递进式报警
import json
import logging
import os
import uuid
from collections import deque
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QGroupBox, QMessageBox, QApplication, QSplitter,
    QTabWidget, QSystemTrayIcon
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap, QPainter

logger = logging.getLogger("sheets_toolkit.ui.cell_monitor")

# 报警级别定义（5级递进）
ALERT_LEVELS = {
    1: {"title": "ℹ️ 监控提示", "icon": QMessageBox.Information,
        "color": "#2196F3", "desc": "单元格值与上次相同，请关注。"},
    2: {"title": "⚠️ 监控警告", "icon": QMessageBox.Warning,
        "color": "#FF9800", "desc": "单元格值已连续2次未发生变化！"},
    3: {"title": "🔴 严重警告", "icon": QMessageBox.Critical,
        "color": "#F44336", "desc": "单元格值已连续3次未变化！请检查数据源！"},
    4: {"title": "🚨 紧急报警", "icon": QMessageBox.Critical,
        "color": "#C62828", "desc": "单元格值已连续4次未变化！可能存在严重问题！"},
    5: {"title": "🚨🚨 极度紧急", "icon": QMessageBox.Critical,
        "color": "#880000", "desc": "单元格值已连续5次+未变化！请立即处理！"},
}


# 持久化文件路径
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MONITOR_SAVE_PATH = os.path.join(_BASE_DIR, "cell_monitors.json")


class MonitorTask:
    """单个监控任务的数据模型"""
    def __init__(self, sid, sheet_name, cell, interval_min, task_id=None):
        self.id = task_id or str(uuid.uuid4())[:8]
        self.sid = sid
        self.sheet_name = sheet_name
        self.cell = cell.upper()
        self.interval_min = interval_min
        self.history = deque(maxlen=5)
        self.no_change_count = 0
        self.check_count = 0
        self.is_running = False
        self.is_paused = False
        self.timer = None       # 由外部赋值 QTimer
        self.worker = None      # 当前 Worker 引用
        self.last_value = None

    @property
    def target_str(self):
        return f"{self.sheet_name}!{self.cell}"

    @property
    def status_text(self):
        if not self.is_running:
            return "⏹ 已停止"
        if self.is_paused:
            return "⏸ 已暂停"
        return "🟢 运行中"

    def to_dict(self):
        """将任务配置序列化为字典（仅保存可恢复的配置，不保存运行时状态）"""
        return {
            "id": self.id,
            "sid": self.sid,
            "sheet_name": self.sheet_name,
            "cell": self.cell,
            "interval_min": self.interval_min,
        }

    @classmethod
    def from_dict(cls, data):
        """从字典反序列化为 MonitorTask 实例"""
        return cls(
            sid=data["sid"],
            sheet_name=data["sheet_name"],
            cell=data["cell"],
            interval_min=data.get("interval_min", 30),
            task_id=data.get("id"),
        )


class CellMonitorWorker(QThread):
    """后台线程：读取指定单元格的值"""
    finished = Signal(str, str, str)  # (task_id, 值, 时间戳)
    error = Signal(str, str)          # (task_id, 错误信息)

    def __init__(self, task_id, spreadsheet_id, sheet_name, cell_address):
        super().__init__()
        self.task_id = task_id
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.cell_address = cell_address

    def run(self):
        try:
            from services.sheet_service import SheetService
            service = SheetService(self.spreadsheet_id)
            range_str = f"{self.sheet_name}!{self.cell_address}"
            data = service.read_data(range_str)
            value = ""
            if data and len(data) > 0 and len(data[0]) > 0:
                value = str(data[0][0])
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.finished.emit(self.task_id, value, ts)
        except Exception as e:
            self.error.emit(self.task_id, str(e))
            logger.error(f"监控读取失败 [{self.task_id}]: {e}")


class CellMonitorWidget(QWidget):
    """单元格值监控面板 — 支持多组监控"""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._tasks = {}  # task_id -> MonitorTask
        self._editing_task_id = None  # 当前正在编辑的任务ID
        self._init_tray_icon()
        self.setup_ui()
        # 启动时自动加载已保存的监控任务
        self._load_tasks()

    # ============================
    # UI 构建
    # ============================

    def _init_tray_icon(self):
        """初始化系统托盘图标（用于发送系统通知）"""
        self._tray_icon = None
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                logger.warning("系统托盘不可用")
                return

            # 尝试获取应用图标，否则创建一个绿色圆形作为备用图标
            app = QApplication.instance()
            icon = None
            if app and not app.windowIcon().isNull():
                icon = app.windowIcon()
            else:
                # 创建一个简单的备用图标（绿色圆形 + “监”字）
                pixmap = QPixmap(64, 64)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setBrush(QColor("#4CAF50"))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(2, 2, 60, 60)
                painter.setPen(QColor("white"))
                font = painter.font()
                font.setPixelSize(32)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(pixmap.rect(), Qt.AlignCenter, "监")
                painter.end()
                icon = QIcon(pixmap)

            self._tray_icon = QSystemTrayIcon(icon, self)
            self._tray_icon.setToolTip("Google Sheets 工具箱 — 单元格监控")
            self._tray_icon.show()
            logger.info(f"系统托盘图标初始化成功，支持消息: {self._tray_icon.supportsMessages()}")
        except Exception as e:
            logger.warning(f"系统托盘初始化失败: {e}")

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        title = QLabel("👁‍🗨 数据监控")
        title.setObjectName("section_title")
        layout.addWidget(title)

        help_label = QLabel(
            "支持同时监控多个表格的多个单元格。每个监控任务独立定时检查，"
            "值未变化时按递进级别报警（最多与最近5次比较）。"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        # ======== 添加任务区 ========
        add_group = QGroupBox("➕ 添加监控任务")
        add_layout = QVBoxLayout(add_group)
        add_layout.setSpacing(6)

        # 第一行：表格ID + 刷新
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("📄 表格链接/ID："))
        self.input_id = QLineEdit()
        self.input_id.setPlaceholderText("输入 Google Sheet 链接或 ID...")
        row1.addWidget(self.input_id, stretch=1)
        self.btn_refresh = QPushButton("🔄 刷新工作表")
        self.btn_refresh.clicked.connect(self._load_sheets)
        row1.addWidget(self.btn_refresh)
        add_layout.addLayout(row1)

        # 第二行：工作表 + 单元格 + 间隔 + 添加按钮
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("📋 工作表："))
        self.sheet_combo = QComboBox()
        self.sheet_combo.setMinimumWidth(120)
        row2.addWidget(self.sheet_combo)

        row2.addSpacing(10)
        row2.addWidget(QLabel("📍 单元格："))
        self.cell_input = QLineEdit("A1")
        self.cell_input.setMaximumWidth(80)
        row2.addWidget(self.cell_input)

        row2.addSpacing(10)
        row2.addWidget(QLabel("⏱ 间隔："))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setValue(30)
        self.interval_spin.setSuffix(" 分钟")
        row2.addWidget(self.interval_spin)

        row2.addSpacing(10)
        self.btn_add = QPushButton("➕ 添加并启动")
        self.btn_add.setObjectName("primary_btn")
        self.btn_add.clicked.connect(self._add_task)
        row2.addWidget(self.btn_add)

        self.btn_save_edit = QPushButton("💾 保存修改")
        self.btn_save_edit.setObjectName("primary_btn")
        self.btn_save_edit.clicked.connect(self._save_edit)
        self.btn_save_edit.setVisible(False)
        row2.addWidget(self.btn_save_edit)

        self.btn_cancel_edit = QPushButton("✖ 取消编辑")
        self.btn_cancel_edit.clicked.connect(self._cancel_edit)
        self.btn_cancel_edit.setVisible(False)
        row2.addWidget(self.btn_cancel_edit)

        row2.addStretch()
        add_layout.addLayout(row2)

        layout.addWidget(add_group)

        # ======== 上下分割：任务列表 + 历史详情 ========
        splitter = QSplitter(Qt.Vertical)

        # --- 上半部分：任务列表 ---
        task_group = QGroupBox("📋 监控任务列表")
        task_layout = QVBoxLayout(task_group)

        # 批量操作按钮
        btn_row = QHBoxLayout()
        self.btn_pause_sel = QPushButton("⏸ 暂停/恢复选中")
        self.btn_pause_sel.clicked.connect(self._toggle_pause_selected)
        btn_row.addWidget(self.btn_pause_sel)
        self.btn_stop_sel = QPushButton("⏹ 停止选中")
        self.btn_stop_sel.clicked.connect(self._stop_selected)
        btn_row.addWidget(self.btn_stop_sel)
        self.btn_remove_sel = QPushButton("🗑 移除选中")
        self.btn_remove_sel.setObjectName("danger_btn")
        self.btn_remove_sel.clicked.connect(self._remove_selected)
        btn_row.addWidget(self.btn_remove_sel)
        self.btn_check_sel = QPushButton("🔍 立即检查选中")
        self.btn_check_sel.setObjectName("secondary_btn")
        self.btn_check_sel.clicked.connect(self._check_selected_now)
        btn_row.addWidget(self.btn_check_sel)
        self.btn_edit_sel = QPushButton("✏️ 编辑选中")
        self.btn_edit_sel.clicked.connect(self._edit_selected)
        btn_row.addWidget(self.btn_edit_sel)
        btn_row.addStretch()
        task_layout.addLayout(btn_row)

        self.task_table = QTableWidget()
        self.task_table.setColumnCount(8)
        self.task_table.setHorizontalHeaderLabels([
            "ID", "监控目标", "间隔", "状态",
            "当前值", "连续未变化", "总检查", "最后检查"
        ])
        self.task_table.setAlternatingRowColors(True)
        self.task_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.task_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.task_table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.task_table.setColumnWidth(0, 60)
        self.task_table.setColumnWidth(2, 70)
        self.task_table.setColumnWidth(3, 80)
        self.task_table.setColumnWidth(4, 120)
        self.task_table.setColumnWidth(5, 90)
        self.task_table.setColumnWidth(6, 60)
        self.task_table.setColumnWidth(7, 140)
        self.task_table.verticalHeader().setDefaultSectionSize(28)
        self.task_table.currentCellChanged.connect(self._on_task_selected)
        task_layout.addWidget(self.task_table)

        splitter.addWidget(task_group)

        # --- 下半部分：选中任务的采集历史 ---
        history_group = QGroupBox("📜 选中任务的采集历史（最近5次）")
        history_layout = QVBoxLayout(history_group)

        self.history_label = QLabel("请在上方选择一个监控任务以查看历史记录")
        self.history_label.setStyleSheet("color: gray; font-style: italic;")
        history_layout.addWidget(self.history_label)

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5)
        self.history_table.setHorizontalHeaderLabels([
            "时间", "采集值", "是否变化", "连续未变化次数", "报警级别"
        ])
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.history_table.setColumnWidth(0, 150)
        self.history_table.setColumnWidth(2, 80)
        self.history_table.setColumnWidth(3, 110)
        self.history_table.setColumnWidth(4, 110)
        self.history_table.verticalHeader().setDefaultSectionSize(28)
        history_layout.addWidget(self.history_table)

        splitter.addWidget(history_group)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, stretch=1)

    # ============================
    # 辅助方法
    # ============================

    def _get_spreadsheet_id(self):
        raw = self.input_id.text().strip()
        if not raw:
            return None
        from ui.batch_backup_widget import extract_spreadsheet_id
        return extract_spreadsheet_id(raw)

    def _load_sheets(self):
        sid = self._get_spreadsheet_id()
        if not sid:
            QMessageBox.warning(self, "提示", "请输入有效的表格链接或ID")
            return
        try:
            QApplication.processEvents()
            from services.sheet_service import SheetService
            service = SheetService(sid)
            sheets = service.list_sheets()
            self.sheet_combo.clear()
            self.sheet_combo.addItems(sheets)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载失败: {e}")

    def _get_selected_task_ids(self):
        """获取当前选中行对应的 task_id 列表"""
        ids = []
        for idx in self.task_table.selectionModel().selectedRows():
            item = self.task_table.item(idx.row(), 0)
            if item:
                ids.append(item.text())
        return ids

    # ============================
    # 任务管理
    # ============================

    def _add_task(self):
        """添加一个新的监控任务并立即启动"""
        sid = self._get_spreadsheet_id()
        if not sid:
            QMessageBox.warning(self, "配置错误", "请输入有效的表格链接或ID")
            return
        sheet_name = self.sheet_combo.currentText()
        if not sheet_name:
            QMessageBox.warning(self, "配置错误", "请先刷新并选择一个工作表")
            return
        cell = self.cell_input.text().strip().upper()
        if not cell:
            QMessageBox.warning(self, "配置错误", "请输入单元格地址（如 A1）")
            return

        interval = self.interval_spin.value()
        task = MonitorTask(sid, sheet_name, cell, interval)

        # 创建定时器
        timer = QTimer(self)
        timer.timeout.connect(lambda tid=task.id: self._do_check(tid))
        task.timer = timer
        task.is_running = True

        self._tasks[task.id] = task

        # 启动定时器
        timer.start(interval * 60 * 1000)
        # 立即执行第一次检查
        self._do_check(task.id)

        self._refresh_task_table()
        self._save_tasks()  # 持久化保存
        logger.info(f"添加监控任务 [{task.id}]: {task.target_str}，间隔 {interval} 分钟")

    def _edit_selected(self):
        """将选中任务的配置加载到输入区进行编辑"""
        ids = self._get_selected_task_ids()
        if len(ids) != 1:
            QMessageBox.warning(self, "提示", "请选择一个（且仅一个）任务进行编辑")
            return
        task = self._tasks.get(ids[0])
        if not task:
            return

        # 暂停任务（如果正在运行）
        if task.is_running and not task.is_paused:
            task.timer.stop()
            task.is_paused = True
            self._refresh_task_table()

        # 加载配置到输入区
        self.input_id.setText(task.sid)
        # 尝试加载工作表列表并选中
        try:
            from services.sheet_service import SheetService
            service = SheetService(task.sid)
            sheets = service.list_sheets()
            self.sheet_combo.clear()
            self.sheet_combo.addItems(sheets)
            idx = self.sheet_combo.findText(task.sheet_name)
            if idx >= 0:
                self.sheet_combo.setCurrentIndex(idx)
        except Exception:
            self.sheet_combo.clear()
            self.sheet_combo.addItem(task.sheet_name)
        self.cell_input.setText(task.cell)
        self.interval_spin.setValue(task.interval_min)

        # 切换到编辑模式
        self._editing_task_id = task.id
        self.btn_add.setVisible(False)
        self.btn_save_edit.setVisible(True)
        self.btn_cancel_edit.setVisible(True)
        logger.info(f"进入编辑模式: 任务 [{task.id}]")

    def _save_edit(self):
        """保存对任务的修改"""
        task = self._tasks.get(self._editing_task_id)
        if not task:
            self._cancel_edit()
            return

        sid = self._get_spreadsheet_id()
        if not sid:
            QMessageBox.warning(self, "配置错误", "请输入有效的表格链接或ID")
            return
        sheet_name = self.sheet_combo.currentText()
        if not sheet_name:
            QMessageBox.warning(self, "配置错误", "请选择一个工作表")
            return
        cell = self.cell_input.text().strip().upper()
        if not cell:
            QMessageBox.warning(self, "配置错误", "请输入单元格地址")
            return

        # 应用修改
        task.sid = sid
        task.sheet_name = sheet_name
        task.cell = cell
        task.interval_min = self.interval_spin.value()

        # 重启定时器
        task.timer.stop()
        task.timer.start(task.interval_min * 60 * 1000)
        task.is_paused = False
        task.is_running = True

        # 退出编辑模式
        self._cancel_edit()
        self._refresh_task_table()
        self._save_tasks()  # 持久化保存
        logger.info(f"已保存任务修改 [{task.id}]: {task.target_str}")

        # 立即执行一次检查
        self._do_check(task.id)

    def _cancel_edit(self):
        """取消编辑，恢复添加模式"""
        self._editing_task_id = None
        self.btn_add.setVisible(True)
        self.btn_save_edit.setVisible(False)
        self.btn_cancel_edit.setVisible(False)

    def _toggle_pause_selected(self):
        """暂停/恢复选中的任务"""
        for tid in self._get_selected_task_ids():
            task = self._tasks.get(tid)
            if not task or not task.is_running:
                continue
            if task.is_paused:
                task.timer.start(task.interval_min * 60 * 1000)
                task.is_paused = False
            else:
                task.timer.stop()
                task.is_paused = True
        self._refresh_task_table()

    def _stop_selected(self):
        """停止选中的任务"""
        for tid in self._get_selected_task_ids():
            task = self._tasks.get(tid)
            if not task:
                continue
            task.timer.stop()
            task.is_running = False
            task.is_paused = False
        self._refresh_task_table()
        self._save_tasks()  # 持久化保存

    def _remove_selected(self):
        """移除选中的任务"""
        ids = self._get_selected_task_ids()
        if not ids:
            return
        reply = QMessageBox.question(
            self, "确认移除",
            f"确定要移除 {len(ids)} 个监控任务吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        for tid in ids:
            task = self._tasks.pop(tid, None)
            if task and task.timer:
                task.timer.stop()
                task.timer.deleteLater()
        self._refresh_task_table()
        self._save_tasks()  # 持久化保存
        self.history_table.setRowCount(0)
        self.history_label.setText("请在上方选择一个监控任务以查看历史记录")

    def _check_selected_now(self):
        """立即检查选中的任务"""
        for tid in self._get_selected_task_ids():
            self._do_check(tid)

    # ============================
    # 定时检查
    # ============================

    def _do_check(self, task_id):
        """对指定任务执行一次检查"""
        task = self._tasks.get(task_id)
        if not task:
            return
        # 防止重复
        if task.worker and task.worker.isRunning():
            return

        worker = CellMonitorWorker(task.id, task.sid, task.sheet_name, task.cell)
        worker.finished.connect(self._on_check_finished)
        worker.error.connect(self._on_check_error)
        task.worker = worker
        worker.start()

    def _on_check_finished(self, task_id, value, timestamp):
        """检查完成回调"""
        task = self._tasks.get(task_id)
        if not task:
            return

        task.check_count += 1
        changed = True
        alert_level = 0

        if task.history:
            last_val = task.history[-1]["value"]
            if value == last_val:
                changed = False
                task.no_change_count += 1
                alert_level = min(task.no_change_count, 5)
            else:
                task.no_change_count = 0

        task.last_value = value
        task.history.append({
            "time": timestamp, "value": value, "changed": changed,
            "no_change_count": task.no_change_count,
            "alert_level": alert_level,
        })

        self._refresh_task_table()

        # 如果当前选中的就是这个任务，刷新历史
        sel_ids = self._get_selected_task_ids()
        if task_id in sel_ids:
            self._show_task_history(task_id)

        # 弹出报警
        if not changed and alert_level > 0:
            self._show_alert(task, alert_level, value, timestamp)

        logger.info(f"[{task_id}] 检查完成: 值='{value}', 变化={changed}")

    def _on_check_error(self, task_id, err):
        """检查失败"""
        logger.error(f"[{task_id}] 检查失败: {err}")
        # 在任务表格中标记错误可通过刷新表格体现
        self._refresh_task_table()

    # ============================
    # 报警弹窗
    # ============================

    def _show_alert(self, task, level, value, timestamp):
        """显示递进式报警弹窗"""
        level = min(level, 5)
        alert = ALERT_LEVELS[level]

        msg_lines = [
            f"<b>{alert['desc']}</b>", "",
            f"📍 监控目标: <code>{task.target_str}</code>",
            f"📊 当前值: <code>{value if value else '(空)'}</code>",
            f"🔢 连续未变化次数: <b>{task.no_change_count}</b>",
            f"🕐 检查时间: {timestamp}",
        ]

        # 高级别报警附加历史
        if level >= 3 and len(task.history) > 1:
            msg_lines += ["", "<b>📜 最近采集历史:</b>"]
            for rec in task.history:
                flag = "✅" if rec["changed"] else "❌"
                msg_lines.append(
                    f"  • {rec['time']}  值: {rec['value'] or '(空)'}  {flag}"
                )

        msg = "<br>".join(msg_lines)

        msgbox = QMessageBox(self)
        msgbox.setWindowTitle(f"{alert['title']} — {task.target_str}")
        msgbox.setIcon(alert["icon"])
        msgbox.setTextFormat(Qt.RichText)
        msgbox.setText(msg)

        if level >= 3:
            msgbox.setStyleSheet(
                f"QMessageBox {{ background-color: #FFF3F3; }}"
                f"QLabel {{ color: {alert['color']}; font-size: 13px; }}"
            )
        if level >= 4:
            msgbox.setStyleSheet(
                f"QMessageBox {{ background-color: #FFEBEE; border: 2px solid {alert['color']}; }}"
                f"QLabel {{ color: {alert['color']}; font-size: 14px; font-weight: bold; }}"
            )

        # 在弹窗阻塞之前发送系统通知（level >= 3）
        if level >= 3:
            self._send_tray_notification(task, level, value)

        msgbox.exec()

    def _send_tray_notification(self, task, level, value):
        """通过系统托盘发送通知（level >= 3 时触发）"""
        if not self._tray_icon:
            return
        alert = ALERT_LEVELS.get(level, ALERT_LEVELS[5])
        # 根据级别选择通知图标类型
        if level >= 4:
            icon_type = QSystemTrayIcon.Critical
        else:
            icon_type = QSystemTrayIcon.Warning
        title = f"{alert['title']} — {task.target_str}"
        body = (
            f"{alert['desc']}\n"
            f"目标: {task.target_str}\n"
            f"当前值: {value if value else '(空)'}\n"
            f"连续未变化: {task.no_change_count} 次"
        )
        # 显示系统通知，持续时间 10 秒
        self._tray_icon.showMessage(title, body, icon_type, 10000)

    # ============================
    # UI 刷新
    # ============================

    def _refresh_task_table(self):
        """刷新任务列表表格"""
        tasks = list(self._tasks.values())
        self.task_table.setRowCount(len(tasks))

        for i, t in enumerate(tasks):
            # ID
            self.task_table.setItem(i, 0, QTableWidgetItem(t.id))
            # 监控目标
            self.task_table.setItem(i, 1, QTableWidgetItem(t.target_str))
            # 间隔
            self.task_table.setItem(i, 2, QTableWidgetItem(f"{t.interval_min}分钟"))
            # 状态
            status_item = QTableWidgetItem(t.status_text)
            if t.is_running and not t.is_paused:
                status_item.setForeground(QColor("#4CAF50"))
            elif t.is_paused:
                status_item.setForeground(QColor("#FF9800"))
            else:
                status_item.setForeground(QColor("#F44336"))
            self.task_table.setItem(i, 3, status_item)
            # 当前值
            val = t.last_value if t.last_value is not None else "—"
            self.task_table.setItem(i, 4, QTableWidgetItem(val))
            # 连续未变化
            nc_item = QTableWidgetItem(str(t.no_change_count))
            nc_item.setTextAlignment(Qt.AlignCenter)
            if t.no_change_count >= 3:
                nc_item.setForeground(Qt.red)
            elif t.no_change_count >= 1:
                nc_item.setForeground(QColor("#FF9800"))
            self.task_table.setItem(i, 5, nc_item)
            # 总检查
            tc_item = QTableWidgetItem(str(t.check_count))
            tc_item.setTextAlignment(Qt.AlignCenter)
            self.task_table.setItem(i, 6, tc_item)
            # 最后检查时间
            last_time = t.history[-1]["time"] if t.history else "—"
            self.task_table.setItem(i, 7, QTableWidgetItem(last_time))

    def _on_task_selected(self, row, col, prev_row, prev_col):
        """选中任务时显示其历史"""
        if row < 0:
            return
        item = self.task_table.item(row, 0)
        if item:
            self._show_task_history(item.text())

    def _show_task_history(self, task_id):
        """显示指定任务的采集历史"""
        task = self._tasks.get(task_id)
        if not task:
            return

        self.history_label.setText(
            f"📊 任务 [{task_id}] {task.target_str}  —  "
            f"已检查 {task.check_count} 次，连续未变化 {task.no_change_count} 次"
        )
        self.history_label.setStyleSheet(
            "font-weight: bold; font-size: 13px; padding: 2px 0;"
        )

        records = list(task.history)
        self.history_table.setRowCount(len(records))

        for i, rec in enumerate(reversed(records)):
            self.history_table.setItem(i, 0, QTableWidgetItem(rec["time"]))

            val_item = QTableWidgetItem(rec["value"] if rec["value"] else "(空)")
            self.history_table.setItem(i, 1, val_item)

            if rec["changed"]:
                ch = QTableWidgetItem("✅ 已变化")
                ch.setForeground(Qt.darkGreen)
            else:
                ch = QTableWidgetItem("❌ 未变化")
                ch.setForeground(Qt.red)
            self.history_table.setItem(i, 2, ch)

            nc = QTableWidgetItem(str(rec["no_change_count"]))
            nc.setTextAlignment(Qt.AlignCenter)
            if rec["no_change_count"] >= 3:
                nc.setForeground(Qt.red)
            elif rec["no_change_count"] >= 1:
                nc.setForeground(QColor("#FF9800"))
            self.history_table.setItem(i, 3, nc)

            level = rec["alert_level"]
            level_map = {
                0: ("—", Qt.gray), 1: ("ℹ️ 提示", Qt.blue),
                2: ("⚠️ 警告", QColor("#FF9800")), 3: ("🔴 严重", Qt.red),
                4: ("🚨 紧急", Qt.darkRed), 5: ("🚨🚨 极度紧急", Qt.darkRed),
            }
            text, color = level_map.get(level, ("—", Qt.gray))
            lv = QTableWidgetItem(text)
            lv.setForeground(color)
            lv.setTextAlignment(Qt.AlignCenter)
            self.history_table.setItem(i, 4, lv)

    # ============================
    # 持久化
    # ============================

    def _save_tasks(self):
        """将当前所有监控任务配置保存到 JSON 文件"""
        try:
            data = [t.to_dict() for t in self._tasks.values()]
            with open(_MONITOR_SAVE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"已保存 {len(data)} 个监控任务到 {_MONITOR_SAVE_PATH}")
        except Exception as e:
            logger.error(f"保存监控任务失败: {e}")

    def _load_tasks(self):
        """从 JSON 文件加载已保存的监控任务并自动启动"""
        if not os.path.exists(_MONITOR_SAVE_PATH):
            return
        try:
            with open(_MONITOR_SAVE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return

            restored = 0
            for item in data:
                try:
                    task = MonitorTask.from_dict(item)

                    # 创建定时器并启动
                    timer = QTimer(self)
                    timer.timeout.connect(lambda tid=task.id: self._do_check(tid))
                    task.timer = timer
                    task.is_running = True

                    self._tasks[task.id] = task

                    # 启动定时器
                    timer.start(task.interval_min * 60 * 1000)
                    # 立即执行第一次检查
                    self._do_check(task.id)

                    restored += 1
                except Exception as e:
                    logger.warning(f"恢复监控任务失败: {e}")

            if restored > 0:
                self._refresh_task_table()
                logger.info(f"已从文件恢复 {restored} 个监控任务")

        except Exception as e:
            logger.error(f"加载监控任务文件失败: {e}")
