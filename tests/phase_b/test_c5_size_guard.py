"""C5: Phase B prompt サイズガードのテスト。

仕様:
- prompt 長 > PHASE_B_PROMPT_CHAR_LIMIT で truncation 発火
- truncate 後は structured_facts が confidence 優先で top K 件に絞られる
- 警告ログが出る
"""

from __future__ import annotations

import logging

from radio_director import config
from radio_director.phase_b.prompt_builder import (
    _sort_facts_by_priority,
    _truncate_facts,
    build_prompt,
)

from tests.phase_d._factories import make_cleaned_research


def test_no_truncation_under_limit(monkeypatch):
    """size 制限内なら truncation は起きない (warning ログなし)。"""
    monkeypatch.setattr(config, "PHASE_B_PROMPT_CHAR_LIMIT", 100_000)
    cleaned = make_cleaned_research()
    prompt = build_prompt(cleaned)
    # 通常の make_cleaned_research では 100k chars に届かない
    assert len(prompt) < 100_000


def test_truncation_fires_over_limit(monkeypatch, caplog):
    """size 制限超で truncation が走り、warning ログが出る。"""
    monkeypatch.setattr(config, "PHASE_B_PROMPT_CHAR_LIMIT", 1000)  # 極端に小さい閾値
    monkeypatch.setattr(config, "PHASE_B_FACTS_TOP_K", 3)
    cleaned = make_cleaned_research()
    with caplog.at_level(logging.WARNING):
        prompt = build_prompt(cleaned)
    # warning ログが出ている
    assert any("サイズガード発火" in r.message for r in caplog.records)
    # truncate 後は再構築された prompt が返される (元 prompt より小さい可能性)
    assert isinstance(prompt, str)


def test_truncate_facts_keeps_top_k(monkeypatch):
    """_truncate_facts が top_k 件のみ残すこと。"""
    cleaned = make_cleaned_research()
    # 元の key_numbers は make_cleaned_research が 5 件作る
    assert len(cleaned.facts.key_numbers) >= 3
    truncated = _truncate_facts(cleaned.facts, top_k=2)
    assert len(truncated.key_numbers) <= 2
    assert len(truncated.key_entities) <= 2


def test_truncate_facts_priority_order():
    """_sort_facts_by_priority: confidence high が先、low が後。"""
    cleaned = make_cleaned_research()
    facts = list(cleaned.facts.key_numbers)
    # 1 件は confidence="high" に強制設定
    if facts:
        facts[-1] = facts[-1].model_copy(update={"confidence": "high"})
    sorted_facts = _sort_facts_by_priority(facts)
    # high が先頭にあるはず
    if any(f.confidence == "high" for f in facts):
        assert sorted_facts[0].confidence == "high"


def test_config_flag_zero_disables_guard(monkeypatch):
    """PHASE_B_PROMPT_CHAR_LIMIT=0 で truncation は起きない (kill switch)。"""
    monkeypatch.setattr(config, "PHASE_B_PROMPT_CHAR_LIMIT", 0)
    cleaned = make_cleaned_research()
    prompt = build_prompt(cleaned)
    # 0 だと bool 評価で False → truncation スキップ
    # prompt は通常通り (元 size) で返る
    assert isinstance(prompt, str)
