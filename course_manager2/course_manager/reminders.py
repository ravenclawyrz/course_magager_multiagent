# -*- coding: utf-8 -*-
"""智能提醒引擎。

规则（严格按需求）：
- 上课前 30 分钟内（课程尚未开始）以及上课进行中 -> 触发上课提醒；
- 作业距截止不足 24 小时、或已逾期 -> 触发作业提醒；
- 同一天同一事项只提醒一次，去重键为 “日期 + 类型 + 事项ID”，去重状态只保存在内存；
- 当前时间可通过 clock 可调用对象注入，也可在各方法中通过 now 参数显式传入。

本模块不依赖 tkinter，返回的 Reminder 数据由 GUI 决定如何弹窗展示。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from .models import Course, Homework, WEEKDAYS
from .periods import end_datetime, format_period_range, start_datetime

#: 事项类型
COURSE_TYPE = "course"
HOMEWORK_TYPE = "homework"

#: 提醒级别
LEVEL_INFO = "info"
LEVEL_WARNING = "warning"
LEVEL_DANGER = "danger"

#: 上课提前提醒的时间窗口
BEFORE_CLASS_MINUTES = 30
BEFORE_CLASS_WINDOW = timedelta(minutes=BEFORE_CLASS_MINUTES)

#: 作业“临近截止”的阈值
HOMEWORK_SOON_WINDOW = timedelta(hours=24)


@dataclass
class Reminder:
    """一条提醒。"""

    item_type: str  # COURSE_TYPE / HOMEWORK_TYPE
    item_id: str
    title: str
    message: str
    level: str = LEVEL_INFO


def format_duration(span: timedelta) -> str:
    """把时间差格式化为中文时长，如 "2天3小时"、"25分钟"、"不足1分钟"。

    结果为非负时长文本；是否“已逾期”由调用方根据语义自行加前缀。
    """
    total = abs(int(span.total_seconds()))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)

    parts: List[str] = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if not days and minutes:
        parts.append(f"{minutes}分钟")
    if not parts:
        return "不足1分钟"
    return "".join(parts)


class ReminderEngine:
    """提醒引擎。

    参数：
        clock: 返回当前 datetime 的可调用对象，默认为 datetime.now；测试时可注入固定时间。
    """

    def __init__(self, clock: Optional[Callable[[], datetime]] = None):
        self.clock: Callable[[], datetime] = clock if clock is not None else datetime.now
        # 已弹窗去重集合，元素为 (日期字符串, 事项类型, 事项ID)
        self._notified: set = set()

    # ------------------------------------------------------------------
    # 时间注入
    # ------------------------------------------------------------------
    def now(self, now: Optional[datetime] = None) -> datetime:
        """获取“当前时间”：显式传入优先，否则调用注入的 clock。"""
        return now if now is not None else self.clock()

    def reset_dedup(self) -> None:
        """清空当天去重记录（主要供测试使用）。"""
        self._notified.clear()

    # ------------------------------------------------------------------
    # 状态判断（同时供“今日提醒”页使用）
    # ------------------------------------------------------------------
    def course_occurrence(
        self, course: Course, now: Optional[datetime] = None
    ) -> Optional[tuple]:
        """若课程今天有课，返回 (开始datetime, 结束datetime)，否则返回 None。"""
        now = self.now(now)
        if course.weekday != now.weekday():
            return None
        today = now.date()
        return (
            start_datetime(today, course.start_period),
            end_datetime(today, course.end_period),
        )

    def course_status(self, course: Course, now: Optional[datetime] = None) -> Optional[Dict]:
        """计算今日课程状态。

        返回字典：{status, start, end, minutes}
        - status="upcoming"：今天尚未开始，minutes 为距开始分钟数（math.ceil 向上取整）；
        - status="ongoing"：上课进行中；
        - status="ended"：今天已结束；
        - 课程今天没课返回 None。
        """
        now = self.now(now)
        occurrence = self.course_occurrence(course, now)
        if occurrence is None:
            return None
        course_start, course_end = occurrence
        if now < course_start:
            # 展示分钟统一向上取整：30:29 显示 31 分钟，不会提前落入 30 分钟窗口
            minutes = max(0, math.ceil((course_start - now).total_seconds() / 60))
            return {
                "status": "upcoming",
                "start": course_start,
                "end": course_end,
                "minutes": minutes,
            }
        if now <= course_end:
            return {
                "status": "ongoing",
                "start": course_start,
                "end": course_end,
                "minutes": 0,
            }
        return {
            "status": "ended",
            "start": course_start,
            "end": course_end,
            "minutes": 0,
        }

    def homework_status(self, homework: Homework, now: Optional[datetime] = None) -> Dict:
        """计算作业截止状态。

        返回字典：{status, remaining, deadline, seconds}
        - status="overdue"：已逾期；
        - status="due_soon"：距截止不足 24 小时（且未逾期）；
        - status="normal"：距截止尚有 24 小时及以上。
        remaining 为 deadline - now 的 timedelta（逾期时为负值）。
        """
        now = self.now(now)
        remaining = homework.deadline - now
        seconds = remaining.total_seconds()
        if seconds < 0:
            status = "overdue"
        elif remaining < HOMEWORK_SOON_WINDOW:
            status = "due_soon"
        else:
            status = "normal"
        return {
            "status": status,
            "remaining": remaining,
            "deadline": homework.deadline,
            "seconds": seconds,
        }

    # ------------------------------------------------------------------
    # 弹窗提醒
    # ------------------------------------------------------------------
    def evaluate(
        self,
        courses: List[Course],
        homeworks: List[Homework],
        now: Optional[datetime] = None,
    ) -> List[Reminder]:
        """计算此刻所有应当触发的提醒（不做去重）。"""
        now = self.now(now)
        reminders: List[Reminder] = []

        # 上课提醒：前30分钟窗口内 / 进行中
        for course in courses:
            status = self.course_status(course, now)
            if status is None:
                continue
            period_text = format_period_range(course.start_period, course.end_period)
            place = f"，上课地点：{course.location}" if course.location else ""
            if status["status"] == "ongoing":
                reminders.append(
                    Reminder(
                        COURSE_TYPE,
                        course.id,
                        "上课提醒",
                        f"《{course.name}》正在上课（{period_text}）{place}".strip(),
                        LEVEL_WARNING,
                    )
                )
            elif status["status"] == "upcoming":
                # 窗口用时间差直接比较（<= 30 分钟），不使用 round：
                # 剩余 30:29 时不提醒，恰为 30:00 时提醒
                delta = status["start"] - now
                if timedelta(0) < delta <= BEFORE_CLASS_WINDOW:
                    seconds_left = delta.total_seconds()
                    # 不足 1 分钟直接显示“即将开始”，避免出现“0 分钟后开始”
                    if seconds_left < 60:
                        time_phrase = "即将开始"
                    else:
                        # 展示分钟使用 math.ceil 向上取整
                        time_phrase = f"{math.ceil(seconds_left / 60)} 分钟后开始"
                    reminders.append(
                        Reminder(
                            COURSE_TYPE,
                            course.id,
                            "上课提醒",
                            f"《{course.name}》{time_phrase}"
                            f"（{period_text}）{place}".strip(),
                            LEVEL_WARNING,
                        )
                    )

        # 作业提醒：不足24小时 / 已逾期
        course_map = {c.id: c for c in courses}
        for homework in homeworks:
            status = self.homework_status(homework, now)
            course = course_map.get(homework.course_id)
            course_name = course.name if course is not None else "未知课程"
            if status["status"] == "overdue":
                overdue_text = format_duration(-status["remaining"])
                reminders.append(
                    Reminder(
                        HOMEWORK_TYPE,
                        homework.id,
                        "作业逾期提醒",
                        f"【{course_name}】{homework.requirement}：已逾期 {overdue_text}"
                        f"（截止时间 {status['deadline'].strftime('%Y-%m-%d %H:%M')}）",
                        LEVEL_DANGER,
                    )
                )
            elif status["status"] == "due_soon":
                left_text = format_duration(status["remaining"])
                reminders.append(
                    Reminder(
                        HOMEWORK_TYPE,
                        homework.id,
                        "作业临近提醒",
                        f"【{course_name}】{homework.requirement}：距截止仅剩 {left_text}"
                        f"（截止时间 {status['deadline'].strftime('%Y-%m-%d %H:%M')}）",
                        LEVEL_WARNING,
                    )
                )

        return reminders

    def check(
        self,
        courses: List[Course],
        homeworks: List[Homework],
        now: Optional[datetime] = None,
    ) -> List[Reminder]:
        """计算此刻应弹窗的新提醒，并按“日期+类型+事项ID”去重。

        被本方法返回过的提醒当天不会再次返回（内存级去重，重启后重置）。
        """
        now = self.now(now)
        today_key = now.date().isoformat()
        # 日期翻转：清理去重集合中所有非当天的 key，
        # 否则跨天后集合无限增长且语义上昨天的记录不应影响今天
        for key in list(self._notified):
            if key[0] != today_key:
                self._notified.discard(key)

        fresh: List[Reminder] = []
        for reminder in self.evaluate(courses, homeworks, now):
            key = (today_key, reminder.item_type, reminder.item_id)
            if key in self._notified:
                continue
            self._notified.add(key)
            fresh.append(reminder)
        return fresh
