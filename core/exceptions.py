# 自定义异常体系与 Google API 重试装饰器
import time
import functools
import logging
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


class SheetToolkitError(Exception):
    """工具箱基础异常类"""
    pass


class AuthError(SheetToolkitError):
    """认证相关异常"""
    pass


class APIError(SheetToolkitError):
    """Google API 调用异常"""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class ConfigError(SheetToolkitError):
    """配置相关异常"""
    pass


class ValidationError(SheetToolkitError):
    """数据验证异常"""
    pass


def retry_on_api_error(max_retries=3, base_delay=1.0):
    """
    Google API 指数退避重试装饰器。

    对 429 (速率限制) 和 5xx (服务器错误) 自动重试，
    使用指数退避策略避免过密请求。

    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟秒数
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import ssl
            import socket
            try:
                import httplib2
                HttpLib2Error = httplib2.HttpLib2Error
            except ImportError:
                class HttpLib2Error(Exception): pass

            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except HttpError as e:
                    last_error = e
                    status = e.resp.status if hasattr(e, 'resp') else 0
                    # 仅对速率限制和服务器错误重试
                    if status in (429, 500, 502, 503) and attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"API 调用失败 (HTTP {status})，"
                            f"{delay:.1f}秒后第 {attempt + 1} 次重试: {e}"
                        )
                        time.sleep(delay)
                    else:
                        raise APIError(
                            f"API 调用失败: {str(e)}",
                            status_code=status
                        ) from e
                except (ssl.SSLError, socket.error, HttpLib2Error, ConnectionError) as e:
                    last_error = e
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"底层网络或 SSL 异常，"
                            f"{delay:.1f}秒后第 {attempt + 1} 次重试: {e}"
                        )
                        time.sleep(delay)
                    else:
                        raise SheetToolkitError(
                            f"网络操作频繁或断开，最终重试失败: {str(e)}"
                        ) from e
                except Exception as e:
                    raise SheetToolkitError(f"操作执行失败: {str(e)}") from e
            raise APIError(f"已达最大重试次数 ({max_retries}): {last_error}")
        return wrapper
    return decorator
