"""run_metadata.json のスキーマと組み立て (Step 1 SSOT 化)。

実行時刻・所要時間・各 phase のトークン数概算 (chars/2) を記録する。
v2 で tiktoken 等の正確な計測を検討する余地あり (本タスクは YAGNI)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict


class PhaseMetric(TypedDict, total=False):
    model: str
    tokens_in: int
    tokens_out: int
    elapsed_sec: float


def build_run_metadata(
    *,
    run_id: str,
    started_at: datetime,
    completed_at: datetime,
    phases: dict[str, PhaseMetric],
    verified_script_path: str = "verified_script.json",
) -> dict[str, Any]:
    """run_metadata.json に書き出す dict を構築する。"""
    return {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_sec": int((completed_at - started_at).total_seconds()),
        "phases": phases,
        "verified_script_path": verified_script_path,
    }
