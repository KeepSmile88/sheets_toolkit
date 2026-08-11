# SheetService 门面类 — 统一封装所有 Google Sheets/Drive 操作
import os
import logging
from datetime import datetime
from core.auth import AuthManager
from core.exceptions import retry_on_api_error, ValidationError

logger = logging.getLogger("sheets_toolkit.service")


class SheetService:
    """
    Google Sheets 操作服务类。
    作为所有 Sheet/Drive 操作的统一入口（门面模式）。
    """

    def __init__(self, spreadsheet_id):
        if not spreadsheet_id or not spreadsheet_id.strip():
            raise ValidationError("Spreadsheet ID 不能为空")
        self.spreadsheet_id = spreadsheet_id.strip()
        self._auth = AuthManager()

    @property
    def sheet_api(self):
        return self._auth.sheets_api.spreadsheets()

    @property
    def service(self):
        """暴露底层服务对象以兼容基于 service.spreadsheets() 的各种调用"""
        return self._auth.sheets_api

    @property
    def drive_api(self):
        return self._auth.drive_api

    # ========================
    # 元数据查询
    # ========================

    @retry_on_api_error()
    def get_metadata(self):
        """获取 Spreadsheet 完整元数据"""
        return self.sheet_api.get(spreadsheetId=self.spreadsheet_id).execute()

    def list_sheets(self):
        """获取所有 Sheet 名称列表"""
        meta = self.get_metadata()
        return [s['properties']['title'] for s in meta['sheets']]

    def get_sheet_id_by_name(self, sheet_name):
        """根据名称获取 Sheet ID"""
        meta = self.get_metadata()
        for s in meta['sheets']:
            if s['properties']['title'] == sheet_name:
                return s['properties']['sheetId']
        return None

    def get_sheet_id_by_index(self, index):
        """根据索引获取 Sheet ID"""
        meta = self.get_metadata()
        sheets = meta.get('sheets', [])
        if 0 <= index < len(sheets):
            return sheets[index]['properties']['sheetId']
        return None

    # ========================
    # 数据读写
    # ========================

    @retry_on_api_error()
    def read_data(self, range_str):
        """
        读取指定范围的数据。

        Args:
            range_str: 范围字符串，如 "Sheet1!A1:B5"
        """
        result = self.sheet_api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=range_str
        ).execute()
        return result.get('values', [])

    @retry_on_api_error()
    def write_data(self, sheet_name, range_, values):
        """
        写入数据到指定范围。

        Args:
            sheet_name: 工作表名称
            range_: 范围（如 "A1:B5"）
            values: 二维列表数据
        """
        range_str = f"{sheet_name}!{range_}"
        body = {"values": values}
        result = self.sheet_api.values().update(
            spreadsheetId=self.spreadsheet_id,
            range=range_str,
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()
        logger.info(f"写入数据到 {range_str}，更新 {result.get('updatedCells', 0)} 个单元格")
        return result

    @retry_on_api_error()
    def append_data(self, sheet_name, range_, values, value_input_option="USER_ENTERED"):
        """追加数据到表格末尾"""
        range_str = f"{sheet_name}!{range_}"
        body = {"values": values}
        result = self.sheet_api.values().append(
            spreadsheetId=self.spreadsheet_id,
            range=range_str,
            valueInputOption=value_input_option,
            body=body
        ).execute()
        logger.info(f"追加数据到 {range_str}")
        return result

    @retry_on_api_error()
    def read_formulas(self, range_str):
        """
        读取指定范围的公式（而非计算后的值）。

        Args:
            range_str: 如 "Sheet1!A1:B5"

        Returns:
            二维列表，包含公式字符串
        """
        result = self.sheet_api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=range_str,
            valueRenderOption="FORMULA"
        ).execute()
        return result.get('values', [])

    @staticmethod
    def batch_write_formula_to_sheets(spreadsheet_ids, sheet_name, cell_range,
                                       formula, progress_callback=None):
        """
        批量向多个 Spreadsheet 的指定位置写入公式。

        Args:
            spreadsheet_ids: Spreadsheet ID 列表
            sheet_name: 工作表名称
            cell_range: 单元格范围（如 "A1" 或 "A1:C1"）
            formula: 公式字符串（如 "=SUM(B2:B100)"）
            progress_callback: 进度回调 (current, total, message)

        Returns:
            results 列表
        """
        results = []
        total = len(spreadsheet_ids)

        for i, sid in enumerate(spreadsheet_ids):
            sid = sid.strip()
            if not sid:
                continue

            try:
                service = SheetService(sid)
                title = service.get_spreadsheet_title()

                if progress_callback:
                    progress_callback(
                        i, total,
                        f"正在写入 ({i + 1}/{total}): {title}"
                    )

                # 写入公式（USER_ENTERED 模式会解析公式）
                service.write_data(sheet_name, cell_range, [[formula]])

                results.append({
                    "source_id": sid,
                    "title": title,
                    "status": "success"
                })
                logger.info(f"批量写公式 [{i + 1}/{total}] 成功: {title}")

            except Exception as e:
                results.append({
                    "source_id": sid,
                    "title": sid[:20] + "...",
                    "status": "error",
                    "error": str(e)
                })
                logger.error(f"批量写公式 [{i + 1}/{total}] 失败: {sid} - {e}")

        if progress_callback:
            success = sum(1 for r in results if r["status"] == "success")
            progress_callback(total, total, f"完成: {success}/{total} 成功")

        return results

    @retry_on_api_error()
    def clear_data(self, range_str):
        """
        清空指定范围的数据。

        Args:
            range_str: 范围字符串，如 "Sheet1!A1:B5"
        """
        result = self.sheet_api.values().clear(
            spreadsheetId=self.spreadsheet_id,
            range=range_str
        ).execute()
        logger.info(f"已清空区域: {range_str}")
        return result

    @retry_on_api_error()
    def batch_update_values(self, data_list):
        """
        批量写入多个范围的数据。

        Args:
            data_list: [{"range": "Sheet1!A1", "values": [[...]]}, ...]
        """
        body = {
            "valueInputOption": "USER_ENTERED",
            "data": data_list
        }
        result = self.sheet_api.values().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body=body
        ).execute()
        logger.info(f"批量更新完成，共 {result.get('totalUpdatedCells', 0)} 个单元格")
        return result

    # ========================
    # 结构操作
    # ========================

    @retry_on_api_error()
    def create_sheet(self, title):
        """创建新的工作表"""
        body = {
            "requests": [{
                "addSheet": {
                    "properties": {"title": title}
                }
            }]
        }
        result = self.sheet_api.batchUpdate(
            spreadsheetId=self.spreadsheet_id, body=body
        ).execute()
        logger.info(f"已创建工作表: {title}")
        return result

    @retry_on_api_error()
    def rename_sheet(self, sheet_id, new_name):
        """重命名工作表"""
        body = {
            "requests": [{
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "title": new_name
                    },
                    "fields": "title"
                }
            }]
        }
        result = self.sheet_api.batchUpdate(
            spreadsheetId=self.spreadsheet_id, body=body
        ).execute()
        logger.info(f"已重命名工作表 {sheet_id} -> {new_name}")
        return result

    @retry_on_api_error()
    def delete_sheet(self, sheet_id):
        """删除工作表"""
        body = {
            "requests": [{
                "deleteSheet": {"sheetId": sheet_id}
            }]
        }
        result = self.sheet_api.batchUpdate(
            spreadsheetId=self.spreadsheet_id, body=body
        ).execute()
        logger.info(f"已删除工作表: {sheet_id}")
        return result

    @retry_on_api_error()
    def delete_rows(self, sheet_id, start_row, end_row):
        """删除指定行范围"""
        body = {
            "requests": [{
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": start_row,
                        "endIndex": end_row
                    }
                }
            }]
        }
        result = self.sheet_api.batchUpdate(
            spreadsheetId=self.spreadsheet_id, body=body
        ).execute()
        logger.info(f"已删除第 {start_row}-{end_row} 行")
        return result

    def preview_rows_to_delete(self, sheet_name, date_column, cutoff_date,
                               skip_header=True, progress_callback=None):
        """
        预览将要删除的行（只扫描不执行删除）。

        返回待删除行的详细信息，供用户确认后再执行实际删除操作。

        Args:
            sheet_name: 工作表名称
            date_column: 日期所在列字母（如 "A", "B", "C"）
            cutoff_date: 截止日期 (datetime)
            skip_header: 是否跳过第一行（表头）
            progress_callback: 进度回调 (message)

        Returns:
            dict: {
                "sheet_name": str,
                "total_rows": int,
                "rows_to_delete": list[dict],  # 每项含 row_index, reason, preview
                "deleted_by_date": int,
                "deleted_empty": int,
                "total_to_delete": int,
                "header": list  # 表头行（如有）
            }
        """
        from datetime import datetime

        # 列字母转为 0-based 索引 (A=0, B=1, ...)
        col_letter = date_column.upper().strip()
        col_index = 0
        for ch in col_letter:
            col_index = col_index * 26 + (ord(ch) - ord('A'))

        # 读取整个工作表数据
        if progress_callback:
            progress_callback(f"正在读取 {sheet_name} 的数据...")
        all_data = self.read_data(sheet_name)

        if not all_data:
            return {
                "sheet_name": sheet_name,
                "total_rows": 0,
                "rows_to_delete": [],
                "deleted_by_date": 0,
                "deleted_empty": 0,
                "total_to_delete": 0,
                "header": []
            }

        # 日期解析格式列表
        date_formats = [
            "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y",
            "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
            "%d-%m-%Y", "%Y.%m.%d", "%d.%m.%Y",
        ]

        def try_parse_date(text):
            """尝试用多种格式解析日期字符串"""
            if not text or not str(text).strip():
                return None
            text = str(text).strip()
            for fmt in date_formats:
                try:
                    return datetime.strptime(text, fmt)
                except ValueError:
                    continue
            try:
                return datetime.fromisoformat(text)
            except (ValueError, TypeError):
                return None

        start_row = 1 if skip_header else 0
        header = all_data[0] if skip_header and all_data else []
        rows_to_delete = []
        deleted_by_date = 0
        deleted_empty = 0

        if progress_callback:
            progress_callback(f"正在扫描 {len(all_data)} 行数据...")

        for row_idx in range(start_row, len(all_data)):
            row = all_data[row_idx]

            # 检查是否为空行
            if not row or all(str(cell).strip() == '' for cell in row):
                rows_to_delete.append({
                    "row_index": row_idx + 1,  # 转换为 1-based 展示
                    "reason": "空行",
                    "preview": "(空行)"
                })
                deleted_empty += 1
                continue

            # 检查日期列
            if col_index < len(row):
                cell_value = row[col_index]
                parsed_date = try_parse_date(cell_value)
                if parsed_date and parsed_date < cutoff_date:
                    # 行数据预览（取前 5 列）
                    preview_data = [str(c)[:20] for c in row[:5]]
                    rows_to_delete.append({
                        "row_index": row_idx + 1,
                        "reason": f"日期过期 ({cell_value})",
                        "preview": " | ".join(preview_data)
                    })
                    deleted_by_date += 1

        return {
            "sheet_name": sheet_name,
            "total_rows": len(all_data),
            "rows_to_delete": rows_to_delete,
            "deleted_by_date": deleted_by_date,
            "deleted_empty": deleted_empty,
            "total_to_delete": deleted_by_date + deleted_empty,
            "header": header
        }

    def delete_rows_by_date_and_empty(self, sheet_name, date_column, cutoff_date,
                                       skip_header=True, progress_callback=None):
        """
        批量删除日期早于指定日期的行和空行。

        Args:
            sheet_name: 工作表名称
            date_column: 日期所在列字母（如 "A", "B", "C"）
            cutoff_date: 截止日期 (datetime)，早于此日期的行将被删除
            skip_header: 是否跳过第一行（表头）
            progress_callback: 进度回调 (message)

        Returns:
            dict: {"deleted_by_date": int, "deleted_empty": int, "total_deleted": int}
        """
        from datetime import datetime

        # 列字母转为 0-based 索引 (A=0, B=1, ...)
        col_letter = date_column.upper().strip()
        col_index = 0
        for ch in col_letter:
            col_index = col_index * 26 + (ord(ch) - ord('A'))

        # 读取整个工作表数据
        range_str = f"{sheet_name}"
        if progress_callback:
            progress_callback(f"正在读取 {sheet_name} 的数据...")
        all_data = self.read_data(range_str)

        if not all_data:
            logger.info(f"{sheet_name} 无数据")
            return {"deleted_by_date": 0, "deleted_empty": 0, "total_deleted": 0}

        # 获取 Sheet ID
        sheet_id = self.get_sheet_id_by_name(sheet_name)
        if sheet_id is None:
            raise ValidationError(f"找不到工作表: {sheet_name}")

        # 常见日期格式列表
        date_formats = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%d-%m-%Y",
            "%Y.%m.%d",
            "%d.%m.%Y",
        ]

        def try_parse_date(text):
            """尝试用多种格式解析日期字符串"""
            if not text or not str(text).strip():
                return None
            text = str(text).strip()
            for fmt in date_formats:
                try:
                    return datetime.strptime(text, fmt)
                except ValueError:
                    continue
            # 尝试 ISO 格式
            try:
                return datetime.fromisoformat(text)
            except (ValueError, TypeError):
                return None

        # 标记要删除的行（从第 1 行或第 0 行开始）
        start_row = 1 if skip_header else 0
        rows_to_delete = []  # 存储 0-based 行索引
        deleted_by_date = 0
        deleted_empty = 0

        if progress_callback:
            progress_callback(f"正在分析 {len(all_data)} 行数据...")

        for row_idx in range(start_row, len(all_data)):
            row = all_data[row_idx]

            # 检查是否为空行
            if not row or all(str(cell).strip() == '' for cell in row):
                rows_to_delete.append(row_idx)
                deleted_empty += 1
                continue

            # 检查日期列
            if col_index < len(row):
                cell_value = row[col_index]
                parsed_date = try_parse_date(cell_value)
                if parsed_date and parsed_date < cutoff_date:
                    rows_to_delete.append(row_idx)
                    deleted_by_date += 1

        if not rows_to_delete:
            logger.info(f"{sheet_name}: 没有需要删除的行")
            return {"deleted_by_date": 0, "deleted_empty": 0, "total_deleted": 0}

        # 从后向前排序，避免删除时索引偏移
        rows_to_delete.sort(reverse=True)

        if progress_callback:
            progress_callback(
                f"正在删除 {len(rows_to_delete)} 行 "
                f"(日期过期: {deleted_by_date}, 空行: {deleted_empty})..."
            )

        # 合并连续行为区间，减少 API 调用次数
        delete_ranges = []
        i = 0
        while i < len(rows_to_delete):
            end = rows_to_delete[i]
            start = end
            # 向后查找连续行（因为是降序排列）
            while i + 1 < len(rows_to_delete) and rows_to_delete[i + 1] == start - 1:
                start = rows_to_delete[i + 1]
                i += 1
            delete_ranges.append((start, end + 1))  # API 是 [start, end) 半开区间
            i += 1

        # 构建批量删除请求（已按从后向前排列）
        requests = []
        for start, end in delete_ranges:
            requests.append({
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": start,
                        "endIndex": end
                    }
                }
            })

        # 执行批量删除
        self.sheet_api.batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": requests}
        ).execute()

        total = deleted_by_date + deleted_empty
        logger.info(
            f"{sheet_name}: 已删除 {total} 行 "
            f"(日期过期: {deleted_by_date}, 空行: {deleted_empty})"
        )

        if progress_callback:
            progress_callback(
                f"✅ {sheet_name}: 已删除 {total} 行 "
                f"(日期过期: {deleted_by_date}, 空行: {deleted_empty})"
            )

        return {
            "deleted_by_date": deleted_by_date,
            "deleted_empty": deleted_empty,
            "total_deleted": total
        }

    # ========================
    # 备注 (Notes) 管理
    # ========================

    @retry_on_api_error()
    def set_note(self, sheet_name, row, col, note_text):
        """
        在指定单元格写入备注。

        Args:
            sheet_name: 工作表名称
            row: 行号（0-based）
            col: 列号（0-based）
            note_text: 备注内容
        """
        sheet_id = self.get_sheet_id_by_name(sheet_name)
        if sheet_id is None:
            raise ValidationError(f"找不到工作表: {sheet_name}")

        requests = [{
            "updateCells": {
                "rows": [{
                    "values": [{
                        "note": note_text
                    }]
                }],
                "fields": "note",
                "start": {
                    "sheetId": sheet_id,
                    "rowIndex": row,
                    "columnIndex": col
                }
            }
        }]
        self.sheet_api.batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": requests}
        ).execute()
        col_letter = chr(ord('A') + col) if col < 26 else f"col{col}"
        logger.info(f"已在 {sheet_name}!{col_letter}{row + 1} 写入备注")

    @retry_on_api_error()
    def delete_note(self, sheet_name, row, col):
        """
        删除指定单元格的备注。

        Args:
            sheet_name: 工作表名称
            row: 行号（0-based）
            col: 列号（0-based）
        """
        # 写入空字符串即可删除备注
        self.set_note(sheet_name, row, col, "")
        col_letter = chr(ord('A') + col) if col < 26 else f"col{col}"
        logger.info(f"已删除 {sheet_name}!{col_letter}{row + 1} 的备注")

    @retry_on_api_error()
    def clear_all_notes_in_sheet(self, sheet_name):
        """
        清除指定工作表中所有单元格的备注。

        使用 repeatCell 请求将整个工作表的 note 字段设为空。
        """
        sheet_id = self.get_sheet_id_by_name(sheet_name)
        if sheet_id is None:
            raise ValidationError(f"找不到工作表: {sheet_name}")

        requests = [{
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id
                },
                "cell": {
                    "note": ""
                },
                "fields": "note"
            }
        }]
        self.sheet_api.batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": requests}
        ).execute()
        logger.info(f"已清除 {sheet_name} 中所有备注")

    def clear_all_notes(self):
        """清除所有工作表中的全部备注"""
        sheets = self.list_sheets()
        count = 0
        for sheet_name in sheets:
            self.clear_all_notes_in_sheet(sheet_name)
            count += 1
        logger.info(f"已清除全部 {count} 个工作表的备注")
        return count

    @retry_on_api_error()
    def get_notes_in_range(self, sheet_name, start_row=0, end_row=None,
                           start_col=0, end_col=None):
        """
        获取指定区域内所有有批注的单元格。

        通过 spreadsheets.get 的 includeGridData 参数拉取 gridData，
        从中提取 note 字段。

        Args:
            sheet_name: 工作表名称
            start_row: 起始行（0-based，默认 0）
            end_row: 结束行（0-based，不含；None 表示不限制）
            start_col: 起始列（0-based，默认 0）
            end_col: 结束列（0-based，不含；None 表示不限制）

        Returns:
            list[dict]: 包含批注的单元格列表
            [{"cell": "A1", "row": 0, "col": 0, "note": "批注内容"}, ...]
        """
        # 构建 A1 范围字符串
        def col_to_letter(c):
            """将 0-based 列号转换为字母（支持多位，如 AA, AB）"""
            result = ""
            while True:
                result = chr(ord('A') + c % 26) + result
                c = c // 26 - 1
                if c < 0:
                    break
            return result

        range_str = sheet_name
        if end_row is not None or end_col is not None:
            s_col = col_to_letter(start_col)
            s_row = start_row + 1  # A1 记法 1-based
            range_str = f"{sheet_name}!{s_col}{s_row}"
            if end_row is not None and end_col is not None:
                e_col = col_to_letter(end_col - 1)
                e_row = end_row
                range_str += f":{e_col}{e_row}"

        # 使用 includeGridData 获取完整单元格数据（含 note）
        resp = self.sheet_api.get(
            spreadsheetId=self.spreadsheet_id,
            ranges=[range_str],
            includeGridData=True
        ).execute()

        notes = []
        for sheet_data in resp.get("sheets", []):
            for grid in sheet_data.get("data", []):
                row_offset = grid.get("startRow", 0)
                col_offset = grid.get("startColumn", 0)
                for r_idx, row_data in enumerate(grid.get("rowData", [])):
                    for c_idx, cell_data in enumerate(row_data.get("values", [])):
                        note_text = cell_data.get("note", "")
                        if note_text:
                            abs_row = row_offset + r_idx
                            abs_col = col_offset + c_idx
                            cell_label = f"{col_to_letter(abs_col)}{abs_row + 1}"
                            notes.append({
                                "cell": cell_label,
                                "row": abs_row,
                                "col": abs_col,
                                "note": note_text
                            })

        logger.info(f"获取批注: {sheet_name} 范围内共 {len(notes)} 条")
        return notes

    @staticmethod
    def batch_manage_notes(spreadsheet_ids, action, sheet_name=None,
                           row=None, col=None, note_text=None,
                           progress_callback=None):
        """
        批量对多个 Spreadsheet 执行备注操作。

        Args:
            spreadsheet_ids: Spreadsheet ID 列表
            action: 操作类型 "write" / "delete" / "clear_all"
            sheet_name: 工作表名称（write/delete 时必填）
            row: 行号 0-based（write/delete 时必填）
            col: 列号 0-based（write/delete 时必填）
            note_text: 备注内容（write 时必填）
            progress_callback: 进度回调 (current, total, message)

        Returns:
            results 列表
        """
        results = []
        total = len(spreadsheet_ids)

        for i, sid in enumerate(spreadsheet_ids):
            sid = sid.strip()
            if not sid:
                continue

            try:
                service = SheetService(sid)
                title = service.get_spreadsheet_title()

                if progress_callback:
                    progress_callback(
                        i, total,
                        f"({i + 1}/{total}) 处理: {title}"
                    )

                if action == "write":
                    service.set_note(sheet_name, row, col, note_text)
                    results.append({
                        "id": sid, "title": title, "status": "success",
                        "detail": f"已写入备注到 {sheet_name}"
                    })
                elif action == "delete":
                    service.delete_note(sheet_name, row, col)
                    results.append({
                        "id": sid, "title": title, "status": "success",
                        "detail": f"已删除备注 {sheet_name}"
                    })
                elif action == "clear_all":
                    count = service.clear_all_notes()
                    results.append({
                        "id": sid, "title": title, "status": "success",
                        "detail": f"已清除 {count} 个工作表的备注"
                    })

                logger.info(f"备注操作 [{i + 1}/{total}] 成功: {title}")

            except Exception as e:
                results.append({
                    "id": sid, "title": sid[:20] + "...",
                    "status": "error", "detail": str(e)
                })
                logger.error(f"备注操作 [{i + 1}/{total}] 失败: {sid} - {e}")

        if progress_callback:
            success = sum(1 for r in results if r["status"] == "success")
            progress_callback(total, total, f"完成: {success}/{total} 成功")

        return results


    @retry_on_api_error()
    def copy_sheet(self, sheet_id, dest_spreadsheet_id=None):
        """将工作表复制到目标 Spreadsheet"""
        dest_id = dest_spreadsheet_id or self.spreadsheet_id
        result = self.sheet_api.sheets().copyTo(
            spreadsheetId=self.spreadsheet_id,
            sheetId=sheet_id,
            body={"destinationSpreadsheetId": dest_id}
        ).execute()
        logger.info(f"已复制工作表 {sheet_id} -> {dest_id}")
        return result

    def copy_sheet_to_and_rename(self, sheet_id, dest_spreadsheet_id, new_name):
        """
        将工作表复制到目标 Spreadsheet 并重命名。

        流程：先用 copyTo 复制工作表到目标表格，再用 batchUpdate
        的 updateSheetProperties 将复制后的工作表重命名为指定名称。

        Args:
            sheet_id: 源工作表的 sheetId（数值）
            dest_spreadsheet_id: 目标 Spreadsheet ID
            new_name: 复制到目标后的新工作表名称

        Returns:
            dict: {"new_sheet_id": int, "title": str}
        """
        # 1. 复制工作表到目标 Spreadsheet
        copy_result = self.sheet_api.sheets().copyTo(
            spreadsheetId=self.spreadsheet_id,
            sheetId=sheet_id,
            body={"destinationSpreadsheetId": dest_spreadsheet_id}
        ).execute()

        new_sheet_id = copy_result.get("sheetId")
        if new_sheet_id is None:
            raise Exception("copyTo 返回结果中缺少 sheetId")

        # 2. 在目标 Spreadsheet 上重命名新工作表
        dest_service = SheetService(dest_spreadsheet_id)
        dest_service.sheet_api.batchUpdate(
            spreadsheetId=dest_spreadsheet_id,
            body={"requests": [{
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": new_sheet_id,
                        "title": new_name
                    },
                    "fields": "title"
                }
            }]}
        ).execute()

        logger.info(
            f"已复制工作表 {sheet_id} -> {dest_spreadsheet_id} "
            f"并重命名为 '{new_name}' (new_sheet_id={new_sheet_id})"
        )
        return {"new_sheet_id": new_sheet_id, "title": new_name}

    @staticmethod
    def batch_copy_sheet_to_targets(source_sid, sheet_name, targets,
                                    progress_callback=None):
        """
        批量将源表格中的某个工作表复制到多个目标表格并重命名。

        Args:
            source_sid: 源 Spreadsheet ID
            sheet_name: 要复制的工作表名称
            targets: 目标列表 [{"dest_id": "xxx", "new_name": "sheet1a"}, ...]
            progress_callback: 进度回调 (current, total, message)

        Returns:
            list[dict]: 结果列表
        """
        import time
        results = []

        # 预先过滤无效目标，确保 total 准确
        valid_targets = [
            t for t in targets
            if t.get("dest_id", "").strip()
        ]
        total = len(valid_targets)
        if total == 0:
            return results

        # 获取源工作表的 sheetId
        source_service = SheetService(source_sid)
        source_sheet_id = source_service.get_sheet_id_by_name(sheet_name)
        if source_sheet_id is None:
            raise Exception(f"源表格中找不到工作表: {sheet_name}")

        for i, target in enumerate(valid_targets):
            dest_id = target["dest_id"].strip()
            new_name = target.get("new_name", "").strip()
            final_name = new_name or sheet_name  # 未指定名称则使用原始工作表名

            try:
                # 获取目标表格标题
                dest_service = SheetService(dest_id)
                dest_title = dest_service.get_spreadsheet_title()

                if progress_callback:
                    progress_callback(
                        i, total,
                        f"({i + 1}/{total}) 正在复制到: {dest_title}..."
                    )

                # 执行复制+重命名
                copy_result = source_service.copy_sheet_to_and_rename(
                    source_sheet_id, dest_id, final_name
                )

                results.append({
                    "dest_id": dest_id,
                    "dest_title": dest_title,
                    "new_sheet_name": copy_result.get("title", final_name),
                    "status": "success"
                })
                logger.info(
                    f"批量复制工作表 [{i + 1}/{total}] 成功: "
                    f"'{final_name}' -> {dest_title}"
                )

                # 避免 API 限流（最后一个不需要等待）
                if i < total - 1:
                    time.sleep(1)

            except Exception as e:
                results.append({
                    "dest_id": dest_id,
                    "dest_title": dest_id[:20] + "...",
                    "new_sheet_name": final_name,
                    "status": "error",
                    "error": str(e)
                })
                logger.error(
                    f"批量复制工作表 [{i + 1}/{total}] 失败: {dest_id} - {e}"
                )

        if progress_callback:
            success = sum(1 for r in results if r["status"] == "success")
            progress_callback(
                total, total,
                f"完成: {success}/{total} 个目标表格复制成功"
            )

        return results

    @retry_on_api_error()
    def batch_rename_sheets(self, base_name="Sheet"):
        """批量重命名所有工作表"""
        meta = self.get_metadata()
        requests = []
        for i, sheet in enumerate(meta['sheets']):
            sheet_id = sheet['properties']['sheetId']
            requests.append({
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "title": f"{base_name}_{i + 1}"
                    },
                    "fields": "title"
                }
            })
        result = self.sheet_api.batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": requests}
        ).execute()
        logger.info(f"已批量重命名 {len(requests)} 个工作表")
        return result

    # ========================
    # 权限与协作
    # ========================

    @retry_on_api_error()
    def invite_editor(self, email):
        """邀请用户为编辑者"""
        body = {
            'type': 'user',
            'role': 'writer',
            'emailAddress': email
        }
        result = self.drive_api.permissions().create(
            fileId=self.spreadsheet_id, body=body
        ).execute()
        logger.info(f"已邀请 {email} 为编辑者")
        return result

    @retry_on_api_error()
    def set_permission(self, email, role='writer', batch=None):
        """设置用户权限"""
        body = {
            'type': 'user',
            'role': role,
            'emailAddress': email
        }
        req = self.drive_api.permissions().create(
            fileId=self.spreadsheet_id, body=body, fields='id'
        )
        if batch is not None:
            batch.add(req)
            return None
            
        result = req.execute()
        logger.info(f"已设置 {email} 权限为 {role}")
        return result

    @retry_on_api_error()
    def get_permission(self, permission_id):
        """获取特定协作者的权限信息"""
        return self.drive_api.permissions().get(
            fileId=self.spreadsheet_id,
            permissionId=permission_id,
            fields="*"
        ).execute()

    @retry_on_api_error()
    def set_copy_requires_writer_permission(self, require_writer: bool = True, batch=None):
        """
        设置“严禁针对该工作簿拉取副本、打印、下载”的安全选项。
        该选项会静默锁定所有 Reader 和 Commenter 的可导出版权。
        """
        body = {
            "copyRequiresWriterPermission": require_writer
        }
        req = self.drive_api.files().update(
            fileId=self.spreadsheet_id,
            body=body,
            fields="id, copyRequiresWriterPermission"
        )
        if batch is not None:
            batch.add(req)
            return None
            
        res = req.execute()

        status = "开启" if require_writer else "关闭"
        logger.info(f"成功将工作簿 {self.spreadsheet_id} 防盗版控制 {status}")
        return res

    @retry_on_api_error()
    def set_writers_can_share_permission(self, can_share: bool = False, batch=None):
        """
        限制编辑者是否具有分享工作簿和更改工作簿权限的能力。
        当 can_share=False 时，仅有 Owner (所有者) 可以管理权限。
        """
        body = {
            "writersCanShare": can_share
        }
        req = self.drive_api.files().update(
            fileId=self.spreadsheet_id,
            body=body,
            fields="id, writersCanShare"
        )
        if batch is not None:
            batch.add(req)
            return None
            
        res = req.execute()

        status = "独占已开启 (编辑者不可分享)" if not can_share else "独占已关闭 (编辑者可分享)"
        logger.info(f"成功将工作簿 {self.spreadsheet_id} 分享权限制修改为: {status}")
        return res

    def remove_permission_recursively(self, file_id, email):
        """
        递归向上移除父级目录中的权限。
        """
        from googleapiclient.errors import HttpError
        try:
            file_meta = self.drive_api.files().get(fileId=file_id, fields="parents").execute()
            parents = file_meta.get("parents", [])
        except HttpError:
            parents = []

        for parent_id in parents:
            try:
                perms_res = self.drive_api.permissions().list(
                    fileId=parent_id,
                    fields="permissions(id,emailAddress,type)"
                ).execute()
                
                for p in perms_res.get("permissions", []):
                    if p.get("type") == "user" and p.get("emailAddress", "").lower() == email.lower():
                        try:
                            self.drive_api.permissions().delete(
                                fileId=parent_id, permissionId=p["id"]
                            ).execute()
                            logger.info(f"已在父级 {parent_id} 中移除 {email} 的权限")
                        except HttpError as e:
                            if 'cannotDeletePermission' in str(e):
                                self.remove_permission_recursively(parent_id, email)
                            else:
                                raise
                        break
                else:
                    self.remove_permission_recursively(parent_id, email)
            except Exception as e:
                logger.warning(f"递归检查父级 {parent_id} 时出错: {e}")

    @retry_on_api_error()
    def remove_all_permissions(self, recursive=False, perms=None, batch=None):
        """回收所有协作者权限（保留 owner）"""
        if perms is None:
            perms = self.drive_api.permissions().list(
                fileId=self.spreadsheet_id,
                fields="permissions(id,emailAddress,role,type)"
            ).execute().get("permissions", [])
        removed = 0
        from googleapiclient.errors import HttpError
        for p in perms:
            if p["role"] != "owner":
                req = self.drive_api.permissions().delete(
                    fileId=self.spreadsheet_id, permissionId=p["id"]
                )
                if batch is not None:
                    batch.add(req)
                    removed += 1
                    continue
                    
                try:
                    req.execute()
                    removed += 1
                except HttpError as e:
                    if 'cannotDeletePermission' in str(e):
                        if recursive and p.get("type") == "user" and p.get("emailAddress"):
                            email = p["emailAddress"]
                            logger.info(f"权限 {email} 继承自父级，开始递归清理...")
                            self.remove_permission_recursively(self.spreadsheet_id, email)
                            try:
                                self.drive_api.permissions().delete(
                                    fileId=self.spreadsheet_id, permissionId=p["id"]
                                ).execute()
                                removed += 1
                            except HttpError:
                                pass
                        else:
                            logger.warning(f"跳过删除继承的权限: {p.get('emailAddress', p['id'])}")
                        continue
                    raise
        logger.info(f"已回收 {removed} 个协作者权限")
        return removed

    @retry_on_api_error()
    def remove_anyone_permission(self, perms=None, batch=None):
        """取消公开链接访问（Anyone 转受限）"""
        if perms is None:
            perms = self.drive_api.permissions().list(
                fileId=self.spreadsheet_id,
                fields="permissions(id,type)"
            ).execute().get("permissions", [])
        removed = 0
        from googleapiclient.errors import HttpError
        for p in perms:
            if p.get("type") == "anyone":
                req = self.drive_api.permissions().delete(
                    fileId=self.spreadsheet_id, permissionId=p["id"]
                )
                if batch is not None:
                    batch.add(req)
                    removed += 1
                    continue
                    
                try:
                    req.execute()
                    removed += 1
                except HttpError as e:
                    logger.warning(f"删除 anyone 权限失败: {e}")
        logger.info(f"已移除 {removed} 个 anyone 权限，转为受限访问")
        return removed

    @retry_on_api_error()
    def sync_permissions(self, target_emails, role="writer", recursive_remove=False, perms=None, batch=None):
        """一键同步权限"""
        if perms is None:
            perms = self.drive_api.permissions().list(
                fileId=self.spreadsheet_id,
                fields="permissions(id,emailAddress,role,type)"
            ).execute().get("permissions", [])
        
        target_emails_lower = {e.lower().strip() for e in target_emails if e.strip()}
        existing_emails_lower = set()
        
        from googleapiclient.errors import HttpError
        for p in perms:
            email = p.get("emailAddress", "").lower()
            if p["role"] == "owner":
                if email:
                    existing_emails_lower.add(email)
                continue
                
            if p.get("type") == "user" and email:
                if email not in target_emails_lower:
                    req = self.drive_api.permissions().delete(
                        fileId=self.spreadsheet_id, permissionId=p["id"]
                    )
                    if batch is not None:
                        batch.add(req)
                        continue
                        
                    try:
                        req.execute()
                    except HttpError as e:
                        if 'cannotDeletePermission' in str(e):
                            if recursive_remove:
                                self.remove_permission_recursively(self.spreadsheet_id, email)
                                try:
                                    self.drive_api.permissions().delete(
                                        fileId=self.spreadsheet_id, permissionId=p["id"]
                                    ).execute()
                                except HttpError:
                                    pass
                            else:
                                logger.warning(f"跳过删除继承的权限: {email}")
                        else:
                            raise
                else:
                    existing_emails_lower.add(email)
                    
        for email in target_emails_lower:
            if email not in existing_emails_lower:
                self.set_permission(email, role, batch=batch)
                
        logger.info(f"一键同步权限已生成，目标 {len(target_emails_lower)} 个用户")

    @retry_on_api_error()
    def list_permissions(self):
        """
        获取当前表格的所有协作者权限列表。

        Returns:
            list[dict]: 权限列表，每项包含 id、emailAddress、role、displayName、type、pendingOwner
        """
        resp = self.drive_api.permissions().list(
            fileId=self.spreadsheet_id,
            fields="permissions(id,emailAddress,role,displayName,type,pendingOwner)"
        ).execute()
        perms = resp.get("permissions", [])
        logger.info(f"获取权限列表: {len(perms)} 个协作者")
        return perms

    @retry_on_api_error()
    def accept_ownership(self, permission_id, batch=None):
        """
        接受转让的所有者权限。

        Args:
            permission_id: 权限 ID
        """
        req = self.drive_api.permissions().update(
            fileId=self.spreadsheet_id,
            permissionId=permission_id,
            body={"role": "owner"},
            transferOwnership=True,
            fields="id,role,emailAddress"
        )
        if batch is not None:
            batch.add(req)
            return None
            
        result = req.execute()
        logger.info(f"已接受所有者权限: {permission_id}")
        return result

    @retry_on_api_error()
    def remove_permission(self, permission_id, recursive=False, email=None, batch=None):
        """
        移除指定的协作者权限。
        
        Args:
            permission_id: 权限 ID
            recursive: 是否递归清理继承的权限
            email: 目标邮箱（用于递归清理）
        """
        from googleapiclient.errors import HttpError
        req = self.drive_api.permissions().delete(
            fileId=self.spreadsheet_id,
            permissionId=permission_id
        )
        if batch is not None:
            batch.add(req)
            return None
            
        try:
            req.execute()
            logger.info(f"已移除权限: {permission_id}")
        except HttpError as e:
            if 'cannotDeletePermission' in str(e):
                if recursive and email:
                    logger.info(f"权限继承自父级，开始递归清理...")
                    self.remove_permission_recursively(self.spreadsheet_id, email)
                    try:
                        self.drive_api.permissions().delete(
                            fileId=self.spreadsheet_id, permissionId=permission_id
                        ).execute()
                    except HttpError:
                        pass
                else:
                    logger.warning(f"无法直接删除继承的权限: {permission_id}")
                    raise ValidationError("无法直接删除此权限，因为它是从上级文件夹继承的。请前往 Google Drive 在父级文件夹中进行修改，或勾选「同时从父文件夹中移除该用户的访问权」。")
            else:
                raise

    @retry_on_api_error()
    def update_permission(self, permission_id, role, batch=None):
        """
        更新指定协作者的权限角色。

        Args:
            permission_id: 权限 ID
            role: 新角色（'reader' 或 'writer'）
        """
        req = self.drive_api.permissions().update(
            fileId=self.spreadsheet_id,
            permissionId=permission_id,
            body={"role": role},
            fields="id,role,emailAddress"
        )
        if batch is not None:
            batch.add(req)
            return None
            
        result = req.execute()
        logger.info(f"已更新权限 {permission_id} 为 {role}")
        return result

    @retry_on_api_error()
    def protect_range(self, sheet_id, start_row, end_row,
                      start_col, end_col, editors):
        """保护指定范围，限制可编辑用户"""
        body = {
            "requests": [{
                "addProtectedRange": {
                    "protectedRange": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": start_row,
                            "endRowIndex": end_row,
                            "startColumnIndex": start_col,
                            "endColumnIndex": end_col
                        },
                        "editors": {"users": editors},
                        "warningOnly": False
                    }
                }
            }]
        }
        result = self.sheet_api.batchUpdate(
            spreadsheetId=self.spreadsheet_id, body=body
        ).execute()
        logger.info(f"已保护范围 ({start_row},{start_col})-({end_row},{end_col})")
        return result

    # ========================
    # 导出与备份
    # ========================

    @retry_on_api_error()
    def export_excel(self, output_file):
        """导出为 Excel 文件"""
        request = self.drive_api.files().export_media(
            fileId=self.spreadsheet_id,
            mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        with open(output_file, 'wb') as f:
            f.write(request.execute())
        logger.info(f"已导出 Excel: {output_file}")
        return output_file

    @retry_on_api_error()
    def copy_spreadsheet(self, new_name=None):
        """复制整个 Spreadsheet（用于备份）"""
        if new_name is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_name = f"备份_{timestamp}"
        body = {'name': new_name}
        result = self.drive_api.files().copy(
            fileId=self.spreadsheet_id, body=body
        ).execute()
        logger.info(f"已复制 Spreadsheet: {new_name} (ID: {result.get('id')})")
        return result

    @retry_on_api_error()
    def copy_to_folder(self, folder_id, new_name=None):
        """
        复制 Spreadsheet 到指定的 Google Drive 文件夹中。

        Args:
            folder_id: 目标 Google Drive 文件夹 ID
            new_name: 备份文件名（默认使用 "原名称_备份_时间戳"）
        """
        if new_name is None:
            title = self.get_spreadsheet_title()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_name = f"{title}_备份_{timestamp}"

        body = {
            'name': new_name,
            'parents': [folder_id]
        }
        result = self.drive_api.files().copy(
            fileId=self.spreadsheet_id, body=body
        ).execute()
        logger.info(
            f"已复制 Spreadsheet 到文件夹 {folder_id}: "
            f"{new_name} (ID: {result.get('id')})"
        )
        return result

    @retry_on_api_error()
    def get_spreadsheet_title(self):
        """获取当前 Spreadsheet 的标题"""
        meta = self.get_metadata()
        return meta.get('properties', {}).get('title', '未命名')

    def backup(self, backup_dir=None):
        """
        执行完整备份：复制 Spreadsheet + 导出 Excel 到本地。

        Args:
            backup_dir: 备份目录（默认使用配置中的备份目录）
        """
        from core.config import AppConfig
        if backup_dir is None:
            backup_dir = AppConfig().backup_dir

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 云端备份
        cloud_result = self.copy_spreadsheet(f"备份_{timestamp}")

        # 本地备份
        local_file = os.path.join(backup_dir, f"backup_{timestamp}.xlsx")
        self.export_excel(local_file)

        logger.info(f"完整备份完成: 云端 ID={cloud_result.get('id')}, 本地={local_file}")
        return {
            "cloud_id": cloud_result.get("id"),
            "local_file": local_file,
            "timestamp": timestamp
        }

    @staticmethod
    def batch_backup_to_folder(spreadsheet_ids, folder_id, progress_callback=None):
        """
        批量备份多个 Spreadsheet 到指定的 Google Drive 文件夹。

        Args:
            spreadsheet_ids: Spreadsheet ID 列表
            folder_id: 目标 Drive 文件夹 ID
            progress_callback: 进度回调函数 (current, total, message)

        Returns:
            results: [{"id": ..., "name": ..., "status": "success"/"error", ...}, ...]
        """
        results = []
        total = len(spreadsheet_ids)

        for i, sid in enumerate(spreadsheet_ids):
            sid = sid.strip()
            if not sid:
                continue

            try:
                service = SheetService(sid)
                title = service.get_spreadsheet_title()

                if progress_callback:
                    progress_callback(
                        i, total,
                        f"正在备份 ({i + 1}/{total}): {title}"
                    )

                result = service.copy_to_folder(folder_id)
                results.append({
                    "source_id": sid,
                    "source_title": title,
                    "backup_id": result.get("id"),
                    "backup_name": result.get("name"),
                    "status": "success"
                })
                logger.info(f"批量备份 [{i + 1}/{total}] 成功: {title}")

            except Exception as e:
                results.append({
                    "source_id": sid,
                    "source_title": sid[:20],
                    "backup_id": None,
                    "backup_name": None,
                    "status": "error",
                    "error": str(e)
                })
                logger.error(f"批量备份 [{i + 1}/{total}] 失败: {sid} - {e}")

        if progress_callback:
            success = sum(1 for r in results if r["status"] == "success")
            progress_callback(
                total, total,
                f"批量备份完成: {success}/{total} 成功"
            )

        return results

    # ========================
    # 健康检查
    # ========================

    def health_check(self):
        """
        对当前 Spreadsheet 进行健康检查。

        检查项目：
        1. 公式错误（#REF!, #N/A, #ERROR!, #VALUE!, etc.）
        2. 空工作表
        3. 数据量统计

        Returns:
            dict: 检查报告
        """
        meta = self.get_metadata()
        title = meta.get('properties', {}).get('title', '未知')
        sheets_info = meta.get('sheets', [])

        report = {
            "title": title,
            "spreadsheet_id": self.spreadsheet_id,
            "sheet_count": len(sheets_info),
            "sheets": [],
            "errors_found": 0,
            "empty_sheets": 0,
            "total_rows": 0
        }

        error_patterns = ['#REF!', '#N/A', '#ERROR!', '#VALUE!', '#DIV/0!', '#NULL!', '#NAME?']

        for sheet_meta in sheets_info:
            sheet_name = sheet_meta['properties']['title']
            sheet_id = sheet_meta['properties']['sheetId']
            grid = sheet_meta['properties'].get('gridProperties', {})
            row_count = grid.get('rowCount', 0)
            col_count = grid.get('columnCount', 0)

            sheet_report = {
                "name": sheet_name,
                "sheet_id": sheet_id,
                "grid_rows": row_count,
                "grid_cols": col_count,
                "data_rows": 0,
                "is_empty": True,
                "errors": []
            }

            try:
                data = self.read_data(sheet_name)
                if data:
                    sheet_report["data_rows"] = len(data)
                    sheet_report["is_empty"] = False
                    report["total_rows"] += len(data)

                    # 检查公式错误
                    for r, row in enumerate(data):
                        for c, cell in enumerate(row):
                            cell_str = str(cell).strip()
                            for err in error_patterns:
                                if err in cell_str:
                                    col_letter = chr(ord('A') + c) if c < 26 else f"col{c}"
                                    sheet_report["errors"].append({
                                        "cell": f"{col_letter}{r + 1}",
                                        "error": err,
                                        "value": cell_str[:50]
                                    })
                                    report["errors_found"] += 1
                else:
                    report["empty_sheets"] += 1
            except Exception as e:
                sheet_report["read_error"] = str(e)

            report["sheets"].append(sheet_report)

        # 获取 Drive 文件信息
        try:
            file_info = self.get_file_info()
            report["last_modified"] = file_info.get("modifiedTime", "未知")
            report["owner"] = file_info.get("owners", [{}])[0].get("emailAddress", "未知")
            report["size"] = file_info.get("size", "未知")
        except Exception:
            pass

        logger.info(f"健康检查完成: {title} - {report['errors_found']} 个错误")
        return report

    @retry_on_api_error()
    def get_file_info(self):
        """获取 Drive 文件详情（修改时间、所有者、大小等）"""
        return self.drive_api.files().get(
            fileId=self.spreadsheet_id,
            fields="id,name,modifiedTime,createdTime,owners,size,webViewLink"
        ).execute()

    # ========================
    # 模板批量创建
    # ========================

    @retry_on_api_error()
    def create_from_template(self, new_name, folder_id=None):
        """
        以当前 Spreadsheet 为模板，创建一个新的副本。

        Args:
            new_name: 新表格名称
            folder_id: 可选，目标文件夹 ID
        """
        body = {'name': new_name}
        if folder_id:
            body['parents'] = [folder_id]
        result = self.drive_api.files().copy(
            fileId=self.spreadsheet_id, body=body
        ).execute()
        logger.info(f"从模板创建: {new_name} (ID: {result.get('id')})")
        return result

    @staticmethod
    def batch_create_from_template(template_id, names, folder_id=None,
                                    progress_callback=None):
        """
        批量从模板创建多个表格。

        Args:
            template_id: 模板 Spreadsheet ID
            names: 新表格名称列表
            folder_id: 可选，目标文件夹 ID
            progress_callback: (current, total, message)
        """
        service = SheetService(template_id)
        results = []
        total = len(names)

        for i, name in enumerate(names):
            name = name.strip()
            if not name:
                continue
            try:
                if progress_callback:
                    progress_callback(i, total, f"创建 ({i+1}/{total}): {name}")
                result = service.create_from_template(name, folder_id)
                results.append({
                    "name": name, "id": result.get("id"), "status": "success"
                })
            except Exception as e:
                results.append({
                    "name": name, "id": None, "status": "error", "error": str(e)
                })
                logger.error(f"创建 {name} 失败: {e}")

        if progress_callback:
            s = sum(1 for r in results if r["status"] == "success")
            progress_callback(total, total, f"完成: {s}/{total} 成功")
        return results

    # ========================
    # 占位符替换与授权 (数据驱动模板引擎)
    # ========================

    @retry_on_api_error()
    def find_and_replace_batch(self, replacements: dict):
        """
        在整个工作簿中批量执行查找和替换。
        主要用于模板引擎的占位符替换。
        
        Args:
            replacements: 字典，键为查找文本（如 "{{姓名}}"），值为替换文本（如 "张三"）
        """
        if not replacements:
            return
            
        requests = []
        for search_text, replace_text in replacements.items():
            requests.append({
                "findReplace": {
                    "find": str(search_text),
                    "replacement": str(replace_text),
                    "matchCase": False,
                    "matchEntireCell": False,
                    "searchByRegex": False,
                    "includeHiddenWorksheets": True
                }
            })
            
        body = {"requests": requests}
        self.sheets_api.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body=body
        ).execute()
        logger.info(f"成功在表格 {self.spreadsheet_id} 中执行 {len(replacements)} 项批量替换")

    @retry_on_api_error()
    def share_with_email(self, email: str, role: str = "reader"):
        """
        将当前表格分享给指定邮箱
        
        Args:
            email: 目标邮箱
            role: 权限角色 ("reader", "writer", "commenter")
        """
        if not email or "@" not in email:
            logger.warning(f"无效的邮箱地址: {email}")
            return None
            
        body = {
            "type": "user",
            "role": role,
            "emailAddress": email.strip()
        }
        
        result = self.drive_api.permissions().create(
            fileId=self.spreadsheet_id,
            body=body,
            sendNotificationEmail=False,  # 根据需要可配置为 True 发送通知
            fields="id"
        ).execute()
        
        logger.info(f"已将表格 {self.spreadsheet_id} ({role}) 分享给 {email}")
        return result

    # ========================
    # 格式化
    # ========================

    @retry_on_api_error()
    def set_cell_format(self, sheet_name, start_row, end_row,
                         start_col, end_col, fmt):
        """
        设置单元格格式。

        Args:
            sheet_name: 工作表名
            start_row, end_row: 行范围 (0-based, 半开)
            start_col, end_col: 列范围 (0-based, 半开)
            fmt: 格式字典，如 {"backgroundColor": {...}, "textFormat": {...}}
        """
        sheet_id = self.get_sheet_id_by_name(sheet_name)
        if sheet_id is None:
            raise ValidationError(f"找不到工作表: {sheet_name}")

        requests = [{
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": start_row,
                    "endRowIndex": end_row,
                    "startColumnIndex": start_col,
                    "endColumnIndex": end_col
                },
                "cell": {"userEnteredFormat": fmt},
                "fields": "userEnteredFormat(" + ",".join(fmt.keys()) + ")"
            }
        }]
        self.sheet_api.batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": requests}
        ).execute()
        logger.info(f"已格式化 {sheet_name} ({start_row},{start_col})-({end_row},{end_col})")

    @staticmethod
    def batch_format_range(spreadsheet_ids, sheet_name, start_row, end_row,
                            start_col, end_col, fmt, progress_callback=None):
        """批量格式化多个表格的指定区域"""
        results = []
        total = len(spreadsheet_ids)
        for i, sid in enumerate(spreadsheet_ids):
            sid = sid.strip()
            if not sid:
                continue
            try:
                if progress_callback:
                    progress_callback(i, total, f"({i+1}/{total}) 格式化中...")
                service = SheetService(sid)
                title = service.get_spreadsheet_title()
                service.set_cell_format(sheet_name, start_row, end_row,
                                        start_col, end_col, fmt)
                results.append({"id": sid, "title": title, "status": "success"})
            except Exception as e:
                results.append({"id": sid, "title": sid[:20], "status": "error", "error": str(e)})
        if progress_callback:
            s = sum(1 for r in results if r["status"] == "success")
            progress_callback(total, total, f"完成: {s}/{total}")
        return results

    # ========================
    # 数据验证
    # ========================

    @retry_on_api_error()
    def set_data_validation(self, sheet_name, start_row, end_row,
                             start_col, end_col, rule):
        """
        为指定区域设置数据验证规则。

        Args:
            rule: 验证规则字典，如：
              下拉列表: {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": "A"}, ...]}, "showCustomUi": True}
              数值范围: {"condition": {"type": "NUMBER_BETWEEN", "values": [{"userEnteredValue": "0"}, {"userEnteredValue": "100"}]}}
              日期: {"condition": {"type": "DATE_IS_VALID"}}
        """
        sheet_id = self.get_sheet_id_by_name(sheet_name)
        if sheet_id is None:
            raise ValidationError(f"找不到工作表: {sheet_name}")

        requests = [{
            "setDataValidation": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": start_row,
                    "endRowIndex": end_row,
                    "startColumnIndex": start_col,
                    "endColumnIndex": end_col
                },
                "rule": rule
            }
        }]
        self.sheet_api.batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": requests}
        ).execute()
        logger.info(f"已设置数据验证 {sheet_name}")

    @staticmethod
    def batch_set_validation(spreadsheet_ids, sheet_name, start_row, end_row,
                              start_col, end_col, rule, progress_callback=None):
        """批量为多个表格设置数据验证规则"""
        results = []
        total = len(spreadsheet_ids)
        for i, sid in enumerate(spreadsheet_ids):
            sid = sid.strip()
            if not sid:
                continue
            try:
                if progress_callback:
                    progress_callback(i, total, f"({i+1}/{total}) 设置验证中...")
                service = SheetService(sid)
                title = service.get_spreadsheet_title()
                service.set_data_validation(sheet_name, start_row, end_row,
                                            start_col, end_col, rule)
                results.append({"id": sid, "title": title, "status": "success"})
            except Exception as e:
                results.append({"id": sid, "title": sid[:20], "status": "error", "error": str(e)})
        if progress_callback:
            s = sum(1 for r in results if r["status"] == "success")
            progress_callback(total, total, f"完成: {s}/{total}")
        return results

    # ========================
    # Drive 文件夹浏览
    # ========================

    @staticmethod
    def list_folder_files(folder_id, check_cancelled=None, supported_mime_types=None, batch_callback=None):
        """
        列出 Google Drive 文件夹下的所有文件。

        Args:
            folder_id: Google Drive 文件夹 ID

        Returns:
            list[dict]: 文件列表，每项包含:
                - id: 文件 ID
                - name: 文件名
                - mimeType: MIME 类型
                - webViewLink: 在线查看链接
                - modifiedTime: 最后修改时间
                - size: 文件大小（字节，文件夹和 Google 文档类型无此字段）
                - permissions: 权限列表
        """
        from core.auth import AuthManager
        auth = AuthManager()
        drive = auth.drive_api

        files = []
        page_token = None

        while True:
            if check_cancelled and check_cancelled():
                break

            q_val = f"'{folder_id}' in parents and trashed = false"
            if supported_mime_types:
                conds = []
                for m in supported_mime_types:
                    if m.endswith('/'):
                        conds.append(f"mimeType contains '{m}'")
                    else:
                        conds.append(f"mimeType='{m}'")
                mime_cond = " or ".join(conds)
                q_val += f" and ({mime_cond})"
            resp = drive.files().list(
                q=q_val,
                fields="nextPageToken, files(id, name, mimeType, webViewLink, "
                       "modifiedTime, size, ownedByMe, permissions(id, emailAddress, role, "
                       "displayName, type, pendingOwner))",
                pageSize=1000,
                pageToken=page_token,
                orderBy="name",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()

            batch = resp.get("files", [])
            files.extend(batch)
            if batch_callback and batch:
                batch_callback(batch)
                
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        logger.info(f"获取文件夹 {folder_id} 下 {len(files)} 个文件")
        return files

    @staticmethod
    def list_all_files_in_folder_recursive(folder_id):
        """
        递归获取 Google Drive 文件夹及其所有子文件夹下的所有文件 ID。

        Args:
            folder_id: 根文件夹 ID

        Returns:
            list[str]: 所有文件的 ID 列表（包含子文件夹本身及其内部的文件）
        """
        from core.auth import AuthManager
        auth = AuthManager()
        drive = auth.drive_api

        all_file_ids = []
        folders_to_process = [folder_id]

        while folders_to_process:
            current_folder_id = folders_to_process.pop(0)
            page_token = None

            while True:
                try:
                    resp = drive.files().list(
                        q=f"'{current_folder_id}' in parents and trashed = false",
                        fields="nextPageToken, files(id, mimeType)",
                        pageSize=1000,
                        pageToken=page_token,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True
                    ).execute()

                    for file in resp.get("files", []):
                        file_id = file.get("id")
                        mime_type = file.get("mimeType")
                        all_file_ids.append(file_id)

                        if mime_type == "application/vnd.google-apps.folder":
                            folders_to_process.append(file_id)

                    page_token = resp.get("nextPageToken")
                    if not page_token:
                        break
                except Exception as e:
                    logger.error(f"递归获取文件夹 {current_folder_id} 失败: {e}")
                    break

        return list(set(all_file_ids))

    @staticmethod
    def list_all_files_with_path(folder_id, progress_callback=None, include_shared=True, check_cancelled=None, supported_mime_types=None, batch_callback=None):
        """
        递归获取文件夹下的所有 Google Drive 文件，并包含相对路径。
        若 folder_id 为 "root"，则进行全局检索（包含 Shared with me, Shared Drives）。
        """
        from core.auth import AuthManager
        auth = AuthManager()
        drive = auth.drive_api

        if folder_id == "root":
            all_spreadsheets = []
            if progress_callback:
                progress_callback("⏳ 正在进行全局检索 (包含共享及子文件夹)...")

            folder_map = {}
            f_token = None
            q_folder = "mimeType='application/vnd.google-apps.folder' and trashed=false"
            if not include_shared:
                q_folder += " and 'me' in owners"
                
            while True:
                if check_cancelled and check_cancelled():
                    break
                try:
                    f_resp = drive.files().list(
                        q=q_folder,
                        fields="nextPageToken, files(id, name, parents)",
                        pageSize=1000,
                        pageToken=f_token,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True
                    ).execute()
                    for f in f_resp.get("files", []):
                        folder_map[f.get("id")] = f
                    f_token = f_resp.get("nextPageToken")
                    if not f_token: break
                except Exception as e:
                    logger.error(f"全局获取文件夹失败: {e}")
                    break

            def build_path(file_parents):
                if not file_parents: return "/"
                pid = file_parents[0]
                path_parts = []
                visited = set()
                while pid and pid not in visited:
                    visited.add(pid)
                    if pid in folder_map:
                        f_info = folder_map[pid]
                        path_parts.insert(0, f_info.get("name", ""))
                        parents = f_info.get("parents")
                        if parents: pid = parents[0]
                        else: break
                    else: break
                if not path_parts: return "/"
                return "/" + "/".join(path_parts) + "/"

            page_token = None
            processed_count = 0
            q_file = "trashed=false"
            if supported_mime_types:
                conds = []
                for m in supported_mime_types:
                    if m.endswith('/'):
                        conds.append(f"mimeType contains '{m}'")
                    else:
                        conds.append(f"mimeType='{m}'")
                mime_cond = " or ".join(conds)
                q_file += f" and ({mime_cond})"
            else:
                q_file += " and mimeType!='application/vnd.google-apps.folder'"
                
            if not include_shared:
                q_file += " and 'me' in owners"
                
            while True:
                if check_cancelled and check_cancelled():
                    break
                try:
                    resp = drive.files().list(
                        q=q_file,
                        fields="nextPageToken, files(id, name, mimeType, webViewLink, modifiedTime, size, ownedByMe, parents, permissions(id, emailAddress, role, displayName, type, pendingOwner))",
                        pageSize=1000,
                        pageToken=page_token,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True
                    ).execute()

                    batch_files = []
                    for file in resp.get("files", []):
                        file["path"] = build_path(file.get("parents", []))
                        all_spreadsheets.append(file)
                        batch_files.append(file)
                        processed_count += 1
                        
                    if batch_callback and batch_files:
                        batch_callback(batch_files)

                    if progress_callback and processed_count % 100 == 0:
                        progress_callback(f"已获取 {processed_count} 个文件...")

                    page_token = resp.get("nextPageToken")
                    if not page_token:
                        break
                except Exception as e:
                    logger.error(f"全局获取文件失败: {e}")
                    break
            
            logger.info(f"获取文件夹 {folder_id} 下 {len(all_spreadsheets)} 个文件")
            return all_spreadsheets
        else:
            all_spreadsheets = []
            folders_to_process = [(folder_id, "/")]
            processed_count = 0

            while folders_to_process:
                if check_cancelled and check_cancelled():
                    break
                current_folder_id, current_path = folders_to_process.pop(0)
                page_token = None

                while True:
                    if check_cancelled and check_cancelled():
                        break
                    try:
                        resp = drive.files().list(
                            q=f"'{current_folder_id}' in parents and trashed = false",
                            fields="nextPageToken, files(id, name, mimeType, webViewLink, modifiedTime, size, ownedByMe, permissions(id, emailAddress, role, displayName, type, pendingOwner))",
                            pageSize=1000,
                            pageToken=page_token,
                            supportsAllDrives=True,
                            includeItemsFromAllDrives=True
                        ).execute()

                        batch_files = []
                        for file in resp.get("files", []):
                            mime_type = file.get("mimeType")
                            file_name = file.get("name", "")
                            
                            if mime_type == "application/vnd.google-apps.folder":
                                folders_to_process.append((file.get("id"), f"{current_path}{file_name}/"))
                            else:
                                is_match = False
                                if not supported_mime_types:
                                    is_match = True
                                else:
                                    for m in supported_mime_types:
                                        if m.endswith('/') and mime_type and mime_type.startswith(m):
                                            is_match = True
                                            break
                                        elif mime_type == m:
                                            is_match = True
                                            break
                                            
                                if is_match:
                                    file["path"] = current_path
                                    all_spreadsheets.append(file)
                                    batch_files.append(file)
                                    processed_count += 1
                                    if progress_callback:
                                        progress_callback(f"已找到 {processed_count} 个文件: {current_path}{file_name}")

                        if batch_callback and batch_files:
                            batch_callback(batch_files)

                        page_token = resp.get("nextPageToken")
                        if not page_token:
                            break
                    except Exception as e:
                        logger.error(f"递归获取文件夹 {current_folder_id} 失败: {e}")
                        break

            logger.info(f"获取文件夹 {folder_id} 下 {len(all_spreadsheets)} 个文件")
            return all_spreadsheets

    # ========================
    # 工作簿删除（移到垃圾桶 / 彻底删除）
    # ========================

    @retry_on_api_error()
    def trash_spreadsheet(self):
        """将当前工作簿移到垃圾桶"""
        result = self.drive_api.files().update(
            fileId=self.spreadsheet_id,
            body={"trashed": True}
        ).execute()
        logger.info(f"已将工作簿移到垃圾桶: {self.spreadsheet_id}")
        return result

    @retry_on_api_error()
    def permanently_delete_spreadsheet(self):
        """彻底永久删除当前工作簿（不可恢复）"""
        self.drive_api.files().delete(
            fileId=self.spreadsheet_id
        ).execute()
        logger.info(f"已彻底删除工作簿: {self.spreadsheet_id}")

    @staticmethod
    def batch_trash_spreadsheets(spreadsheet_ids, progress_callback=None):
        """
        批量将多个 Spreadsheet 移到垃圾桶。

        Args:
            spreadsheet_ids: Spreadsheet ID 列表
            progress_callback: 进度回调 (current, total, message)

        Returns:
            results 列表
        """
        results = []
        total = len(spreadsheet_ids)

        for i, sid in enumerate(spreadsheet_ids):
            sid = sid.strip()
            if not sid:
                continue
            try:
                service = SheetService(sid)
                title = service.get_spreadsheet_title()

                if progress_callback:
                    progress_callback(
                        i, total,
                        f"正在移到垃圾桶 ({i + 1}/{total}): {title}"
                    )

                service.trash_spreadsheet()
                results.append({
                    "id": sid, "title": title, "status": "success",
                    "detail": "已移到垃圾桶"
                })
                logger.info(f"批量移到垃圾桶 [{i + 1}/{total}] 成功: {title}")

            except Exception as e:
                results.append({
                    "id": sid, "title": sid[:20] + "...",
                    "status": "error", "detail": str(e)
                })
                logger.error(f"批量移到垃圾桶 [{i + 1}/{total}] 失败: {sid} - {e}")

        if progress_callback:
            success = sum(1 for r in results if r["status"] == "success")
            progress_callback(total, total, f"完成: {success}/{total} 成功")

        return results

    @staticmethod
    def batch_permanently_delete_spreadsheets(spreadsheet_ids, progress_callback=None):
        """
        批量彻底永久删除多个 Spreadsheet（不可恢复）。

        Args:
            spreadsheet_ids: Spreadsheet ID 列表
            progress_callback: 进度回调 (current, total, message)

        Returns:
            results 列表
        """
        results = []
        total = len(spreadsheet_ids)

        for i, sid in enumerate(spreadsheet_ids):
            sid = sid.strip()
            if not sid:
                continue
            try:
                service = SheetService(sid)
                title = service.get_spreadsheet_title()

                if progress_callback:
                    progress_callback(
                        i, total,
                        f"正在彻底删除 ({i + 1}/{total}): {title}"
                    )

                service.permanently_delete_spreadsheet()
                results.append({
                    "id": sid, "title": title, "status": "success",
                    "detail": "已彻底删除"
                })
                logger.info(f"批量彻底删除 [{i + 1}/{total}] 成功: {title}")

            except Exception as e:
                results.append({
                    "id": sid, "title": sid[:20] + "...",
                    "status": "error", "detail": str(e)
                })
                logger.error(f"批量彻底删除 [{i + 1}/{total}] 失败: {sid} - {e}")

        if progress_callback:
            success = sum(1 for r in results if r["status"] == "success")
            progress_callback(total, total, f"完成: {success}/{total} 成功")

        return results

    # ========================
    # 子工作表删除
    # ========================

    def delete_sheets_by_names(self, sheet_names):
        """
        按名称批量删除同一个 Spreadsheet 中的多个子工作表。

        会自动确保至少保留一个工作表（Google API 要求）。

        Args:
            sheet_names: 要删除的子工作表名称列表

        Returns:
            dict: {"deleted": [...], "skipped": [...], "not_found": [...]}
        """
        meta = self.get_metadata()
        all_sheets = meta.get("sheets", [])
        total_count = len(all_sheets)

        # 构建名称 -> sheetId 的映射
        name_to_id = {}
        for s in all_sheets:
            name = s["properties"]["title"]
            sid = s["properties"]["sheetId"]
            name_to_id[name] = sid

        deleted = []
        skipped = []
        not_found = []
        delete_count = 0

        for name in sheet_names:
            name = name.strip()
            if not name:
                continue

            if name not in name_to_id:
                not_found.append(name)
                continue

            # 确保至少保留一个工作表
            if total_count - delete_count <= 1:
                skipped.append(name)
                logger.warning(
                    f"跳过删除 '{name}': 至少需要保留一个工作表"
                )
                continue

            try:
                self.delete_sheet(name_to_id[name])
                deleted.append(name)
                delete_count += 1
            except Exception as e:
                skipped.append(name)
                logger.error(f"删除子工作表 '{name}' 失败: {e}")

        logger.info(
            f"子工作表删除完成: 删除 {len(deleted)}, "
            f"跳过 {len(skipped)}, 未找到 {len(not_found)}"
        )
        return {
            "deleted": deleted,
            "skipped": skipped,
            "not_found": not_found
        }

    @staticmethod
    def batch_delete_sheets(delete_map, progress_callback=None):
        """
        跨多个 Spreadsheet 批量删除指定的子工作表。

        Args:
            delete_map: dict，格式为 {spreadsheet_id: [sheet_name_1, sheet_name_2, ...]}
            progress_callback: 进度回调 (current, total, message)

        Returns:
            results 列表
        """
        results = []
        items = list(delete_map.items())
        total = len(items)

        for i, (sid, sheet_names) in enumerate(items):
            sid = sid.strip()
            if not sid or not sheet_names:
                continue

            try:
                service = SheetService(sid)
                title = service.get_spreadsheet_title()

                if progress_callback:
                    progress_callback(
                        i, total,
                        f"正在处理 ({i + 1}/{total}): {title}"
                    )

                result = service.delete_sheets_by_names(sheet_names)
                results.append({
                    "id": sid,
                    "title": title,
                    "status": "success",
                    "deleted": result["deleted"],
                    "skipped": result["skipped"],
                    "not_found": result["not_found"],
                    "detail": (
                        f"删除 {len(result['deleted'])} 个, "
                        f"跳过 {len(result['skipped'])} 个, "
                        f"未找到 {len(result['not_found'])} 个"
                    )
                })
                logger.info(f"批量删除子工作表 [{i + 1}/{total}] 成功: {title}")

            except Exception as e:
                results.append({
                    "id": sid, "title": sid[:20] + "...",
                    "status": "error", "deleted": [], "skipped": [],
                    "not_found": [], "detail": str(e)
                })
                logger.error(
                    f"批量删除子工作表 [{i + 1}/{total}] 失败: {sid} - {e}"
                )

        if progress_callback:
            success = sum(1 for r in results if r["status"] == "success")
            progress_callback(total, total, f"完成: {success}/{total} 成功")

        return results

    # ========================
    # 文件状态检测
    # ========================

    @staticmethod
    def batch_check_spreadsheet_status(spreadsheet_ids, progress_callback=None):
        """
        批量检测多个 Spreadsheet 的文件状态。

        检测结果包含三种状态：
        - "active": 文件正常存在
        - "trashed": 文件在垃圾桶中
        - "deleted": 文件已被彻底删除或无权访问

        Args:
            spreadsheet_ids: Spreadsheet ID 列表
            progress_callback: 进度回调 (current, total, message)

        Returns:
            results 列表，每项包含 id, title, status, detail
        """
        from core.auth import AuthManager
        auth = AuthManager()
        drive = auth.drive_api

        results = []
        total = len(spreadsheet_ids)

        for i, sid in enumerate(spreadsheet_ids):
            sid = sid.strip()
            if not sid:
                continue

            if progress_callback:
                progress_callback(
                    i, total,
                    f"正在检测 ({i + 1}/{total}): {sid[:20]}..."
                )

            try:
                # 使用 supportsAllDrives 以支持共享云端硬盘
                # 请求 trashed 字段来判断是否在垃圾桶中
                file_info = drive.files().get(
                    fileId=sid,
                    fields="id,name,trashed,mimeType",
                    supportsAllDrives=True
                ).execute()

                name = file_info.get("name", "未知")
                trashed = file_info.get("trashed", False)

                if trashed:
                    results.append({
                        "id": sid,
                        "title": name,
                        "file_status": "trashed",
                        "detail": "在垃圾桶中（可恢复）"
                    })
                else:
                    results.append({
                        "id": sid,
                        "title": name,
                        "file_status": "active",
                        "detail": "正常（未删除）"
                    })

                logger.info(
                    f"状态检测 [{i + 1}/{total}]: {name} -> "
                    f"{'垃圾桶' if trashed else '正常'}"
                )

            except Exception as e:
                error_str = str(e)
                # Google API 返回 404 表示文件不存在（已被彻底删除）
                # 返回 403 表示无权限访问
                if "404" in error_str or "not found" in error_str.lower():
                    results.append({
                        "id": sid,
                        "title": "—",
                        "file_status": "deleted",
                        "detail": "已彻底删除（不可恢复）"
                    })
                elif "403" in error_str or "forbidden" in error_str.lower():
                    results.append({
                        "id": sid,
                        "title": "—",
                        "file_status": "no_access",
                        "detail": "无权限访问"
                    })
                else:
                    results.append({
                        "id": sid,
                        "title": "—",
                        "file_status": "error",
                        "detail": f"检测失败: {error_str[:50]}"
                    })
                logger.warning(f"状态检测 [{i + 1}/{total}] 异常: {sid} - {e}")

        if progress_callback:
            active = sum(1 for r in results if r["file_status"] == "active")
            trashed = sum(1 for r in results if r["file_status"] == "trashed")
            deleted = sum(1 for r in results if r["file_status"] == "deleted")
            progress_callback(
                total, total,
                f"检测完成: {active} 正常, {trashed} 垃圾桶, {deleted} 已删除"
            )

        return results

    # ========================
    # 恢复与导出（配合右键菜单）
    # ========================

    @retry_on_api_error()
    def restore_spreadsheet(self):
        """将当前工作簿从垃圾桶恢复"""
        result = self.drive_api.files().update(
            fileId=self.spreadsheet_id,
            body={"trashed": False}
        ).execute()
        logger.info(f"已将工作簿从垃圾桶恢复: {self.spreadsheet_id}")
        return result

    @staticmethod
    def batch_restore_spreadsheets(spreadsheet_ids, progress_callback=None):
        """
        批量将多个 Spreadsheet 从垃圾桶恢复。
        """
        results = []
        total = len(spreadsheet_ids)

        for i, sid in enumerate(spreadsheet_ids):
            sid = sid.strip()
            if not sid:
                continue
            try:
                service = SheetService(sid)
                # 即便在垃圾桶，一般也可以获取 title
                title = service.get_spreadsheet_title()

                if progress_callback:
                    progress_callback(
                        i, total,
                        f"正在恢复 ({i + 1}/{total}): {title}"
                    )

                service.restore_spreadsheet()
                results.append({
                    "id": sid, "title": title, "status": "success",
                    "detail": "已恢复"
                })
                logger.info(f"批量恢复 [{i + 1}/{total}] 成功: {title}")

            except Exception as e:
                results.append({
                    "id": sid, "title": sid[:20] + "...",
                    "status": "error", "detail": str(e)
                })
                logger.error(f"批量恢复 [{i + 1}/{total}] 失败: {sid} - {e}")

        if progress_callback:
            success = sum(1 for r in results if r["status"] == "success")
            progress_callback(total, total, f"完成: {success}/{total} 成功")

        return results

    @staticmethod
    def batch_export_spreadsheets(spreadsheet_ids, save_dir, progress_callback=None):
        """
        批量导出多个 Spreadsheet 为 Excel 文件，保存到指定目录。
        """
        import os
        from core.auth import AuthManager
        auth = AuthManager()
        drive = auth.drive_api

        results = []
        total = len(spreadsheet_ids)
        mime_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

        for i, sid in enumerate(spreadsheet_ids):
            sid = sid.strip()
            if not sid:
                continue

            try:
                # 获取文件名以决定保存路径
                file_info = drive.files().get(
                    fileId=sid, fields="name", supportsAllDrives=True
                ).execute()
                title = file_info.get("name", f"spreadsheet_{sid[:8]}")

                if progress_callback:
                    progress_callback(
                        i, total,
                        f"正在导出 ({i + 1}/{total}): {title}"
                    )

                # 下载
                request = drive.files().export_media(fileId=sid, mimeType=mime_type)
                file_content = request.execute()
                
                # 清理文件名中的非法字符
                safe_title = "".join([c for c in title if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).rstrip()
                save_path = os.path.join(save_dir, f"{safe_title}.xlsx")
                
                # 防止同名文件覆盖
                counter = 1
                while os.path.exists(save_path):
                    save_path = os.path.join(save_dir, f"{safe_title} ({counter}).xlsx")
                    counter += 1

                with open(save_path, "wb") as f:
                    f.write(file_content)

                results.append({
                    "id": sid, "title": title, "status": "success",
                    "detail": f"已导出至 {os.path.basename(save_path)}"
                })
                logger.info(f"批量导出 [{i + 1}/{total}] 成功: {save_path}")

            except Exception as e:
                results.append({
                    "id": sid, "title": sid[:20] + "...",
                    "status": "error", "detail": str(e)
                })
                logger.error(f"批量导出 [{i + 1}/{total}] 失败: {sid} - {e}")

        if progress_callback:
            success = sum(1 for r in results if r["status"] == "success")
            progress_callback(total, total, f"完成: {success}/{total} 成功")

        return results
