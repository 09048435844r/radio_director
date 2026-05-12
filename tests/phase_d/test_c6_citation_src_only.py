"""C6 補完: citation_normalizer が [src=N] 単独形式を認識すること。

C6 で Phase C inline format を [src=N] のみに簡素化したが、citation_normalizer
は旧形式 ([src=N][TIER] や [TIER] のみ) しか認識していなかったため、
citation_tags_total が 0 になる regression を発生させていた (regression run で観測)。
"""

from __future__ import annotations

from radio_director.models.cleaned_research import CleanedResearch
from radio_director.models.script import DialogTurn, Script, ScriptSegment, SegmentMetrics
from radio_director.phase_d.citation_normalizer import normalize_citations

from tests.phase_d._factories import make_cleaned_research, make_show_spec


_DEFAULT_METRICS = SegmentMetrics(
    prompt_chars=0, output_chars=0, elapsed_sec=0.0, attempts=1, used_fallback=False
)


def _script_with_text(text: str) -> Script:
    show = make_show_spec(n_topics=3)
    segments = [
        ScriptSegment(
            segment_type="intro",
            title="イントロ",
            turns=[
                DialogTurn(speaker="A", text=text),
                DialogTurn(speaker="B", text="そうですわね"),
                DialogTurn(speaker="A", text="そうなのだ"),
                DialogTurn(speaker="B", text="確かに"),
            ],
        ),
        ScriptSegment(
            segment_type="deep_dive",
            topic_index=0,
            title="t0",
            turns=[DialogTurn(speaker="A" if i % 2 == 0 else "B", text=f"d{i}") for i in range(4)],
        ),
        ScriptSegment(
            segment_type="deep_dive",
            topic_index=1,
            title="t1",
            turns=[DialogTurn(speaker="A" if i % 2 == 0 else "B", text=f"d{i}") for i in range(4)],
        ),
        ScriptSegment(
            segment_type="deep_dive",
            topic_index=2,
            title="t2",
            turns=[DialogTurn(speaker="A" if i % 2 == 0 else "B", text=f"d{i}") for i in range(4)],
        ),
        ScriptSegment(
            segment_type="conclusion",
            title="まとめ",
            turns=[DialogTurn(speaker="A" if i % 2 == 0 else "B", text=f"c{i}") for i in range(4)],
        ),
    ]
    metrics = {
        "intro": _DEFAULT_METRICS,
        "deep_dive_0": _DEFAULT_METRICS,
        "deep_dive_1": _DEFAULT_METRICS,
        "deep_dive_2": _DEFAULT_METRICS,
        "conclusion": _DEFAULT_METRICS,
    }
    return Script(show_spec=show, segments=segments, metrics=metrics)


def test_src_only_format_detected():
    """[src=N] 単独形式が citation として認識されること (C6 修正後)。"""
    cleaned = make_cleaned_research()
    script = _script_with_text("研究によると [src=1] という結果になっています")
    findings, _warnings = normalize_citations(script, cleaned)
    src_only_findings = [f for f in findings if f.raw == "[src=1]"]
    assert len(src_only_findings) >= 1


def test_src_only_tier_resolved_from_sources():
    """[src=N] 単独形式の tier は cleaned.sources から逆引きされること。"""
    cleaned = make_cleaned_research()
    script = _script_with_text("研究によると [src=1] という結果")
    findings, _warnings = normalize_citations(script, cleaned)
    src_finding = next(f for f in findings if f.source_idx == 1)
    # cleaned.sources[0].domain_tier と一致すること
    assert src_finding.tier == cleaned.sources[0].domain_tier


def test_src_only_out_of_range_emits_warning():
    """範囲外の [src=N] は unknown_source_idx warning を発出すること。"""
    cleaned = make_cleaned_research()
    n_sources = len(cleaned.sources)
    script = _script_with_text(f"研究によると [src={n_sources + 10}] という結果")
    findings, warnings = normalize_citations(script, cleaned)
    assert any(w.code == "unknown_source_idx" for w in warnings)


def test_legacy_formats_still_work():
    """[src=N][AAA] 等の旧形式も引き続き認識されること (C6 後の regression 防止)。"""
    cleaned = make_cleaned_research()
    script = _script_with_text("[src=1][AAA] と [src=2][AAA][medium] と [AAA] のテスト")
    findings, _warnings = normalize_citations(script, cleaned)
    # 3 件全て検出されること
    assert len(findings) >= 3


def test_src_only_not_double_counted_when_inside_full():
    """[src=N][AAA] が [src=N] と [AAA] の両方として二重カウントされないこと。"""
    cleaned = make_cleaned_research()
    script = _script_with_text("[src=1][AAA] のみ")
    findings, _warnings = normalize_citations(script, cleaned)
    # 1 件のみ (full tag として消費)
    assert len(findings) == 1
