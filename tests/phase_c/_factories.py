"""Phase C テスト用の合成データファクトリ。"""

from __future__ import annotations

from typing import Any

from radio_director.models.show_spec import ShowSpec


def make_turn(speaker: str = "A", text: str = "サンプル発話") -> dict[str, Any]:
    return {"speaker": speaker, "text": text}


def make_turns(n: int = 4) -> list[dict[str, Any]]:
    return [
        make_turn("A" if i % 2 == 0 else "B", f"発話{i + 1}")
        for i in range(n)
    ]


def make_show_spec(*, n_topics: int = 3) -> ShowSpec:
    topics = [
        {
            "title": f"トピック{i + 1}",
            "hook": f"フック{i + 1}",
            "key_claims": [
                {
                    "text": f"事実{i + 1}-1",
                    "source_idx": i + 1,
                    "source_tier": "AAA",
                    "confidence": "medium",
                },
                {
                    "text": f"事実{i + 1}-2",
                    "source_idx": i + 10,
                    "source_tier": "A",
                    "confidence": "high",
                },
            ],
            "tone": "驚き" if i == 0 else "解説",
            "estimated_turns": 14,
        }
        for i in range(n_topics)
    ]
    return ShowSpec.model_validate(
        {
            "title": "テスト番組",
            "thumbnail_title": "テスト番組",
            "hook": "視聴者を引き込むフック",
            "angle": "テスト切り口",
            "arc": "導入→深掘り→まとめ",
            "tone": "驚きと解説",
            "topics": topics,
            "conclusion_message": "今日のまとめメッセージ",
        }
    )
