# modules/structure_ops.py — 结构操作便捷函数（薄封装层）
from services.sheet_service import SheetService


def create_sheet(spreadsheet_id, title):
    """创建新工作表"""
    return SheetService(spreadsheet_id).create_sheet(title)


def rename_sheet(spreadsheet_id, sheet_id, new_name):
    """重命名工作表"""
    return SheetService(spreadsheet_id).rename_sheet(sheet_id, new_name)


def clear_range(spreadsheet_id, range_):
    """清空区域数据"""
    return SheetService(spreadsheet_id).clear_data(range_)


def delete_rows(spreadsheet_id, sheet_id, start_row, end_row):
    """删除指定行范围"""
    return SheetService(spreadsheet_id).delete_rows(sheet_id, start_row, end_row)


def copy_sheet(spreadsheet_id, sheet_id, dest_spreadsheet_id=None):
    """复制工作表到目标 Spreadsheet"""
    return SheetService(spreadsheet_id).copy_sheet(sheet_id, dest_spreadsheet_id)


def list_sheet_names(spreadsheet_id):
    """获取所有工作表名称列表"""
    return SheetService(spreadsheet_id).list_sheets()


def export_to_excel(spreadsheet_id, file_path):
    """导出为 Excel 文件"""
    return SheetService(spreadsheet_id).export_excel(file_path)
