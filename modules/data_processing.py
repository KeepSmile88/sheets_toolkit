# modules/data_processing.py — 数据处理便捷函数
import logging
from datetime import datetime, timedelta
from services.strategy.sum_strategy import SumStrategy
from services.strategy.filter_strategy import FilterStrategy

logger = logging.getLogger("sheets_toolkit.modules.data_processing")


def sum_range(values, col_index=0):
    """对指定列求和"""
    strategy = SumStrategy(col_index)
    return strategy.process(values)


def filter_rows_by_condition(values, col_index, expected):
    """按条件过滤数据行"""
    strategy = FilterStrategy(col_index, expected)
    return strategy.process(values)


def find_keyword(values, keyword):
    """在数据中查找关键词，返回 (行, 列) 索引"""
    for r, row in enumerate(values):
        for c, cell in enumerate(row):
            if keyword in str(cell):
                return r, c
    return -1, -1


def filter_by_date(values, date_col, days):
    """按日期过滤：保留最近 N 天内的数据行"""
    if not values:
        return []
    result = [values[0]]  # 保留表头
    cutoff = datetime.now() - timedelta(days=days)
    for row in values[1:]:
        try:
            if len(row) > date_col:
                date_val = datetime.fromisoformat(row[date_col])
                if date_val >= cutoff:
                    result.append(row)
        except (ValueError, TypeError) as e:
            logger.debug(f"跳过无效日期值: {e}")
            continue
    return result
