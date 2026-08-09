# 配色库管理器 — JSON 持久化存储用户自定义的配色方案
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("sheets_toolkit.services.color_scheme")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(BASE_DIR, "color_schemes.json")


class ColorSchemeLibrary:
    """
    配色库 — 管理用户自定义的配色方案。
    每个方案包含：名称、背景色、字体颜色、是否粗体、分类。
    """

    def __init__(self, path=None):
        self.path = path or DEFAULT_PATH
        self._schemes = []
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._schemes = data.get("schemes", [])
            except (json.JSONDecodeError, IOError):
                self._schemes = []
                self._save_defaults()
        else:
            self._save_defaults()

    def _save_defaults(self):
        """创建默认配色方案"""
        self._schemes = [
            {
                "id": "1", "name": "表头蓝",
                "bg": {"red": 0.25, "green": 0.52, "blue": 0.96},
                "fg": {"red": 1.0, "green": 1.0, "blue": 1.0},
                "bold": True, "category": "表头",
                "description": "蓝底白字粗体，适合表头行"
            },
            {
                "id": "2", "name": "成功绿",
                "bg": {"red": 0.85, "green": 0.95, "blue": 0.85},
                "fg": {"red": 0.1, "green": 0.5, "blue": 0.1},
                "bold": False, "category": "状态",
                "description": "浅绿底深绿字，标记已完成或成功"
            },
            {
                "id": "3", "name": "警告黄",
                "bg": {"red": 1.0, "green": 0.95, "blue": 0.8},
                "fg": {"red": 0.7, "green": 0.5, "blue": 0.0},
                "bold": False, "category": "状态",
                "description": "浅黄底棕色字，标记需注意项"
            },
            {
                "id": "4", "name": "错误红",
                "bg": {"red": 1.0, "green": 0.85, "blue": 0.85},
                "fg": {"red": 0.8, "green": 0.1, "blue": 0.1},
                "bold": True, "category": "状态",
                "description": "浅红底红字粗体，标记错误或紧急"
            },
            {
                "id": "5", "name": "中性灰",
                "bg": {"red": 0.94, "green": 0.94, "blue": 0.94},
                "fg": {"red": 0.3, "green": 0.3, "blue": 0.3},
                "bold": False, "category": "通用",
                "description": "浅灰底深灰字，用于辅助信息"
            },
            {
                "id": "6", "name": "高亮紫",
                "bg": {"red": 0.91, "green": 0.87, "blue": 1.0},
                "fg": {"red": 0.4, "green": 0.2, "blue": 0.7},
                "bold": False, "category": "高亮",
                "description": "浅紫底紫字，用于重点标注"
            }
        ]
        self.save()

    def save(self):
        try:
            data = {
                "version": "1.0",
                "updated": datetime.now().isoformat(),
                "schemes": self._schemes
            }
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error(f"配色库保存失败: {e}")

    @property
    def schemes(self):
        return self._schemes

    def get_by_id(self, sid):
        for s in self._schemes:
            if s["id"] == sid:
                return s
        return None

    def add(self, name, bg, fg, bold=False, category="通用", description=""):
        new_id = str(max([int(s.get("id", 0)) for s in self._schemes], default=0) + 1)
        entry = {
            "id": new_id, "name": name,
            "bg": bg, "fg": fg, "bold": bold,
            "category": category, "description": description,
            "created": datetime.now().isoformat()
        }
        self._schemes.append(entry)
        self.save()
        return entry

    def update(self, sid, **kwargs):
        entry = self.get_by_id(sid)
        if entry:
            for k, v in kwargs.items():
                if k in entry and k != "id":
                    entry[k] = v
            self.save()
            return entry
        return None

    def delete(self, sid):
        self._schemes = [s for s in self._schemes if s["id"] != sid]
        self.save()

    def get_categories(self):
        return sorted(set(s.get("category", "通用") for s in self._schemes))

    def to_sheets_format(self, scheme):
        """将配色方案转换为 Google Sheets API 格式字典"""
        fmt = {}
        if scheme.get("bg"):
            fmt["backgroundColor"] = scheme["bg"]
        text = {}
        if scheme.get("fg"):
            text["foregroundColor"] = scheme["fg"]
        if scheme.get("bold"):
            text["bold"] = True
        if text:
            fmt["textFormat"] = text
        return fmt
