# -*- coding: utf-8 -*-
"""数据模型层：课程（Course）与作业（Homework）。

约束：
- 仅使用 Python 标准库，禁止 import tkinter；
- 字段校验失败时抛出 ValueError（类型错误抛出 TypeError），中文错误信息；
- 提供 to_dict / from_dict，供 JSON 持久化使用。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict

#: 星期显示名，索引 0 表示周一，与 Python 的 datetime.weekday() 保持一致
WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

#: 星期文本的常见中文别名
_WEEKDAY_ALIASES = {
    "周一": 0, "星期一": 0, "礼拜一": 0,
    "周二": 1, "星期二": 1, "礼拜二": 1,
    "周三": 2, "星期三": 2, "礼拜三": 2,
    "周四": 3, "星期四": 3, "礼拜四": 3,
    "周五": 4, "星期五": 4, "礼拜五": 4,
    "周六": 5, "星期六": 5, "礼拜六": 5,
    "周日": 6, "周天": 6, "星期日": 6, "星期天": 6, "礼拜日": 6, "礼拜天": 6,
}


def normalize_weekday(value: Any) -> int:
    """把各种形式的星期取值统一为 0（周一）~6（周日）的整数。

    支持：
    - 0~6 的整数；
    - "周一"~"周日"、"星期一"~"星期日"、"礼拜一"等中文写法；
    - "0"~"6" 的数字字符串。

    无法识别时抛出 ValueError；类型不支持时抛出 TypeError。
    """
    if isinstance(value, bool):
        raise TypeError("星期取值不能是布尔类型")
    if isinstance(value, int):
        if 0 <= value <= 6:
            return value
        raise ValueError("星期必须在 0(周一)~6(周日) 之间")
    if isinstance(value, str):
        text = value.strip()
        if text in _WEEKDAY_ALIASES:
            return _WEEKDAY_ALIASES[text]
        if text.isdigit() and 0 <= int(text) <= 6:
            return int(text)
        raise ValueError(f"无法识别的星期取值：{value!r}")
    raise TypeError(f"星期取值类型不支持：{type(value).__name__}")


def _new_id() -> str:
    """生成一个新的十六进制唯一 ID。"""
    return uuid.uuid4().hex


def _validate_period(value: Any, field_name: str) -> int:
    """校验节次必须是 1~13 之间的整数。"""
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            value = int(str(value).strip())
        except (TypeError, ValueError):
            raise TypeError(f"{field_name}必须是1~13之间的整数")
    if not 1 <= value <= 13:
        raise ValueError(f"{field_name}必须在1~13之间，当前为：{value}")
    return value


@dataclass
class Course:
    """课程数据模型。

    必填：名称 name、星期 weekday（0~6）、起始节次 start_period、结束节次 end_period。
    可选：上课地点 location、授课教师 teacher。
    id 未指定时自动生成。
    """

    name: str
    weekday: int
    start_period: int
    end_period: int
    location: str = ""
    teacher: str = ""
    id: str = field(default_factory=_new_id)

    def __post_init__(self) -> None:
        # 课程名称必填
        if not isinstance(self.name, str):
            raise TypeError("课程名称必须是文本")
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("课程名称不能为空")

        # 星期校验（支持中文）
        self.weekday = normalize_weekday(self.weekday)

        # 节次校验：1<=起<=止<=13
        self.start_period = _validate_period(self.start_period, "起始节次")
        self.end_period = _validate_period(self.end_period, "结束节次")
        if self.start_period > self.end_period:
            raise ValueError("起始节次不能大于结束节次")

        # 可选字段统一去除首尾空白
        if self.location is None:
            self.location = ""
        if self.teacher is None:
            self.teacher = ""
        if not isinstance(self.location, str) or not isinstance(self.teacher, str):
            raise TypeError("上课地点和授课教师必须是文本")
        self.location = self.location.strip()
        self.teacher = self.teacher.strip()

    def to_dict(self) -> Dict[str, Any]:
        """序列化为可写入 JSON 的字典。"""
        return {
            "id": self.id,
            "name": self.name,
            "weekday": self.weekday,
            "start_period": self.start_period,
            "end_period": self.end_period,
            "location": self.location,
            "teacher": self.teacher,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Course":
        """从字典反序列化；id 原样保留（不在此静默替换）。

        id 处理约定（BUG-001 修复）：
        - 数据中的 id 原样带入模型：缺失键得到 None、空串仍为 ""、
          整数等非字符串值也先原样保留；
        - 合法性（必须为“非空 str”）统一交给
          CourseService._repair_ids 判定，无效 id 由其重分配并置
          dirty=True，在 load() 中 save() 落盘，从而保证自愈可持久化、
          二次加载幂等；
        - 直接调用构造器 Course(name=..., ...) 不传 id 的路径不受影响，
          仍由 dataclass 的 default_factory=_new_id 自动生成 uuid。

        其他容错约定：
        - data 不是 dict 时抛出中文 TypeError；
        - 缺少必填键时把 KeyError 转为中文 ValueError；
        - 字段取值/类型不合法时由构造校验抛出中文 ValueError/TypeError。
        """
        if not isinstance(data, dict):
            raise TypeError("课程数据必须是 JSON 对象")
        try:
            name = data["name"]
            weekday = data["weekday"]
            start_period = data["start_period"]
            end_period = data["end_period"]
        except KeyError as exc:
            # 缺键统一转成中文 ValueError，便于上层逐条容错时记录与提示
            raise ValueError(f"课程数据缺少必填字段：{exc.args[0]}")
        return cls(
            # 显式传入原始 id（可能是 None/""/整数），绝不触发 default_factory，
            # 这样 service 层的 id 自愈逻辑才能检测到问题并落盘
            id=data.get("id"),
            name=name,
            weekday=weekday,
            start_period=start_period,
            end_period=end_period,
            location=data.get("location", ""),
            teacher=data.get("teacher", ""),
        )


@dataclass
class Homework:
    """作业数据模型。

    必填：所属课程 course_id、作业要求 requirement、提交截止时间 deadline（datetime）。
    id 未指定时自动生成。
    """

    course_id: str
    requirement: str
    deadline: datetime
    id: str = field(default_factory=_new_id)

    def __post_init__(self) -> None:
        # 作业必须关联一门课程
        if not isinstance(self.course_id, str):
            raise TypeError("作业所属课程ID必须是文本")
        self.course_id = self.course_id.strip()
        if not self.course_id:
            raise ValueError("作业必须关联一门课程")

        # 作业要求必填
        if not isinstance(self.requirement, str):
            raise TypeError("作业要求必须是文本")
        self.requirement = self.requirement.strip()
        if not self.requirement:
            raise ValueError("作业要求不能为空")

        # 截止时间必须是 datetime（不接受仅 date，避免时分缺失）
        if not isinstance(self.deadline, datetime):
            raise TypeError("提交截止时间必须是 datetime 类型")
        # 拒绝带时区的截止时间：全程序统一使用本地时间（naive datetime），
        # 否则与 datetime.now()（naive）做时间差会抛 TypeError
        if self.deadline.tzinfo is not None:
            raise ValueError("截止时间不能带时区，请使用本地时间")

    def to_dict(self) -> Dict[str, Any]:
        """序列化为可写入 JSON 的字典，deadline 以 ISO 字符串保存。"""
        return {
            "id": self.id,
            "course_id": self.course_id,
            "requirement": self.requirement,
            "deadline": self.deadline.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Homework":
        """从字典反序列化；deadline 支持 ISO 格式字符串或 datetime；id 原样保留。

        id 处理约定与 Course.from_dict 一致（BUG-001 修复）：原始 id
        （缺失键 None、空串、整数等）原样带入模型，合法性统一由
        CourseService._repair_ids 判定并重分配落盘；直接构造不传 id
        时仍由 default_factory=_new_id 自动生成 uuid。

        容错约定：
        - data 不是 dict 时抛出中文 TypeError；
        - 缺少必填键时把 KeyError 转为中文 ValueError；
        - 仅 10 字符的纯日期串（YYYY-MM-DD、无时分）抛中文 ValueError，
          要求提供具体时间；
        - 无法识别的时间串抛中文 ValueError；
        - 带时区的截止时间由构造校验统一拒绝。
        """
        if not isinstance(data, dict):
            raise TypeError("作业数据必须是 JSON 对象")
        try:
            raw_deadline = data["deadline"]
            course_id = data["course_id"]
            requirement = data["requirement"]
        except KeyError as exc:
            raise ValueError(f"作业数据缺少必填字段：{exc.args[0]}")

        if isinstance(raw_deadline, datetime):
            deadline = raw_deadline
        elif isinstance(raw_deadline, str):
            text = raw_deadline.strip()
            # 纯日期串恰好 10 字符（YYYY-MM-DD）且确为合法日期：缺少时分必须拒绝；
            # 先校验确实是日期，避免把同样 10 字符的其他坏串误报为“只填日期”
            if len(text) == 10:
                try:
                    date.fromisoformat(text)
                except ValueError:
                    pass
                else:
                    raise ValueError(
                        "截止时间不能只填日期，请提供具体的时分，例如：2026-10-12 18:00"
                    )
            try:
                deadline = datetime.fromisoformat(text)
            except ValueError:
                raise ValueError(
                    f"截止时间格式无法识别：{raw_deadline!r}，"
                    "请使用 YYYY-MM-DD HH:MM 格式"
                )
        else:
            raise TypeError("截止时间必须是 ISO 格式的时间字符串")

        return cls(
            # 与 Course.from_dict 同理：原始 id（None/""/整数等）原样带入，
            # 交由 CourseService._repair_ids 统一判定“非空 str 才合法”，
            # 避免在反序列化阶段静默替换导致自愈不落盘
            id=data.get("id"),
            course_id=course_id,
            requirement=requirement,
            deadline=deadline,
        )
