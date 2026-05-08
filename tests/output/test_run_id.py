"""run_id 命名規則の単体テスト。"""

from __future__ import annotations

from datetime import datetime

from radio_director.output.run_id import SLUG_MAX_LEN, build_run_id, slugify


def test_slugify_ascii_simple():
    assert slugify("Yuru Stoic Philosophy") == "yuru-stoic-philosophy"


def test_slugify_with_punctuation():
    assert slugify("AI / Machine Learning!") == "ai-machine-learning"


def test_slugify_japanese_falls_back_to_theme():
    assert slugify("ゆるストイック哲学") == "theme"


def test_slugify_mixed_japanese_and_ascii():
    """混在では ASCII 部分のみ残る。"""
    assert slugify("AI と人工知能") == "ai"


def test_slugify_empty_input():
    assert slugify("") == "theme"


def test_slugify_only_punctuation():
    assert slugify("!!!???") == "theme"


def test_slugify_max_length_truncated():
    long = "a" * 100
    result = slugify(long)
    assert len(result) == SLUG_MAX_LEN
    assert result == "a" * SLUG_MAX_LEN


def test_slugify_repeated_dashes_collapsed():
    assert slugify("foo---bar___baz") == "foo-bar-baz"


def test_build_run_id_format():
    now = datetime(2026, 5, 9, 20, 15, 32)
    assert build_run_id("Sleep and Immunity", now=now) == "2026-05-09_20-15_sleep-and-immunity"


def test_build_run_id_japanese_theme():
    now = datetime(2026, 5, 9, 20, 15, 32)
    assert build_run_id("ゆるストイック", now=now) == "2026-05-09_20-15_theme"
