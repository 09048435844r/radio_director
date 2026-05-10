"""segment_generator の retry / fallback ロジック検証。

FakeLLMClient で LLM 呼び出しを差し替え、リトライ回数とフォールバック発火を
確認する。time.sleep をモンキーパッチして待機時間をゼロにする。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from radio_director.phase_b.llm_client import LLMClient, LLMRequestError
from radio_director.phase_c import segment_generator
from radio_director.phase_c.segment_generator import generate_segment

from tests.phase_c._factories import make_show_spec, make_turns


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(segment_generator.time, "sleep", lambda _s: None)


class FakeLLMClient(LLMClient):
    """指定したシーケンスで responses を返すモック。例外は raise する。"""

    def __init__(self, responses: list[Any]):
        self._responses = list(responses)
        self.calls = 0

    def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.5,
        max_tokens: int = 4096,
        json_mode: bool = True,
    ) -> str:
        self.calls += 1
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _success_payload() -> str:
    return json.dumps({"turns": make_turns(6)}, ensure_ascii=False)


def test_succeeds_on_first_attempt():
    show = make_show_spec(n_topics=3)
    client = FakeLLMClient([_success_payload()])
    seg, metrics = generate_segment(
        segment_type="intro",
        topic_index=None,
        show_spec=show,
        prior_segments=None,
        client=client,
    )
    assert metrics.attempts == 1
    assert metrics.used_fallback is False
    assert client.calls == 1
    assert len(seg.turns) == 6


def test_retries_then_succeeds_on_third_attempt():
    show = make_show_spec(n_topics=3)
    client = FakeLLMClient(
        [
            LLMRequestError("transient 1"),
            LLMRequestError("transient 2"),
            _success_payload(),
        ]
    )
    seg, metrics = generate_segment(
        segment_type="deep_dive",
        topic_index=1,
        show_spec=show,
        prior_segments=None,
        client=client,
    )
    assert metrics.attempts == 3
    assert metrics.used_fallback is False
    assert seg.topic_index == 1
    assert client.calls == 3


def test_falls_back_after_max_attempts():
    show = make_show_spec(n_topics=3)
    client = FakeLLMClient(
        [
            LLMRequestError("fail 1"),
            LLMRequestError("fail 2"),
            LLMRequestError("fail 3"),
        ]
    )
    seg, metrics = generate_segment(
        segment_type="intro",
        topic_index=None,
        show_spec=show,
        prior_segments=None,
        client=client,
        max_attempts=3,
    )
    assert metrics.attempts == 3
    assert metrics.used_fallback is True
    assert client.calls == 3
    assert seg.segment_type == "intro"
    assert len(seg.turns) >= 4  # フォールバックも min_length を満たす


def test_falls_back_on_repeated_parse_errors():
    """LLM が JSON にならない出力を返し続けた場合もフォールバックする。"""
    show = make_show_spec(n_topics=3)
    client = FakeLLMClient(
        [
            "これは JSON ではない",
            "これも JSON ではない",
            "<think>still bad</think>",
        ]
    )
    seg, metrics = generate_segment(
        segment_type="conclusion",
        topic_index=None,
        show_spec=show,
        prior_segments=None,
        client=client,
        max_attempts=3,
    )
    assert metrics.used_fallback is True
    assert metrics.attempts == 3
    assert seg.segment_type == "conclusion"


def test_fallback_segment_for_deep_dive_uses_topic_metadata():
    show = make_show_spec(n_topics=3)
    client = FakeLLMClient(
        [LLMRequestError("x")] * 3
    )
    seg, metrics = generate_segment(
        segment_type="deep_dive",
        topic_index=2,
        show_spec=show,
        prior_segments=None,
        client=client,
        max_attempts=3,
    )
    assert metrics.used_fallback is True
    target = show.topics[2]
    assert any(target.title in turn.text for turn in seg.turns)


def test_metrics_record_prompt_and_output_chars():
    show = make_show_spec(n_topics=3)
    payload = _success_payload()
    client = FakeLLMClient([payload])
    seg, metrics = generate_segment(
        segment_type="intro",
        topic_index=None,
        show_spec=show,
        prior_segments=None,
        client=client,
    )
    assert metrics.prompt_chars > 0
    assert metrics.output_chars == len(payload)
    assert metrics.elapsed_sec >= 0.0


# ---------------------------------------------------------------------------
# backlog §6: deep_dive にも prior_segments が prompt 経由で渡される
# ---------------------------------------------------------------------------


def test_deep_dive_passes_prior_segments_to_prompt(monkeypatch):
    """generate_segment(deep_dive) で prior_segments が prompt に反映される。"""
    from radio_director.models.script import DialogTurn, ScriptSegment

    show = make_show_spec(n_topics=3)
    intro = ScriptSegment(
        segment_type="intro",
        title="i",
        turns=[
            DialogTurn(speaker="A", text="UNIQUE_PRIOR_MARKER_42"),
            DialogTurn(speaker="B", text="x"),
            DialogTurn(speaker="A", text="y"),
            DialogTurn(speaker="B", text="z"),
        ],
    )
    captured: dict[str, str] = {}

    class CapturingClient(FakeLLMClient):
        def generate(self, prompt, **kwargs):
            captured["prompt"] = prompt
            return super().generate(prompt, **kwargs)

    client = CapturingClient([_success_payload()])
    generate_segment(
        segment_type="deep_dive",
        topic_index=0,
        show_spec=show,
        prior_segments=[intro],
        client=client,
    )
    assert "UNIQUE_PRIOR_MARKER_42" in captured["prompt"]
    assert "[intro]" in captured["prompt"]
