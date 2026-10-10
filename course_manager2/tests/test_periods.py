# -*- coding: utf-8 -*-
"""作息时间表（13 节课）常量与辅助函数测试。"""
from __future__ import annotations

from datetime import date, datetime, time

import pytest

from course_manager.periods import (
    MAX_PERIOD,
    PERIODS,
    end_datetime,
    format_period,
    format_period_range,
    get_period_end,
    get_period_start,
    start_datetime,
)

#: task.md 规定的 13 节起止时间（HH:MM）
期望时间表 = {
    1: ("08:00", "08:45"),
    2: ("08:55", "09:40"),
    3: ("10:00", "10:45"),
    4: ("10:55", "11:40"),
    5: ("12:00", "12:45"),
    6: ("12:55", "14:00"),
    7: ("14:00", "14:45"),
    8: ("14:55", "15:40"),
    9: ("16:00", "16:45"),
    10: ("16:55", "17:40"),
    11: ("18:00", "18:45"),
    12: ("18:55", "19:40"),
    13: ("19:45", "20:20"),
}


def test_PERIODS恰好13节且键连续完整() -> None:
    assert MAX_PERIOD == 13
    assert len(PERIODS) == 13
    assert set(PERIODS.keys()) == set(range(1, 14))


@pytest.mark.parametrize("节次", list(range(1, 14)))
def test_每节起止时间与需求完全一致(节次: int) -> None:
    开始, 结束 = PERIODS[节次]
    期望开始, 期望结束 = 期望时间表[节次]
    assert 开始.strftime("%H:%M") == 期望开始
    assert 结束.strftime("%H:%M") == 期望结束


def test_重点核对_第6节为午休大节_12点55到14点() -> None:
    assert get_period_start(6) == time(12, 55)
    assert get_period_end(6) == time(14, 0)


def test_重点核对_第13节_19点45到20点20() -> None:
    assert get_period_start(13) == time(19, 45)
    assert get_period_end(13) == time(20, 20)


def test_format_period_单节格式() -> None:
    assert format_period(1) == "第1节 08:00-08:45"
    assert format_period(6) == "第6节 12:55-14:00"
    assert format_period(13) == "第13节 19:45-20:20"


def test_format_period_range_单节区间() -> None:
    assert format_period_range(3, 3) == "第3节 10:00-10:45"


def test_format_period_range_多节区间取首始末止() -> None:
    assert format_period_range(1, 3) == "第1-3节 08:00-10:45"
    assert format_period_range(6, 7) == "第6-7节 12:55-14:45"
    assert format_period_range(11, 13) == "第11-13节 18:00-20:20"


def test_format_period_range_起大于止_抛中文ValueError() -> None:
    with pytest.raises(ValueError, match="起始节次不能大于结束节次"):
        format_period_range(5, 2)


def test_start_datetime_日期加起始节次组合() -> None:
    day = date(2026, 10, 12)
    assert start_datetime(day, 1) == datetime(2026, 10, 12, 8, 0)
    assert start_datetime(day, 6) == datetime(2026, 10, 12, 12, 55)
    assert start_datetime(day, 13) == datetime(2026, 10, 12, 19, 45)


def test_end_datetime_日期加结束节次组合() -> None:
    day = date(2026, 10, 12)
    assert end_datetime(day, 1) == datetime(2026, 10, 12, 8, 45)
    assert end_datetime(day, 6) == datetime(2026, 10, 12, 14, 0)
    assert end_datetime(day, 13) == datetime(2026, 10, 12, 20, 20)


@pytest.mark.parametrize("坏节次", [0, 14, -1])
def test_节次越界_抛ValueError(坏节次: int) -> None:
    with pytest.raises(ValueError, match="节次必须在1~13之间"):
        get_period_start(坏节次)


def test_节次非整数_抛TypeError() -> None:
    with pytest.raises(TypeError, match="节次必须是整数"):
        get_period_start("3")
    with pytest.raises(TypeError, match="节次必须是整数"):
        get_period_start(True)
