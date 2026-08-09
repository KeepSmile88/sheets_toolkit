# 任务队列表格视图
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView


class TaskQueueView(QTableWidget):
    """已调度任务列表视图"""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.scheduler = controller.scheduler.scheduler
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels(["任务ID", "类型", "状态", "下次执行"])
        self.setMinimumHeight(180)
        self.setAlternatingRowColors(True)

        # 列宽自适应
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.setColumnWidth(1, 100)
        self.setColumnWidth(2, 80)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.verticalHeader().setDefaultSectionSize(28)

    def refresh(self):
        """刷新任务列表"""
        jobs = self.scheduler.get_jobs()
        self.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            self.setItem(row, 0, QTableWidgetItem(job.id))
            self.setItem(row, 1, QTableWidgetItem(job.trigger.__class__.__name__))
            status = "✅ 活跃" if job.next_run_time else "⏹ 暂停"
            self.setItem(row, 2, QTableWidgetItem(status))
            self.setItem(row, 3, QTableWidgetItem(str(job.next_run_time or "—")))
