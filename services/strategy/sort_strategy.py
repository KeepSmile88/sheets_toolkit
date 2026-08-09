# 排序策略
from services.strategy.base_strategy import DataStrategy


class SortStrategy(DataStrategy):
    """
    按指定列排序数据行。
    保留表头行，仅排序数据行。
    """

    def __init__(self, col_index=0, reverse=False, numeric=False):
        self.col_index = col_index
        self.reverse = reverse
        self.numeric = numeric

    @property
    def name(self):
        order = "降序" if self.reverse else "升序"
        return f"排序(列{self.col_index}, {order})"

    def process(self, values):
        if not values or len(values) < 2:
            return values

        header = values[0]
        data = values[1:]

        def sort_key(row):
            if len(row) <= self.col_index:
                return "" if not self.numeric else 0
            val = row[self.col_index]
            if self.numeric:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return 0
            return str(val)

        sorted_data = sorted(data, key=sort_key, reverse=self.reverse)
        return [header] + sorted_data
