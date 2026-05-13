"""Step 9 partial (postscript): Phase B planner の thumbnail_title 安定化テスト。

3 層構造:
  1. max_attempts を 3 に増加
  2. retry 時に失敗理由を prompt に inline 表示
  3. 最終 LLM 失敗時に deterministic な末尾切り詰め fallback
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from radio_director import config
from radio_director.phase_b.parser import ShowSpecParseError
from radio_director.phase_b.planner import (
    _build_failure_reason,
    _is_thumbnail_too_long_error,
    plan_show,
)

from tests.phase_d._factories import make_cleaned_research


def _make_show_json(thumbnail_title: str = "正規タイトル") -> str:
    """有効な ShowSpec JSON を生成 (thumbnail_title だけ差し替え可)。"""
    return json.dumps({
        "title": "テスト番組タイトル",
        "thumbnail_title": thumbnail_title,
        "hook": "視聴者を引き込むフックです",
        "angle": "切り口",
        "arc": "導入→深掘り→まとめ",
        "tone": "驚き",
        "topics": [
            {
                "title": f"トピック{i+1}",
                "hook": f"フック{i+1}",
                "key_claims": [
                    {
                        "text": f"claim{i+1}",
                        "source_idx": i + 1,
                        "source_tier": "AAA",
                        "confidence": "medium",
                    }
                ],
                "tone": "驚き",
                "estimated_turns": 14,
            }
            for i in range(3)
        ],
        "conclusion_message": "視聴後のアクションを示唆するまとめ",
    }, ensure_ascii=False)


# ─── ヘルパ関数 ────────────────────────────────────────────────────
def test_is_thumbnail_too_long_error_positive():
    """thumbnail_title 長さ違反は判定 True"""
    msg = "ShowSpec validation failed: thumbnail_title String should have at most 15 characters [type=string_too_long]"
    exc = ShowSpecParseError(msg)
    assert _is_thumbnail_too_long_error(exc) is True


def test_is_thumbnail_too_long_error_negative_other():
    """別フィールドのエラーは判定 False"""
    msg = "ShowSpec validation failed: title String should have at most 100 characters"
    exc = ShowSpecParseError(msg)
    assert _is_thumbnail_too_long_error(exc) is False


def test_is_thumbnail_too_long_error_none():
    assert _is_thumbnail_too_long_error(None) is False


def test_build_failure_reason_with_thumbnail():
    """thumbnail_title 長すぎ → reason に具体値を含む"""
    bad_title = "Mac/iPhoneでGPT-4並み？"  # ASCII + 日本語混在
    raw = _make_show_json(thumbnail_title=bad_title)
    exc = ShowSpecParseError("ShowSpec validation failed: thumbnail_title")
    reason = _build_failure_reason(exc, raw)
    assert bad_title in reason
    # 「N字」の表記が含まれる (具体値は文字数依存なので緩く判定)
    assert "字" in reason


# ─── plan_show: 3 attempts → 3 回目で成功 ─────────────────────────
def test_plan_show_succeeds_on_third_attempt(monkeypatch):
    """1st: 17字 fail, 2nd: 16字 fail, 3rd: 12字 pass"""
    monkeypatch.setattr(config, "PHASE_B_PLANNER_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(config, "PHASE_B_THUMBNAIL_TITLE_TRUNCATE_ENABLED", False)

    responses = [
        _make_show_json(thumbnail_title="あ" * 17),  # 17 chars
        _make_show_json(thumbnail_title="あ" * 16),  # 16 chars
        _make_show_json(thumbnail_title="あ" * 12),  # 12 chars (valid)
    ]
    client = MagicMock()
    client.generate = MagicMock(side_effect=responses)

    cleaned = make_cleaned_research()
    spec = plan_show(cleaned, client=client)
    assert len(spec.thumbnail_title) == 12
    assert client.generate.call_count == 3


# ─── plan_show: 全 attempt 失敗 + truncate fallback で完走 ────────
def test_plan_show_truncate_fallback(monkeypatch):
    """1-3 全 attempt が 17字で fail → truncate fallback が 15字に短縮して成功"""
    monkeypatch.setattr(config, "PHASE_B_PLANNER_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(config, "PHASE_B_THUMBNAIL_TITLE_TRUNCATE_ENABLED", True)
    monkeypatch.setattr(config, "PHASE_B_THUMBNAIL_TITLE_MAX_LENGTH", 15)

    bad_json = _make_show_json(thumbnail_title="あ" * 17)
    client = MagicMock()
    client.generate = MagicMock(return_value=bad_json)

    cleaned = make_cleaned_research()
    spec = plan_show(cleaned, client=client)
    # truncate で 15字になる
    assert len(spec.thumbnail_title) == 15
    assert client.generate.call_count == 3


# ─── plan_show: truncate disabled → 全失敗で例外 ──────────────────
def test_plan_show_truncate_disabled_raises(monkeypatch):
    """TRUNCATE_ENABLED=False で全 attempt 失敗 → ShowSpecParseError"""
    monkeypatch.setattr(config, "PHASE_B_PLANNER_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(config, "PHASE_B_THUMBNAIL_TITLE_TRUNCATE_ENABLED", False)

    bad_json = _make_show_json(thumbnail_title="あ" * 17)
    client = MagicMock()
    client.generate = MagicMock(return_value=bad_json)

    cleaned = make_cleaned_research()
    with pytest.raises(ShowSpecParseError):
        plan_show(cleaned, client=client)
    assert client.generate.call_count == 3


# ─── plan_show: retry prompt に失敗理由が inline ─────────────────
def test_plan_show_retry_includes_failure_reason(monkeypatch):
    """retry 時に prompt に「前回の試行で失敗した理由」が inline される"""
    monkeypatch.setattr(config, "PHASE_B_PLANNER_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(config, "PHASE_B_RETRY_INCLUDE_FAILURE_REASON", True)
    monkeypatch.setattr(config, "PHASE_B_THUMBNAIL_TITLE_TRUNCATE_ENABLED", True)

    responses = [
        _make_show_json(thumbnail_title="あ" * 17),  # fail
        _make_show_json(thumbnail_title="正規タイトル"),  # success
    ]
    client = MagicMock()
    client.generate = MagicMock(side_effect=responses)

    cleaned = make_cleaned_research()
    plan_show(cleaned, client=client)
    # 2 回目の generate 呼び出しの prompt に「前回の試行」が含まれていること
    second_call_prompt = client.generate.call_args_list[1].args[0]
    assert "前回の試行" in second_call_prompt
    assert "あ" * 17 in second_call_prompt or "17字" in second_call_prompt


# ─── plan_show: max_attempts 明示指定で override ─────────────────
def test_plan_show_explicit_max_attempts_override(monkeypatch):
    """max_attempts を明示指定すると config を override"""
    monkeypatch.setattr(config, "PHASE_B_PLANNER_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(config, "PHASE_B_THUMBNAIL_TITLE_TRUNCATE_ENABLED", False)

    bad_json = _make_show_json(thumbnail_title="あ" * 17)
    client = MagicMock()
    client.generate = MagicMock(return_value=bad_json)

    cleaned = make_cleaned_research()
    with pytest.raises(ShowSpecParseError):
        plan_show(cleaned, client=client, max_attempts=2)
    # 明示指定の 2 が優先される (5 ではない)
    assert client.generate.call_count == 2
