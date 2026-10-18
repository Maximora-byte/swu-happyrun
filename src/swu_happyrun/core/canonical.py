"""Version 1 Python JSON canonicalization, not RFC 8785/JCS."""

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def canonical_profile_json(profile: BaseModel | dict[str, Any]) -> bytes:
    """Hash content excluding only the top-level self-referential revision.

    sort_keys, compact separators, UTF-8, ensure_ascii=False, allow_nan=False.
    Array order and numeric representation (1 versus 1.0) are significant;
    callers hash validated model_dump(mode='json') data consistently.
    """
    data = profile.model_dump(mode="json") if isinstance(profile, BaseModel) else dict(profile)
    data.pop("revision", None)
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def profile_revision(profile: BaseModel | dict[str, Any]) -> str:
    return hashlib.sha256(canonical_profile_json(profile)).hexdigest()
