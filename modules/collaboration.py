# modules/collaboration.py — 协作管理便捷函数
from services.sheet_service import SheetService


def invite_editor(spreadsheet_id, email):
    """邀请用户为编辑者"""
    return SheetService(spreadsheet_id).invite_editor(email)


def remove_all_permissions(spreadsheet_id):
    """回收所有协作者权限（保留 owner）"""
    return SheetService(spreadsheet_id).remove_all_permissions()


def set_readonly(spreadsheet_id, email):
    """设置用户为只读权限"""
    return SheetService(spreadsheet_id).set_permission(email, 'reader')
