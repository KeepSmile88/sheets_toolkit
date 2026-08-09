# 多线程任务执行器：用于在后台线程执行 Command 对象
import logging
import traceback
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

logger = logging.getLogger("sheets_toolkit.executor")


class TaskSignals(QObject):
    """任务执行信号，用于线程安全地向 UI 报告状态"""
    started = Signal(str)           # 任务开始
    finished = Signal(str)          # 任务完成
    error = Signal(str)             # 任务出错
    progress = Signal(str)          # 进度文本消息
    progress_percent = Signal(int)  # 进度百分比 (0-100)
    result = Signal(object)         # 执行结果


class TaskRunner(QRunnable):
    """
    可运行任务单元，在线程池中异步执行 Command 对象。

    Args:
        name: 任务名称（用于日志和 UI 显示）
        command: 实现了 execute(service) 的命令对象
        service: SheetService 实例
    """
    def __init__(self, name, command, service):
        super().__init__()
        self.name = name
        self.command = command
        self.service = service
        self.signals = TaskSignals()
        self._is_cancelled = False
        self.setAutoDelete(True)

    def cancel(self):
        """标记任务为已取消"""
        self._is_cancelled = True
        logger.info(f"任务已标记为取消: {self.name}")

    @property
    def is_cancelled(self):
        return self._is_cancelled

    @Slot()
    def run(self):
        """执行任务（在工作线程中运行）"""
        if self._is_cancelled:
            self.signals.error.emit(f"⛔ 任务已取消: {self.name}")
            return

        try:
            self.signals.started.emit(f"🚀 任务开始: {self.name}")
            logger.info(f"开始执行任务: {self.name}")

            result = self.command.execute(self.service)

            if self._is_cancelled:
                self.signals.error.emit(f"⛔ 任务已取消: {self.name}")
                return

            self.signals.progress.emit(f"➡️ 执行结果: {result}")
            self.signals.result.emit(result)
            self.signals.finished.emit(f"✅ 任务完成: {self.name}")
            logger.info(f"任务完成: {self.name}")

        except Exception as e:
            error_msg = f"❌ 任务出错 [{self.name}]: {str(e)}"
            logger.error(f"任务执行失败: {self.name}\n{traceback.format_exc()}")
            self.signals.error.emit(error_msg)
