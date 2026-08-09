# modules/drive_ops.py — Drive 操作便捷函数
from services.sheet_service import SheetService


def copy_spreadsheet(spreadsheet_id, new_name):
    """复制整个 Spreadsheet"""
    return SheetService(spreadsheet_id).copy_spreadsheet(new_name)
