# -*- coding: utf-8 -*-
"""智能提醒引擎测试：课程状态、窗口边界、作业状态、当天去重与跨日清理。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from course_manager.models import Course, Homework
from course_manager.reminders import (
    BEFORE_CLASS_MINUTES,
    LEVEL_DANGER,
    LEVEL_WARNING,
    ReminderEngine,
    format_duration,
)

#: 周一第3节 10:00 开始、第4节 11:40 结束
周一课 = Course(name="软件工程", weekday=0, start_period=3, end_period=4,
              location="教一楼101", teacher="王老师")


def _引擎(固定时刻: datetime) -> ReminderEngine:
    return ReminderEngine(clock=lambda: 固定时刻)


# ---------------------------------------------------------------------------
# format_duration
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("时长", "期望文本"),
    [
        (timedelta(days=2, hours=3), "2天3小时"),
        (timedelta(hours=5), "5小时"),
        (timedelta(minutes=25), "25分钟"),
        (timedelta(seconds=30), "不足1分钟"),
        (timedelta(0), "不足1分钟"),
    ],
)
def test_format_duration_中文时长格式(时长: timedelta, 期望文本: str) -> None:
    assert format_duration(时长) == 期望文本


# ---------------------------------------------------------------------------
# course_status
# ---------------------------------------------------------------------------
def test_课程状态_未开始_剩余整小时显示180分钟() -> None:
    engine = _引擎(datetime(2026, 10, 12, 7, 0, 0))
    status = engine.course_status(周一课)
    assert status["status"] == "upcoming"
    assert status["minutes"] == 180
    assert status["start"] == datetime(2026, 10, 12, 10, 0)
    assert status["end"] == datetime(2026, 10, 12, 11, 40)


def test_课程状态_未开始_不足一分钟向上取整为1分钟() -> None:
    engine = _引擎(datetime(2026, 10, 12, 9, 59, 30))
    status = engine.course_status(周一课)
    assert status["status"] == "upcoming"
    assert status["minutes"] == 1


def test_课程状态_进行中() -> None:
    engine = _引擎(datetime(2026, 10, 12, 10, 30, 0))
    status = engine.course_status(周一课)
    assert status["status"] == "ongoing"
    assert status["minutes"] == 0


def test_课程状态_恰好下课时刻_仍算进行中() -> None:
    engine = _引擎(datetime(2026, 10, 12, 11, 40, 0))
    assert engine.course_status(周一课)["status"] == "ongoing"


def test_课程状态_已结束() -> None:
    engine = _引擎(datetime(2026, 10, 12, 11, 40, 1))
    status = engine.course_status(周一课)
    assert status["status"] == "ended"
    assert status["minutes"] == 0


def test_课程状态_非上课日返回None() -> None:
    # 2026-10-13 周二
    engine = _引擎(datetime(2026, 10, 13, 10, 0, 0))
    assert engine.course_status(周一课) is None


# ---------------------------------------------------------------------------
# evaluate 窗口边界
# ---------------------------------------------------------------------------
def _找上课提醒(engine: ReminderEngine):
    reminders = engine.evaluate([周一课], [])
    return [r for r in reminders if r.item_id == 周一课.id]


def test_evaluate_距开始30分29秒_不提醒() -> None:
    # 10:00 - 30:29 = 09:29:31
    engine = _引擎(datetime(2026, 10, 12, 9, 29, 31))
    assert _找上课提醒(engine) == []


def test_evaluate_恰好30分钟_提醒() -> None:
    engine = _引擎(datetime(2026, 10, 12, 9, 30, 0))
    提醒 = _找上课提醒(engine)
    assert len(提醒) == 1
    assert 提醒[0].level == LEVEL_WARNING
    assert "30 分钟后开始" in 提醒[0].message


def test_evaluate_仅剩59秒_显示即将开始() -> None:
    engine = _引擎(datetime(2026, 10, 12, 9, 59, 1))
    提醒 = _找上课提醒(engine)
    assert len(提醒) == 1
    assert "即将开始" in 提醒[0].message
    assert "0 分钟" not in 提醒[0].message


def test_evaluate_上课中_提醒() -> None:
    engine = _引擎(datetime(2026, 10, 12, 10, 20, 0))
    提醒 = _找上课提醒(engine)
    assert len(提醒) == 1
    assert 提醒[0].title == "上课提醒"
    assert "正在上课" in 提醒[0].message


def test_evaluate_下课后_不提醒() -> None:
    engine = _引擎(datetime(2026, 10, 12, 11, 45, 0))
    assert _找上课提醒(engine) == []


def test_evaluate_远超30分钟_不提醒() -> None:
    engine = _引擎(datetime(2026, 10, 12, 8, 0, 0))
    assert _找上课提醒(engine) == []


def test_evaluate_上课提醒含地点信息() -> None:
    engine = _引擎(datetime(2026, 10, 12, 10, 20, 0))
    提醒 = _找上课提醒(engine)[0]
    assert "教一楼101" in 提醒.message


# ---------------------------------------------------------------------------
# homework_status
# ---------------------------------------------------------------------------
现在 = datetime(2026, 10, 12, 12, 0, 0)


def _作业状态(deadline: datetime):
    homework = Homework(course_id="c1", requirement="作业要求", deadline=deadline)
    return _引擎(现在).homework_status(homework)


def test_作业状态_超过24小时_正常() -> None:
    status = _作业状态(现在 + timedelta(hours=25))
    assert status["status"] == "normal"
    assert status["seconds"] > 0


def test_作业状态_不足24小时_临近截止() -> None:
    status = _作业状态(现在 + timedelta(hours=23, minutes=59, seconds=59))
    assert status["status"] == "due_soon"
    assert 0 < status["seconds"] < 24 * 3600


def test_作业状态_恰好24小时_边界不算临近() -> None:
    # 严格小于 24h 才提醒：恰好 24h 仍为 normal
    status = _作业状态(现在 + timedelta(hours=24))
    assert status["status"] == "normal"
    assert status["seconds"] == 24 * 3600


def test_作业状态_已逾期() -> None:
    status = _作业状态(现在 - timedelta(minutes=10))
    assert status["status"] == "overdue"
    assert status["seconds"] < 0


def test_evaluate_作业临近_橙色警告级别() -> None:
    homework = Homework(course_id=周一课.id, requirement="提交文档",
                        deadline=现在 + timedelta(hours=10))
    engine = _引擎(现在)
    提醒 = engine.evaluate([周一课], [homework])
    作业提醒 = [r for r in 提醒 if r.item_id == homework.id]
    assert len(作业提醒) == 1
    assert 作业提醒[0].level == LEVEL_WARNING
    assert "作业临近提醒" == 作业提醒[0].title


def test_evaluate_作业逾期_红色危险级别() -> None:
    homework = Homework(course_id=周一课.id, requirement="补交文档",
                        deadline=现在 - timedelta(hours=2))
    engine = _引擎(现在)
    提醒 = engine.evaluate([周一课], [homework])
    作业提醒 = [r for r in 提醒 if r.item_id == homework.id]
    assert len(作业提醒) == 1
    assert 作业提醒[0].level == LEVEL_DANGER
    assert "已逾期" in 作业提醒[0].message


def test_evaluate_作业正常_不提醒() -> None:
    homework = Homework(course_id=周一课.id, requirement="远期作业",
                        deadline=现在 + timedelta(days=3))
    engine = _引擎(现在)
    assert all(r.item_id != homework.id for r in engine.evaluate([周一课], [homework]))


def test_evaluate_未知课程作业_仍能产生提醒() -> None:
    homework = Homework(course_id="已删除课程", requirement="孤儿作业",
                        deadline=现在 + timedelta(hours=5))
    engine = _引擎(现在)
    提醒 = [r for r in engine.evaluate([], [homework]) if r.item_id == homework.id]
    assert len(提醒) == 1
    assert "未知课程" in 提醒[0].message


# ---------------------------------------------------------------------------
# 去重 check
# ---------------------------------------------------------------------------
def test_check_同一天第二次调用_不再重复提醒() -> None:
    engine = _引擎(datetime(2026, 10, 12, 9, 30, 0))
    第一次 = engine.check([周一课], [])
    assert len(第一次) == 1
    第二次 = engine.check([周一课], [])
    assert 第二次 == []


def test_reset_dedup_清空后可再次提醒() -> None:
    engine = _引擎(datetime(2026, 10, 12, 9, 30, 0))
    assert len(engine.check([周一课], [])) == 1
    assert engine.check([周一课], []) == []
    engine.reset_dedup()
    assert len(engine.check([周一课], [])) == 1


def test_check_跨日后旧key被清理_且下周同日可再次提醒() -> None:
    engine = _引擎(datetime(2026, 10, 12, 9, 30, 0))
    周一提醒 = engine.check([周一课], [])
    assert len(周一提醒) == 1

    # 次日（周二）：课程今天无课，不产生提醒；昨天的去重 key 应被清理
    次日 = datetime(2026, 10, 13, 9, 30, 0)
    assert engine.check([周一课], [], now=次日) == []
    assert engine._notified == set(), "跨日后旧的去重 key 应被清理"

    # 下周一（2026-10-19）同一时间：去重不应阻止再次提醒
    下周一 = datetime(2026, 10, 19, 9, 30, 0)
    再次 = engine.check([周一课], [], now=下周一)
    assert len(再次) == 1
    assert all(k[0] == "2026-10-19" for k in engine._notified)


def test_check_上课常量_提前窗口确为30分钟() -> None:
    assert BEFORE_CLASS_MINUTES == 30
