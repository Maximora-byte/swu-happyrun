import hashlib

import pytest

from swu_happyrun.core.canonical import canonical_profile_json, profile_revision


def test_revision_has_fixed_cross_platform_vector():
    # revision itself is excluded, avoiding a self-referential hash.
    data = {"revision": "old", "b": [2, 1], "a": "学校"}
    expected = '{"a":"学校","b":[2,1]}'.encode()
    assert canonical_profile_json(data) == expected
    assert profile_revision(data) == hashlib.sha256(expected).hexdigest()
    assert profile_revision(data | {"revision": "new"}) == profile_revision(data)
    assert profile_revision({"b": [2, 1], "a": "学校"}) == profile_revision(data)


def test_nested_revision_is_part_of_content():
    assert profile_revision({"nested": {"revision": "a"}}) != profile_revision(
        {"nested": {"revision": "b"}}
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object()])
def test_non_json_values_rejected(value):
    with pytest.raises((ValueError, TypeError)):
        profile_revision({"value": value})
