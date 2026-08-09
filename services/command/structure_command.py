# 结构操作命令集（创建/重命名/删除工作表）
import logging
from services.command.base_command import SheetCommand

logger = logging.getLogger("sheets_toolkit.command.structure")


class CreateSheetCommand(SheetCommand):
    """创建新工作表"""

    def __init__(self, title):
        self.title = title
        self._created_sheet_id = None

    @property
    def description(self):
        return f"创建工作表: {self.title}"

    def execute(self, service):
        result = service.create_sheet(self.title)
        # 提取新创建的 sheet ID
        replies = result.get("replies", [])
        if replies:
            props = replies[0].get("addSheet", {}).get("properties", {})
            self._created_sheet_id = props.get("sheetId")
        return f"已创建工作表: {self.title}"

    def undo(self, service):
        if self._created_sheet_id is not None:
            service.delete_sheet(self._created_sheet_id)
            return f"已撤销创建工作表: {self.title}"
        return "无法撤销：未记录工作表 ID"


class RenameSheetCommand(SheetCommand):
    """重命名工作表"""

    def __init__(self, sheet_id, new_name):
        self.sheet_id = sheet_id
        self.new_name = new_name
        self._old_name = None

    @property
    def description(self):
        return f"重命名工作表为: {self.new_name}"

    def execute(self, service):
        # 备份旧名称
        meta = service.get_metadata()
        for s in meta['sheets']:
            if s['properties']['sheetId'] == self.sheet_id:
                self._old_name = s['properties']['title']
                break
        service.rename_sheet(self.sheet_id, self.new_name)
        return f"已重命名: {self._old_name} -> {self.new_name}"

    def undo(self, service):
        if self._old_name:
            service.rename_sheet(self.sheet_id, self._old_name)
            return f"已恢复名称: {self._old_name}"
        return "无法撤销：未记录原名称"


class DeleteRowsCommand(SheetCommand):
    """删除指定行范围"""

    def __init__(self, sheet_id, start_row, end_row):
        self.sheet_id = sheet_id
        self.start_row = start_row
        self.end_row = end_row

    @property
    def description(self):
        return f"删除第 {self.start_row + 1}-{self.end_row} 行"

    def execute(self, service):
        service.delete_rows(self.sheet_id, self.start_row, self.end_row)
        return f"已删除第 {self.start_row + 1}-{self.end_row} 行"

    def undo(self, service):
        return "无法撤销：删除行操作目前不可逆（除非有全量备份）"


class BatchCreateSheetsCommand(SheetCommand):
    """批量创建指定名称的工作表"""
    
    def __init__(self, names):
        self.names = names
        self._created_ids = []

    @property
    def description(self):
        return f"批量创建 {len(self.names)} 个工作表"

    def execute(self, service):
        requests = [{"addSheet": {"properties": {"title": name}}} for name in self.names]
        result = service.service.spreadsheets().batchUpdate(
            spreadsheetId=service.spreadsheet_id,
            body={"requests": requests}
        ).execute()
        
        replies = result.get("replies", [])
        for rep in replies:
            props = rep.get("addSheet", {}).get("properties", {})
            if "sheetId" in props:
                self._created_ids.append(props["sheetId"])
                
        return f"已成功批量新建 {len(self.names)} 个工作表"

    def undo(self, service):
        if not self._created_ids:
            return "无法撤销：未记录到新工作表 ID"
        requests = [{"deleteSheet": {"sheetId": sid}} for sid in self._created_ids]
        service.service.spreadsheets().batchUpdate(
            spreadsheetId=service.spreadsheet_id,
            body={"requests": requests}
        ).execute()
        return f"已撤销批量建表（清除了 {len(self._created_ids)} 个工作表）"


class ClearAdvancedCommand(SheetCommand):
    """高级区域清空命令（可选清空值或批注）"""

    def __init__(self, range_str, clear_values=True, clear_notes=False):
        self.range_str = range_str
        self.clear_values = clear_values
        self.clear_notes = clear_notes

    @property
    def description(self):
        parts = []
        if self.clear_values: parts.append("内容/公式")
        if self.clear_notes: parts.append("批注")
        return f"清空 {self.range_str} 的 {'与'.join(parts)}"

    def execute(self, service):
        # google sheets API userEnteredFormat 等 fields 来剥离清空
        fields = []
        if self.clear_values:
            fields.append("userEnteredValue")
        if self.clear_notes:
            fields.append("note")
            
        if not fields:
            return "未选择任何清空项"
            
        field_mask = ",".join(fields)
        
        # 将 range_str 转为 GridRange 比较麻烦，但 UpdateCells 也可以通过 DataFilter 使用 a1Range
        # 为了兼容撤销，真正的原位清空比较复杂，这里我们仅发起正向清空
        requests = [{
            "updateCells": {
                "range": service._parse_range(self.range_str),
                "fields": field_mask
            }
        }]
        
        service.service.spreadsheets().batchUpdate(
            spreadsheetId=service.spreadsheet_id,
            body={"requests": requests}
        ).execute()
        
        return f"已清空 {self.range_str} 的所选属性"

    def undo(self, service):
        return "无法撤销：当前清空操作不可逆（请提前备份）"


class InsertRowsCommand(SheetCommand):
    """指定位置插入若干空行"""
    
    def __init__(self, sheet_id, start_index, num_rows):
        self.sheet_id = sheet_id
        self.start_index = start_index
        self.num_rows = num_rows

    @property
    def description(self):
        return f"在第 {self.start_index + 1} 行位置插入 {self.num_rows} 行"

    def execute(self, service):
        requests = [{
            "insertDimension": {
                "range": {
                    "sheetId": self.sheet_id,
                    "dimension": "ROWS",
                    "startIndex": self.start_index,
                    "endIndex": self.start_index + self.num_rows
                },
                "inheritFromBefore": True
            }
        }]
        service.service.spreadsheets().batchUpdate(
            spreadsheetId=service.spreadsheet_id,
            body={"requests": requests}
        ).execute()
        return f"成功插入 {self.num_rows} 行"

    def undo(self, service):
        # 撤销插入等同于删除这些行
        requests = [{
            "deleteDimension": {
                "range": {
                    "sheetId": self.sheet_id,
                    "dimension": "ROWS",
                    "startIndex": self.start_index,
                    "endIndex": self.start_index + self.num_rows
                }
            }
        }]
        service.service.spreadsheets().batchUpdate(
            spreadsheetId=service.spreadsheet_id,
            body={"requests": requests}
        ).execute()
        return f"已撤销并删除了刚才插入的 {self.num_rows} 行"
