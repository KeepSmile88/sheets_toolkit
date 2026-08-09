# 清空数据命令（已修复：使用 clear API 而非写入空值）
import logging
from services.command.base_command import SheetCommand

logger = logging.getLogger("sheets_toolkit.command.clear")


class ClearCommand(SheetCommand):
    """
    清空指定区域数据命令。
    执行前备份数据，支持 undo 撤销。
    """

    def __init__(self, sheet_name, range_):
        self.sheet = sheet_name
        self.range = range_
        self._backup_data = None

    @property
    def description(self):
        return f"清空 {self.sheet}!{self.range}"

    def execute(self, service):
        range_str = f"{self.sheet}!{self.range}"

        # 备份原始数据
        try:
            self._backup_data = service.read_data(range_str)
        except Exception:
            self._backup_data = None

        # 使用正确的 clear API
        service.clear_data(range_str)
        return f"已清空区域: {range_str}"

    def undo(self, service):
        if self._backup_data:
            service.write_data(self.sheet, self.range, self._backup_data)
            logger.info(f"已恢复清空的数据: {self.sheet}!{self.range}")
            return f"已恢复数据: {self.sheet}!{self.range}"
        else:
            logger.warning("无法撤销：没有备份数据")
            return "无法撤销：没有备份数据"
