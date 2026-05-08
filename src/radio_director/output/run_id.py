"""run_id 命名規則 (Step 1 SSOT 化)。

形式: {YYYY-MM-DD}_{HH-MM}_{theme_slug}
theme_slug は ASCII の英数字とハイフンのみで最大 40 字。日本語は
'theme' にフォールバック (重複時は writer 側で _2/_3 が付与される)。
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

_SLUG_NON_ASCII = re.compile(r"[^a-z0-9-]+")
_SLUG_REPEATED_DASH = re.compile(r"-+")
SLUG_MAX_LEN = 40


def slugify(theme: str) -> str:
    """theme を ASCII slug に正規化する。

    日本語 / 全角文字は ASCII 化できずに落ちて 'theme' にフォールバック。
    v2 で pykakasi 等のローマ字化を検討する余地あり (本タスクは YAGNI)。
    """
    normalized = unicodedata.normalize("NFKD", theme or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_NON_ASCII.sub("-", ascii_only)
    slug = _SLUG_REPEATED_DASH.sub("-", slug).strip("-")
    return slug[:SLUG_MAX_LEN] or "theme"


def build_run_id(theme: str, *, now: datetime | None = None) -> str:
    """run_id 文字列を構築する。

    Args:
        theme: 番組テーマ (ASCII / 日本語のいずれも可)
        now: 時刻 (テスト用に注入可能、デフォルト現在時刻)

    Returns:
        "{YYYY-MM-DD}_{HH-MM}_{theme_slug}" 形式の文字列
    """
    now = now or datetime.now()
    return f"{now.strftime('%Y-%m-%d_%H-%M')}_{slugify(theme)}"
