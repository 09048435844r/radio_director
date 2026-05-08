"""Phase B planner.plan_show の retry 動作検証。

Step 1 SSOT 化で thumbnail_title (max_length=15) 違反等の ValidationError
を吸収するため max_attempts=2 を導入した。FakeLLMClient で動作確認する。
"""

from __future__ import annotations

import json

import pytest

from radio_director.models.research_brief import ResearchBrief
from radio_director.phase_a.decoder import decode
from radio_director.phase_b.llm_client import LLMClient
from radio_director.phase_b.parser import ShowSpecParseError
from radio_director.phase_b.planner import plan_show

from tests.phase_a._factories import kn, make_brief
from tests.phase_b._factories import make_show_spec


def _cleaned():
    return decode(ResearchBrief.model_validate(make_brief(key_numbers=[kn(1)] * 5)))


class FakeLLMClient(LLMClient):
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0

    def generate(self, prompt, *, temperature=0.5, max_tokens=4096, json_mode=True):
        self.calls += 1
        return self._responses.pop(0)


def _good_payload(thumbnail_title: str = "免疫の真実") -> str:
    return json.dumps(make_show_spec(thumbnail_title=thumbnail_title), ensure_ascii=False)


def _bad_thumbnail_payload() -> str:
    """thumbnail_title が 15 字を超えて Pydantic ValidationError を誘発する。"""
    return json.dumps(
        make_show_spec(thumbnail_title="あいうえおかきくけこさしすせそたちつ"),  # 18 chars
        ensure_ascii=False,
    )


def test_first_attempt_success():
    client = FakeLLMClient([_good_payload()])
    show = plan_show(_cleaned(), client=client)
    assert show.thumbnail_title == "免疫の真実"
    assert client.calls == 1


def test_retry_then_succeeds():
    """1 回目失敗 → 2 回目成功で attempts=2 で完了。"""
    client = FakeLLMClient([_bad_thumbnail_payload(), _good_payload()])
    show = plan_show(_cleaned(), client=client)
    assert show.thumbnail_title == "免疫の真実"
    assert client.calls == 2


def test_two_consecutive_failures_raise():
    """連続失敗で ShowSpecParseError 伝播。"""
    client = FakeLLMClient([_bad_thumbnail_payload(), _bad_thumbnail_payload()])
    with pytest.raises(ShowSpecParseError):
        plan_show(_cleaned(), client=client)
    assert client.calls == 2


def test_max_attempts_3_allows_more_retries():
    """max_attempts=3 で 2 回失敗 → 3 回目成功。"""
    client = FakeLLMClient(
        [_bad_thumbnail_payload(), _bad_thumbnail_payload(), _good_payload()]
    )
    show = plan_show(_cleaned(), client=client, max_attempts=3)
    assert show.thumbnail_title == "免疫の真実"
    assert client.calls == 3
