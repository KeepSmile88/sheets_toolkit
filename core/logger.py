# 统一日志模块：支持文件日志 + 控制台 + Qt 信号实时推送
import logging
import os
from PySide6.QtCore import QObject, Signal


class QtLogHandler(logging.Handler):
    """
    自定义日志处理器，将日志消息通过 Qt 信号推送到 UI。
    """

    def __init__(self, signal_emitter):
        super().__init__()
        self.signal_emitter = signal_emitter

    def emit(self, record):
        try:
            msg = self.format(record)
            self.signal_emitter.log_signal.emit(msg)
        except Exception:
            self.handleError(record)


class LogSignalEmitter(QObject):
    """日志信号发射器，用于线程安全地向 UI 推送日志"""
    log_signal = Signal(str)


# 全局日志信号发射器（单例）
_log_emitter = None


def get_log_emitter():
    """获取全局日志信号发射器"""
    global _log_emitter
    if _log_emitter is None:
        _log_emitter = LogSignalEmitter()
    return _log_emitter


def setup_logger(name="sheets_toolkit", level=logging.INFO, log_dir="logs"):
    """
    配置并返回统一的日志记录器。

    Args:
        name: 日志记录器名称
        level: 日志级别
        log_dir: 日志文件存储目录

    Returns:
        logging.Logger: 配置好的日志记录器
    """
    logger = logging.getLogger(name)

    # 避免重复添加处理器
    if logger.handlers:
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件输出
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(
            os.path.join(log_dir, "toolkit.log"),
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"无法创建日志文件: {e}")

    # Qt 信号输出（推送到 UI）
    emitter = get_log_emitter()
    qt_handler = QtLogHandler(emitter)
    qt_formatter = logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    qt_handler.setFormatter(qt_formatter)
    logger.addHandler(qt_handler)

    return logger


def get_logger(name=None):
    """
    获取子日志记录器。

    Args:
        name: 子模块名称，会自动添加前缀 sheets_toolkit.

    Returns:
        logging.Logger
    """
    if name:
        return logging.getLogger(f"sheets_toolkit.{name}")
    return logging.getLogger("sheets_toolkit")
