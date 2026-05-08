"""runner.run_pipeline の単体テスト (Mock LLM で E2E)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from radio_director.phase_b.llm_client import LLMClient
from radio_director.runner import run_pipeline

from tests.phase_a._factories import kn, ke, sc, make_brief
from tests.phase_b._factories import make_show_spec
from tests.phase_c._factories import make_turns


class _StubLLMClient(LLMClient):
    """Phase B / C / D の各 LLM コールに対し JSON 応答を順番に返す。

    Phase B: 1 コール (ShowSpec)
    Phase C: 1 (intro) + N (deep_dive) + 1 (conclusion) = N+2 コール
    Phase D: 1 コール (VideoMetadata)
    """

    def __init__(self, *, n_topics: int = 3):
        super().__init__()
        self.n_topics = n_topics
        self.calls = 0
        self._show_spec_payload = json.dumps(
            make_show_spec(thumbnail_title="テスト動画"),
            ensure_ascii=False,
        )
        self._turns_payload = json.dumps(
            {"turns": make_turns(6)}, ensure_ascii=False
        )
        self._metadata_payload = json.dumps(
            {
                "title": "テストタイトル",
                "description": "概要." * 30,
                "hashtags": ["a", "b", "c", "d", "e"],
            },
            ensure_ascii=False,
        )

    def generate(self, prompt, *, temperature=0.5, max_tokens=4096, json_mode=True):
        self.calls += 1
        # 簡易判定: prompt 内のキーワードで Phase を識別
        if "ラジオ番組ディレクター" in prompt and "json_schema" not in prompt and "対話台本" not in prompt:
            return self._show_spec_payload
        if "対話台本" in prompt or "ずんだもん" in prompt and "ディレクター" not in prompt:
            return self._turns_payload
        if "メタデータ最適化" in prompt:
            return self._metadata_payload
        # フォールバック: prompt の冒頭で振り分け
        if "メタデータ最適化" in prompt[:200]:
            return self._metadata_payload
        if "ディレクター" in prompt[:200]:
            return self._show_spec_payload
        return self._turns_payload


def _write_brief_fixture(tmp_path: Path) -> Path:
    payload = make_brief(key_numbers=[kn(1)] * 5)
    path = tmp_path / "research_brief.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_run_pipeline_creates_all_artifacts(tmp_path):
    brief_path = _write_brief_fixture(tmp_path)
    output_root = tmp_path / "output"
    client = _StubLLMClient()

    run_dir = run_pipeline(brief_path, output_root=output_root, client=client)

    assert run_dir.exists()
    assert run_dir.parent == output_root
    # 5 ファイル + phase_logs/
    assert (run_dir / "cleaned_research.json").is_file()
    assert (run_dir / "show_spec.json").is_file()
    assert (run_dir / "verified_script.json").is_file()
    assert (run_dir / "run_metadata.json").is_file()
    assert (run_dir / "phase_logs").is_dir()


def test_run_pipeline_run_id_format(tmp_path):
    brief_path = _write_brief_fixture(tmp_path)
    output_root = tmp_path / "output"
    client = _StubLLMClient()
    run_dir = run_pipeline(brief_path, output_root=output_root, client=client)
    # run_id は "YYYY-MM-DD_HH-MM_theme" 形式
    parts = run_dir.name.split("_")
    assert len(parts) >= 3
    assert "-" in parts[0]  # date


def test_run_pipeline_verified_script_has_thumbnail_title(tmp_path):
    brief_path = _write_brief_fixture(tmp_path)
    output_root = tmp_path / "output"
    client = _StubLLMClient()
    run_dir = run_pipeline(brief_path, output_root=output_root, client=client)

    verified_data = json.loads((run_dir / "verified_script.json").read_text(encoding="utf-8"))
    assert verified_data["metadata"]["thumbnail_title"]
    assert len(verified_data["metadata"]["thumbnail_title"]) <= 15


def test_run_pipeline_run_metadata_schema(tmp_path):
    brief_path = _write_brief_fixture(tmp_path)
    output_root = tmp_path / "output"
    client = _StubLLMClient()
    run_dir = run_pipeline(brief_path, output_root=output_root, client=client)

    md = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
    assert md["run_id"] == run_dir.name
    assert "started_at" in md
    assert "completed_at" in md
    assert isinstance(md["duration_sec"], int)
    assert set(md["phases"].keys()) == {"phase_a", "phase_b", "phase_c", "phase_d"}
    assert md["verified_script_path"] == "verified_script.json"
