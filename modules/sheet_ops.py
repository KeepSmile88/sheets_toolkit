# modules/sheet_ops.py — Sheet 查询便捷函数
from services.sheet_service import SheetService


def list_sheet_names(spreadsheet_id):
    """获取所有工作表名称列表"""
    return SheetService(spreadsheet_id).list_sheets()


def get_sheet_id_by_name(spreadsheet_id, sheet_name):
    """根据名称获取 Sheet ID"""
    return SheetService(spreadsheet_id).get_sheet_id_by_name(sheet_name)
