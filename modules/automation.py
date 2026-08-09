# modules/automation.py — 自动化操作便捷函数
import logging
from services.sheet_service import SheetService

logger = logging.getLogger("sheets_toolkit.modules.automation")


def batch_copy_template(spreadsheet_id, template_sheet_id, n, prefix="副本"):
    """
    批量复制模板工作表。

    Args:
        spreadsheet_id: 目标 Spreadsheet ID
        template_sheet_id: 模板 Sheet ID
        n: 复制数量
        prefix: 名称前缀
    """
    service = SheetService(spreadsheet_id)
    results = []
    for i in range(n):
        result = service.copy_sheet(template_sheet_id)
        results.append(result)
        logger.info(f"已复制模板第 {i + 1}/{n} 份")
    return results


def batch_rename(spreadsheet_id, base_name='Sheet'):
    """批量重命名所有工作表"""
    service = SheetService(spreadsheet_id)
    return service.batch_rename_sheets(base_name)


def backup_spreadsheet(spreadsheet_id, backup_dir=None):
    """
    执行完整备份（云端复制 + 本地导出 Excel）。

    Args:
        spreadsheet_id: Spreadsheet ID
        backup_dir: 备份保存目录（默认使用配置中的目录）
    """
    service = SheetService(spreadsheet_id)
    return service.backup(backup_dir)
