# modules/protection.py — 保护范围便捷函数
from services.sheet_service import SheetService


def protect_range(spreadsheet_id, sheet_id, start_row, end_row,
                  start_col, end_col, editors):
    """保护指定范围，限制可编辑用户"""
    return SheetService(spreadsheet_id).protect_range(
        sheet_id, start_row, end_row, start_col, end_col, editors
    )
