# Google Sheets 与 Drive API 授权封装（单例模式）
# 支持用户自选 JSON 凭据文件 + 浏览器 OAuth 验证
import os
import logging
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from core.exceptions import AuthError

logger = logging.getLogger("sheets_toolkit.auth")

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AuthManager:
    """
    Google API 认证管理器（单例模式）。
    支持用户自选 credentials.json 文件，通过浏览器进行 OAuth 验证。
    缓存 sheets_api 和 drive_api 实例，避免重复创建。
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
        self._creds = None
        import threading
        self._local = threading.local()
        self._token_path = os.path.join(BASE_DIR, "token.json")
        self._creds_path = os.path.join(BASE_DIR, "credentials.json")
        self._user_email = None

        # 从配置中加载上次使用的凭据路径
        self._load_saved_creds_path()

        # 启动时尝试加载已保存的 token（不弹浏览器）
        self._try_load_token()

    def _load_saved_creds_path(self):
        """从配置中加载上次使用的凭据文件路径"""
        try:
            from core.config import AppConfig
            config = AppConfig()
            saved_path = config.get("credentials_path", "")
            if saved_path and os.path.exists(saved_path):
                self._creds_path = saved_path
                logger.info(f"已加载保存的凭据路径: {saved_path}")
        except Exception:
            pass

    def _try_load_token(self):
        """
        启动时静默加载已保存的 token（不弹浏览器）。
        如果 token 有效或可刷新，直接构建 API 实例。
        """
        if not os.path.exists(self._token_path):
            return

        try:
            creds = Credentials.from_authorized_user_file(self._token_path, SCOPES)

            if creds and creds.valid:
                # token 有效，直接使用
                self._creds = creds
                self._build_services(creds)
                logger.info("已从 token 文件恢复登录状态")
            elif creds and creds.expired and creds.refresh_token:
                # token 过期但可刷新
                creds.refresh(Request())
                with open(self._token_path, 'w') as token:
                    token.write(creds.to_json())
                self._creds = creds
                self._build_services(creds)
                logger.info("已刷新过期 token 并恢复登录状态")
        except Exception as e:
            logger.warning(f"加载 token 失败（将在需要时重新认证）: {e}")

    def _build_services(self, creds):
        """根据凭据构建 API 服务实例并获取用户邮箱"""
        if not hasattr(self, '_local'):
            import threading
            self._local = threading.local()
        self._local.sheets_api = build('sheets', 'v4', credentials=creds)
        self._local.drive_api = build('drive', 'v3', credentials=creds)
        try:
            about = self._local.drive_api.about().get(fields="user").execute()
            self._user_email = about.get("user", {}).get("emailAddress", "")
            logger.info(f"当前用户: {self._user_email}")
        except Exception:
            pass

    def set_credentials_path(self, path):
        """
        设置自定义的 credentials.json 文件路径。

        Args:
            path: credentials.json 的绝对路径
        """
        if not os.path.exists(path):
            raise AuthError(f"凭据文件不存在: {path}")

        # 验证文件是否为有效的 JSON
        import json
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # 检查是否包含必要的 OAuth 字段
            if 'installed' not in data and 'web' not in data:
                raise AuthError(
                    "无效的凭据文件：缺少 'installed' 或 'web' 配置。\n"
                    "请确保从 Google Cloud Console 下载的是 OAuth 2.0 客户端 ID 凭据。"
                )
        except json.JSONDecodeError:
            raise AuthError("无效的 JSON 文件")

        self._creds_path = path
        logger.info(f"已设置凭据路径: {path}")

        # 保存到配置
        try:
            from core.config import AppConfig
            config = AppConfig()
            config.set("credentials_path", path)
        except Exception:
            pass

    def authenticate_with_file(self, creds_path):
        """
        使用指定的 credentials.json 文件进行认证。
        会清除旧的 token，重新走 OAuth 流程，在浏览器中打开授权页面。

        Args:
            creds_path: credentials.json 的绝对路径

        Returns:
            bool: 认证是否成功
        """
        self.set_credentials_path(creds_path)

        # 清除旧的 token 和 API 实例
        self._creds = None
        if hasattr(self, '_local'):
            self._local.sheets_api = None
            self._local.drive_api = None
        self._user_email = None

        # 删除旧 token 文件（强制重新认证）
        if os.path.exists(self._token_path):
            try:
                os.remove(self._token_path)
                logger.info("已删除旧的 token 文件")
            except OSError as e:
                logger.warning(f"删除旧 token 失败: {e}")

        # 执行认证
        self._authenticate()
        return self.is_authenticated

    def _authenticate(self):
        """执行 OAuth2 认证流程（自动在浏览器中打开授权页面）"""
        try:
            creds = None
            if os.path.exists(self._token_path):
                creds = Credentials.from_authorized_user_file(self._token_path, SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    logger.info("刷新已过期的凭据...")
                    creds.refresh(Request())
                else:
                    if not os.path.exists(self._creds_path):
                        raise AuthError(
                            f"找不到凭据文件: {self._creds_path}\n"
                            "请从 Google Cloud Console 下载 credentials.json，\n"
                            "或在菜单中选择「🔑 选择凭据文件」指定文件位置。"
                        )
                    logger.info("启动 OAuth2 认证流程（将在浏览器中打开）...")
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self._creds_path, SCOPES
                    )
                    creds = flow.run_local_server(port=0)

                # 保存凭据
                with open(self._token_path, 'w') as token:
                    token.write(creds.to_json())
                logger.info("凭据已保存")

            self._creds = creds
            if not hasattr(self, '_local'):
                import threading
                self._local = threading.local()
            self._local.sheets_api = build('sheets', 'v4', credentials=creds)
            self._local.drive_api = build('drive', 'v3', credentials=creds)

            # 获取当前用户邮箱
            try:
                about = self._local.drive_api.about().get(fields="user").execute()
                self._user_email = about.get("user", {}).get("emailAddress", "")
                logger.info(f"Google API 认证成功: {self._user_email}")
            except Exception:
                logger.info("Google API 认证成功")

        except AuthError:
            raise
        except Exception as e:
            raise AuthError(f"认证失败: {str(e)}") from e

    @property
    def sheets_api(self):
        """获取 Sheets API 服务实例"""
        if not hasattr(self, '_local'):
            import threading
            self._local = threading.local()
        if getattr(self._local, 'sheets_api', None) is None:
            if not self.is_authenticated:
                self._authenticate()
            else:
                self._local.sheets_api = build('sheets', 'v4', credentials=self._creds)
        return self._local.sheets_api

    @property
    def drive_api(self):
        """获取 Drive API 服务实例"""
        if not hasattr(self, '_local'):
            import threading
            self._local = threading.local()
        if getattr(self._local, 'drive_api', None) is None:
            if not self.is_authenticated:
                self._authenticate()
            else:
                self._local.drive_api = build('drive', 'v3', credentials=self._creds)
        return self._local.drive_api

    def refresh(self):
        """强制刷新认证（清除缓存并重新认证）"""
        logger.info("强制刷新认证...")
        if hasattr(self, '_local'):
            self._local.sheets_api = None
            self._local.drive_api = None
        self._creds = None
        self._authenticate()

    def logout(self):
        """注销：清除 token 文件和所有缓存"""
        self._creds = None
        if hasattr(self, '_local'):
            self._local.sheets_api = None
            self._local.drive_api = None
        self._user_email = None

        if os.path.exists(self._token_path):
            try:
                os.remove(self._token_path)
                logger.info("已注销并删除 token 文件")
            except OSError as e:
                logger.warning(f"删除 token 文件失败: {e}")

    @property
    def is_authenticated(self):
        """检查是否已认证"""
        return self._creds is not None and self._creds.valid

    @property
    def user_email(self):
        """获取当前认证用户的邮箱"""
        return self._user_email or ""

    @property
    def credentials_path(self):
        """获取当前使用的凭据文件路径"""
        return self._creds_path

    @property
    def auth_status(self):
        """
        获取认证状态信息。

        Returns:
            dict: {"authenticated": bool, "email": str, "creds_path": str}
        """
        return {
            "authenticated": self.is_authenticated,
            "email": self._user_email or "",
            "creds_path": self._creds_path,
            "token_exists": os.path.exists(self._token_path)
        }


def get_services():
    """
    向后兼容的便捷函数。
    返回 (sheets_api, drive_api) 元组。
    """
    auth = AuthManager()
    return auth.sheets_api, auth.drive_api

