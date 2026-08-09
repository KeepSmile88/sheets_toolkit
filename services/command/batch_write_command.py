# 批量写入命令
import logging
from services.command.base_command import SheetCommand

logger = logging.getLogger("sheets_toolkit.command.batch_write")


class BatchWriteCommand(SheetCommand):
    """
    批量写入多个范围的数据。

    Args:
        data_list: [{"range": "Sheet1!A1", "values": [[...]]}, ...]
    """

    def __init__(self, data_list):
        self.data_list = data_list

    @property
    def description(self):
        return f"批量写入 {len(self.data_list)} 个区域"

    def execute(self, service):
        result = service.batch_update_values(self.data_list)
        return f"批量写入完成，共更新 {result.get('totalUpdatedCells', 0)} 个单元格"
