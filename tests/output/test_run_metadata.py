"""run_metadata 構築の単体テスト。"""

from __future__ import annotations

from datetime import datetime

from radio_director.output.run_metadata import build_run_metadata


def test_basic_construction():
    started = datetime(2026, 5, 9, 20, 15, 32)
    completed = datetime(2026, 5, 9, 20, 19, 48)
    md = build_run_metadata(
        run_id="2026-05-09_20-15_x",
        started_at=started,
        completed_at=completed,
        phases={
            "phase_b": {"model": "qwen3.5-122b", "tokens_in": 1234, "tokens_out": 567},
        },
    )
    assert md["run_id"] == "2026-05-09_20-15_x"
    assert md["started_at"] == "2026-05-09T20:15:32"
    assert md["completed_at"] == "2026-05-09T20:19:48"
    assert md["duration_sec"] == 256
    assert md["phases"]["phase_b"]["model"] == "qwen3.5-122b"
    assert md["verified_script_path"] == "verified_script.json"


def test_zero_duration():
    same = datetime(2026, 5, 9, 20, 0, 0)
    md = build_run_metadata(
        run_id="x", started_at=same, completed_at=same, phases={},
    )
    assert md["duration_sec"] == 0
    assert md["phases"] == {}


def test_custom_verified_script_path():
    md = build_run_metadata(
        run_id="x",
        started_at=datetime(2026, 5, 9),
        completed_at=datetime(2026, 5, 9),
        phases={},
        verified_script_path="custom/path.json",
    )
    assert md["verified_script_path"] == "custom/path.json"
