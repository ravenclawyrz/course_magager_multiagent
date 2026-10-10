# -*- coding: utf-8 -*-
"""业务服务层测试：增删改查、冲突检测、级联删除、id 自愈、作业归属。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from course_manager import storage
from course_manager.service import ConflictError, CourseService


# ---------------------------------------------------------------------------
# 课程增删改查
# ---------------------------------------------------------------------------
def test_添加课程_返回课程并可按ID查询(服务: CourseService) -> None:
    course = 服务.add_course("高等数学", 0, 1, 2, "教一楼", "张老师")
    assert isinstance(course.id, str) and course.id
    assert 服务.get_course(course.id) is course
    assert 服务.get_course("不存在") is None


def test_课程列表_按星期与起始节次排序(服务: CourseService) -> None:
    c1 = 服务.add_course("周三课", 2, 5, 6)
    c2 = 服务.add_course("周一课", 0, 3, 4)
    c3 = 服务.add_course("周一早课", 0, 1, 2)
    assert 服务.list_courses() == [c3, c2, c1]


def test_修改课程_保留ID并更新字段(服务: CourseService) -> None:
    course = 服务.add_course("旧课名", 0, 1, 2, "旧地点", "旧教师")
    updated = 服务.update_course(course.id, "新课名", 3, 5, 6, "新地点", "新教师")
    assert updated.id == course.id
    assert updated.name == "新课名"
    assert updated.weekday == 3
    assert (updated.start_period, updated.end_period) == (5, 6)
    assert (updated.location, updated.teacher) == ("新地点", "新教师")
    # 旧对象字段不应残留：课程总数仍为 1
    assert len(服务.courses) == 1


def test_修改不存在的课程_抛中文ValueError(服务: CourseService) -> None:
    with pytest.raises(ValueError, match="要修改的课程不存在"):
        服务.update_course("missing", "名", 0, 1, 2)


def test_删除不存在的课程_抛中文ValueError(服务: CourseService) -> None:
    with pytest.raises(ValueError, match="要删除的课程不存在"):
        服务.delete_course("missing")


# ---------------------------------------------------------------------------
# 作业增删改查
# ---------------------------------------------------------------------------
def test_添加作业_课程不存在时_抛中文ValueError(服务: CourseService) -> None:
    with pytest.raises(ValueError, match="作业所属课程不存在"):
        服务.add_homework("无此课程", "作业要求", datetime(2026, 10, 12, 18, 0))


def test_作业列表_可按课程筛选并按截止时间升序(服务: CourseService) -> None:
    甲 = 服务.add_course("课程甲", 0, 1, 2)
    乙 = 服务.add_course("课程乙", 1, 1, 2)
    h1 = 服务.add_homework(甲.id, "甲作业2", datetime(2026, 10, 20, 18, 0))
    h2 = 服务.add_homework(甲.id, "甲作业1", datetime(2026, 10, 15, 12, 0))
    h3 = 服务.add_homework(乙.id, "乙作业", datetime(2026, 10, 14, 9, 0))

    assert [h.id for h in 服务.list_homeworks(甲.id)] == [h2.id, h1.id]
    assert [h.id for h in 服务.list_homeworks(乙.id)] == [h3.id]
    # 不筛选时返回全部，仍按截止时间排序
    assert [h.id for h in 服务.list_homeworks()] == [h3.id, h2.id, h1.id]


def test_修改作业_更新要求与截止时间(服务: CourseService) -> None:
    course = 服务.add_course("课程甲", 0, 1, 2)
    homework = 服务.add_homework(course.id, "旧要求", datetime(2026, 10, 12, 18, 0))

    updated = 服务.update_homework(
        homework.id,
        requirement="新要求",
        deadline=datetime(2026, 10, 20, 9, 30),
    )
    assert updated.id == homework.id
    assert updated.course_id == course.id
    assert updated.requirement == "新要求"
    assert updated.deadline == datetime(2026, 10, 20, 9, 30)


def test_修改作业_未传字段保持原值(服务: CourseService) -> None:
    course = 服务.add_course("课程甲", 0, 1, 2)
    homework = 服务.add_homework(course.id, "保持不变", datetime(2026, 10, 12, 18, 0))
    updated = 服务.update_homework(homework.id, requirement="只改要求")
    assert updated.requirement == "只改要求"
    assert updated.deadline == datetime(2026, 10, 12, 18, 0)
    assert updated.course_id == course.id


def test_修改不存在的作业_抛中文ValueError(服务: CourseService) -> None:
    with pytest.raises(ValueError, match="要修改的作业不存在"):
        服务.update_homework("missing", requirement="x")


def test_删除作业_不存在抛错(服务: CourseService) -> None:
    with pytest.raises(ValueError, match="要删除的作业不存在"):
        服务.delete_homework("missing")


def test_删除作业(服务: CourseService) -> None:
    course = 服务.add_course("课程甲", 0, 1, 2)
    homework = 服务.add_homework(course.id, "待删除", datetime(2026, 10, 12, 18, 0))
    服务.delete_homework(homework.id)
    assert 服务.get_homework(homework.id) is None
    assert 服务.list_homeworks(course.id) == []


# ---------------------------------------------------------------------------
# 冲突检测
# ---------------------------------------------------------------------------
def test_同星期区间重叠_抛ConflictError且数据未写入(
    服务: CourseService, 数据文件: Path
) -> None:
    服务.add_course("已存在课", 0, 1, 2)
    with pytest.raises(ConflictError) as 捕获:
        服务.add_course("冲突课", 0, 2, 3)
    # 冲突对象被携带在异常中
    assert [c.name for c in 捕获.value.conflicts] == ["已存在课"]
    # 内存中只有第一门课
    assert len(服务.courses) == 1
    # 落盘文件同样只有第一门课（异常路径未保存）
    另一服务 = CourseService(数据文件)
    assert [c.name for c in 另一服务.courses] == ["已存在课"]
    assert len(另一服务.homeworks) == 0


def test_冲突异常信息包含课程名称与时间(服务: CourseService) -> None:
    服务.add_course("操作系统", 2, 3, 4)
    with pytest.raises(ConflictError, match="操作系统"):
        服务.add_course("编译原理", 2, 4, 5)


def test_force为True_同星期重叠也可保存(服务: CourseService) -> None:
    服务.add_course("已存在课", 0, 1, 2)
    新课 = 服务.add_course("冲突课", 0, 2, 3, force=True)
    assert 新课 is not None
    assert len(服务.courses) == 2


def test_区间相邻_第6节与第7节_不报冲突(服务: CourseService) -> None:
    # 第6节 12:55-14:00，第7节 14:00-14:45，首尾相接不重叠
    服务.add_course("午休前课", 0, 6, 6)
    相邻课 = 服务.add_course("午后首课", 0, 7, 7)
    assert 相邻课.name == "午后首课"
    assert len(服务.courses) == 2


def test_同星期不重叠区间_不报冲突(服务: CourseService) -> None:
    服务.add_course("上午课", 0, 1, 2)
    服务.add_course("下午课", 0, 3, 4)
    assert len(服务.courses) == 2


def test_不同星期_相同节次_不报冲突(服务: CourseService) -> None:
    服务.add_course("周一课", 0, 1, 2)
    服务.add_course("周二课", 1, 1, 2)
    assert len(服务.courses) == 2


def test_find_conflicts_跨星期查询结果为空(服务: CourseService) -> None:
    服务.add_course("周一课", 0, 1, 2)
    assert 服务.find_conflicts(3, 1, 2) == []
    assert len(服务.find_conflicts(0, 1, 2)) == 1


def test_修改课程_与其他课程冲突_被拦截(服务: CourseService) -> None:
    甲 = 服务.add_course("课程甲", 0, 1, 2)
    乙 = 服务.add_course("课程乙", 2, 5, 6)
    with pytest.raises(ConflictError):
        服务.update_course(乙.id, "课程乙改", 0, 2, 3)
    # 修改未生效
    assert 服务.get_course(乙.id).weekday == 2
    assert 服务.get_course(甲.id) is not None


def test_修改课程_排除自身_保持原时间不产生自冲突(服务: CourseService) -> None:
    甲 = 服务.add_course("课程甲", 0, 1, 2)
    updated = 服务.update_course(甲.id, "课程甲改名", 0, 1, 2, location="新地点")
    assert updated.id == 甲.id
    assert updated.name == "课程甲改名"
    assert updated.location == "新地点"


def test_修改课程_冲突时force可保存(服务: CourseService) -> None:
    甲 = 服务.add_course("课程甲", 0, 1, 2)
    乙 = 服务.add_course("课程乙", 2, 5, 6)
    updated = 服务.update_course(乙.id, "课程乙改", 0, 2, 3, force=True)
    assert updated.weekday == 0
    assert len(服务.courses) == 2
    assert 服务.get_course(甲.id) is not None


# ---------------------------------------------------------------------------
# 级联删除
# ---------------------------------------------------------------------------
def test_删除课程_级联删除其全部作业_其他课程作业保留(
    服务: CourseService, 数据文件: Path
) -> None:
    甲 = 服务.add_course("课程甲", 0, 1, 2)
    乙 = 服务.add_course("课程乙", 1, 1, 2)
    服务.add_homework(甲.id, "甲作业1", datetime(2026, 10, 12, 18, 0))
    服务.add_homework(甲.id, "甲作业2", datetime(2026, 10, 13, 18, 0))
    乙作业 = 服务.add_homework(乙.id, "乙作业", datetime(2026, 10, 14, 18, 0))

    删除作业数 = 服务.delete_course(甲.id)
    assert 删除作业数 == 2
    assert 服务.list_homeworks(甲.id) == []
    assert [h.id for h in 服务.list_homeworks(乙.id)] == [乙作业.id]

    重启服务 = CourseService(数据文件)
    assert [c.name for c in 重启服务.courses] == ["课程乙"]
    assert [h.requirement for h in 重启服务.homeworks] == ["乙作业"]


def test_删除无作业课程_返回0(服务: CourseService) -> None:
    甲 = 服务.add_course("无作业课", 0, 1, 2)
    assert 服务.delete_course(甲.id) == 0


# ---------------------------------------------------------------------------
# id 自愈
# ---------------------------------------------------------------------------
def test_id自愈_整数id_重分配落盘_二次加载幂等(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    storage.save_data(
        {
            "courses": [
                {"id": 123, "name": "整数ID课", "weekday": 0,
                 "start_period": 1, "end_period": 2, "location": "", "teacher": ""}
            ],
            "homeworks": [],
        },
        path,
    )

    s1 = CourseService(path)
    新id = s1.courses[0].id
    assert isinstance(新id, str) and 新id
    assert 新id != "123"

    落盘 = json.loads(path.read_text(encoding="utf-8"))
    assert 落盘["courses"][0]["id"] == 新id

    s2 = CourseService(path)
    assert s2.courses[0].id == 新id


def test_id自愈_重复id_重分配落盘_二次加载幂等(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    storage.save_data(
        {
            "courses": [
                {"id": "dup", "name": "重复课甲", "weekday": 0,
                 "start_period": 1, "end_period": 2, "location": "", "teacher": ""},
                {"id": "dup", "name": "重复课乙", "weekday": 2,
                 "start_period": 3, "end_period": 4, "location": "", "teacher": ""},
            ],
            "homeworks": [],
        },
        path,
    )

    s1 = CourseService(path)
    ids = [c.id for c in s1.courses]
    assert len(set(ids)) == 2
    assert "dup" in ids

    落盘ids = [c["id"] for c in json.loads(path.read_text(encoding="utf-8"))["courses"]]
    assert 落盘ids == ids

    s2 = CourseService(path)
    assert [c.id for c in s2.courses] == ids


def test_id自愈_空串id_重分配落盘_二次加载幂等(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    storage.save_data(
        {
            "courses": [
                {"id": "", "name": "空串ID课", "weekday": 0,
                 "start_period": 1, "end_period": 2, "location": "", "teacher": ""}
            ],
            "homeworks": [],
        },
        path,
    )

    s1 = CourseService(path)
    新id = s1.courses[0].id
    assert isinstance(新id, str) and 新id

    落盘 = json.loads(path.read_text(encoding="utf-8"))
    assert 落盘["courses"][0]["id"] == 新id, "空串 id 应在加载后完成自愈并落盘"

    s2 = CourseService(path)
    assert s2.courses[0].id == 新id, "二次加载应幂等，id 不应再次变化"


def test_id自愈_课程与作业之间id重复也重分配(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    storage.save_data(
        {
            "courses": [
                {"id": "shared", "name": "课程", "weekday": 0,
                 "start_period": 1, "end_period": 2, "location": "", "teacher": ""}
            ],
            "homeworks": [
                {"id": "shared", "course_id": "shared", "requirement": "作业",
                 "deadline": "2026-10-12 18:00"}
            ],
        },
        path,
    )
    s1 = CourseService(path)
    ids = [s1.courses[0].id, s1.homeworks[0].id]
    assert len(set(ids)) == 2
    s2 = CourseService(path)
    assert [s2.courses[0].id, s2.homeworks[0].id] == ids


# ---------------------------------------------------------------------------
# update_homework 归属与重名课程隔离
# ---------------------------------------------------------------------------
def test_修改作业_课程不存在_报错且归属不变(
    服务: CourseService, 数据文件: Path
) -> None:
    course = 服务.add_course("课程甲", 0, 1, 2)
    homework = 服务.add_homework(course.id, "作业", datetime(2026, 10, 12, 18, 0))

    with pytest.raises(ValueError, match="作业所属课程不存在"):
        服务.update_homework(homework.id, course_id="幽灵课程")

    # 归属保持不变（内存 + 落盘）
    assert 服务.get_homework(homework.id).course_id == course.id
    重启 = CourseService(数据文件)
    assert 重启.homeworks[0].course_id == course.id
    assert 重启.homeworks[0].requirement == "作业"


def test_重名两门课_作业互不串改(服务: CourseService) -> None:
    甲 = 服务.add_course("程序设计", 0, 1, 2)
    乙 = 服务.add_course("程序设计", 2, 3, 4)
    作业甲 = 服务.add_homework(甲.id, "甲的作业", datetime(2026, 10, 12, 18, 0))
    作业乙 = 服务.add_homework(乙.id, "乙的作业", datetime(2026, 10, 13, 18, 0))

    服务.update_homework(作业甲.id, requirement="甲的作业已改")
    assert 服务.get_homework(作业乙.id).requirement == "乙的作业"
    assert 服务.get_homework(作业乙.id).course_id == 乙.id
    assert 服务.get_homework(作业甲.id).course_id == 甲.id

    # 将甲的作业改派到乙课程，乙原有作业不受影响
    服务.update_homework(作业甲.id, course_id=乙.id)
    assert 服务.list_homeworks(甲.id) == []
    assert {h.id for h in 服务.list_homeworks(乙.id)} == {作业甲.id, 作业乙.id}
