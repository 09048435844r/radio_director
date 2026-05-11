"""台本本文から数値を抽出し canonical 形に正規化する（決定論）。

研究側 stage3_synthesize.py の STATISTIC_PATTERN を参考に、台本の自然文
（コンマ区切り、漢数字単位、OR/HR/RR 表記）に対応するよう拡張。

highly_specific 判定は仕様 §3.1.1 / 研究側 _is_highly_specific と同等基準で
ゼロベース実装する。

C4 (Step 7): 旧閾値 (小数3桁以上 OR 100万以上の整数で末尾非000) では
n=1,250 / 15% / OR=0.85 / 95%CI 等の現実的な医学・統計数値が全て素通りし
false_positive_candidates が常にゼロだった事象を修正。
閾値・分類基準を radio_director.config に外出しし、デフォルトで:
  - MIN_INTEGER = 100 (旧 1,000,000)
  - MIN_DECIMAL_PLACES = 1 (旧 3)
  - INCLUDE_PERCENT = True (% を含む値は specific 扱い)
  - INCLUDE_STATISTIC_NOTATION = True (n=/OR=/p</CI 等は specific 扱い)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from radio_director import config as _config
from radio_director.models.script import Script

_NUMBER_PATTERN = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<unit>(?:\s*)(?:%|‰|倍|人|件|円|ドル|年|時間|分|秒|億|万|千|兆|台|個|回|本|名)?)"
)
_OR_HR_PATTERN = re.compile(
    r"(?P<kind>OR|HR|RR|p)\s*(?P<op>[=＝<>])\s*(?P<num>\d+(?:\.\d+)?)"
)

_HIGHLY_SPECIFIC_DECIMAL = re.compile(r"^-?\d+\.(\d+)$")
_HIGHLY_SPECIFIC_INT = re.compile(r"^-?(\d+)$")


@dataclass(frozen=True)
class ExtractedNumber:
    canonical: str
    raw: str
    segment_id: str
    is_highly_specific: bool


def extract_numbers(script: Script) -> list[ExtractedNumber]:
    """Script の全 segment / 全 turn から数値を抽出する。"""
    results: list[ExtractedNumber] = []
    for seg in script.segments:
        seg_id = _segment_id(seg.segment_type, seg.topic_index)
        for turn in seg.turns:
            results.extend(_extract_from_text(turn.text, seg_id))
    return results


def _segment_id(segment_type: str, topic_index: int | None) -> str:
    if segment_type == "deep_dive":
        return f"deep_dive_{topic_index}"
    return segment_type


def _extract_from_text(text: str, segment_id: str) -> list[ExtractedNumber]:
    out: list[ExtractedNumber] = []
    seen: set[tuple[int, int]] = set()

    for m in _OR_HR_PATTERN.finditer(text):
        span = m.span()
        seen.add(span)
        kind = m.group("kind")
        op = m.group("op")
        num = m.group("num")
        if op in ("=", "＝"):
            canonical = f"{num}{kind}"
        else:
            canonical = f"{kind}{op}{num}"
        out.append(
            ExtractedNumber(
                canonical=canonical,
                raw=m.group(0),
                segment_id=segment_id,
                is_highly_specific=is_highly_specific(num),
            )
        )

    for m in _NUMBER_PATTERN.finditer(text):
        span = m.span()
        if any(s <= span[0] < e for s, e in seen):
            continue
        num_raw = m.group("num")
        unit_raw = m.group("unit") or ""
        unit = unit_raw.strip()
        canonical = num_raw.replace(",", "") + unit
        raw = m.group(0).strip()
        if not unit and "." not in num_raw and len(num_raw.replace(",", "")) <= 1:
            continue
        out.append(
            ExtractedNumber(
                canonical=canonical,
                raw=raw,
                segment_id=segment_id,
                is_highly_specific=is_highly_specific(num_raw),
            )
        )

    return out


# C4: 統計量表記 (n=, OR=, HR=, RR=, SMD=, p<, CI 等)
_STATISTIC_NOTATION_PATTERN = re.compile(
    r"(?:OR|HR|RR|SMD|n\s*[=＝]|p\s*[<>=]|CI)",
    flags=re.IGNORECASE,
)


def is_highly_specific(value: str) -> bool:
    """値が「具体的・統計的」かを判定する (C4 で拡張済み、閾値は config 外出し)。

    判定基準 (config 既定値):
    1. % を含む値 (例: "15%", "95%CI") → True
    2. 統計量表記 (n=, OR=, HR=, RR=, SMD=, p<, CI) を含む → True
    3. 小数点以下 N 桁以上 (例: "0.12" / "0.207" / "23.847") → True
    4. M 以上の整数 (例: "100", "1,250") → True
    """
    if not isinstance(value, str) or not value:
        return False
    cleaned = value.replace(",", "").replace(" ", "").replace("　", "").strip()

    # C4: percent 表現は specific 扱い (config 制御)
    if _config.PHASE_D_HS_INCLUDE_PERCENT and "%" in cleaned:
        return True

    # C4: 統計量表記 (n=/OR=/p<等) は specific 扱い (config 制御)
    if (
        _config.PHASE_D_HS_INCLUDE_STATISTIC_NOTATION
        and _STATISTIC_NOTATION_PATTERN.search(cleaned)
    ):
        return True

    m = _HIGHLY_SPECIFIC_DECIMAL.match(cleaned)
    if m and len(m.group(1)) >= _config.PHASE_D_HS_MIN_DECIMAL_PLACES:
        return True

    m = _HIGHLY_SPECIFIC_INT.match(cleaned)
    if m:
        try:
            n = int(m.group(1))
        except ValueError:
            return False
        if n >= _config.PHASE_D_HS_MIN_INTEGER:
            return True

    return False
