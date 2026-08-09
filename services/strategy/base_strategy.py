# 策略模式抽象基类
from abc import ABC, abstractmethod


class DataStrategy(ABC):
    """
    数据处理策略基类。
    所有数据处理策略必须实现 process() 方法。
    """

    @property
    def name(self):
        """策略名称"""
        return self.__class__.__name__

    @abstractmethod
    def process(self, values):
        """
        处理数据。

        Args:
            values: 二维列表数据

        Returns:
            处理结果（类型取决于具体策略）
        """
        pass
