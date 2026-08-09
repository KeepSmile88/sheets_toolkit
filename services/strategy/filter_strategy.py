# 按条件过滤数据行策略
from services.strategy.base_strategy import DataStrategy


class FilterStrategy(DataStrategy):
    """
    按指定列的值过滤数据行。
    保留表头行，仅过滤数据行。
    """

    def __init__(self, col_index, expected_value):
        self.col_index = col_index
        self.expected_value = expected_value

    @property
    def name(self):
        return f"过滤(列{self.col_index}={self.expected_value})"

    def process(self, values):
        if not values:
            return []
        header = values[0]
        rows = [header]
        for row in values[1:]:
            if len(row) > self.col_index and row[self.col_index] == self.expected_value:
                rows.append(row)
        return rows
