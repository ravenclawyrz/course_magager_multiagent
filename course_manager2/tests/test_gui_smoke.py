# -*- coding: utf-8 -*-
"""GUI 冒烟测试：仅在 DISPLAY 可用且 Tk 可初始化时执行。

约定：
- data_path 一律注入 tmp_path；
- 时间通过固定 clock 注入；
- 每个用例结束后必须销毁窗口；
- messagebox 全部 monkeypatch，杜绝弹窗阻塞。
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

if not os.environ.get("DISPLAY"):
    pytest.skip("当前环境无 DISPLAY，跳过 GUI 冒烟测试", allow_module_level=True)

try:
    _探针 = tk.Tk()
    _探针.destroy()
except tk.TclError as _异常:  # pragma: no cover - 取决于运行环境
    pytest.skip(f"Tk 无法初始化：{_异常}", allow_module_level=True)

from course_manager.gui import app as gui_module  # noqa: E402
from course_manager.gui.app import CourseManagerApp  # noqa: E402


固定时刻 = datetime(2026, 10, 12, 9, 30, 0)  # 周一 09:30


@pytest.fixture
def 主窗口(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # 屏蔽所有可能的弹窗
    monkeypatch.setattr(gui_module.messagebox, "showwarning", lambda *a, **k: None)
    monkeypatch.setattr(gui_module.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(gui_module.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(gui_module.messagebox, "askyesno", lambda *a, **k: False)

    app = CourseManagerApp(
        data_path=tmp_path / "data.json",
        clock=lambda: 固定时刻,
    )
    try:
        yield app
    finally:
        # 用例结束必须销毁窗口，防止残留
        try:
            if app.root.winfo_exists():
                app.root.destroy()
        except tk.TclError:
            pass


def test_实例化窗口_root_update不报错(主窗口: CourseManagerApp) -> None:
    主窗口.root.update()
    主窗口.root.update_idletasks()
    主窗口.root.update()


def test_四个标签页标题_与需求一致(主窗口: CourseManagerApp) -> None:
    texts = [主窗口.notebook.tab(tab, "text") for tab in 主窗口.notebook.tabs()]
    assert texts == ["课程管理", "作业管理", "课表展示", "今日提醒"]


def test_窗口标题正确(主窗口: CourseManagerApp) -> None:
    assert 主窗口.root.title() == "课程作业管理助手"


def test_注入课程与临近作业后_全部刷新不报错(主窗口: CourseManagerApp) -> None:
    course = 主窗口.service.add_course(
        "软件工程",
        固定时刻.weekday(),
        3,
        4,
        "教一楼101",
        "王老师",
    )
    # 距截止不足 24 小时的作业（当天 18:00）
    主窗口.service.add_homework(
        course.id,
        "提交需求规格说明书",
        datetime(2026, 10, 12, 18, 0, 0),
    )
    # 再添加一门其他天的课程，覆盖课表多列渲染
    周三课 = 主窗口.service.add_course("高等数学", 2, 1, 2, "教二楼", "李老师")
    主窗口.service.add_homework(
        周三课.id, "完成习题", datetime(2026, 10, 15, 12, 0, 0)
    )

    主窗口.refresh_all()
    主窗口.root.update()

    # 作业树中应存在 2 条记录
    assert len(主窗口.homework_tree.get_children()) == 2
    # 课表七个列头均已构建
    assert len(主窗口.schedule_inner.winfo_children()) >= 7


def test_切换四个标签页_不报错(主窗口: CourseManagerApp) -> None:
    for tab in 主窗口.notebook.tabs():
        主窗口.notebook.select(tab)
        主窗口.root.update()
