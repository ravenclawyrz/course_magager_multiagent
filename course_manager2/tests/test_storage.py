# -*- coding: utf-8 -*-
"""JSON 持久化层测试：往返一致、中文明文、损坏回退备份、临时文件清理。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from course_manager import storage
from course_manager.storage import EMPTY_DATA, load_data, save_data


def _一份含中文的数据() -> dict:
    return {
        "courses": [
            {
                "id": "c001",
                "name": "高等数学",
                "weekday": 0,
                "start_period": 1,
                "end_period": 2,
                "location": "第一教学楼302",
                "teacher": "张教授",
            }
        ],
        "homeworks": [
            {
                "id": "h001",
                "course_id": "c001",
                "requirement": "完成极限章节习题",
                "deadline": "2026-10-12 18:00",
            }
        ],
    }


def test_文件不存在时_返回空结构(tmp_path: Path) -> None:
    assert load_data(tmp_path / "not_exists.json") == EMPTY_DATA


def test_正常保存再加载_数据完全一致(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    data = _一份含中文的数据()
    save_data(data, path)
    assert load_data(path) == data


def test_JSON明文存储中文_字节中直接含中文且不转义(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    save_data(_一份含中文的数据(), path)
    raw = path.read_bytes()
    # ensure_ascii=False：UTF-8 中文原文直接出现在文件中
    assert "高等数学".encode("utf-8") in raw
    assert "第一教学楼302".encode("utf-8") in raw
    assert "完成极限章节习题".encode("utf-8") in raw
    # 不应出现 \\uXXXX 形式的 ASCII 转义
    assert b"\\u" not in raw
    # 文件本身应可被 UTF-8 正常解码
    raw.decode("utf-8")


@pytest.mark.parametrize(
    "场景",
    [
        "空文件",
        "损坏JSON",
        "根节点为数组",
        "非UTF8字节",
    ],
)
def test_四类损坏文件_均回退空结构并备份原文件(tmp_path: Path, 场景: str) -> None:
    path = tmp_path / "data.json"
    if 场景 == "空文件":
        path.write_bytes(b"")
    elif 场景 == "损坏JSON":
        path.write_text('{"courses": [, }', encoding="utf-8")
    elif 场景 == "根节点为数组":
        path.write_text("[]", encoding="utf-8")
    elif 场景 == "非UTF8字节":
        path.write_bytes(b"\xff\xfe\x00\x80not-utf8")
    else:  # pragma: no cover - 参数穷举保护
        raise AssertionError(场景)

    result = load_data(path)
    # 统一回退为空结构
    assert result == {"courses": [], "homeworks": []}

    目录文件 = {p.name for p in tmp_path.iterdir()}
    # 原文件已不在
    assert "data.json" not in 目录文件
    # 且被备份为 data.json.corrupt-*
    备份 = [name for name in 目录文件 if name.startswith("data.json.corrupt-")]
    assert len(备份) == 1, f"场景 {场景} 应恰好产生一份备份，实际：{目录文件}"


def test_空对象缺少顶层键时_按空列表处理(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_text("{}", encoding="utf-8")  # 空对象：缺键时取默认空列表，属正常
    assert load_data(path) == {"courses": [], "homeworks": []}


def test_顶层courses不是数组_备份并回退(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_text('{"courses": "不是数组", "homeworks": []}', encoding="utf-8")
    assert load_data(path) == {"courses": [], "homeworks": []}
    目录文件 = {p.name for p in tmp_path.iterdir()}
    assert "data.json" not in 目录文件
    assert any(n.startswith("data.json.corrupt-") for n in 目录文件)


def test_保存后临时文件不残留_只留正式文件(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    save_data(_一份含中文的数据(), path)
    残留临时文件 = list(tmp_path.glob("*.tmp.*"))
    assert 残留临时文件 == []
    assert path.exists()
    # 文件内容为合法 JSON
    assert json.loads(path.read_text(encoding="utf-8")) == _一份含中文的数据()


def test_重复保存_始终无临时文件残留(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    for i in range(3):
        save_data(_一份含中文的数据(), path)
    assert list(tmp_path.glob("*.tmp.*")) == []


def test_保存会自动创建父目录(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deep" / "data.json"
    save_data(_一份含中文的数据(), path)
    assert path.exists()
    assert load_data(path) == _一份含中文的数据()
