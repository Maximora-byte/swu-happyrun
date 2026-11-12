"""Offline inventory gate. Never parses raw pages or grants device capabilities.

This is an allowlisted metadata format, not a sanitizer or a proof that input
is free of personal data. Keep source samples private and review them manually.
No selector, protocol signature, record evidence or live adapter is implemented.
"""

import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from swu_happyrun.core.models import Digest, ProtocolVersion, UUIDString

Version = Annotated[str, StringConstraints(pattern=r"^[0-9][0-9A-Za-z._+-]{0,63}$")]
Package = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", max_length=200)
]
PageState = Literal["start", "running", "ended", "upload_pending", "valid", "invalid", "unknown"]
_REQUIRED_STATES = {"start", "running", "ended", "upload_pending", "valid", "invalid", "unknown"}


class SampleInventory(BaseModel):
    """Private review metadata, deliberately separate from shared wire models."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)
    schema_version: ProtocolVersion
    provenance: Literal["synthetic", "locally_redacted"]
    app_package: Package
    app_version: Version
    android_version: Version
    environment_version: Version
    profile_id: UUIDString
    profile_revision: Digest
    rules_digest: Digest
    point_source_digest: Digest
    crs: Literal["WGS84", "GCJ02", "BD09"]
    states: list[PageState]
    record_binding_reviewed: bool

    @model_validator(mode="after")
    def review_complete(self) -> Self:
        if set(self.states) != _REQUIRED_STATES or len(self.states) != len(_REQUIRED_STATES):
            raise ValueError("state_inventory_incomplete")
        if not self.record_binding_reviewed:
            raise ValueError("record_binding_unreviewed")
        return self


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def validate_sample_inventory(
    text: str,
    *,
    expected_app_version: str | None = None,
    expected_profile_revision: str | None = None,
) -> SampleInventory:
    """Reject unknown fields; never echo payloads, fetch references or write files.

    A successful result only means this inventory is structurally complete.
    Reviewers must establish provenance and actual page/record semantics locally.
    """
    try:
        if not isinstance(text, str) or len(text.encode("utf-8")) > 65536:
            raise ValueError("size_limit")
        data = json.loads(text, object_pairs_hook=_unique_keys)
        result = SampleInventory.model_validate(data)
    except (ValueError, TypeError, RecursionError):
        raise ValueError("invalid_sample_inventory") from None
    if (expected_app_version is not None and result.app_version != expected_app_version) or (
        expected_profile_revision is not None
        and result.profile_revision != expected_profile_revision
    ):
        raise ValueError("sample_context_mismatch")
    return result
