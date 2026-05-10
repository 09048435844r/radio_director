"""conductor の sequential 実行検証 (backlog §6)。

完全 sequential 化により、各 segment が直前までに完成した全 segment を
prior_segments として受け取ることを mock client 経由で検証する。
"""

from __future__ import annotations

import json

from radio_director.models.script import DialogTurn, ScriptSegment
from radio_director.phase_b.llm_client import LLMClient
from radio_director.phase_c.conductor import conduct

from tests.phase_c._factories import make_show_spec, make_turns


class _RecordingClient(LLMClient):
    """各 generate 呼び出しの prompt と呼び出し順を記録する mock。"""

    def __init__(self, response: str):
        self.response = response
        self.prompts: list[str] = []

    def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.5,
        max_tokens: int = 4096,
        json_mode: bool = True,
    ) -> str:
        self.prompts.append(prompt)
        return self.response


def _segment_payload(speaker_marker: str) -> str:
    """テスト識別用のマーカー入り JSON payload を返す。"""
    turns = [
        {"speaker": "A", "text": f"発話A {speaker_marker}"},
        {"speaker": "B", "text": f"発話B {speaker_marker}"},
        {"speaker": "A", "text": f"発話A2 {speaker_marker}"},
        {"speaker": "B", "text": f"発話B2 {speaker_marker}"},
    ]
    return json.dumps({"turns": turns}, ensure_ascii=False)


def test_conduct_runs_segments_sequentially():
    """intro → deep_dive×N → conclusion の順で 5 回 LLM call が走る。"""
    show = make_show_spec(n_topics=3)
    client = _RecordingClient(
        json.dumps({"turns": make_turns(6)}, ensure_ascii=False)
    )
    script = conduct(show, client=client)
    # intro + deep_dive×3 + conclusion = 5 segments / 5 calls
    assert len(client.prompts) == 5
    assert len(script.segments) == 5
    assert script.segments[0].segment_type == "intro"
    assert script.segments[1].segment_type == "deep_dive"
    assert script.segments[2].segment_type == "deep_dive"
    assert script.segments[3].segment_type == "deep_dive"
    assert script.segments[4].segment_type == "conclusion"


def test_conduct_accumulates_prior_segments_in_prompts():
    """N 番目の segment の prompt に、それまでに完成した全 segment text が含まれる。"""
    show = make_show_spec(n_topics=3)
    # 4 ターンの固定 response (segment_type 識別用 marker は LLM 出力に
    # 含まれないため、入力 prompt のラベル ([intro], [topic N: ...]) を見る)
    client = _RecordingClient(_segment_payload("ZZZ"))
    conduct(show, client=client)

    # prompt[0] = intro: 「これまでの台本」ブロックなし
    assert "これまでの台本" not in client.prompts[0]

    # prompt[1] = deep_dive[0]: intro の text が含まれる
    assert "[intro]" in client.prompts[1]
    assert "発話A ZZZ" in client.prompts[1]

    # prompt[2] = deep_dive[1]: intro + deep_dive[0] の両方が含まれる
    assert "[intro]" in client.prompts[2]
    assert f"[topic 1: {show.topics[0].title}]" in client.prompts[2]

    # prompt[3] = deep_dive[2]: 3 つの prior すべて
    assert "[intro]" in client.prompts[3]
    assert f"[topic 1: {show.topics[0].title}]" in client.prompts[3]
    assert f"[topic 2: {show.topics[1].title}]" in client.prompts[3]

    # prompt[4] = conclusion: 全 4 prior すべて
    assert "[intro]" in client.prompts[4]
    assert f"[topic 3: {show.topics[2].title}]" in client.prompts[4]


def test_conduct_does_not_use_threadpool():
    """sequential 化の確認: ThreadPoolExecutor を使っていないため呼び出し順が安定。

    LLM 呼び出し回数 = 5、prompt 配列長 = 5、順序は intro → dd0 → dd1 → dd2 → conclusion。
    """
    show = make_show_spec(n_topics=3)
    client = _RecordingClient(_segment_payload("YYY"))
    script = conduct(show, client=client)
    # segment 数と LLM call 回数の 1:1 対応 (並列なし)
    assert len(client.prompts) == len(script.segments)


def test_conduct_uses_full_prior_text_not_truncated():
    """各 segment は前 segment の **全 turn** を context として受け取る (旧 4-turn 制限なし)。

    LLM が返す turns 数は固定 4 だが、prompt 内の prior 表示は full text。
    最低限 4 turn なので「打ち切り境界」テストの代わりに「全 turn 数 = LLM 出力 turn 数」を見る。
    """
    show = make_show_spec(n_topics=3)
    # 8 ターン (4 turn 境界を超える) 返すよう設定
    payload = json.dumps(
        {
            "turns": [
                {"speaker": "A" if i % 2 == 0 else "B", "text": f"FULL_TURN_{i}"}
                for i in range(8)
            ]
        },
        ensure_ascii=False,
    )
    client = _RecordingClient(payload)
    conduct(show, client=client)

    # deep_dive[1] の prompt に intro の 8 ターンすべて (FULL_TURN_0..FULL_TURN_7) が含まれる
    dd1_prompt = client.prompts[2]
    for i in range(8):
        assert f"FULL_TURN_{i}" in dd1_prompt
