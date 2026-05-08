"""台本本文から数値を抽出し canonical 形に正規化する（決定論）。

研究側 stage3_synthesize.py の STATISTIC_PATTERN を参考に、台本の自然文
（コンマ区切り、漢数字単位、OR/HR/RR 表記）に対応するよう拡張。

highly_specific 判定は仕様 §3.1.1 / 研究側 _is_highly_specific と同等基準で
ゼロベース実装する:
  1. 小数 3 桁以上 (例: 0.207, 23.847)
  2. 100 万以上の整数で末尾 ≠ 000 (例: 2,847,193)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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


def is_highly_specific(value: str) -> bool:
    """仕様 §3.1.1 と同等の判定:
    - 小数 3 桁以上 (高精度数値)
    - 100 万以上の整数で末尾が 000 でない (細かい集計値)
    """
    if not isinstance(value, str) or not value:
        return False
    cleaned = value.replace(",", "").replace(" ", "").replace("　", "").strip()

    m = _HIGHLY_SPECIFIC_DECIMAL.match(cleaned)
    if m and len(m.group(1)) >= 3:
        return True

    m = _HIGHLY_SPECIFIC_INT.match(cleaned)
    if m:
        try:
            n = int(m.group(1))
        except ValueError:
            return False
        if n >= 1_000_000 and n % 1000 != 0:
            return True

    return False
