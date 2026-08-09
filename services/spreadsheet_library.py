# 表格库管理器 — 使用 Fernet 加密的持久化表格信息存储
# 支持分组管理、模糊搜索、正则搜索
import os
import re
import json
import uuid
import logging
from datetime import datetime
from cryptography.fernet import Fernet

logger = logging.getLogger("sheets_toolkit.services.spreadsheet_library")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA_PATH = os.path.join(BASE_DIR, "spreadsheet_library.enc")
DEFAULT_KEY_PATH = os.path.join(BASE_DIR, ".sheet_lib_key")


class SpreadsheetLibrary:
    """
    加密表格库 — 管理用户保存的表格信息。

    数据结构：
    {
        "groups": {
            "group_id": {"name": "分组名", "created": "..."}
        },
        "entries": [
            {
                "id": "uuid",
                "group_id": "group_id",
                "name": "表格名称",
                "link": "https://docs.google.com/...",
                "spreadsheet_id": "自动提取的 ID",
                "notes": "备注",
                "is_starred": False,
                "tags": ["标签1", "标签2"],
                "created": "...",
                "updated": "..."
            }
        ]
    }
    """

    def __init__(self, data_path=None, key_path=None):
        self._data_path = data_path or DEFAULT_DATA_PATH
        self._key_path = key_path or DEFAULT_KEY_PATH
        self._fernet = self._init_encryption()
        self._data = {"groups": {}, "entries": []}
        self.load()

    def _init_encryption(self):
        """初始化加密器：加载或生成密钥"""
        if os.path.exists(self._key_path):
            with open(self._key_path, 'rb') as f:
                key = f.read()
        else:
            key = Fernet.generate_key()
            with open(self._key_path, 'wb') as f:
                f.write(key)
            logger.info("已生成新的加密密钥")
        return Fernet(key)

    def load(self):
        """从加密文件加载数据"""
        if not os.path.exists(self._data_path):
            self._data = {"groups": {}, "entries": []}
            self._init_default_groups()
            self.save()
            return

        try:
            with open(self._data_path, 'rb') as f:
                encrypted = f.read()
            decrypted = self._fernet.decrypt(encrypted)
            self._data = json.loads(decrypted.decode('utf-8'))
            count = len(self._data.get("entries", []))
            logger.info(f"已加载表格库: {count} 条记录")
        except Exception as e:
            logger.error(f"表格库加载失败: {e}")
            self._data = {"groups": {}, "entries": []}
            self._init_default_groups()

        # 向后兼容：为旧条目填充缺少的新字段
        self._migrate_entries()

    def _init_default_groups(self):
        """创建默认分组"""
        self._data["groups"] = {
            "default": {"name": "默认", "created": datetime.now().isoformat()},
            "important": {"name": "重要", "created": datetime.now().isoformat()},
            "archive": {"name": "归档", "created": datetime.now().isoformat()}
        }

    def save(self):
        """加密并保存数据"""
        try:
            raw = json.dumps(self._data, ensure_ascii=False, indent=2)
            encrypted = self._fernet.encrypt(raw.encode('utf-8'))
            with open(self._data_path, 'wb') as f:
                f.write(encrypted)
            logger.info(f"表格库已保存 ({len(self._data.get('entries', []))} 条)")
        except Exception as e:
            logger.error(f"表格库保存失败: {e}")

    # ========================
    # 分组管理
    # ========================

    @property
    def groups(self):
        return self._data.get("groups", {})

    def get_group_names(self):
        """获取所有分组名称列表"""
        return [g["name"] for g in self.groups.values()]

    def get_group_id_by_name(self, name):
        """根据名称获取分组 ID"""
        for gid, g in self.groups.items():
            if g["name"] == name:
                return gid
        return None

    def add_group(self, name):
        """添加新分组"""
        gid = str(uuid.uuid4())[:8]
        self._data["groups"][gid] = {
            "name": name,
            "created": datetime.now().isoformat()
        }
        self.save()
        return gid

    def rename_group(self, group_id, new_name):
        """重命名分组"""
        if group_id in self._data["groups"]:
            self._data["groups"][group_id]["name"] = new_name
            self.save()

    def delete_group(self, group_id):
        """删除分组（将其中的条目移到 default 组）"""
        if group_id in self._data["groups"] and group_id != "default":
            # 将关联条目的分组改为 default
            for entry in self._data["entries"]:
                if entry.get("group_id") == group_id:
                    entry["group_id"] = "default"
            del self._data["groups"][group_id]
            self.save()

    def move_group(self, group_id, new_full_name):
        """
        移动分组到新位置（修改分组的完整路径名）。

        会级联更新所有以旧路径为前缀的子分组。
        例如: 将 "A->B" 移动到 "C->B"，则 "A->B->X" 也会变为 "C->B->X"。

        Args:
            group_id: 要移动的分组 ID
            new_full_name: 新的完整路径名（如 "父分组->子分组"）
        """
        if group_id not in self._data["groups"]:
            return
        if group_id == "default":
            return

        old_full_name = self._data["groups"][group_id]["name"]
        if old_full_name == new_full_name:
            return

        # 更新自身
        self._data["groups"][group_id]["name"] = new_full_name

        # 级联更新所有子分组（名称以 "旧路径->" 开头的分组）
        old_prefix = old_full_name + "->"
        new_prefix = new_full_name + "->"
        for gid, g in self._data["groups"].items():
            if gid != group_id and g["name"].startswith(old_prefix):
                g["name"] = new_prefix + g["name"][len(old_prefix):]

        self.save()
        logger.info(f"分组移动: {old_full_name} -> {new_full_name}")

    # ========================
    # 条目管理
    # ========================

    @property
    def entries(self):
        return self._data.get("entries", [])

    def _extract_id(self, link):
        """从链接中提取 Spreadsheet ID"""
        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', link)
        if match:
            return match.group(1)
        link = link.strip()
        if re.match(r'^[a-zA-Z0-9-_]{10,}$', link):
            return link
        return ""

    def add_entry(self, name, link, group_name="默认", notes="", is_starred=False, tags=None):
        """
        添加表格条目。

        Args:
            name: 表格名称
            link: 表格链接或 ID
            group_name: 分组名称
            notes: 备注
            is_starred: 是否星标
            tags: 标签列表
        """
        group_id = self.get_group_id_by_name(group_name)
        if not group_id:
            group_id = self.add_group(group_name)

        entry = {
            "id": str(uuid.uuid4())[:8],
            "group_id": group_id,
            "name": name,
            "link": link,
            "spreadsheet_id": self._extract_id(link),
            "notes": notes,
            "is_starred": is_starred,
            "tags": tags or [],
            "health_status": "unknown",
            "health_detail": "",
            "health_checked_at": "",
            "created": datetime.now().isoformat(),
            "updated": datetime.now().isoformat()
        }
        self._data["entries"].append(entry)
        self.save()
        return entry

    def update_entry(self, entry_id, **kwargs):
        """更新条目"""
        for entry in self._data["entries"]:
            if entry["id"] == entry_id:
                for k, v in kwargs.items():
                    if k in entry and k != "id":
                        entry[k] = v
                if "link" in kwargs:
                    entry["spreadsheet_id"] = self._extract_id(kwargs["link"])
                if "group_name" in kwargs:
                    gid = self.get_group_id_by_name(kwargs["group_name"])
                    if gid:
                        entry["group_id"] = gid
                entry["updated"] = datetime.now().isoformat()
                self.save()
                return entry
        return None

    def delete_entry(self, entry_id):
        """删除条目"""
        self._data["entries"] = [
            e for e in self._data["entries"] if e["id"] != entry_id
        ]
        self.save()

    def get_entry(self, entry_id):
        """获取条目"""
        for e in self._data["entries"]:
            if e["id"] == entry_id:
                return e
        return None

    def get_entries_by_group(self, group_id):
        """获取指定分组的所有条目"""
        return [e for e in self.entries if e.get("group_id") == group_id]

    # ========================
    # 搜索
    # ========================

    def search(self, keyword, use_regex=False):
        """
        搜索表格库。

        Args:
            keyword: 搜索关键词
            use_regex: 是否使用正则表达式

        Returns:
            匹配的条目列表
        """
        if not keyword.strip():
            return self.entries

        results = []
        for entry in self.entries:
            tags_str = " ".join(entry.get("tags", []))
            searchable = f"{entry.get('name','')} {entry.get('link','')} {entry.get('notes','')} {entry.get('spreadsheet_id','')} {tags_str}"

            if use_regex:
                try:
                    if re.search(keyword, searchable, re.IGNORECASE):
                        results.append(entry)
                except re.error:
                    pass
            else:
                # 模糊搜索：关键词拆分，全部匹配
                kw_lower = keyword.lower()
                if kw_lower in searchable.lower():
                    results.append(entry)

        return results

    def get_group_name(self, group_id):
        """获取分组名称"""
        g = self._data["groups"].get(group_id)
        return g["name"] if g else "未知"

    # ========================
    # 向后兼容迁移
    # ========================

    def _migrate_entries(self):
        """为旧版条目填充缺少的新字段"""
        defaults = {
            "is_starred": False,
            "tags": [],
            "health_status": "unknown",
            "health_detail": "",
            "health_checked_at": ""
        }
        changed = False
        for entry in self._data.get("entries", []):
            for key, default_val in defaults.items():
                if key not in entry:
                    entry[key] = default_val
                    changed = True
        if changed:
            self.save()
            logger.info("已迁移旧版条目数据结构")

    # ========================
    # 健康状态
    # ========================

    def update_health(self, entry_id, status, detail=""):
        """
        更新条目的健康状态。

        Args:
            entry_id: 条目 ID
            status: 状态值 ('ok' / 'warning' / 'error' / 'unknown')
            detail: 状态详情摘要
        """
        for entry in self._data["entries"]:
            if entry["id"] == entry_id:
                entry["health_status"] = status
                entry["health_detail"] = detail
                entry["health_checked_at"] = datetime.now().isoformat()
                self.save()
                return True
        return False

    # ========================
    # 导出 / 导入
    # ========================

    def export_data(self, group_id=None):
        """
        导出表格库数据。

        Args:
            group_id: 可选，指定分组 ID 仅导出该分组；None 表示全量导出

        Returns:
            dict: 可序列化为 JSON 的数据字典
        """
        if group_id and group_id != "__all__":
            groups = {group_id: self._data["groups"].get(group_id, {})}
            entries = [e for e in self._data["entries"] if e.get("group_id") == group_id]
        else:
            groups = dict(self._data["groups"])
            entries = list(self._data["entries"])

        return {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "groups": groups,
            "entries": entries
        }

    def import_data(self, data, merge=True):
        """
        导入表格库数据。

        Args:
            data: 导入的数据字典（由 export_data 生成）
            merge: True=合并（按 spreadsheet_id 去重），False=覆盖

        Returns:
            dict: {“added”: int, “skipped”: int, “groups_added”: int}
        """
        imported_groups = data.get("groups", {})
        imported_entries = data.get("entries", [])

        stats = {"added": 0, "skipped": 0, "groups_added": 0}

        if not merge:
            # 覆盖模式：替换全部数据
            self._data["groups"] = imported_groups
            self._data["entries"] = imported_entries
            self._migrate_entries()
            self.save()
            stats["added"] = len(imported_entries)
            stats["groups_added"] = len(imported_groups)
            return stats

        # 合并模式：按 spreadsheet_id 去重
        existing_sids = set(
            e.get("spreadsheet_id", "") for e in self._data["entries"]
            if e.get("spreadsheet_id")
        )

        # 合并分组
        for gid, ginfo in imported_groups.items():
            if gid not in self._data["groups"]:
                self._data["groups"][gid] = ginfo
                stats["groups_added"] += 1

        # 合并条目
        for entry in imported_entries:
            sid = entry.get("spreadsheet_id", "")
            if sid and sid in existing_sids:
                stats["skipped"] += 1
                continue
            # 生成新 ID 避免冲突
            entry["id"] = str(uuid.uuid4())[:8]
            self._data["entries"].append(entry)
            if sid:
                existing_sids.add(sid)
            stats["added"] += 1

        self._migrate_entries()
        self.save()
        logger.info(
            f"导入完成: 新增 {stats['added']} 条, "
            f"跳过 {stats['skipped']} 条, "
            f"新增分组 {stats['groups_added']} 个"
        )
        return stats


class AccountManager:
    """
    多账号管理器 — 管理多个 SpreadsheetLibrary 实例。

    每个账号有独立的加密数据文件，共用同一加密密钥。
    账号元数据保存在 spreadsheet_accounts.json 中。

    数据结构：
    {
        "accounts": [
            {"id": "uuid", "name": "账号1", "data_file": "sheet_lib_acc1.enc"}
        ],
        "active_index": 0
    }
    """

    ACCOUNTS_FILE = os.path.join(BASE_DIR, "spreadsheet_accounts.json")

    def __init__(self):
        self._accounts = []
        self._active_index = 0
        self._libraries = {}  # 缓存: account_id -> SpreadsheetLibrary
        self._load_accounts()
        self._migrate_legacy_data()

    # ========================
    # 账号元数据持久化
    # ========================

    def _load_accounts(self):
        """加载账号列表"""
        if os.path.exists(self.ACCOUNTS_FILE):
            try:
                with open(self.ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._accounts = data.get("accounts", [])
                self._active_index = data.get("active_index", 0)
                logger.info(f"已加载 {len(self._accounts)} 个账号")
            except Exception as e:
                logger.error(f"账号配置加载失败: {e}")
                self._accounts = []
                self._active_index = 0

    def _save_accounts(self):
        """保存账号列表"""
        try:
            data = {
                "accounts": self._accounts,
                "active_index": self._active_index,
            }
            with open(self.ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"账号配置保存失败: {e}")

    def _migrate_legacy_data(self):
        """自动迁移旧的单文件数据到第一个账号"""
        if self._accounts:
            return  # 已有账号，无需迁移

        # 检查是否存在旧数据文件
        if os.path.exists(DEFAULT_DATA_PATH):
            acc_id = str(uuid.uuid4())[:8]
            # 旧文件就地作为第一个账号的数据文件
            self._accounts.append({
                "id": acc_id,
                "name": "默认账号",
                "data_file": os.path.basename(DEFAULT_DATA_PATH),
            })
            self._active_index = 0
            self._save_accounts()
            logger.info("已将旧数据迁移为「默认账号」")
        else:
            # 全新安装，创建默认账号
            self.add_account("默认账号")

    # ========================
    # 账号 CRUD
    # ========================

    @property
    def accounts(self):
        """返回账号列表 (只读副本)"""
        return list(self._accounts)

    @property
    def active_index(self):
        return self._active_index

    @active_index.setter
    def active_index(self, idx):
        if 0 <= idx < len(self._accounts):
            self._active_index = idx
            self._save_accounts()

    def add_account(self, name):
        """新增账号，返回 account_id"""
        acc_id = str(uuid.uuid4())[:8]
        data_file = f"sheet_lib_{acc_id}.enc"
        self._accounts.append({
            "id": acc_id,
            "name": name,
            "data_file": data_file,
        })
        self._save_accounts()
        # 立即初始化该账号的数据文件
        self.get_library(acc_id)
        logger.info(f"新增账号: {name} ({acc_id})")
        return acc_id

    def rename_account(self, acc_id, new_name):
        """重命名账号"""
        for acc in self._accounts:
            if acc["id"] == acc_id:
                acc["name"] = new_name
                self._save_accounts()
                return True
        return False

    def delete_account(self, acc_id):
        """删除账号及其数据文件"""
        if len(self._accounts) <= 1:
            logger.warning("至少保留一个账号")
            return False

        target = None
        for i, acc in enumerate(self._accounts):
            if acc["id"] == acc_id:
                target = acc
                self._accounts.pop(i)
                # 调整活动索引
                if self._active_index >= len(self._accounts):
                    self._active_index = len(self._accounts) - 1
                break

        if target:
            # 删除数据文件
            data_path = os.path.join(BASE_DIR, target["data_file"])
            if os.path.exists(data_path):
                try:
                    os.remove(data_path)
                except OSError:
                    pass
            # 清除缓存
            self._libraries.pop(acc_id, None)
            self._save_accounts()
            logger.info(f"已删除账号: {target['name']}")
            return True
        return False

    def get_account_name(self, acc_id):
        """获取账号名称"""
        for acc in self._accounts:
            if acc["id"] == acc_id:
                return acc["name"]
        return "未知"

    # ========================
    # Library 实例管理
    # ========================

    def get_library(self, acc_id):
        """获取指定账号的 SpreadsheetLibrary 实例（带缓存）"""
        if acc_id not in self._libraries:
            acc = None
            for a in self._accounts:
                if a["id"] == acc_id:
                    acc = a
                    break
            if not acc:
                return None
            data_path = os.path.join(BASE_DIR, acc["data_file"])
            self._libraries[acc_id] = SpreadsheetLibrary(data_path=data_path)
        return self._libraries[acc_id]

    def get_active_library(self):
        """获取当前活动账号的 Library"""
        if not self._accounts:
            return None
        acc = self._accounts[self._active_index]
        return self.get_library(acc["id"])

    def get_active_account(self):
        """获取当前活动账号信息"""
        if not self._accounts:
            return None
        return self._accounts[self._active_index]

    def reload_library(self, acc_id):
        """重新加载指定账号的数据"""
        self._libraries.pop(acc_id, None)
        return self.get_library(acc_id)

    # ========================
    # 全局搜索
    # ========================

    def search_all(self, keyword, use_regex=False):
        """
        跨所有账号搜索。

        Returns:
            list[dict]: 每项包含 account_id, account_name, entry
        """
        results = []
        for acc in self._accounts:
            lib = self.get_library(acc["id"])
            if not lib:
                continue
            matched = lib.search(keyword, use_regex)
            for entry in matched:
                results.append({
                    "account_id": acc["id"],
                    "account_name": acc["name"],
                    "entry": entry,
                })
        return results

