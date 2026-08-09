from services.command.base_command import BaseCommand

class BatchUpdateCommand(BaseCommand):
    """
    基于批量坐标和数据列表，执行批量数据覆写命令 (支持撤销)
    """
    def __init__(self, service, update_data_list):
        """
        :param service: SheetService 实例
        :param update_data_list: 列表，格式为 [{"range": "Sheet1!A1:B2", "values": [[1, 2], [3, 4]]}, ...]
        """
        super().__init__(service)
        self.update_data_list = update_data_list
        self.previous_data_list = []
        
    def execute(self):
        # 1. 备份原始数据以便撤销
        self.previous_data_list = []
        for update in self.update_data_list:
            range_str = update["range"]
            # 读取当前数据
            old_values = self.service.read_data(range_str)
            self.previous_data_list.append({
                "range": range_str,
                "values": old_values
            })
            
        # 2. 组装并执行批量更新
        data = []
        for update in self.update_data_list:
            data.append({
                "range": update["range"],
                "values": update["values"]
            })
            
        body = {
            "valueInputOption": "USER_ENTERED",
            "data": data
        }
        
        self.service.service.spreadsheets().values().batchUpdate(
            spreadsheetId=self.service.spreadsheet_id,
            body=body
        ).execute()

    def undo(self):
        # 恢复原始数据
        if not self.previous_data_list:
            return
            
        body = {
            "valueInputOption": "USER_ENTERED",
            "data": self.previous_data_list
        }
        
        self.service.service.spreadsheets().values().batchUpdate(
            spreadsheetId=self.service.spreadsheet_id,
            body=body
        ).execute()


class BatchUpdateFormatCommand(BaseCommand):
    """
    执行批量格式化命令，如设置背景色和文字粗体等
    """
    def __init__(self, service, range_str, format_dict):
        super().__init__(service)
        self.range_str = range_str
        self.format_dict = format_dict
        
    def _parse_a1_notation(self, a1):
        """简单的 A1 到 GridRange 解析器"""
        import re
        parts = a1.split('!')
        sheet_name = parts[0] if len(parts) > 1 else None
        cells = parts[-1].split(':')
        
        start_cell = cells[0]
        end_cell = cells[1] if len(cells) > 1 else start_cell
        
        def col_to_index(col_str):
            num = 0
            for char in col_str:
                num = num * 26 + (ord(char.upper()) - ord('A') + 1)
            return num - 1

        match_start = re.match(r"([A-Za-z]+)(\d*)", start_cell)
        match_end = re.match(r"([A-Za-z]+)(\d*)", end_cell)
        
        grid_range = {}
        
        if sheet_name:
            sheet_id = self.service.get_sheet_id_by_name(sheet_name)
            if sheet_id is not None:
                grid_range["sheetId"] = sheet_id
                
        if match_start:
            grid_range["startColumnIndex"] = col_to_index(match_start.group(1))
            if match_start.group(2):
                grid_range["startRowIndex"] = int(match_start.group(2)) - 1
                
        if match_end:
            grid_range["endColumnIndex"] = col_to_index(match_end.group(1)) + 1
            if match_end.group(2):
                grid_range["endRowIndex"] = int(match_end.group(2))
                
        return grid_range

    def execute(self):
        grid_range = self._parse_a1_notation(self.range_str)
        fields = ",".join(self.format_dict.keys())
        
        request = {
            "repeatCell": {
                "range": grid_range,
                "cell": {
                    "userEnteredFormat": self.format_dict
                },
                "fields": f"userEnteredFormat({fields})"
            }
        }
        
        body = {
            "requests": [request]
        }
        self.service.service.spreadsheets().batchUpdate(
            spreadsheetId=self.service.spreadsheet_id,
            body=body
        ).execute()

    def undo(self):
        # TODO: 格式化撤销较为复杂，目前需要用户手动在 Google Sheet 历史中恢复
        pass
