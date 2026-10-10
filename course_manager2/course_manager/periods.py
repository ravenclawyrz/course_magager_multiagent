# -*- coding: utf-8 -*-
"""13 节课时间表常量与查询/格式化函数。

时间表（严格按需求）：
第1节 08:00-08:45、第2节 08:55-09:40、第3节 10:00-10:45、
第4节 10:55-11:40、第5节 12:00-12:45、第6节 12:55-14:00、
第7节 14:00-14:45、第8节 14:55-15:40、第9节 16:00-16:45、
第10节 16:55-17:40、第11节 18:00-18:45、第12节 18:55-19:40、
第13节 19:45-20:20。
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Dict, Tuple

#: 节次 -> (开始时间, 结束时间)
PERIODS: Dict[int, Tuple[time, time]] = {
    1: (time(8, 0), time(8, 45)),
    2: (time(8, 55), time(9, 40)),
    3: (time(10, 0), time(10, 45)),
    4: (time(10, 55), time(11, 40)),
    5: (time(12, 0), time(12, 45)),
    6: (time(12, 55), time(14, 0)),
    7: (time(14, 0), time(14, 45)),
    8: (time(14, 55), time(15, 40)),
    9: (time(16, 0), time(16, 45)),
    10: (time(16, 55), time(17, 40)),
    11: (time(18, 0), time(18, 45)),
    12: (time(18, 55), time(19, 40)),
    13: (time(19, 45), time(20, 20)),
}

#: 最大节次
MAX_PERIOD = 13


def _check_period(period: int) -> int:
    """校验节次合法性，返回整数节次。"""
    if isinstance(period, bool) or not isinstance(period, int):
        raise TypeError(f"节次必须是整数，收到：{period!r}")
    if period not in PERIODS:
        raise ValueError(f"节次必须在1~{MAX_PERIOD}之间，收到：{period}")
    return period


def get_period_start(period: int) -> time:
    """返回某节课的开始时间，如第1节 -> 08:00。"""
    return PERIODS[_check_period(period)][0]


def get_period_end(period: int) -> time:
    """返回某节课的结束时间，如第1节 -> 08:45。"""
    return PERIODS[_check_period(period)][1]


def _hm(value: time) -> str:
    """把 time 格式化为 HH:MM。"""
    return value.strftime("%H:%M")


def format_period(period: int) -> str:
    """格式化单节课，如："第1节 08:00-08:45"。"""
    start, end = PERIODS[_check_period(period)]
    return f"第{period}节 {_hm(start)}-{_hm(end)}"


def format_period_range(start_period: int, end_period: int) -> str:
    """格式化节次区间。

    单节："第1节 08:00-08:45"；
    多节："第1-3节 08:00-10:45"（时间取首节开始与末节结束）。
    """
    _check_period(start_period)
    _check_period(end_period)
    if start_period > end_period:
        raise ValueError("起始节次不能大于结束节次")
    start = PERIODS[start_period][0]
    end = PERIODS[end_period][1]
    if start_period == end_period:
        head = f"第{start_period}节"
    else:
        head = f"第{start_period}-{end_period}节"
    return f"{head} {_hm(start)}-{_hm(end)}"


def start_datetime(day: date, start_period: int) -> datetime:
    """把某日期与起始节次组合为具体的开始 datetime。"""
    return datetime.combine(day, get_period_start(start_period))


def end_datetime(day: date, end_period: int) -> datetime:
    """把某日期与结束节次组合为具体的结束 datetime。"""
    return datetime.combine(day, get_period_end(end_period))
