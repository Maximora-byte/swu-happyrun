"""Synthetic metadata only; no real app page, identifier or route is a fixture."""

import json

import pytest


def inventory():
    return {
        "schema_version": 1,
        "provenance": "synthetic",
        "app_package": "example.synthetic.app",
        "app_version": "0.0.0-test",
        "android_version": "15",
        "environment_version": "0.0.0-test",
        "profile_id": "00000000-0000-0000-0000-000000000001",
        "profile_revision": "a" * 64,
        "rules_digest": "b" * 64,
        "point_source_digest": "c" * 64,
        "crs": "WGS84",
        "states": ["start", "running", "ended", "upload_pending", "valid", "invalid", "unknown"],
        "record_binding_reviewed": True,
    }


def validate(data, **kwargs):
    from swu_happyrun.drivers.adapter_inputs import validate_sample_inventory

    return validate_sample_inventory(json.dumps(data), **kwargs)


def test_inventory_is_only_offline_review_not_execution_permission():
    result = validate(inventory())
    assert result.app_version == "0.0.0-test"
    assert not hasattr(result, "capabilities")
    assert not hasattr(result, "evidence")


@pytest.mark.parametrize(
    "field",
    [
        "Authorization",
        "Cookie",
        "token",
        "password",
        "signature",
        "serial",
        "account",
        "screenshot",
        "route",
        "payload",
    ],
)
def test_unknown_or_sensitive_fields_rejected_without_echo(field):
    data = inventory()
    data[field] = {"nested": "synthetic-secret-never-echo"}
    with pytest.raises(ValueError) as error:
        validate(data)
    assert str(error.value) == "invalid_sample_inventory"
    assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("app_version", ""),
        ("android_version", "unknown"),
        ("environment_version", "latest"),
        ("crs", "unknown"),
        ("profile_revision", "bad"),
        ("record_binding_reviewed", False),
        ("states", ["start"]),
        ("schema_version", True),
        ("provenance", "raw"),
        ("app_package", "https://example.invalid/?token=secret"),
    ],
)
def test_missing_or_unreviewed_metadata_rejected(field, value):
    data = inventory()
    data[field] = value
    with pytest.raises(ValueError, match="^invalid_sample_inventory$"):
        validate(data)


@pytest.mark.parametrize("field", list(inventory()))
def test_every_required_field_is_required(field):
    data = inventory()
    del data[field]
    with pytest.raises(ValueError):
        validate(data)


def test_context_must_match_exact_version_and_profile():
    data = inventory()
    validate(
        data,
        expected_app_version=data["app_version"],
        expected_profile_revision=data["profile_revision"],
    )
    for mismatch in [{"expected_app_version": "9.9"}, {"expected_profile_revision": "d" * 64}]:
        with pytest.raises(ValueError, match="^sample_context_mismatch$"):
            validate(data, **mismatch)


@pytest.mark.parametrize(
    "text",
    ['{"schema_version":1,"schema_version":1}', "null", "[]", "{", "x" * 65537],
    ids=["duplicate-keys", "null", "array", "malformed", "over-limit"],
)
def test_bad_json_duplicate_keys_and_large_inputs_rejected(text):
    from swu_happyrun.drivers.adapter_inputs import validate_sample_inventory

    with pytest.raises(ValueError, match="^invalid_sample_inventory$"):
        validate_sample_inventory(text)
