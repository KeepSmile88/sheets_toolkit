# 备份命令：复制 Spreadsheet + 导出 Excel 到本地 / 批量备份到指定文件夹
import logging
from services.command.base_command import SheetCommand

logger = logging.getLogger("sheets_toolkit.command.backup")


class BackupCommand(SheetCommand):
    """
    执行完整备份：在云端复制 Spreadsheet + 导出 Excel 到本地。
    """

    def __init__(self, backup_dir=None):
        self.backup_dir = backup_dir
        self.result = None

    @property
    def description(self):
        return "完整备份（云端 + 本地）"

    def execute(self, service):
        self.result = service.backup(self.backup_dir)
        return (
            f"备份完成: 云端 ID={self.result['cloud_id']}, "
            f"本地文件={self.result['local_file']}"
        )


class BackupToFolderCommand(SheetCommand):
    """
    将当前 Spreadsheet 备份到指定的 Google Drive 文件夹中。
    """

    def __init__(self, folder_id):
        self.folder_id = folder_id
        self.result = None

    @property
    def description(self):
        return f"备份到文件夹 {self.folder_id[:15]}..."

    def execute(self, service):
        self.result = service.copy_to_folder(self.folder_id)
        return (
            f"备份成功: {self.result.get('name')} "
            f"(ID: {self.result.get('id')})"
        )


class BatchBackupCommand(SheetCommand):
    """
    批量备份多个 Spreadsheet 到指定的 Google Drive 文件夹。

    注意：此命令不使用 service 参数，而是自己创建多个 SheetService。
    """

    def __init__(self, spreadsheet_ids, folder_id, progress_callback=None):
        self.spreadsheet_ids = spreadsheet_ids
        self.folder_id = folder_id
        self.progress_callback = progress_callback
        self.results = []

    @property
    def description(self):
        return f"批量备份 {len(self.spreadsheet_ids)} 个表格到文件夹"

    def execute(self, service):
        from services.sheet_service import SheetService
        self.results = SheetService.batch_backup_to_folder(
            self.spreadsheet_ids,
            self.folder_id,
            self.progress_callback
        )
        success = sum(1 for r in self.results if r["status"] == "success")
        total = len(self.results)
        return f"批量备份完成: {success}/{total} 成功"
