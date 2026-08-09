# 去重策略
from services.strategy.base_strategy import DataStrategy


class DedupStrategy(DataStrategy):
    """
    按指定列去重数据行。
    保留表头行和每个唯一值的第一次出现。
    """

    def __init__(self, col_index=0):
        self.col_index = col_index

    @property
    def name(self):
        return f"去重(列{self.col_index})"

    def process(self, values):
        if not values:
            return []

        header = values[0]
        seen = set()
        result = [header]

        for row in values[1:]:
            if len(row) > self.col_index:
                key = row[self.col_index]
                if key not in seen:
                    seen.add(key)
                    result.append(row)
            else:
                result.append(row)

        return result
