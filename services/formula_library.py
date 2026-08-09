# 公式库管理器 — 用 JSON 持久化存储用户自定义的函数公式集
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("sheets_toolkit.services.formula_library")

# 默认存储路径：项目根目录下的 formula_library.json
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LIB_PATH = os.path.join(BASE_DIR, "formula_library.json")


class FormulaLibrary:
    """
    公式库 — 管理用户自定义的函数公式集合。
    每条公式包含：名称、公式内容、描述、默认工作表、默认单元格、分类标签。
    支持增删改查和 JSON 持久化。
    """

    def __init__(self, path=None):
        self.path = path or DEFAULT_LIB_PATH
        self._formulas = []
        self.load()

    def load(self):
        """从 JSON 文件加载公式库"""
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._formulas = data.get("formulas", [])
                logger.info(f"已加载 {len(self._formulas)} 条公式")
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"公式库加载失败: {e}")
                self._formulas = []
        else:
            self._formulas = []
            self._save_with_defaults()

    def _save_with_defaults(self):
        """创建带示例的默认公式库"""
        self._formulas = [
            {
                "id": "1",
                "name": "区域求和",
                "formula": "=SUM(B2:B100)",
                "description": "对 B 列（B2 到 B100）求和",
                "sheet_name": "Sheet1",
                "cell": "B1",
                "category": "数学",
                "created": datetime.now().isoformat()
            },
            {
                "id": "2",
                "name": "VLOOKUP 查找",
                "formula": "=VLOOKUP(A2,Sheet2!A:B,2,0)",
                "description": "从 Sheet2 的 A:B 区域查找 A2 对应的值",
                "sheet_name": "Sheet1",
                "cell": "C2",
                "category": "查找",
                "created": datetime.now().isoformat()
            },
            {
                "id": "3",
                "name": "条件计数",
                "formula": '=COUNTIF(C2:C100,"完成")',
                "description": "统计 C 列中值为 '完成' 的单元格数量",
                "sheet_name": "Sheet1",
                "cell": "D1",
                "category": "统计",
                "created": datetime.now().isoformat()
            }
        ]
        self.save()

    def save(self):
        """保存公式库到 JSON 文件"""
        try:
            data = {
                "version": "1.0",
                "updated": datetime.now().isoformat(),
                "formulas": self._formulas
            }
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"公式库已保存: {len(self._formulas)} 条")
        except IOError as e:
            logger.error(f"公式库保存失败: {e}")

    @property
    def formulas(self):
        return self._formulas

    def get_by_id(self, formula_id):
        """根据 ID 获取公式"""
        for f in self._formulas:
            if f["id"] == formula_id:
                return f
        return None

    def add(self, name, formula, description="", sheet_name="Sheet1",
            cell="A1", category="通用"):
        """添加新公式"""
        new_id = str(max([int(f.get("id", 0)) for f in self._formulas], default=0) + 1)
        entry = {
            "id": new_id,
            "name": name,
            "formula": formula,
            "description": description,
            "sheet_name": sheet_name,
            "cell": cell,
            "category": category,
            "created": datetime.now().isoformat()
        }
        self._formulas.append(entry)
        self.save()
        logger.info(f"已添加公式: {name}")
        return entry

    def update(self, formula_id, **kwargs):
        """更新公式的指定字段"""
        entry = self.get_by_id(formula_id)
        if entry:
            for key, value in kwargs.items():
                if key in entry and key != "id":
                    entry[key] = value
            entry["updated"] = datetime.now().isoformat()
            self.save()
            logger.info(f"已更新公式: {entry.get('name')}")
            return entry
        return None

    def delete(self, formula_id):
        """删除公式"""
        self._formulas = [f for f in self._formulas if f["id"] != formula_id]
        self.save()
        logger.info(f"已删除公式 ID={formula_id}")

    def get_categories(self):
        """获取所有分类标签"""
        cats = set()
        for f in self._formulas:
            cats.add(f.get("category", "通用"))
        return sorted(cats)

    def search(self, keyword):
        """按关键词搜索公式"""
        keyword = keyword.lower()
        return [
            f for f in self._formulas
            if keyword in f.get("name", "").lower()
            or keyword in f.get("formula", "").lower()
            or keyword in f.get("description", "").lower()
            or keyword in f.get("category", "").lower()
        ]
