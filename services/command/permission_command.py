# 权限操作命令集
import logging
from services.command.base_command import SheetCommand

logger = logging.getLogger("sheets_toolkit.command.permission")


class InviteEditorCommand(SheetCommand):
    """邀请用户为编辑者"""

    def __init__(self, email):
        self.email = email

    @property
    def description(self):
        return f"邀请 {self.email} 为编辑者"

    def execute(self, service):
        service.invite_editor(self.email)
        return f"已邀请 {self.email} 为编辑者"


class SetPermissionCommand(SheetCommand):
    """设置用户权限"""

    def __init__(self, email, role='writer'):
        self.email = email
        self.role = role

    @property
    def description(self):
        return f"设置 {self.email} 权限为 {self.role}"

    def execute(self, service):
        service.set_permission(self.email, self.role)
        return f"已设置 {self.email} 权限为 {self.role}"


class RemoveAllPermissionsCommand(SheetCommand):
    """回收所有协作者权限"""

    @property
    def description(self):
        return "回收所有协作者权限"

    def execute(self, service):
        removed = service.remove_all_permissions()
        return f"已回收 {removed} 个协作者权限"
