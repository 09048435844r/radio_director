"""キャラクター口調 / 名前表記の決定論的検証 (backlog §8、2026-05-10)。

本運用 1 本目で speaker B (四国めたん) が「のだ」語尾を使う致命的な口調
崩壊バグを観測。LLM 出力の確率的揺れに対して、Phase D で決定論的に検出
する第 2 防御層を追加する。生成側の予防 (Phase C プロンプト強化) と
2 段構え。

検出範囲 (v1 は警告のみ、自動修正なし):

1. wrong_speaker_voice: speaker=B が「のだ / なのだ / のだー」語尾で
   発話しているケース (B が A の語尾を使う致命的口調崩壊)。
   speaker=A の「ですわ / ですわね / ますわ」語尾の検出は対称性のため
   入れるが、こちらは本運用では未観測。

   注: ずんだもん (A) の「なのだ」過剰使用 (30-50% 目安) は Phase C
   プロンプト目安としてのみ運用し、Phase D の決定論検出対象には
   しない (目安違反は警告化しない設計判断、backlog §8)。

2. character_name_corruption: 任意の text 中にキャラ名の表記揺れ
   (「四国メタン」「四国メたん」「ズンダもん」「ずんだ門」等) が
   出現したケース。正規表記「ずんだもん」「四国めたん」は許容、
   揺れた表記のみを検出。

LLM コール禁止 (Phase D 決定論寄り設計の Guardrail §3.1)。
"""

from __future__ import annotations

import re

from radio_director.models.script import Script
from radio_director.models.verified_script import VerificationWarning

# めたん (B) が使ってはならない、ずんだもん語尾の suffix リスト
# 末尾の句読点・記号を除去後の最後の数文字に対する suffix 一致で判定
_B_FORBIDDEN_SUFFIXES = ("のだー", "なのだ", "のだ")

# ずんだもん (A) が使ってはならない、めたん語尾の suffix リスト
# (対称性のため検出、本運用未観測)
_A_FORBIDDEN_SUFFIXES = ("ですわね", "ですわ", "ますわ")

# テキスト末尾から除去する句読点・記号 (語尾判定用)
_TRAILING_PUNCT = "。、！？!?…．.,，~〜♪♡♥☆★ \n\t\r"

# キャラ名表記揺れ patterns (正規表記「ずんだもん」「四国めたん」のみ許容)
# 部分文字列マッチで検出。スペース無視。
_NAME_CORRUPTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 四国めたん の揺れ
    ("四国メたん", re.compile(r"四国メたん")),
    ("四国メタン", re.compile(r"四国メタン")),
    ("四国メータン", re.compile(r"四国メータン")),
    ("シコクメタン", re.compile(r"シコクメタン")),
    ("しこくめたん", re.compile(r"しこくめたん")),
    # ずんだもん の揺れ
    ("ズンダもん", re.compile(r"ズンダもん")),
    ("ずんだ門", re.compile(r"ずんだ門")),
    ("ずんだモン", re.compile(r"ずんだモン")),
    ("ズンダモン", re.compile(r"ズンダモン")),
)


def check_character_voice(script: Script) -> list[VerificationWarning]:
    """script 全体を走査して口調・名前表記の violation を warnings として返す。

    検出対象:
    - speaker=B が「のだ」「なのだ」「のだー」語尾 (致命的)
    - speaker=A が「ですわ」「ですわね」「ますわ」語尾 (対称性、未観測)
    - 任意 text 中のキャラ名表記揺れ
    """
    warnings: list[VerificationWarning] = []

    for seg in script.segments:
        seg_id = _segment_id(seg.segment_type, seg.topic_index)
        for turn_idx, turn in enumerate(seg.turns):
            voice_warning = _check_voice_suffix(turn.speaker, turn.text, seg_id, turn_idx)
            if voice_warning is not None:
                warnings.append(voice_warning)
            warnings.extend(_check_name_corruption(turn.text, seg_id, turn_idx))

    return warnings


def _segment_id(segment_type: str, topic_index: int | None) -> str:
    if segment_type == "deep_dive" and topic_index is not None:
        return f"deep_dive_{topic_index}"
    return segment_type


def _strip_trailing(text: str) -> str:
    return text.rstrip(_TRAILING_PUNCT)


def _check_voice_suffix(
    speaker: str, text: str, seg_id: str, turn_idx: int
) -> VerificationWarning | None:
    stripped = _strip_trailing(text)
    if not stripped:
        return None
    if speaker == "B":
        for suffix in _B_FORBIDDEN_SUFFIXES:
            if stripped.endswith(suffix):
                return VerificationWarning(
                    code="wrong_speaker_voice",
                    message=(
                        f"speaker=B (四国めたん) が A (ずんだもん) 語尾"
                        f"「{suffix}」を使っています (turn {turn_idx}): {stripped[-20:]!r}"
                    ),
                    location=seg_id,
                )
    elif speaker == "A":
        for suffix in _A_FORBIDDEN_SUFFIXES:
            if stripped.endswith(suffix):
                return VerificationWarning(
                    code="wrong_speaker_voice",
                    message=(
                        f"speaker=A (ずんだもん) が B (四国めたん) 語尾"
                        f"「{suffix}」を使っています (turn {turn_idx}): {stripped[-20:]!r}"
                    ),
                    location=seg_id,
                )
    return None


def _check_name_corruption(
    text: str, seg_id: str, turn_idx: int
) -> list[VerificationWarning]:
    findings: list[VerificationWarning] = []
    for label, pattern in _NAME_CORRUPTION_PATTERNS:
        if pattern.search(text):
            findings.append(
                VerificationWarning(
                    code="character_name_corruption",
                    message=(
                        f"キャラ名表記揺れ「{label}」を検出 (turn {turn_idx})。"
                        "正規表記「ずんだもん」「四国めたん」を使ってください。"
                    ),
                    location=seg_id,
                )
            )
    return findings
