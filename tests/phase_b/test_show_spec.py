"""ShowSpec / TopicSpec / Claim の Pydantic 検証。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from radio_director.models.show_spec import ShowSpec

from tests.phase_b._factories import make_claim, make_show_spec, make_topic


def test_validates_well_formed_payload():
    show = ShowSpec.model_validate(make_show_spec())
    assert show.title == "寝不足が免疫を壊す？"
    assert len(show.topics) == 2


def test_invalid_source_tier_raises():
    bad = make_show_spec(
        topics=[make_topic(key_claims=[make_claim(source_tier="Z")])] * 2,
    )
    with pytest.raises(ValidationError):
        ShowSpec.model_validate(bad)


def test_invalid_confidence_raises():
    bad = make_show_spec(
        topics=[make_topic(key_claims=[make_claim(confidence="unknown")])] * 2,
    )
    with pytest.raises(ValidationError):
        ShowSpec.model_validate(bad)


def test_topic_count_too_low_raises():
    bad = make_show_spec(topics=[make_topic()])  # 1 件
    with pytest.raises(ValidationError):
        ShowSpec.model_validate(bad)


def test_topic_count_too_high_raises():
    bad = make_show_spec(topics=[make_topic()] * 5)
    with pytest.raises(ValidationError):
        ShowSpec.model_validate(bad)


def test_zero_key_claims_raises():
    bad = make_show_spec(
        topics=[make_topic(key_claims=[])] * 2,
    )
    with pytest.raises(ValidationError):
        ShowSpec.model_validate(bad)


def test_estimated_turns_zero_raises():
    bad = make_show_spec(
        topics=[make_topic(estimated_turns=0)] * 2,
    )
    with pytest.raises(ValidationError):
        ShowSpec.model_validate(bad)


def test_extra_top_level_fields_ignored():
    payload = make_show_spec()
    payload["bogus_field"] = "abc"
    show = ShowSpec.model_validate(payload)
    assert not hasattr(show, "bogus_field")


def test_thumbnail_title_boundary_15_chars_ok():
    payload = make_show_spec(thumbnail_title="あいうえおかきくけこさしすせそ")  # 15 chars
    show = ShowSpec.model_validate(payload)
    assert show.thumbnail_title == "あいうえおかきくけこさしすせそ"


def test_thumbnail_title_16_chars_raises():
    payload = make_show_spec(thumbnail_title="あいうえおかきくけこさしすせそた")  # 16 chars
    with pytest.raises(ValidationError):
        ShowSpec.model_validate(payload)


def test_thumbnail_title_empty_raises():
    payload = make_show_spec(thumbnail_title="")
    with pytest.raises(ValidationError):
        ShowSpec.model_validate(payload)


def test_thumbnail_title_missing_raises():
    payload = make_show_spec()
    payload.pop("thumbnail_title")
    with pytest.raises(ValidationError):
        ShowSpec.model_validate(payload)
