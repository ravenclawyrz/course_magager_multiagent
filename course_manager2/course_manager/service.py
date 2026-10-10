# -*- coding: utf-8 -*-
"""业务服务层。

职责：
- 课程 / 作业的增删改查；
- 课程时间冲突检测（同一星期、节次区间重叠）；
- 删除课程时级联删除其作业；
- 从 JSON 文件加载、保存数据。

本模块不依赖 tkinter；冲突通过 ConflictError 异常告知调用方（GUI 自行弹确认框，
用户确认后以 force=True 再次调用即可继续保存）。
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Course, Homework, WEEKDAYS, normalize_weekday
from .periods import format_period_range
from . import storage


class ConflictError(ValueError):
    """课程时间冲突异常，conflicts 属性携带冲突的已有课程列表。"""

    def __init__(self, conflicts: List[Course], message: str = "课程时间冲突"):
        self.conflicts: List[Course] = list(conflicts)
        desc = "；".join(
            f"《{c.name}》（{WEEKDAYS[c.weekday]} {format_period_range(c.start_period, c.end_period)}）"
            for c in self.conflicts
        )
        super().__init__(f"{message}：{desc}")


class CourseService:
    """课程与作业的业务服务对象。

    参数：
        data_path: JSON 数据文件路径，默认 storage.DEFAULT_DATA_PATH；测试可传 tmp 目录路径。
    """

    def __init__(self, data_path: "str | Path | None" = None):
        self.data_path = Path(data_path) if data_path is not None else storage.DEFAULT_DATA_PATH
        self.courses: List[Course] = []
        self.homeworks: List[Homework] = []
        self.load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def load(self) -> None:
        """从 JSON 文件重新载入课程与作业（逐条容错 + id 自愈）。

        - 单条课程/作业反序列化失败（任何异常）时跳过该条并记录到 stderr，
          不会因为一条坏记录废掉整个库；
        - id 必须是非空 str，且课程与作业之间不得重复；
          无效/重复 id 用 uuid4().hex 重新分配；
        - 一旦发生 id 重分配，立即保存一次，使数据文件完成自愈。
        """
        data = storage.load_data(self.data_path)

        courses: List[Course] = []
        for item in data["courses"]:
            try:
                courses.append(Course.from_dict(item))
            except Exception as exc:
                # 单条坏记录仅跳过，不影响其他课程加载
                print(
                    f"[课程作业管理助手] 跳过损坏的课程记录：{item!r}；原因：{exc}",
                    file=sys.__stderr__,
                )

        homeworks: List[Homework] = []
        for item in data["homeworks"]:
            try:
                homeworks.append(Homework.from_dict(item))
            except Exception as exc:
                print(
                    f"[课程作业管理助手] 跳过损坏的作业记录：{item!r}；原因：{exc}",
                    file=sys.__stderr__,
                )

        # id 校验与修复（非空 str + 全局唯一），返回是否发生过重分配
        dirty = self._repair_ids(courses, homeworks)

        self.courses = courses
        self.homeworks = homeworks

        if dirty:
            try:
                # 重分配后落盘一次，后续重启即读到干净数据
                self.save()
            except OSError as exc:
                print(
                    f"[课程作业管理助手] 修复 id 后保存失败：{exc}",
                    file=sys.__stderr__,
                )

    @staticmethod
    def _repair_ids(courses: List[Course], homeworks: List[Homework]) -> bool:
        """校验并修复课程/作业的 id。

        规则：id 必须为非空 str；所有课程、作业共享一个唯一命名空间，
        无效或重复时用 uuid4().hex 重新分配。返回是否发生过重分配。
        """
        seen = set()
        dirty = False
        for obj in list(courses) + list(homeworks):
            if not isinstance(obj.id, str) or not obj.id.strip():
                obj.id = uuid.uuid4().hex
                dirty = True
            if obj.id in seen:
                obj.id = uuid.uuid4().hex
                dirty = True
            seen.add(obj.id)
        return dirty

    def save(self) -> None:
        """把当前课程与作业写入 JSON 文件。"""
        storage.save_data(self.to_dict(), self.data_path)

    def to_dict(self) -> Dict[str, Any]:
        """导出为可序列化字典。"""
        return {
            "courses": [c.to_dict() for c in self.courses],
            "homeworks": [h.to_dict() for h in self.homeworks],
        }

    # ------------------------------------------------------------------
    # 课程查询 / 冲突检测
    # ------------------------------------------------------------------
    def list_courses(self) -> List[Course]:
        """返回全部课程，按星期、起始节次排序。"""
        return sorted(self.courses, key=lambda c: (c.weekday, c.start_period, c.end_period))

    def get_course(self, course_id: str) -> Optional[Course]:
        """按 ID 获取课程，不存在返回 None。"""
        for course in self.courses:
            if course.id == course_id:
                return course
        return None

    def find_conflicts(
        self,
        weekday: Any,
        start_period: int,
        end_period: int,
        exclude_id: Optional[str] = None,
    ) -> List[Course]:
        """查找与给定时间冲突的课程。

        冲突定义：同一星期且节次区间重叠
        （已有.起 <= 新.止 且 新.起 <= 已有.止）。
        exclude_id 用于修改课程时排除自身。
        """
        weekday = normalize_weekday(weekday)
        return [
            c
            for c in self.courses
            if c.id != exclude_id
            and c.weekday == weekday
            and c.start_period <= end_period
            and start_period <= c.end_period
        ]

    # ------------------------------------------------------------------
    # 课程增 / 改 / 删
    # ------------------------------------------------------------------
    def add_course(
        self,
        name: str,
        weekday: Any,
        start_period: int,
        end_period: int,
        location: str = "",
        teacher: str = "",
        force: bool = False,
    ) -> Course:
        """添加课程。

        存在冲突且 force=False 时抛出 ConflictError（此时尚未写入任何数据）；
        force=True 表示用户已知晓冲突，仍允许保存。
        """
        course = Course(
            name=name,
            weekday=weekday,
            start_period=start_period,
            end_period=end_period,
            location=location,
            teacher=teacher,
        )
        conflicts = self.find_conflicts(course.weekday, course.start_period, course.end_period)
        if conflicts and not force:
            raise ConflictError(conflicts)
        self.courses.append(course)
        self.save()
        return course

    def update_course(
        self,
        course_id: str,
        name: str,
        weekday: Any,
        start_period: int,
        end_period: int,
        location: str = "",
        teacher: str = "",
        force: bool = False,
    ) -> Course:
        """修改指定课程（保留原 ID）。冲突规则与 add_course 相同。"""
        old = self.get_course(course_id)
        if old is None:
            raise ValueError("要修改的课程不存在")

        updated = Course(
            id=old.id,
            name=name,
            weekday=weekday,
            start_period=start_period,
            end_period=end_period,
            location=location,
            teacher=teacher,
        )
        conflicts = self.find_conflicts(
            updated.weekday,
            updated.start_period,
            updated.end_period,
            exclude_id=updated.id,
        )
        if conflicts and not force:
            raise ConflictError(conflicts)

        index = self.courses.index(old)
        self.courses[index] = updated
        self.save()
        return updated

    def delete_course(self, course_id: str) -> int:
        """删除课程，并级联删除该课程下的全部作业。

        返回被一起删除的作业数量；课程不存在时抛出 ValueError。
        """
        course = self.get_course(course_id)
        if course is None:
            raise ValueError("要删除的课程不存在")
        self.courses.remove(course)
        removed_homeworks = sum(1 for h in self.homeworks if h.course_id == course_id)
        self.homeworks = [h for h in self.homeworks if h.course_id != course_id]
        self.save()
        return removed_homeworks

    # ------------------------------------------------------------------
    # 作业增 / 改 / 删 / 查
    # ------------------------------------------------------------------
    def add_homework(self, course_id: str, requirement: str, deadline: Any) -> Homework:
        """为某课程添加作业。课程不存在时抛出 ValueError。"""
        if self.get_course(course_id) is None:
            raise ValueError("作业所属课程不存在")
        homework = Homework(course_id=course_id, requirement=requirement, deadline=deadline)
        self.homeworks.append(homework)
        self.save()
        return homework

    def update_homework(
        self,
        homework_id: str,
        requirement: Optional[str] = None,
        deadline: Any = None,
        course_id: Optional[str] = None,
    ) -> Homework:
        """修改作业。未传入的字段保持原值。"""
        old = self.get_homework(homework_id)
        if old is None:
            raise ValueError("要修改的作业不存在")

        new_course_id = old.course_id if course_id is None else course_id
        if self.get_course(new_course_id) is None:
            raise ValueError("作业所属课程不存在")

        updated = Homework(
            id=old.id,
            course_id=new_course_id,
            requirement=old.requirement if requirement is None else requirement,
            deadline=old.deadline if deadline is None else deadline,
        )
        index = self.homeworks.index(old)
        self.homeworks[index] = updated
        self.save()
        return updated

    def delete_homework(self, homework_id: str) -> None:
        """删除作业；不存在时抛出 ValueError。"""
        homework = self.get_homework(homework_id)
        if homework is None:
            raise ValueError("要删除的作业不存在")
        self.homeworks.remove(homework)
        self.save()

    def get_homework(self, homework_id: str) -> Optional[Homework]:
        """按 ID 获取作业，不存在返回 None。"""
        for homework in self.homeworks:
            if homework.id == homework_id:
                return homework
        return None

    def list_homeworks(self, course_id: Optional[str] = None) -> List[Homework]:
        """列出作业，可按课程筛选；默认按截止时间升序排列。"""
        items = self.homeworks
        if course_id is not None:
            items = [h for h in items if h.course_id == course_id]
        return sorted(items, key=lambda h: (h.deadline, h.id))
