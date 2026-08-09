# MVC 控制器：连接 View 与 Service，管理所有业务操作
import logging
from PySide6.QtCore import QThreadPool, QObject, Signal, Slot
from services.sheet_service import SheetService
from core.executor import TaskRunner
from core.scheduler import TaskScheduler

logger = logging.getLogger("sheets_toolkit.controller")


class SheetController(QObject):
    """
    应用控制器 — 所有业务操作的中枢。
    View 层通过 Controller 间接使用 Service，不直接调用业务模块。
    """
    # 信号
    connection_success = Signal(list)   # 连接成功，参数为 sheet 名称列表
    connection_error = Signal(str)      # 连接失败
    log_message = Signal(str)           # 日志消息

    def __init__(self, view=None):
        super().__init__()
        self.view = view
        self.service = None
        self.pool = QThreadPool()
        self.scheduler = TaskScheduler()
        self._command_history = []  # 已执行的命令历史（用于撤销）

    # ========================
    # 连接管理
    # ========================

    def connect_sheet(self, spreadsheet_id):
        """连接到指定的 Spreadsheet"""
        try:
            self.service = SheetService(spreadsheet_id)
            sheets = self.service.list_sheets()
            if self.view:
                self.view.update_sheet_list(sheets)
            self.connection_success.emit(sheets)
            self._log(f"✅ 已连接到表格 (共 {len(sheets)} 个工作表)")

            # 保存到最近列表
            from core.config import AppConfig
            AppConfig().add_recent_spreadsheet(spreadsheet_id)

        except Exception as e:
            error_msg = f"❌ 连接失败: {str(e)}"
            self.connection_error.emit(error_msg)
            self._log(error_msg)
            logger.error(f"连接表格失败: {e}")

    @property
    def is_connected(self):
        return self.service is not None

    # ========================
    # 命令执行
    # ========================

    def run_command(self, command):
        """
        异步执行命令。
        命令会在线程池中执行，结果通过信号推送到 UI。
        """
        if not self.service:
            self._log("❌ 请先连接表格")
            return

        task = TaskRunner(command.description, command, self.service)
        task.signals.started.connect(self._log)
        task.signals.progress.connect(self._log)
        task.signals.finished.connect(lambda msg: self._on_command_finished(command, msg))
        task.signals.error.connect(lambda msg: self._on_command_error(command, msg))
        self.pool.start(task)

    def _on_command_finished(self, command, msg):
        """命令执行成功后的回调"""
        self._log(msg)
        # 加入历史记录
        self._command_history.append(command)
        # 通知 history_view
        if self.view and hasattr(self.view, 'history_view'):
            self.view.history_view.add_entry(command, msg, success=True)

    def _on_command_error(self, command, msg):
        """命令执行失败后的回调"""
        self._log(msg)
        if self.view and hasattr(self.view, 'history_view'):
            self.view.history_view.add_entry(command, msg, success=False)

    def run_command_sync(self, command):
        """同步执行命令（用于 UI 层需要立即返回结果的场景）"""
        if not self.service:
            self._log("❌ 请先连接表格")
            return None
        try:
            result = command.execute(self.service)
            self._command_history.append(command)
            if self.view and hasattr(self.view, 'history_view'):
                self.view.history_view.add_entry(command, str(result), success=True)
            return result
        except Exception as e:
            self._log(f"❌ 命令执行失败: {e}")
            return None

    # ========================
    # 撤销
    # ========================

    def undo_last(self):
        """撤销最近一条可撤销的命令"""
        if not self.service:
            self._log("❌ 请先连接表格")
            return None

        # 从后往前找到可撤销的命令
        while self._command_history:
            cmd = self._command_history.pop()
            if getattr(cmd, 'is_undoable', False):
                try:
                    result = cmd.undo(self.service)
                    self._log(f"↩️ {result}")
                    return result
                except Exception as e:
                    self._log(f"❌ 撤销失败: {e}")
                    return None

        self._log("⚠️ 没有可撤销的操作")
        return None

    # ========================
    # 调度
    # ========================

    def schedule(self, scheduled_command):
        """注册调度任务"""
        scheduled_command.register(self.scheduler, self)
        self._log(f"📅 已计划任务: {scheduled_command.name}")

    # ========================
    # 便捷方法 — 所有操作都通过 Controller
    # ========================

    def get_current_sheet_id(self):
        """获取当前选中的 Sheet ID"""
        if not self.service or not self.view:
            return None
        index = self.view.sheet_list.currentIndex()
        return self.service.get_sheet_id_by_index(index)

    def get_current_range(self):
        """构造当前的范围字符串"""
        if not self.view:
            return ""
        sheet = self.view.sheet_list.currentText()
        range_ = self.view.range_input.text()
        return f"{sheet}!{range_}"

    # ========================
    # 日志
    # ========================

    def _log(self, text):
        """输出日志到 UI 和日志系统"""
        self.log_message.emit(str(text))
        if self.view:
            self.view.log(text)
        logger.info(text)

    def shutdown(self):
        """清理资源"""
        self.scheduler.shutdown()
        self.pool.waitForDone(3000)
        logger.info("控制器已关闭")
