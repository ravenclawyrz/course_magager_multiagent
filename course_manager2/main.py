# -*- coding: utf-8 -*-
"""程序入口。

启动命令：python3 main.py

Tk 根窗口只在 main() 内实例化主窗口对象时创建，并用 if __name__ == "__main__" 保护，
保证 import 本模块时不会弹出任何窗口或对话框。
"""
from __future__ import annotations

from course_manager.gui.app import CourseManagerApp


def main() -> None:
    """创建并运行课程作业管理助手。"""
    app = CourseManagerApp()
    app.run()


if __name__ == "__main__":
    main()
