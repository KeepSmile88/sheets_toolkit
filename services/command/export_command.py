# 导出 Excel 文件命令
import logging
from services.command.base_command import SheetCommand

logger = logging.getLogger("sheets_toolkit.command.export")


class ExportCommand(SheetCommand):
    """导出 Spreadsheet 为 Excel 文件"""

    def __init__(self, output_file):
        self.output_file = output_file

    @property
    def description(self):
        return f"导出 Excel 到 {self.output_file}"

    def execute(self, service):
        service.export_excel(self.output_file)
        return f"已导出 Excel: {self.output_file}"
