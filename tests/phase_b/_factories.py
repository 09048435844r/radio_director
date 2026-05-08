"""Phase B テスト用の合成データファクトリ。"""

from __future__ import annotations

from typing import Any


def make_claim(**overrides: Any) -> dict[str, Any]:
    base = {
        "text": "睡眠不足者の感染率は2.94倍 [AAA]",
        "source_idx": 3,
        "source_tier": "AAA",
        "confidence": "medium",
    }
    base.update(overrides)
    return base


def make_topic(**overrides: Any) -> dict[str, Any]:
    base = {
        "title": "睡眠と免疫の意外な関係",
        "hook": "実は寝不足が風邪を呼ぶ",
        "key_claims": [make_claim()],
        "tone": "驚き",
        "estimated_turns": 14,
    }
    base.update(overrides)
    return base


def make_show_spec(**overrides: Any) -> dict[str, Any]:
    base = {
        "title": "寝不足が免疫を壊す？",
        "hook": "今夜の睡眠が来週の風邪を決める",
        "angle": "寝不足が『風邪』を呼ぶ",
        "arc": "導入→深掘り→まとめ",
        "tone": "驚き寄り",
        "topics": [make_topic(), make_topic()],
        "conclusion_message": "今夜は早く寝ましょう",
    }
    base.update(overrides)
    return base
