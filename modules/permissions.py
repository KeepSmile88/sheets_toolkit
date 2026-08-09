# modules/permissions.py — 权限设置便捷函数
from services.sheet_service import SheetService


def set_file_permission(spreadsheet_id, email, role='writer'):
    """设置用户权限"""
    return SheetService(spreadsheet_id).set_permission(email, role)
