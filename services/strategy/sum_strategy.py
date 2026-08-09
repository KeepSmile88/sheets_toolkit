# 列求和策略
import logging
from services.strategy.base_strategy import DataStrategy

logger = logging.getLogger("sheets_toolkit.strategy.sum")


class SumStrategy(DataStrategy):
    """对指定列求和"""

    def __init__(self, col_index=0):
        self.col_index = col_index

    @property
    def name(self):
        return f"求和(列{self.col_index})"

    def process(self, values):
        total = 0.0
        for row in values:
            try:
                if len(row) > self.col_index:
                    total += float(row[self.col_index])
            except (ValueError, TypeError) as e:
                logger.debug(f"跳过无法转换为数值的单元格: {row[self.col_index] if len(row) > self.col_index else 'N/A'}")
                continue
        return total
