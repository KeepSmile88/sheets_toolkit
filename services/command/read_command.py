# 读取数据命令
import logging
from services.command.base_command import SheetCommand

logger = logging.getLogger("sheets_toolkit.command.read")


class ReadCommand(SheetCommand):
    """读取指定范围数据"""

    def __init__(self, sheet_name, range_):
        self.sheet = sheet_name
        self.range = range_
        self.result_data = None

    @property
    def description(self):
        return f"读取 {self.sheet}!{self.range}"

    def execute(self, service):
        range_str = f"{self.sheet}!{self.range}"
        self.result_data = service.read_data(range_str)
        rows = len(self.result_data)
        logger.info(f"读取 {range_str}，共 {rows} 行")
        return self.result_data
