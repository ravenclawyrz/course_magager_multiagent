# -*- coding: utf-8 -*-
"""pytest 公共夹具。

约定：
- 所有文件路径一律来自 tmp_path，绝不触碰真实用户目录；
- 所有“当前时间”一律通过注入的时钟或显式 now 参数提供；
- 逻辑层测试不 import tkinter，保证无显示环境也可运行。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

import pytest

# 保证无论从哪个目录启动 pytest，都能导入工程根下的 course_manager 包
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from course_manager.models import Course, Homework  # noqa: E402
from course_manager.reminders import ReminderEngine  # noqa: E402
from course_manager.service import CourseService  # noqa: E402

#: 基准日：2026-10-12 为周一（weekday=0），便于构造“今天有课”的场景
基准日 = datetime(2026, 10, 12)


@pytest.fixture
def 周一八点钟() -> datetime:
    """固定基准时刻：2026-10-12（周一）08:00。"""
    return datetime(2026, 10, 12, 8, 0, 0)


@pytest.fixture
def 数据文件(tmp_path: Path) -> Path:
    """测试专用数据文件路径（位于 pytest 临时目录）。"""
    return tmp_path / "data.json"


@pytest.fixture
def 服务(数据文件: Path) -> CourseService:
    """绑定临时数据文件的业务服务。"""
    return CourseService(数据文件)


@pytest.fixture
def 固定时钟(周一八点钟: datetime) -> Callable[[], datetime]:
    """返回固定时刻的可调用时钟。"""
    return lambda: 周一八点钟


@pytest.fixture
def 引擎(固定时钟: Callable[[], datetime]) -> ReminderEngine:
    """注入固定时钟的提醒引擎。"""
    return ReminderEngine(clock=固定时钟)


@pytest.fixture
def 周一课程() -> Course:
    """一节周一第3-4节（10:00-11:40）的课程。"""
    return Course(
        name="软件工程",
        weekday=0,
        start_period=3,
        end_period=4,
        location="教一楼101",
        teacher="王老师",
    )


@pytest.fixture
def 周一作业(周一课程: Course) -> Homework:
    """属于周一课程、截止 2026-10-12 18:00 的作业。"""
    return Homework(
        course_id=周一课程.id,
        requirement="完成需求规格说明书",
        deadline=datetime(2026, 10, 12, 18, 0, 0),
    )
