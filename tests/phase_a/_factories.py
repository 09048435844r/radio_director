"""テスト用の合成データファクトリ。"""

from __future__ import annotations

from typing import Any


def make_brief(
    *,
    sources: list[dict[str, Any]] | None = None,
    key_numbers: list[dict[str, Any]] | None = None,
    key_entities: list[dict[str, Any]] | None = None,
    surprising_claims: list[dict[str, Any]] | None = None,
    controversies: list[dict[str, Any]] | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "20260508_000000",
        "theme": "テストテーマ",
        "angle": "テスト用 angle",
        "research_mode": "lecture",
        "created_at": "2026-05-08T00:00:00",
        "research_content": "本文 (略)",
        "research_sources": sources
        if sources is not None
        else [
            {
                "title": "AAA source",
                "url": "https://nature.com/a",
                "snippet": None,
                "domain_score": 90,
                "domain_tier": "AAA",
            },
            {
                "title": "B source",
                "url": "https://example.com/b",
                "snippet": None,
                "domain_score": 30,
                "domain_tier": "B",
            },
        ],
        "queries": ["q1", "q2"],
        "structured_facts": {
            "key_numbers": key_numbers
            if key_numbers is not None
            else [_kn(1)] * 5,
            "key_entities": key_entities if key_entities is not None else [],
            "surprising_claims": surprising_claims
            if surprising_claims is not None
            else [],
            "controversies": controversies if controversies is not None else [],
        },
    }
    if extras:
        base.update(extras)
    return base


def _kn(source_idx: int, **overrides: Any) -> dict[str, Any]:
    fact = {
        "value": "10",
        "unit": "%",
        "context": "サンプル数値",
        "source_idx": source_idx,
        "cross_validated_sources": [source_idx],
        "confidence": "medium",
        "flags": [],
    }
    fact.update(overrides)
    return fact


def kn(source_idx: int = 1, **overrides: Any) -> dict[str, Any]:
    return _kn(source_idx, **overrides)


def ke(source_idx: int = 1, **overrides: Any) -> dict[str, Any]:
    fact = {
        "name": "サンプル機関",
        "type": "institution",
        "role": "研究機関",
        "source_idx": source_idx,
        "cross_validated_sources": [source_idx],
        "confidence": "medium",
        "flags": [],
    }
    fact.update(overrides)
    return fact


def sc(source_idx: int = 1, **overrides: Any) -> dict[str, Any]:
    fact = {
        "statement": "驚きの主張",
        "why_surprising": "意外な理由",
        "source_idx": source_idx,
        "cross_validated_sources": [source_idx],
        "confidence": "medium",
        "flags": [],
    }
    fact.update(overrides)
    return fact
