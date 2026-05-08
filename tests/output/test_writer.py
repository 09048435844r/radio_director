"""OutputWriter の単体テスト (tmp_path で実 IO 検証)。"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from radio_director.output.writer import OutputWriter


class _Toy(BaseModel):
    name: str
    value: int


def test_creates_run_dir_and_phase_logs(tmp_path):
    writer = OutputWriter("2026-05-09_20-15_test", root=tmp_path)
    assert writer.run_dir == tmp_path / "2026-05-09_20-15_test"
    assert writer.run_dir.is_dir()
    assert (writer.run_dir / "phase_logs").is_dir()


def test_collision_appends_n2(tmp_path):
    """同名 run_id が既に存在する場合は _2 が付与される。"""
    (tmp_path / "2026-05-09_20-15_test").mkdir()
    writer = OutputWriter("2026-05-09_20-15_test", root=tmp_path)
    assert writer.run_dir.name == "2026-05-09_20-15_test_2"


def test_collision_chain_n3(tmp_path):
    """_2 までも存在する場合は _3 が付与される。"""
    (tmp_path / "x").mkdir()
    (tmp_path / "x_2").mkdir()
    writer = OutputWriter("x", root=tmp_path)
    assert writer.run_dir.name == "x_3"


def test_save_json_pydantic_model(tmp_path):
    writer = OutputWriter("run", root=tmp_path)
    path = writer.save_json("toy.json", _Toy(name="abc", value=42))
    assert path == writer.run_dir / "toy.json"
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed == {"name": "abc", "value": 42}


def test_save_json_dict(tmp_path):
    writer = OutputWriter("run", root=tmp_path)
    path = writer.save_json("meta.json", {"foo": "bar", "n": [1, 2]})
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed == {"foo": "bar", "n": [1, 2]}


def test_save_json_japanese_not_escaped(tmp_path):
    writer = OutputWriter("run", root=tmp_path)
    path = writer.save_json("jp.json", {"text": "睡眠と免疫"})
    body = path.read_text(encoding="utf-8")
    assert "睡眠と免疫" in body  # ensure_ascii=False


def test_phase_log_path(tmp_path):
    writer = OutputWriter("run", root=tmp_path)
    p = writer.phase_log_path("phase_b.log")
    assert p == writer.run_dir / "phase_logs" / "phase_b.log"
    # ディレクトリは既に作られている
    assert p.parent.is_dir()
    # ファイル自体はまだ存在しない (呼び出し側責任)
    assert not p.exists()
