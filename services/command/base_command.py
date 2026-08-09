# 命令模式抽象基类
from abc import ABC, abstractmethod


class SheetCommand(ABC):
    """
    命令模式基类。
    所有 Sheet 操作命令必须实现 execute() 方法。
    可选实现 undo() 以支持撤销操作。
    """

    @property
    def description(self):
        """命令描述（用于日志和 UI 显示）"""
        return self.__class__.__name__

    @abstractmethod
    def execute(self, service):
        """
        执行命令。

        Args:
            service: SheetService 实例

        Returns:
            执行结果
        """
        pass

    def undo(self, service):
        """
        撤销命令（可选实现）。
        默认抛出 NotImplementedError。
        """
        raise NotImplementedError(f"{self.description} 不支持撤销操作")

    @property
    def is_undoable(self):
        """此命令是否支持撤销"""
        try:
            # 检查子类是否重写了 undo 方法
            return type(self).undo is not SheetCommand.undo
        except Exception:
            return False
