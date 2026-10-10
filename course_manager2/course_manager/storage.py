# -*- coding: utf-8 -*-
"""JSON 持久化层。

- UTF-8 编码、ensure_ascii=False，保证中文直接可读；
- 存储路径通过函数参数传入，默认常量 DEFAULT_DATA_PATH 可被覆盖，便于测试使用 tmp 目录；
- 保存采用“先写临时文件再替换”的原子写法（临时文件名带 pid+uuid，写后 fsync），
  避免写到一半数据损坏或多进程临时文件冲突；
- 读取时若文件为空 / JSON 损坏 / 非 UTF-8 编码 / 顶层结构被篡改，则把原文件改名备份为
  data.json.corrupt-<时间戳>（同目录），并返回空结构，保证程序可以启动。
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict

#: 默认数据文件路径（位于用户主目录下）；测试时可通过参数覆盖
DEFAULT_DATA_PATH = Path.home() / ".course_manager" / "data.json"

#: 空数据结构
EMPTY_DATA: Dict[str, list] = {"courses": [], "homeworks": []}


def _empty_data() -> Dict[str, list]:
    """返回一份新的空结构（每次新建，避免外部修改共享对象）。"""
    return {"courses": [], "homeworks": []}


def _normalize(data: Any) -> Dict[str, list]:
    """校验并归一化顶层结构，保证返回 {courses: [...], homeworks: [...]}。

    根节点不是 dict、或 courses/homeworks 键不是列表时抛出 ValueError，
    由调用方统一做备份与回退。
    """
    if not isinstance(data, dict):
        raise ValueError("数据文件根节点必须是 JSON 对象")
    courses = data.get("courses", [])
    homeworks = data.get("homeworks", [])
    if not isinstance(courses, list) or not isinstance(homeworks, list):
        raise ValueError("顶层 courses / homeworks 必须是数组")
    return {"courses": courses, "homeworks": homeworks}


def _quarantine(file_path: Path, reason: str) -> "Path | None":
    """把无法使用的数据文件改名备份为 data.json.corrupt-<时间戳>（同目录）。

    返回备份文件路径；备份本身失败时返回 None（不影响主流程回退空结构）。
    """
    timestamp = time.strftime("%Y%m%d%H%M%S")
    backup = file_path.with_name(f"{file_path.name}.corrupt-{timestamp}")
    # 同一秒内连续损坏时，不能覆盖上一份备份，追加短 uuid 保证唯一
    if backup.exists():
        backup = file_path.with_name(
            f"{file_path.name}.corrupt-{timestamp}-{uuid.uuid4().hex[:6]}"
        )
    try:
        file_path.rename(backup)
    except OSError as exc:
        print(
            f"[课程作业管理助手] 数据文件损坏且备份失败：{file_path}（{reason}）：{exc}",
            file=sys.__stderr__,
        )
        return None
    print(
        f"[课程作业管理助手] 数据文件损坏（{reason}），原文件已备份至：{backup}",
        file=sys.__stderr__,
    )
    return backup


def load_data(path: "str | Path" = DEFAULT_DATA_PATH) -> Dict[str, list]:
    """读取数据文件。

    - 文件不存在：返回空结构；
    - 空文件 / JSON 语法损坏 / 非 UTF-8 编码：备份原文件后返回空结构；
    - 根节点不是 dict、顶层 courses/homeworks 类型不对：备份后返回空结构。

    注意：open/read 阶段的 PermissionError 不在此捕获，任其向上抛出。
    """
    file_path = Path(path)
    if not file_path.exists():
        return _empty_data()

    try:
        with file_path.open("r", encoding="utf-8") as f:
            # 空文件同样会抛 json.JSONDecodeError（Expecting value）；
            # 非 UTF-8 字节会在读取解码时抛 UnicodeDecodeError，两者一并捕获
            data = json.load(f)
    except json.JSONDecodeError as exc:
        _quarantine(file_path, f"JSON 解析失败：{exc}")
        return _empty_data()
    except UnicodeDecodeError as exc:
        _quarantine(file_path, f"文件不是合法 UTF-8 编码：{exc}")
        return _empty_data()

    try:
        return _normalize(data)
    except ValueError as exc:
        _quarantine(file_path, str(exc))
        return _empty_data()


def save_data(data: Dict[str, Any], path: "str | Path" = DEFAULT_DATA_PATH) -> None:
    """把数据以 JSON 原子写入文件（UTF-8、ensure_ascii=False、缩进2）。

    临时文件名带 pid+uuid 后缀保证唯一；json.dump 后 flush+fsync 落盘，
    再用 replace 原子替换正式文件；无论成功与否 finally 都清理临时文件。
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(
        f"{file_path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    )
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            # 先刷 Python 缓冲区，再 fsync 强制写入磁盘，防止掉盘丢数据
            f.flush()
            os.fsync(f.fileno())
        # 原子替换，避免写入中断导致数据文件损坏
        tmp_path.replace(file_path)
    finally:
        # replace 成功后临时文件已不存在；失败时负责把残留临时文件清掉
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
