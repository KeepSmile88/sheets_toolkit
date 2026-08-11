# 配置管理模块：加载/保存 JSON 配置文件
import json
import os
from core.exceptions import ConfigError

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_VERSION = "V1.2"

# 默认配置
DEFAULT_CONFIG = {
    "default_spreadsheet_id": "",
    "backup_dir": "backups",
    "log_level": "INFO",
    "theme": "light",
    "max_retries": 3,
    "retry_delay": 1.0,
    "recent_spreadsheets": []
}


class AppConfig:
    """
    应用配置管理器（单例模式）。
    从 config.json 加载配置，支持动态读写和持久化。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._config_path = os.path.join(BASE_DIR, "config.json")
        self._config = {}
        self.load()

    def load(self):
        """从 config.json 加载配置，不存在则使用默认值"""
        try:
            if os.path.exists(self._config_path):
                with open(self._config_path, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
            else:
                self._config = DEFAULT_CONFIG.copy()
                self.save()
        except (json.JSONDecodeError, IOError) as e:
            raise ConfigError(f"配置文件加载失败: {e}")

    def save(self):
        """将当前配置保存到 config.json"""
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=4, ensure_ascii=False)
        except IOError as e:
            raise ConfigError(f"配置文件保存失败: {e}")

    def get(self, key, default=None):
        """获取配置项"""
        return self._config.get(key, default)

    def set(self, key, value):
        """设置配置项并自动保存"""
        self._config[key] = value
        self.save()

    def add_recent_spreadsheet(self, spreadsheet_id):
        """添加到最近使用列表（去重，最多保留 10 个）"""
        recent = self._config.get("recent_spreadsheets", [])
        if spreadsheet_id in recent:
            recent.remove(spreadsheet_id)
        recent.insert(0, spreadsheet_id)
        self._config["recent_spreadsheets"] = recent[:10]
        self.save()

    @property
    def base_dir(self):
        """项目根目录"""
        return BASE_DIR

    @property
    def backup_dir(self):
        """备份文件存放目录（绝对路径）"""
        backup = self.get("backup_dir", "backups")
        if not os.path.isabs(backup):
            backup = os.path.join(BASE_DIR, backup)
        os.makedirs(backup, exist_ok=True)
        return backup

    def to_dict(self):
        """返回配置的完整字典"""
        return self._config.copy()
