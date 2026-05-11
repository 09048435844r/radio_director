"""Step 7 C1: Phase D production gate (soft gate, retry, hard fail) のテスト。

Mock を活用して LLM/Phase B/Phase C を回避し、matched_ratio のみ制御する。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from radio_director import config
from radio_director.runner import QualityGateError, run_pipeline


def _make_verified_with_ratio(matched_ratio: float):
    """matched_ratio だけ制御した最小 VerifiedScript mock を生成する。"""
    verified = MagicMock()
    verified.metrics.matched_ratio = matched_ratio
    verified.metrics.matched_to_structured_facts = int(matched_ratio * 100)
    verified.metrics.total_numbers_extracted = 100
    verified.metrics.highly_specific_count = 0
    verified.metrics.highly_specific_unmatched = 0
    verified.metrics.false_positive_candidates = 0
    verified.metrics.citation_tags_total = 0
    verified.metrics.citation_tags_normalized = 0
    verified.metrics.citation_tags_inconsistent = 0
    verified.metadata.title = "test"
    verified.metadata.hashtags = []
    verified.metadata.chapters = []
    verified.metadata.references = []
    verified.warnings = []
    return verified


@pytest.fixture
def fake_brief(tmp_path: Path) -> Path:
    """最小限の research_brief.json を生成する fixture。"""
    brief_path = tmp_path / "brief.json"
    # phase_d/_factories の CleanedResearch を再利用するために本物の brief を流す
    # シンプルに既存のテストパターンを参考に、模擬 JSON を書く
    import json

    brief = {
        "session_id": "test_gate",
        "theme": "テスト",
        "research_mode": "lecture",
        "created_at": "2026-05-12T00:00:00",
        "research_content": "テスト本文",
        "research_sources": [
            {
                "title": "src1",
                "url": "https://example.com/1",
                "snippet": "snip",
                "content": "本文",
                "domain_score": 99,
                "domain_tier": "AAA",
            }
        ],
        "queries": ["q1"],
        "angle": "テスト angle",
        "structured_facts": {
            "key_numbers": [
                {
                    "value": "10",
                    "unit": "%",
                    "context": "test",
                    "source_idx": 1,
                    "cross_validated_sources": [1],
                    "confidence": "medium",
                    "flags": [],
                }
            ],
            "key_entities": [],
            "surprising_claims": [],
            "controversies": [],
        },
        "curated_topics": None,
        "perplexity_usage": None,
        "gemini_usage_planning": None,
        "pipeline_metadata": {
            "pipeline_version": "test",
            "ollama_model": "test",
            "ollama_endpoints": {},
            "total_duration_seconds": 0,
            "stages": {},
            "source_tier_breakdown": {},
            "cache_hits": 0,
        },
    }
    brief_path.write_text(json.dumps(brief, ensure_ascii=False))
    return brief_path


def _patch_phases(matched_ratios: list[float]):
    """Phase B/C/D を mock して、verify が指定された matched_ratio を順に返すようにする。

    matched_ratios = [first_attempt, retry_1, retry_2, ...]
    """
    # iteratorize
    it = iter(matched_ratios)

    def fake_verify(*args, **kwargs):
        return _make_verified_with_ratio(next(it))

    fake_show_spec = MagicMock()
    fake_show_spec.title = "test"
    fake_show_spec.topics = []

    fake_script = MagicMock()
    fake_script.segments = []
    fake_script.metrics = {}

    return (
        patch("radio_director.runner.plan_show", return_value=fake_show_spec),
        patch("radio_director.runner.conduct", return_value=fake_script),
        patch("radio_director.runner.verify", side_effect=fake_verify),
        patch(
            "radio_director.runner.LLMClient.from_env",
            return_value=MagicMock(model="test-model"),
        ),
    )


# ─── Gate pass: matched_ratio が threshold 以上 → 保存 ────────────────
def test_gate_pass_at_threshold(monkeypatch, fake_brief, tmp_path):
    monkeypatch.setattr(config, "PHASE_D_MATCHED_RATIO_GATE", 0.30)
    monkeypatch.setattr(config, "PHASE_D_RETRY_ENABLED", True)
    monkeypatch.setattr(config, "PHASE_D_RETRY_MAX", 1)

    patches = _patch_phases([0.5])
    with patches[0], patches[1], patches[2], patches[3]:
        run_dir = run_pipeline(fake_brief, output_root=tmp_path)
    assert (run_dir / "verified_script.json").exists()
    assert not (run_dir / "verified_script.failed.json").exists()


# ─── Gate fail → retry → pass ──────────────────────────────────────────
def test_gate_retry_then_pass(monkeypatch, fake_brief, tmp_path):
    monkeypatch.setattr(config, "PHASE_D_MATCHED_RATIO_GATE", 0.30)
    monkeypatch.setattr(config, "PHASE_D_RETRY_ENABLED", True)
    monkeypatch.setattr(config, "PHASE_D_RETRY_MAX", 1)

    # 1 回目: 0.1 (fail) → retry 後 0.4 (pass)
    patches = _patch_phases([0.1, 0.4])
    with patches[0], patches[1], patches[2], patches[3]:
        run_dir = run_pipeline(fake_brief, output_root=tmp_path)
    assert (run_dir / "verified_script.json").exists()
    assert not (run_dir / "verified_script.failed.json").exists()


# ─── Gate fail → retry fail → hard fail ─────────────────────────────
def test_gate_retry_then_hard_fail(monkeypatch, fake_brief, tmp_path):
    monkeypatch.setattr(config, "PHASE_D_MATCHED_RATIO_GATE", 0.30)
    monkeypatch.setattr(config, "PHASE_D_RETRY_ENABLED", True)
    monkeypatch.setattr(config, "PHASE_D_RETRY_MAX", 1)

    # 1 回目: 0.1 (fail) → retry 後 0.1 (still fail) → QualityGateError
    patches = _patch_phases([0.1, 0.1])
    with patches[0], patches[1], patches[2], patches[3]:
        with pytest.raises(QualityGateError):
            run_pipeline(fake_brief, output_root=tmp_path)

    # verified_script.failed.json は保存されている、verified_script.json は出ない
    # tmp_path 配下を walk して確認
    failed_files = list(tmp_path.rglob("verified_script.failed.json"))
    ok_files = list(tmp_path.rglob("verified_script.json"))
    assert len(failed_files) == 1
    assert len(ok_files) == 0


# ─── Legacy: retry disabled → matched_ratio 低くても保存 ───────────────
def test_legacy_no_retry_low_ratio_still_saves(monkeypatch, fake_brief, tmp_path):
    monkeypatch.setattr(config, "PHASE_D_MATCHED_RATIO_GATE", 0.30)
    monkeypatch.setattr(config, "PHASE_D_RETRY_ENABLED", False)
    monkeypatch.setattr(config, "PHASE_D_RETRY_MAX", 1)

    # 0.1 でも RETRY_ENABLED=False なので保存される
    patches = _patch_phases([0.1])
    with patches[0], patches[1], patches[2], patches[3]:
        run_dir = run_pipeline(fake_brief, output_root=tmp_path)
    assert (run_dir / "verified_script.json").exists()


# ─── Retry max=2: 2 回 retry してから pass ───────────────────────────
def test_gate_retry_max_2(monkeypatch, fake_brief, tmp_path):
    monkeypatch.setattr(config, "PHASE_D_MATCHED_RATIO_GATE", 0.30)
    monkeypatch.setattr(config, "PHASE_D_RETRY_ENABLED", True)
    monkeypatch.setattr(config, "PHASE_D_RETRY_MAX", 2)

    # 1 回目: 0.1 → retry1: 0.2 → retry2: 0.5 (pass)
    patches = _patch_phases([0.1, 0.2, 0.5])
    with patches[0], patches[1], patches[2], patches[3]:
        run_dir = run_pipeline(fake_brief, output_root=tmp_path)
    assert (run_dir / "verified_script.json").exists()
