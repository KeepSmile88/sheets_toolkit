# modules/data_ops.py — 数据读写便捷函数（薄封装层）
# 所有操作委托给 SheetService，避免重复创建 API 实例
from services.sheet_service import SheetService


def read_range(spreadsheet_id, range_):
    """读取指定范围的数据"""
    service = SheetService(spreadsheet_id)
    return service.read_data(range_)


def write_range(spreadsheet_id, range_, values):
    """写入数据到指定范围（range_ 应包含 Sheet 名称如 'Sheet1!A1:B5'）"""
    service = SheetService(spreadsheet_id)
    # 解析 sheet_name 和 range
    if '!' in range_:
        sheet_name, cell_range = range_.split('!', 1)
    else:
        sheet_name = "Sheet1"
        cell_range = range_
    return service.write_data(sheet_name, cell_range, values)


def clear_range(spreadsheet_id, range_):
    """清空指定范围的数据"""
    service = SheetService(spreadsheet_id)
    return service.clear_data(range_)
