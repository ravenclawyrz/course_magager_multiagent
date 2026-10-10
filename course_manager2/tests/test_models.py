# -*- coding: utf-8 -*-
"""数据模型层测试：Course / Homework 的构造校验与序列化往返。"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

import pytest

from course_manager.models import Course, Homework, normalize_weekday


# ---------------------------------------------------------------------------
# 正常构造
# ---------------------------------------------------------------------------
def test_课程正常构造_可选字段有默认值() -> None:
    course = Course(name="高等数学", weekday=0, start_period=1, end_period=2)
    assert course.name == "高等数学"
    assert course.weekday == 0
    assert course.start_period == 1
    assert course.end_period == 2
    assert course.location == ""
    assert course.teacher == ""
    assert isinstance(course.id, str) and course.id


def test_课程中文字段_to_dict_from_dict_往返一致() -> None:
    course = Course(
        name="软件工程项目实践",
        weekday="星期三",
        start_period=6,
        end_period=7,
        location="  教三楼208 ",
        teacher=" 李教授 ",
    )
    data = course.to_dict()
    assert data["name"] == "软件工程项目实践"
    assert data["weekday"] == 2
    # 可选字段在构造时已去除首尾空白
    assert data["location"] == "教三楼208"
    assert data["teacher"] == "李教授"

    rebuilt = Course.from_dict(data)
    assert rebuilt == course


def test_作业正常构造_to_dict_from_dict_往返一致() -> None:
    deadline = datetime(2026, 10, 12, 18, 30)
    homework = Homework(
        course_id="course-001",
        requirement="完成第三章全部习题",
        deadline=deadline,
    )
    data = homework.to_dict()
    assert data["deadline"] == deadline.isoformat()
    assert data["course_id"] == "course-001"

    rebuilt = Homework.from_dict(data)
    assert rebuilt == homework
    assert rebuilt.deadline == deadline


def test_课程星期支持中文字符串并被归一化() -> None:
    course = Course(name="大学英语", weekday="周五", start_period=1, end_period=1)
    assert course.weekday == 4
    assert course.start_period == course.end_period == 1


def test_课程节次支持数字字符串() -> None:
    course = Course(name="体育", weekday=0, start_period="5", end_period="6")
    assert course.start_period == 5
    assert course.end_period == 6


def test_课程地点为None时转空字符串() -> None:
    course = Course(name="物理", weekday=0, start_period=1, end_period=2, location=None)
    assert course.location == ""


# ---------------------------------------------------------------------------
# 课程校验：异常路径
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("空名称", ["", "   ", "\t\n"])
def test_课程名称为空或纯空白_抛中文ValueError(空名称: str) -> None:
    with pytest.raises(ValueError, match="课程名称不能为空"):
        Course(name=空名称, weekday=0, start_period=1, end_period=2)


@pytest.mark.parametrize("坏星期", [7, -1, "星期八", "礼拜八", "monday"])
def test_课程星期越界或无法识别_抛中文ValueError(坏星期) -> None:
    with pytest.raises(ValueError):
        Course(name="测试课", weekday=坏星期, start_period=1, end_period=2)


def test_星期取值为布尔_抛TypeError() -> None:
    with pytest.raises(TypeError, match="布尔"):
        normalize_weekday(True)
    with pytest.raises(TypeError, match="布尔"):
        Course(name="测试课", weekday=False, start_period=1, end_period=2)


@pytest.mark.parametrize("坏节次", [0, 14, -3])
def test_课程节次越界_抛中文ValueError(坏节次: int) -> None:
    with pytest.raises(ValueError, match="1~13"):
        Course(name="测试课", weekday=0, start_period=坏节次, end_period=坏节次)


def test_起始节次大于结束节次_抛中文ValueError() -> None:
    with pytest.raises(ValueError, match="起始节次不能大于结束节次"):
        Course(name="测试课", weekday=0, start_period=5, end_period=3)


def test_单节课程_起等于止_允许() -> None:
    course = Course(name="单节小课", weekday=2, start_period=6, end_period=6)
    assert course.start_period == course.end_period == 6
    assert Course.from_dict(course.to_dict()) == course


# ---------------------------------------------------------------------------
# Homework 校验：异常路径
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("课程ID", "要求"),
    [("", "有要求"), ("   ", "有要求"), ("course-1", ""), ("course-1", "   ")],
)
def test_作业课程ID或要求为空_抛中文ValueError(课程ID: str, 要求: str) -> None:
    with pytest.raises(ValueError):
        Homework(course_id=课程ID, requirement=要求, deadline=datetime(2026, 10, 12, 18, 0))


def test_作业截止时间传入纯date对象_抛中文TypeError() -> None:
    with pytest.raises(TypeError, match="必须是 datetime"):
        Homework(course_id="course-1", requirement="作业要求", deadline=date(2026, 10, 12))


def test_作业截止时间直接构造带时区_被拒() -> None:
    aware = datetime(2026, 10, 12, 18, 0, tzinfo=timezone(timedelta(hours=8)))
    with pytest.raises(ValueError, match="不能带时区"):
        Homework(course_id="course-1", requirement="作业要求", deadline=aware)


def test_作业截止时间from_dict带时区_被拒() -> None:
    data = {
        "id": "hw-1",
        "course_id": "course-1",
        "requirement": "作业要求",
        "deadline": "2026-10-12T18:00:00+08:00",
    }
    with pytest.raises(ValueError, match="不能带时区"):
        Homework.from_dict(data)


def test_作业截止时间为纯日期串_被拒() -> None:
    data = {
        "id": "hw-1",
        "course_id": "course-1",
        "requirement": "作业要求",
        "deadline": "2026-10-12",
    }
    with pytest.raises(ValueError, match="不能只填日期"):
        Homework.from_dict(data)


def test_作业截止时间为无法识别串_抛中文ValueError() -> None:
    data = {
        "id": "hw-1",
        "course_id": "course-1",
        "requirement": "作业要求",
        "deadline": "not-a-date!",
    }
    with pytest.raises(ValueError, match="格式无法识别"):
        Homework.from_dict(data)


def test_作业截止时间_正常YYYY_MM_DD_HH_MM_可解析() -> None:
    data = {
        "id": "hw-1",
        "course_id": "course-1",
        "requirement": "作业要求",
        "deadline": "2026-10-12 18:00",
    }
    homework = Homework.from_dict(data)
    assert homework.deadline == datetime(2026, 10, 12, 18, 0)


# ---------------------------------------------------------------------------
# from_dict 容错：缺键 / 非对象
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("删除的键", ["name", "weekday", "start_period", "end_period"])
def test_课程from_dict_缺少必填键_抛中文ValueError(删除的键: str) -> None:
    data = {
        "name": "测试课",
        "weekday": 0,
        "start_period": 1,
        "end_period": 2,
    }
    del data[删除的键]
    with pytest.raises(ValueError, match="课程数据缺少必填字段"):
        Course.from_dict(data)


@pytest.mark.parametrize("非对象", [[], "课程文本", 123, None])
def test_课程from_dict_非dict_抛中文TypeError(非对象) -> None:
    with pytest.raises(TypeError, match="课程数据必须是 JSON 对象"):
        Course.from_dict(非对象)


@pytest.mark.parametrize("删除的键", ["course_id", "requirement", "deadline"])
def test_作业from_dict_缺少必填键_抛中文ValueError(删除的键: str) -> None:
    data = {
        "course_id": "course-1",
        "requirement": "作业要求",
        "deadline": "2026-10-12 18:00",
    }
    del data[删除的键]
    with pytest.raises(ValueError, match="作业数据缺少必填字段"):
        Homework.from_dict(data)


@pytest.mark.parametrize("非对象", [[], 42, None])
def test_作业from_dict_非dict_抛中文TypeError(非对象) -> None:
    with pytest.raises(TypeError, match="作业数据必须是 JSON 对象"):
        Homework.from_dict(非对象)


def test_作业from_dict_deadline为数字_抛中文TypeError() -> None:
    with pytest.raises(TypeError, match="截止时间必须是 ISO 格式"):
        Homework.from_dict(
            {"course_id": "c1", "requirement": "r", "deadline": 20261012}
        )


# ---------------------------------------------------------------------------
# normalize_weekday
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("取值", "期望"),
    [(0, 0), (6, 6), (3, 3)],
)
def test_normalize_weekday_整数写法(取值: int, 期望: int) -> None:
    assert normalize_weekday(取值) == 期望


@pytest.mark.parametrize(
    ("文本", "期望"),
    [
        ("周一", 0), ("周二", 1), ("周三", 2), ("周四", 3),
        ("周五", 4), ("周六", 5), ("周日", 6),
        ("星期一", 0), ("星期三", 2), ("星期日", 6),
        ("礼拜一", 0), ("礼拜五", 4), ("礼拜天", 6),
        ("周天", 6), ("星期天", 6), ("礼拜日", 6),
    ],
)
def test_normalize_weekday_中文各种写法(文本: str, 期望: int) -> None:
    assert normalize_weekday(文本) == 期望


@pytest.mark.parametrize(
    ("文本", "期望"),
    [("0", 0), ("6", 6), ("  周四  ", 3), ("\t2\n", 2)],
)
def test_normalize_weekday_数字字符串与前后空白(文本: str, 期望: int) -> None:
    assert normalize_weekday(文本) == 期望


@pytest.mark.parametrize("坏取值", [7, -1, "星期八", "8"])
def test_normalize_weekday_非法值抛ValueError(坏取值) -> None:
    with pytest.raises(ValueError):
        normalize_weekday(坏取值)


@pytest.mark.parametrize("坏取值", [3.0, None, [1], object()])
def test_normalize_weekday_类型不支持抛TypeError(坏取值) -> None:
    with pytest.raises(TypeError):
        normalize_weekday(坏取值)
