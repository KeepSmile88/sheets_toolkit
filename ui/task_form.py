# 调度任务表单 — 添加和管理调度任务
import logging
from datetime import datetime, timedelta
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QPushButton,
    QLineEdit, QComboBox, QDateTimeEdit, QHBoxLayout
)
from services.command.write_command import WriteCommand
from core.scheduler import ScheduledCommand

logger = logging.getLogger("sheets_toolkit.ui.task_form")


class TaskForm(QWidget):
    """调度任务创建表单"""

    def __init__(self, controller, task_queue_view, log_func=None):
        super().__init__()
        self.controller = controller
        self.queue_view = task_queue_view
        self._log = log_func or (lambda x: None)
        self.setMinimumHeight(180)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("任务名称")

        self.type_select = QComboBox()
        self.type_select.addItems(["once", "interval", "daily"])

        self.sheet_input = QLineEdit()
        self.sheet_input.setPlaceholderText("工作表名")

        self.range_input = QLineEdit()
        self.range_input.setPlaceholderText("写入范围，如 A1")

        self.datetime_input = QDateTimeEdit(datetime.now() + timedelta(minutes=1))
        self.datetime_input.setCalendarPopup(True)

        self.interval_input = QLineEdit()
        self.interval_input.setPlaceholderText("间隔秒数（如 60）")

        add_btn = QPushButton("➕ 添加任务")
        add_btn.clicked.connect(self.add_task)

        clear_btn = QPushButton("🗑 清空所有调度")
        clear_btn.setObjectName("danger_btn")
        clear_btn.clicked.connect(self.clear_all)

        layout.addWidget(QLabel("任务名称"))
        layout.addWidget(self.name_input)
        layout.addWidget(QLabel("任务类型"))
        layout.addWidget(self.type_select)
        layout.addWidget(QLabel("Sheet 名 / 范围"))
        layout.addWidget(self.sheet_input)
        layout.addWidget(self.range_input)
        layout.addWidget(QLabel("开始时间 / 间隔"))
        layout.addWidget(self.datetime_input)
        layout.addWidget(self.interval_input)

        btns = QHBoxLayout()
        btns.addWidget(add_btn)
        btns.addWidget(clear_btn)
        layout.addLayout(btns)

    def add_task(self):
        """添加调度任务"""
        name = self.name_input.text().strip()
        if not name:
            self._log("⚠️ 请输入任务名称")
            return

        type_ = self.type_select.currentText()
        sheet = self.sheet_input.text().strip()
        range_ = self.range_input.text().strip()

        if not sheet or not range_:
            self._log("⚠️ 请输入工作表名和范围")
            return

        cmd = WriteCommand(sheet, range_, [["调度测试"]])

        try:
            if type_ == "once":
                run_time = self.datetime_input.dateTime().toPython()
                sched = ScheduledCommand(name, cmd, "once", {"run_date": run_time})
            elif type_ == "interval":
                interval_text = self.interval_input.text().strip()
                if not interval_text:
                    self._log("⚠️ 请输入间隔秒数")
                    return
                interval = int(interval_text)
                sched = ScheduledCommand(name, cmd, "interval", {"seconds": interval})
            else:
                dt = self.datetime_input.dateTime().toPython()
                sched = ScheduledCommand(name, cmd, "daily", {"hour": dt.hour, "minute": dt.minute})

            self.controller.schedule(sched)
            if self.queue_view:
                self.queue_view.refresh()
            self._log(f"📅 任务 {name} 已添加")

        except ValueError:
            self._log("❌ 间隔秒数格式无效")
        except Exception as e:
            self._log(f"❌ 添加任务失败: {e}")
            logger.error(f"添加调度任务失败: {e}")

    def clear_all(self):
        """清空所有调度任务"""
        self.controller.scheduler.clear_all()
        if self.queue_view:
            self.queue_view.refresh()
        self._log("🗑 已清除所有调度任务")
