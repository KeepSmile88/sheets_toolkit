# 写入数据命令（支持撤销）
import logging
from services.command.base_command import SheetCommand

logger = logging.getLogger("sheets_toolkit.command.write")


class WriteCommand(SheetCommand):
    """
    写入数据命令。
    执行前备份原有数据，支持 undo 撤销。
    """

    def __init__(self, sheet_name, range_, values):
        self.sheet = sheet_name
        self.range = range_
        self.values = values
        self._backup_data = None  # 执行前的原始数据

    @property
    def description(self):
        return f"写入数据到 {self.sheet}!{self.range}"

    def execute(self, service):
        # 备份原始数据（用于撤销）
        try:
            range_str = f"{self.sheet}!{self.range}"
            self._backup_data = service.read_data(range_str)
        except Exception:
            self._backup_data = None
            logger.debug("无法备份原始数据（目标区域可能为空）")

        result = service.write_data(self.sheet, self.range, self.values)
        return f"已写入 {result.get('updatedCells', 0)} 个单元格到 {self.sheet}!{self.range}"

    def undo(self, service):
        if self._backup_data is not None:
            service.write_data(self.sheet, self.range, self._backup_data)
            logger.info(f"已撤销写入: {self.sheet}!{self.range}")
            return f"已撤销写入 {self.sheet}!{self.range}"
        else:
            # 如果没有备份，则清空
            service.clear_data(f"{self.sheet}!{self.range}")
            logger.info(f"已撤销写入（清空）: {self.sheet}!{self.range}")
            return f"已撤销写入（清空） {self.sheet}!{self.range}"
