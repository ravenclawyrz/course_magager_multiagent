# -*- coding: utf-8 -*-
"""tkinter 图形界面层。

界面用 ttk.Notebook 组织四个标签页：课程管理、作业管理、课表展示、今日提醒。

架构约束：
- 仅本模块（gui 子包）允许 import tkinter；
- import 时不创建 Tk 根窗口、不弹对话框；根窗口在 CourseManagerApp 实例化时创建，
  而该类只在 main.py 的 main() 中实例化，并用 if __name__ == "__main__" 保护；
- 当前时间与数据路径均可注入（clock / data_path），便于无界面单元测试。
"""
from __future__ import annotations

import sys
import tkinter as tk
from datetime import datetime
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from ..models import WEEKDAYS, Course, Homework
from ..periods import MAX_PERIOD, PERIODS, format_period_range
from ..reminders import (
    BEFORE_CLASS_MINUTES,
    ReminderEngine,
    format_duration,
)
from ..service import ConflictError, CourseService

#: 截止时间输入/显示格式
DATETIME_PATTERN = "%Y-%m-%d %H:%M"

#: 作业筛选下拉框中的“全部课程”项
ALL_COURSES = "全部课程"

#: 自动检查间隔（毫秒），需求规定 30 秒
CHECK_INTERVAL_MS = 30_000

# ---------------- 颜色 ----------------
COLOR_OVERDUE = "#C0392B"   # 红色：逾期 / 进行中
COLOR_SOON = "#D35400"      # 橙色：临近截止 / 30分钟内上课
COLOR_ENDED = "#888888"     # 灰色：已结束
COLOR_TODAY_HEADER = "#F7C948"  # 当天表头背景
COLOR_TODAY_BG = "#FFF7CC"      # 当天空白区域背景
COLOR_TODAY_CARD = "#FFFDF0"    # 当天课程卡片背景
COLOR_NORMAL_CARD = "#FFFFFF"

#: 中文字体候选，优先尝试微软雅黑，再回退常见中文字体，最后使用系统默认
FONT_CANDIDATES = [
    "Microsoft YaHei",
    "微软雅黑",
    "Noto Sans CJK SC",
    "Noto Sans CJK",
    "WenQuanYi Micro Hei",
    "WenQuanYi Zen Hei",
    "SimHei",
    "Arial Unicode MS",
]


class CourseManagerApp:
    """课程作业管理助手主窗口。

    参数：
        data_path: JSON 数据文件路径，None 时使用默认路径；测试可传 tmp 目录；
        clock: 返回当前 datetime 的可调用对象，None 时使用 datetime.now。
    """

    def __init__(
        self,
        data_path: "str | None" = None,
        clock: "Optional[Callable[[], datetime]]" = None,
    ):
        # 业务服务与提醒引擎（均不依赖 tkinter）
        self.service = CourseService(data_path)
        self.engine = ReminderEngine(clock=clock)

        # 当前在列表中选中的事项 ID
        self.selected_course_id: Optional[str] = None
        self.selected_homework_id: Optional[str] = None

        # 程序选中列表项时用于抑制“回填表单”动作的标志
        self._syncing = False

        # 作业页课程下拉“展示串 -> 课程ID”映射，下拉框只认 ID 不认名称，
        # 避免重名课程导致作业被改派；refresh_all 前先置空
        self._course_label_map: Dict[str, str] = {}

        # 唯一的 Tk 根窗口：只能在这里创建
        self.root = tk.Tk()
        self.root.title("课程作业管理助手")
        self.root.geometry("1020x740")
        self.root.minsize(880, 620)

        self.font_family: Optional[str] = None
        self.font_bold: Optional[tkfont.Font] = None
        self._configure_font()

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=6)

        self._build_course_tab()
        self._build_homework_tab()
        self._build_schedule_tab()
        self._build_today_tab()

        self.refresh_all()

        # 启动后立即检查一次；之后每 30 秒自动检查
        self.root.after(300, self._tick)

    # ==================================================================
    # 基础设置
    # ==================================================================
    def _configure_font(self) -> None:
        """挑选支持中文的字体并设置为 Tk 默认字体，保证 Linux 下中文不乱码。"""
        available = set(tkfont.families(self.root))
        chosen = next((name for name in FONT_CANDIDATES if name in available), None)
        if chosen is not None:
            self.font_family = chosen
            # 修改 Tk 内置命名字体，使所有默认控件统一使用中文字体
            for font_name in (
                "TkDefaultFont",
                "TkTextFont",
                "TkMenuFont",
                "TkHeadingFont",
                "TkTooltipFont",
            ):
                try:
                    tkfont.nametofont(font_name).configure(family=chosen)
                except tk.TclError:
                    continue
            self.font_bold = tkfont.Font(family=chosen, size=10, weight="bold")
        else:
            # 回退：直接使用系统默认字体
            self.font_family = None
            self.font_bold = tkfont.Font(weight="bold")

        style = ttk.Style(self.root)
        style.configure("Treeview", rowheight=26)
        style.configure("Treeview.Heading", font=self.font_bold)
        style.configure("TNotebook.Tab", padding=(14, 6))

    def run(self) -> None:
        """进入 Tk 主事件循环。"""
        self.root.mainloop()

    def destroy(self) -> None:
        """关闭主窗口（供测试调用）。"""
        self.root.destroy()

    @staticmethod
    def _show_persist_error(err: Exception, fail_title: str) -> None:
        """保存 / 删除类操作失败时的统一提示。

        - OSError（文件权限、磁盘满、IO 错误等）：固定友好文案，
          不把底层 errno 抛给用户；
        - ValueError / TypeError：展示模型层给出的中文错误信息。

        参数：
            err: 捕获到的异常；
            fail_title: 非 OSError 时弹窗标题（如“输入有误”“删除失败”）。
        """
        if isinstance(err, OSError):
            messagebox.showerror("保存失败", "数据保存失败，请检查文件权限或磁盘空间")
        else:
            messagebox.showerror(fail_title, str(err))

    # ==================================================================
    # 标签页一：课程管理
    # ==================================================================
    def _build_course_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="课程管理")

        # ---------- 表单区 ----------
        form = ttk.LabelFrame(tab, text="课程信息（带 * 为必填）")
        form.pack(fill="x", padx=8, pady=(8, 4))
        for col in range(5):
            form.columnconfigure(col, weight=1 if col in (1, 4) else 0)

        self.course_name_var = tk.StringVar()
        self.course_weekday_var = tk.StringVar(value=WEEKDAYS[0])
        self.course_start_var = tk.StringVar(value="1")
        self.course_end_var = tk.StringVar(value="2")
        self.course_location_var = tk.StringVar()
        self.course_teacher_var = tk.StringVar()

        # 节次直接取自 periods 模块常量，不再经过薄包装函数
        period_values = [str(i) for i in sorted(PERIODS)]

        # 第一行：名称、星期
        ttk.Label(form, text="课程名称*：").grid(row=0, column=0, sticky="e", padx=4, pady=6)
        ttk.Entry(form, textvariable=self.course_name_var).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        ttk.Label(form, text="星期*：").grid(row=0, column=2, sticky="e", padx=4)
        ttk.Combobox(
            form,
            textvariable=self.course_weekday_var,
            values=list(WEEKDAYS),
            state="readonly",
            width=8,
        ).grid(row=0, column=3, sticky="w", padx=4)

        # 第二行：节次区间
        ttk.Label(form, text="上课节次*：第").grid(row=1, column=0, sticky="e", padx=4, pady=6)
        period_row = ttk.Frame(form)
        period_row.grid(row=1, column=1, columnspan=3, sticky="w", padx=4)
        ttk.Combobox(
            period_row, textvariable=self.course_start_var, values=period_values,
            state="readonly", width=4,
        ).pack(side="left")
        ttk.Label(period_row, text="节  到  第").pack(side="left", padx=6)
        ttk.Combobox(
            period_row, textvariable=self.course_end_var, values=period_values,
            state="readonly", width=4,
        ).pack(side="left")
        ttk.Label(period_row, text="节（共13节）").pack(side="left", padx=6)

        # 第三行：地点、教师
        ttk.Label(form, text="上课地点：").grid(row=2, column=0, sticky="e", padx=4, pady=6)
        ttk.Entry(form, textvariable=self.course_location_var).grid(
            row=2, column=1, sticky="ew", padx=4
        )
        ttk.Label(form, text="授课教师：").grid(row=2, column=2, sticky="e", padx=4)
        ttk.Entry(form, textvariable=self.course_teacher_var).grid(
            row=2, column=3, sticky="ew", padx=4
        )

        # ---------- 按钮区 ----------
        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", padx=8, pady=4)
        ttk.Button(buttons, text="添加课程", command=self._add_course).pack(side="left", padx=3)
        ttk.Button(buttons, text="保存修改", command=self._update_selected_course).pack(side="left", padx=3)
        ttk.Button(buttons, text="删除选中课程", command=self._delete_selected_course).pack(side="left", padx=3)
        ttk.Button(buttons, text="清空表单", command=self._clear_course_form).pack(side="left", padx=3)

        # ---------- 课程列表 ----------
        table_frame = ttk.Frame(tab)
        table_frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        columns = ("name", "weekday", "periods", "location", "teacher")
        self.course_tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        self.course_tree.heading("name", text="课程名称")
        self.course_tree.heading("weekday", text="星期")
        self.course_tree.heading("periods", text="节次区间")
        self.course_tree.heading("location", text="上课地点")
        self.course_tree.heading("teacher", text="授课教师")
        self.course_tree.column("name", width=180, anchor="w")
        self.course_tree.column("weekday", width=70, anchor="center")
        self.course_tree.column("periods", width=200, anchor="center")
        self.course_tree.column("location", width=150, anchor="w")
        self.course_tree.column("teacher", width=120, anchor="w")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.course_tree.yview)
        self.course_tree.configure(yscrollcommand=scrollbar.set)
        self.course_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.course_tree.bind("<<TreeviewSelect>>", self._on_course_select)

    def _clear_course_form(self) -> None:
        """清空课程表单为默认值。"""
        self.course_name_var.set("")
        self.course_weekday_var.set(WEEKDAYS[0])
        self.course_start_var.set("1")
        self.course_end_var.set("2")
        self.course_location_var.set("")
        self.course_teacher_var.set("")

    def _on_course_select(self, _event=None) -> None:
        """选中课程后把信息回填到表单。"""
        if self._syncing:
            return
        selected = self.course_tree.selection()
        if not selected:
            return
        course = self.service.get_course(selected[0])
        if course is None:
            return
        self.selected_course_id = course.id
        self.course_name_var.set(course.name)
        self.course_weekday_var.set(WEEKDAYS[course.weekday])
        self.course_start_var.set(str(course.start_period))
        self.course_end_var.set(str(course.end_period))
        self.course_location_var.set(course.location)
        self.course_teacher_var.set(course.teacher)

    def _parse_course_form(self) -> Dict:
        """读取并校验课程表单，返回可直接传给 service 的字段字典。"""
        name = self.course_name_var.get().strip()
        if not name:
            raise ValueError("请填写课程名称")
        weekday_text = self.course_weekday_var.get()
        if weekday_text not in WEEKDAYS:
            raise ValueError("请选择上课星期")
        weekday = WEEKDAYS.index(weekday_text)
        try:
            start = int(self.course_start_var.get())
            end = int(self.course_end_var.get())
        except ValueError:
            raise ValueError("节次必须是 1~13 的整数")
        if not (1 <= start <= MAX_PERIOD) or not (1 <= end <= MAX_PERIOD):
            raise ValueError(f"节次必须在 1~{MAX_PERIOD} 之间")
        if start > end:
            raise ValueError("起始节次不能大于结束节次")
        return {
            "name": name,
            "weekday": weekday,
            "start_period": start,
            "end_period": end,
            "location": self.course_location_var.get().strip(),
            "teacher": self.course_teacher_var.get().strip(),
        }

    def _add_course(self) -> None:
        """“添加课程”按钮：校验后保存，冲突时弹确认框允许强制保存。"""
        try:
            data = self._parse_course_form()
            self.service.add_course(**data)
        except ConflictError as exc:
            if messagebox.askyesno("时间冲突", f"{exc}\n\n是否仍要保存该课程？"):
                try:
                    self.service.add_course(**data, force=True)
                except (ValueError, TypeError, OSError) as err:
                    self._show_persist_error(err, "添加失败")
                    return
            else:
                return
        except (ValueError, TypeError, OSError) as err:
            self._show_persist_error(err, "输入有误")
            return
        self._clear_course_form()
        self.selected_course_id = None
        self.refresh_all()

    def _update_selected_course(self) -> None:
        """“保存修改”按钮。"""
        course_id = self.selected_course_id
        if not course_id or self.service.get_course(course_id) is None:
            messagebox.showinfo("提示", "请先在下方列表中选择要修改的课程")
            return
        try:
            data = self._parse_course_form()
            self.service.update_course(course_id, **data)
        except ConflictError as exc:
            if messagebox.askyesno("时间冲突", f"{exc}\n\n是否仍要保存修改？"):
                try:
                    self.service.update_course(course_id, **data, force=True)
                except (ValueError, TypeError, OSError) as err:
                    self._show_persist_error(err, "修改失败")
                    return
            else:
                return
        except (ValueError, TypeError, OSError) as err:
            self._show_persist_error(err, "输入有误")
            return
        self._clear_course_form()
        self.selected_course_id = None
        self.refresh_all()

    def _delete_selected_course(self) -> None:
        """“删除选中课程”按钮：确认后级联删除作业。"""
        course_id = self.selected_course_id
        course = self.service.get_course(course_id) if course_id else None
        if course is None:
            messagebox.showinfo("提示", "请先在下方列表中选择要删除的课程")
            return
        homework_count = len(self.service.list_homeworks(course.id))
        extra = f"\n该课程下的 {homework_count} 项作业也将一并删除。" if homework_count else ""
        if not messagebox.askyesno("确认删除", f"确定要删除课程《{course.name}》吗？{extra}"):
            return
        try:
            self.service.delete_course(course.id)
        except (ValueError, TypeError, OSError) as err:
            self._show_persist_error(err, "删除失败")
            return
        self._clear_course_form()
        self.selected_course_id = None
        self.refresh_all()

    def _refresh_course_tree(self) -> None:
        """刷新课程列表，并尽量保持原来的选中状态。"""
        self._syncing = True
        try:
            self.course_tree.delete(*self.course_tree.get_children())
            for course in self.service.list_courses():
                self.course_tree.insert(
                    "",
                    "end",
                    iid=course.id,
                    values=(
                        course.name,
                        WEEKDAYS[course.weekday],
                        format_period_range(course.start_period, course.end_period),
                        course.location,
                        course.teacher,
                    ),
                )
            if self.selected_course_id and self.service.get_course(self.selected_course_id):
                self.course_tree.selection_set(self.selected_course_id)
                self.course_tree.focus(self.selected_course_id)
            else:
                self.selected_course_id = None
        finally:
            self._syncing = False

    # ==================================================================
    # 标签页二：作业管理
    # ==================================================================
    def _build_homework_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="作业管理")

        # ---------- 筛选区 ----------
        filter_row = ttk.Frame(tab)
        filter_row.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(filter_row, text="按课程筛选：").pack(side="left")
        self.hw_filter_var = tk.StringVar(value=ALL_COURSES)
        self.hw_filter_combo = ttk.Combobox(
            filter_row, textvariable=self.hw_filter_var, state="readonly", width=30
        )
        self.hw_filter_combo.pack(side="left", padx=4)
        self.hw_filter_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_homework_tree())

        # ---------- 表单区 ----------
        form = ttk.LabelFrame(tab, text="作业信息")
        form.pack(fill="x", padx=8, pady=4)
        form.columnconfigure(1, weight=1)

        self.hw_course_var = tk.StringVar()
        self.hw_requirement_var = tk.StringVar()
        self.hw_deadline_var = tk.StringVar()

        ttk.Label(form, text="所属课程*：").grid(row=0, column=0, sticky="e", padx=4, pady=6)
        # 只读下拉：只能从消歧展示串中选择，展示串经映射还原为 course_id，
        # 不再通过课程名称反查，杜绝重名课程改派作业
        self.hw_course_combo = ttk.Combobox(
            form, textvariable=self.hw_course_var, width=38, state="readonly"
        )
        self.hw_course_combo.grid(row=0, column=1, sticky="w", padx=4)

        ttk.Label(form, text="作业要求*：").grid(row=1, column=0, sticky="e", padx=4, pady=6)
        ttk.Entry(form, textvariable=self.hw_requirement_var).grid(
            row=1, column=1, columnspan=3, sticky="ew", padx=4
        )

        ttk.Label(form, text="截止时间*：").grid(row=2, column=0, sticky="e", padx=4, pady=6)
        ttk.Entry(form, textvariable=self.hw_deadline_var, width=24).grid(
            row=2, column=1, sticky="w", padx=4
        )
        ttk.Label(form, text="格式：YYYY-MM-DD HH:MM，如 2026-10-12 18:00").grid(
            row=2, column=2, sticky="w", padx=4
        )

        # ---------- 按钮区 ----------
        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", padx=8, pady=4)
        ttk.Button(buttons, text="添加作业", command=self._add_homework).pack(side="left", padx=3)
        ttk.Button(buttons, text="保存修改", command=self._update_selected_homework).pack(side="left", padx=3)
        ttk.Button(buttons, text="删除选中作业", command=self._delete_selected_homework).pack(side="left", padx=3)
        ttk.Button(buttons, text="清空表单", command=self._clear_homework_form).pack(side="left", padx=3)

        # ---------- 作业列表 ----------
        table_frame = ttk.Frame(tab)
        table_frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        columns = ("course", "requirement", "deadline", "status")
        self.homework_tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        self.homework_tree.heading("course", text="所属课程")
        self.homework_tree.heading("requirement", text="作业要求")
        self.homework_tree.heading("deadline", text="截止时间")
        self.homework_tree.heading("status", text="状态")
        self.homework_tree.column("course", width=160, anchor="w")
        self.homework_tree.column("requirement", width=340, anchor="w")
        self.homework_tree.column("deadline", width=150, anchor="center")
        self.homework_tree.column("status", width=180, anchor="center")
        # 橙色=临近截止，红色=已逾期
        self.homework_tree.tag_configure("due_soon", foreground=COLOR_SOON)
        self.homework_tree.tag_configure("overdue", foreground=COLOR_OVERDUE)

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.homework_tree.yview)
        self.homework_tree.configure(yscrollcommand=scrollbar.set)
        self.homework_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.homework_tree.bind("<<TreeviewSelect>>", self._on_homework_select)

    @staticmethod
    def _format_course_base_label(course: Course) -> str:
        """生成课程消歧展示串主体：“名称（周X 第a-b节）”。

        例如两门同名课程分别展示为：
        "高数（周一 第1-2节）"、"高数（周三 第3-4节）"。
        """
        if course.start_period == course.end_period:
            period_text = f"第{course.start_period}节"
        else:
            period_text = f"第{course.start_period}-{course.end_period}节"
        return f"{course.name}（{WEEKDAYS[course.weekday]} {period_text}）"

    def _course_options(self) -> List[Tuple[str, str]]:
        """返回 (展示串, course_id) 列表，并保证展示串全局唯一。

        名称+星期+节次完全相同导致主体串重复时，后出现者末尾追加短 id
        （如 #ab12）；若短 id 仍碰撞，则不断换用新的 uuid4 随机后缀
        （先 4 位、再 6 位）直到未被占用，保证下拉项、映射 key 全局唯一。
        """
        options: List[Tuple[str, str]] = []
        used = set()
        for course in self.service.list_courses():
            base = self._format_course_base_label(course)
            label = base
            if label in used:
                # 主体串重复：先按课程 id 前 4 位消歧
                label = f"{base} #{course.id[:4]}"
            # 回查唯一性：id 前缀碰撞（或与其它已用标签撞）时换随机后缀，
            # 4 位仍撞则升到 6 位，循环直到拿到全局唯一的展示串
            suffix_len = 4
            while label in used:
                label = f"{base} #{uuid4().hex[:suffix_len]}"
                if suffix_len < 6:
                    suffix_len = 6
            used.add(label)
            options.append((label, course.id))
        return options

    def _label_for_course_id(self, course_id: str) -> str:
        """按 course_id 反查当前展示串（回填编辑表单用），找不到返回空串。"""
        for label, cid in self._course_label_map.items():
            if cid == course_id:
                return label
        return ""

    def _refresh_course_combos(self) -> None:
        """刷新作业页的课程下拉框（筛选框 + 表单框）及展示串->ID 映射。

        两个下拉框的值均为消歧展示串，内部一律通过 self._course_label_map
        还原为 course_id；若原选中项对应课程已不存在则复位。
        """
        options = self._course_options()
        labels = [label for label, _cid in options]
        self._course_label_map = {label: cid for label, cid in options}

        # 筛选下拉：含“全部课程”
        filter_values = [ALL_COURSES] + labels
        self.hw_filter_combo.configure(values=filter_values)
        if self.hw_filter_var.get() not in filter_values:
            self.hw_filter_var.set(ALL_COURSES)

        # 表单下拉：仅具体课程；保留仍然有效的选中项
        self.hw_course_combo.configure(values=labels)
        if self.hw_course_var.get() not in labels:
            self.hw_course_var.set("")

    def _clear_homework_form(self) -> None:
        """清空作业表单。"""
        self.hw_course_var.set("")
        self.hw_requirement_var.set("")
        self.hw_deadline_var.set("")

    def _on_homework_select(self, _event=None) -> None:
        """选中作业后回填表单。"""
        if self._syncing:
            return
        selected = self.homework_tree.selection()
        if not selected:
            return
        homework = self.service.get_homework(selected[0])
        if homework is None:
            return
        self.selected_homework_id = homework.id
        # 回填时按 course_id 定位消歧展示串，不使用课程名称
        self.hw_course_var.set(self._label_for_course_id(homework.course_id))
        self.hw_requirement_var.set(homework.requirement)
        self.hw_deadline_var.set(homework.deadline.strftime(DATETIME_PATTERN))

    def _parse_homework_form(self) -> Dict:
        """读取并校验作业表单，返回字段字典。

        所属课程通过消歧展示串在映射中还原 course_id，全程不使用名称反查。
        """
        label = self.hw_course_var.get().strip()
        course_id = self._course_label_map.get(label)
        if not label or course_id is None:
            raise ValueError("请选择作业所属课程")
        requirement = self.hw_requirement_var.get().strip()
        if not requirement:
            raise ValueError("请填写作业要求")
        deadline_text = self.hw_deadline_var.get().strip()
        if not deadline_text:
            raise ValueError("请填写提交截止时间")
        try:
            deadline = datetime.strptime(deadline_text, DATETIME_PATTERN)
        except ValueError:
            raise ValueError("截止时间格式应为 YYYY-MM-DD HH:MM，例如 2026-10-12 18:00")
        return {
            "course_id": course_id,
            "requirement": requirement,
            "deadline": deadline,
        }

    def _add_homework(self) -> None:
        """“添加作业”按钮。"""
        try:
            data = self._parse_homework_form()
            self.service.add_homework(**data)
        except (ValueError, TypeError, OSError) as err:
            self._show_persist_error(err, "输入有误")
            return
        self._clear_homework_form()
        self.selected_homework_id = None
        self.refresh_all()

    def _update_selected_homework(self) -> None:
        """“保存修改”按钮。"""
        homework_id = self.selected_homework_id
        if not homework_id or self.service.get_homework(homework_id) is None:
            messagebox.showinfo("提示", "请先在下方列表中选择要修改的作业")
            return
        try:
            data = self._parse_homework_form()
            self.service.update_homework(homework_id, **data)
        except (ValueError, TypeError, OSError) as err:
            self._show_persist_error(err, "输入有误")
            return
        self._clear_homework_form()
        self.selected_homework_id = None
        self.refresh_all()

    def _delete_selected_homework(self) -> None:
        """“删除选中作业”按钮。"""
        homework_id = self.selected_homework_id
        homework = self.service.get_homework(homework_id) if homework_id else None
        if homework is None:
            messagebox.showinfo("提示", "请先在下方列表中选择要删除的作业")
            return
        if not messagebox.askyesno("确认删除", f"确定要删除该作业吗？\n{homework.requirement}"):
            return
        try:
            self.service.delete_homework(homework.id)
        except (ValueError, TypeError, OSError) as err:
            self._show_persist_error(err, "删除失败")
            return
        self._clear_homework_form()
        self.selected_homework_id = None
        self.refresh_all()

    def _refresh_homework_tree(self) -> None:
        """刷新作业列表，应用筛选条件与橙/红颜色，并保持选中状态。"""
        filter_label = self.hw_filter_var.get()
        course_id = None
        # 按课程筛选同样以展示串 -> course_id 映射定位，不做名称反查
        if filter_label and filter_label != ALL_COURSES:
            course_id = self._course_label_map.get(filter_label)

        self._syncing = True
        try:
            self.homework_tree.delete(*self.homework_tree.get_children())
            for homework in self.service.list_homeworks(course_id):
                status_info = self.engine.homework_status(homework)
                status = status_info["status"]
                if status == "overdue":
                    status_text = f"已逾期 {format_duration(-status_info['remaining'])}"
                else:
                    status_text = f"剩余 {format_duration(status_info['remaining'])}"
                course = self.service.get_course(homework.course_id)
                self.homework_tree.insert(
                    "",
                    "end",
                    iid=homework.id,
                    values=(
                        course.name if course else "（课程已删除）",
                        homework.requirement,
                        homework.deadline.strftime(DATETIME_PATTERN),
                        status_text,
                    ),
                    tags=(status,) if status in ("due_soon", "overdue") else (),
                )
            if self.selected_homework_id and self.service.get_homework(self.selected_homework_id):
                self.homework_tree.selection_set(self.selected_homework_id)
                self.homework_tree.focus(self.selected_homework_id)
            else:
                self.selected_homework_id = None
        finally:
            self._syncing = False

    # ==================================================================
    # 标签页三：课表展示
    # ==================================================================
    def _build_schedule_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="课表展示")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(toolbar, text="一周课表（当天所在列整列高亮）").pack(side="left")
        ttk.Button(toolbar, text="刷新课表", command=self._refresh_schedule).pack(side="right")

        canvas = tk.Canvas(tab, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        self.schedule_inner = ttk.Frame(canvas)
        window_item = canvas.create_window((0, 0), window=self.schedule_inner, anchor="nw")

        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        scrollbar.pack(side="right", fill="y", pady=(0, 8))

        # 让内部框架宽度跟随画布，列宽才能均分
        canvas.bind(
            "<Configure>", lambda e: canvas.itemconfig(window_item, width=e.width)
        )
        self.schedule_inner.bind(
            "<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        self._enable_mousewheel(canvas)

        for col in range(7):
            self.schedule_inner.columnconfigure(col, weight=1, uniform="weekday")
        # 课程卡片所在行（row=1）纵向拉伸，使当天列高亮背景填满整个纵向区域
        self.schedule_inner.rowconfigure(1, weight=1)

    def _refresh_schedule(self) -> None:
        """重建课表：七列表头 + 当天高亮 + 课程卡片。"""
        for child in self.schedule_inner.winfo_children():
            child.destroy()

        today_index = self.engine.now().weekday()

        # 按星期分组课程
        grouped: List[List[Course]] = [[] for _ in range(7)]
        for course in self.service.list_courses():
            grouped[course.weekday].append(course)

        for col in range(7):
            is_today = col == today_index
            header_bg = COLOR_TODAY_HEADER if is_today else "#E8E8E8"
            column_bg = COLOR_TODAY_BG if is_today else "#F5F5F5"

            # 表头（含日期）
            header_text = WEEKDAYS[col] + ("（今天）" if is_today else "")
            tk.Label(
                self.schedule_inner,
                text=header_text,
                bg=header_bg,
                font=self.font_bold,
                padx=6,
                pady=6,
                relief="solid",
                bd=1,
            ).grid(row=0, column=col, sticky="nsew", padx=1, pady=(1, 2))

            # 该列容器：整列着色实现“整列高亮”
            day_column = tk.Frame(self.schedule_inner, bg=column_bg)
            day_column.grid(row=1, column=col, sticky="nsew", padx=1)

            if not grouped[col]:
                tk.Label(
                    day_column,
                    text="无课程",
                    bg=column_bg,
                    fg="#999999",
                    pady=8,
                ).pack(fill="x", padx=4, pady=4)
                continue

            card_bg = COLOR_TODAY_CARD if is_today else COLOR_NORMAL_CARD
            for course in grouped[col]:
                self._build_course_card(day_column, course, card_bg)

    def _build_course_card(self, parent: tk.Widget, course: Course, card_bg: str) -> None:
        """在课表中构建一张课程卡片：名称、节次区间、地点、教师。"""
        card = tk.Frame(parent, bg=card_bg, bd=1, relief="solid", padx=6, pady=4)
        card.pack(fill="x", padx=4, pady=4)

        tk.Label(
            card, text=course.name, bg=card_bg, font=self.font_bold,
            anchor="w", justify="left", wraplength=120,
        ).pack(fill="x")
        tk.Label(
            card,
            text=format_period_range(course.start_period, course.end_period),
            bg=card_bg, anchor="w", justify="left",
        ).pack(fill="x")
        if course.location:
            tk.Label(card, text=f"地点：{course.location}", bg=card_bg,
                     anchor="w", justify="left", wraplength=120).pack(fill="x")
        if course.teacher:
            tk.Label(card, text=f"教师：{course.teacher}", bg=card_bg,
                     anchor="w", justify="left", wraplength=120).pack(fill="x")

    # ==================================================================
    # 标签页四：今日提醒
    # ==================================================================
    def _build_today_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="今日提醒")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", padx=8, pady=(8, 4))
        self.today_summary_var = tk.StringVar()
        ttk.Label(toolbar, textvariable=self.today_summary_var,
                  font=self.font_bold).pack(side="left")
        ttk.Button(toolbar, text="立即刷新", command=self._refresh_today).pack(side="right")

        canvas = tk.Canvas(tab, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        self.today_inner = ttk.Frame(canvas)
        window_item = canvas.create_window((0, 0), window=self.today_inner, anchor="nw")

        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        scrollbar.pack(side="right", fill="y", pady=(0, 8))
        canvas.bind(
            "<Configure>", lambda e: canvas.itemconfig(window_item, width=e.width)
        )
        self.today_inner.bind(
            "<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        self._enable_mousewheel(canvas)

    def _add_section_title(self, text: str) -> None:
        """在“今日提醒”页添加一个分节标题。"""
        tk.Label(
            self.today_inner, text=text, font=self.font_bold,
            anchor="w", bg="#F0F0F0", padx=8, pady=5,
        ).pack(fill="x", padx=4, pady=(8, 4))

    def _add_status_line(self, text: str, color: str) -> None:
        """在“今日提醒”页添加一整行状态文本。"""
        tk.Label(
            self.today_inner, text=text, fg=color, anchor="w",
            justify="left", padx=8, pady=3, wraplength=900,
        ).pack(fill="x", padx=4)

    def _refresh_today(self) -> None:
        """重建“今日提醒”页内容。"""
        for child in self.today_inner.winfo_children():
            child.destroy()

        now = self.engine.now()
        self.today_summary_var.set(
            f"今天是 {now.strftime('%Y年%m月%d日')} {WEEKDAYS[now.weekday()]}　"
            f"更新时间 {now.strftime('%H:%M:%S')}"
        )

        # ---------- 今日课程 ----------
        self._add_section_title("一、今日课程状态")
        today_courses = [
            c for c in self.service.list_courses() if c.weekday == now.weekday()
        ]
        if not today_courses:
            self._add_status_line("今天没有课程安排。", COLOR_ENDED)
        for course in today_courses:
            status = self.engine.course_status(course, now)
            extras = []
            if course.location:
                extras.append(f"地点：{course.location}")
            if course.teacher:
                extras.append(f"教师：{course.teacher}")
            extra_text = ("　" + "，".join(extras)) if extras else ""

            if status["status"] == "upcoming":
                minutes = status["minutes"]
                state_text = f"距开始还有 {minutes} 分钟"
                color = COLOR_SOON if minutes <= BEFORE_CLASS_MINUTES else "#333333"
            elif status["status"] == "ongoing":
                state_text = "上课中（进行中）"
                color = COLOR_OVERDUE
            else:
                state_text = "已结束"
                color = COLOR_ENDED

            self._add_status_line(
                f"《{course.name}》　{format_period_range(course.start_period, course.end_period)}"
                f"{extra_text}　=> {state_text}",
                color,
            )

        # ---------- 作业截止状态 ----------
        self._add_section_title("二、作业截止状态（全部作业）")
        homeworks = self.service.list_homeworks()
        if not homeworks:
            self._add_status_line("暂无作业。", COLOR_ENDED)
        for homework in homeworks:
            status = self.engine.homework_status(homework, now)
            course = self.service.get_course(homework.course_id)
            course_name = course.name if course else "未知课程"
            deadline_text = status["deadline"].strftime(DATETIME_PATTERN)
            if status["status"] == "overdue":
                state = f"已逾期 {format_duration(-status['remaining'])}"
                color = COLOR_OVERDUE
            elif status["status"] == "due_soon":
                state = f"剩余 {format_duration(status['remaining'])}（不足24小时）"
                color = COLOR_SOON
            else:
                state = f"剩余 {format_duration(status['remaining'])}"
                color = "#333333"
            self._add_status_line(
                f"[{deadline_text}] 【{course_name}】{homework.requirement}　=> {state}",
                color,
            )

    # ==================================================================
    # 智能提醒轮询
    # ==================================================================
    def _show_due_reminders(self) -> None:
        """检查当前应触发的提醒并聚合弹窗（已做当天去重）。"""
        reminders = self.engine.check(self.service.courses, self.service.homeworks)
        if not reminders:
            return
        content = "\n\n".join(
            f"{index + 1}. {item.title}：{item.message}"
            for index, item in enumerate(reminders)
        )
        messagebox.showwarning("智能提醒", content, parent=self.root)

    def _tick(self) -> None:
        """每 30 秒执行一次：弹窗提醒 + 刷新动态页面。

        防御性约定：任何一步抛异常都只记录到 stderr，且无论是否异常，
        finally 中都重新 after(30s) 排程，保证 30 秒轮询链永久不中断。
        """
        try:
            self._show_due_reminders()
            self._refresh_schedule()
            self._refresh_today()
            self._refresh_homework_tree()
        except Exception as exc:
            # 不用默认 stderr（可能被 GUI 重定向），写解释器原始 stderr
            print(f"[课程作业管理助手] 自动检查发生异常：{exc}", file=sys.__stderr__)
        finally:
            # 无论成功或失败都安排下一次轮询；但窗口已销毁后 after 会抛
            # TclError 形成关停噪声。winfo_exists() 返回 0 时不再排程；
            # 若根窗口连同 Tcl 解释器一起被销毁，winfo_exists 自身也会抛
            # TclError，此时同样视为窗口已不存在，静默停止轮询
            try:
                window_exists = bool(self.root.winfo_exists())
            except tk.TclError:
                window_exists = False
            if window_exists:
                self.root.after(CHECK_INTERVAL_MS, self._tick)

    # ==================================================================
    # 统一刷新 / 工具
    # ==================================================================
    def refresh_all(self) -> None:
        """数据发生变化后统一刷新全部标签页。"""
        self._refresh_course_tree()
        self._refresh_course_combos()
        self._refresh_homework_tree()
        self._refresh_schedule()
        self._refresh_today()

    @staticmethod
    def _enable_mousewheel(canvas: tk.Canvas) -> None:
        """为画布启用鼠标滚轮（兼容 Linux 的 Button-4/5 与通用 MouseWheel）。"""

        def on_enter(_event):
            canvas.bind_all(
                "<Button-4>", lambda _e: canvas.yview_scroll(-1, "units")
            )
            canvas.bind_all(
                "<Button-5>", lambda _e: canvas.yview_scroll(1, "units")
            )
            canvas.bind_all(
                "<MouseWheel>",
                lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"),
            )

        def on_leave(_event):
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", on_enter)
        canvas.bind("<Leave>", on_leave)
