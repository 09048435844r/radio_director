"""output ディレクトリへの artifact 書き出し (Step 1 SSOT 化)。

~/radio_director/output/<run_id>/ に各種 JSON artifact と phase_logs/ を
配置する。run_id 重複時は _2 / _3 ... を付与して衝突を回避。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

DEFAULT_OUTPUT_ROOT = Path.home() / "radio_director" / "output"

_MAX_COLLISION_ATTEMPTS = 100


class OutputWriter:
    """単一 run の output ディレクトリを管理する。

    インスタンス化時に <root>/<run_id>/ (重複時 <root>/<run_id>_2/ など) を
    作成し、phase_logs/ サブディレクトリも併せて作る。save_json で
    Pydantic モデルまたは dict を JSON ファイルとして保存する。
    """

    def __init__(self, run_id: str, root: Path = DEFAULT_OUTPUT_ROOT) -> None:
        self.run_id = run_id
        self.root = root
        self.run_dir = self._resolve_unique_dir()
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "phase_logs").mkdir()

    def _resolve_unique_dir(self) -> Path:
        candidate = self.root / self.run_id
        if not candidate.exists():
            return candidate
        for n in range(2, _MAX_COLLISION_ATTEMPTS + 1):
            alt = self.root / f"{self.run_id}_{n}"
            if not alt.exists():
                return alt
        raise RuntimeError(
            f"run_id 衝突が {_MAX_COLLISION_ATTEMPTS} 回連続: {self.run_id}"
        )

    def save_json(self, name: str, payload: BaseModel | dict[str, Any]) -> Path:
        """name (例: 'verified_script.json') で run_dir/ 直下に保存する。"""
        path = self.run_dir / name
        if isinstance(payload, BaseModel):
            path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
        else:
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        return path

    def phase_log_path(self, name: str) -> Path:
        """phase_logs/<name> のパスを返す (実際の書き込みは呼び出し側責任)。"""
        return self.run_dir / "phase_logs" / name
