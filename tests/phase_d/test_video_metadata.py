"""VideoMetadata / SourceRef / Chapter の Pydantic 検証 (Step 1 SSOT 化)。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from radio_director.models.video_metadata import (
    Chapter,
    SourceRef,
    VideoMetadata,
)


def _valid_metadata_kwargs(**overrides):
    base = {
        "title": "テスト動画",
        "thumbnail_title": "テスト",
        "description": "x" * 60,
        "hashtags": ["a", "b", "c"],
        "chapters": [
            Chapter(timestamp="00:00", title="イントロ"),
            Chapter(timestamp="00:30", title="まとめ"),
        ],
    }
    base.update(overrides)
    return base


def test_well_formed_metadata():
    md = VideoMetadata(**_valid_metadata_kwargs())
    assert md.thumbnail_title == "テスト"
    assert md.references == []  # default empty


def test_thumbnail_title_15_chars_ok():
    md = VideoMetadata(
        **_valid_metadata_kwargs(thumbnail_title="あいうえおかきくけこさしすせそ")  # 15
    )
    assert len(md.thumbnail_title) == 15


def test_thumbnail_title_16_chars_raises():
    with pytest.raises(ValidationError):
        VideoMetadata(
            **_valid_metadata_kwargs(thumbnail_title="あいうえおかきくけこさしすせそた")  # 16
        )


def test_thumbnail_title_empty_raises():
    with pytest.raises(ValidationError):
        VideoMetadata(**_valid_metadata_kwargs(thumbnail_title=""))


def test_thumbnail_title_missing_raises():
    kwargs = _valid_metadata_kwargs()
    kwargs.pop("thumbnail_title")
    with pytest.raises(ValidationError):
        VideoMetadata(**kwargs)


def test_source_ref_minimal():
    ref = SourceRef(url="https://nature.com/x")
    assert str(ref.url).startswith("https://nature.com/")
    assert ref.title is None
    assert ref.tier is None


def test_source_ref_full():
    ref = SourceRef(url="https://nature.com/x", title="サンプル論文", tier="AAA")
    assert ref.tier == "AAA"
    assert ref.title == "サンプル論文"


def test_source_ref_invalid_url_raises():
    with pytest.raises(ValidationError):
        SourceRef(url="not-a-url")


def test_source_ref_invalid_tier_raises():
    with pytest.raises(ValidationError):
        SourceRef(url="https://nature.com/x", tier="Z")


def test_video_metadata_with_references():
    refs = [
        SourceRef(url="https://nature.com/a", title="A", tier="AAA"),
        SourceRef(url="https://example.com/b", tier="B"),
    ]
    md = VideoMetadata(**_valid_metadata_kwargs(references=refs))
    assert len(md.references) == 2
    assert md.references[0].tier == "AAA"
