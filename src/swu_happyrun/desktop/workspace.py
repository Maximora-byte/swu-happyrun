"""Persistent synthetic identities and profiles; no account or credential storage."""

import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from swu_happyrun.core.canonical import profile_revision
from swu_happyrun.core.models import JobSpec, RouteProfile, SchoolProfile, UUIDString


class _Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: int = Field(alias="schema")
    agent_id: UUIDString
    device_id: UUIDString
    profile_id: UUIDString
    route_id: UUIDString


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("workspace_invalid")
        result[key] = value
    return result


def _check_path(path):
    for part in [*reversed(path.parents), path]:
        if part.is_symlink() or (
            part.exists()
            and getattr(part.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("workspace_link_not_allowed")


def _write_new(path, value):
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


@dataclass(frozen=True)
class Workspace:
    root: Path
    agent_id: str
    device_id: str
    school: SchoolProfile
    route: RouteProfile

    @classmethod
    def open(cls, root: Path):
        root = Path(root).absolute()
        if ".." in root.parts:
            raise ValueError("workspace_invalid")
        _check_path(root)
        if os.name == "nt":
            from swu_happyrun.drivers.mumu.windows_private import (
                provision_private_directory,
                verify_directory,
            )

            if not root.exists():
                provision_private_directory(root)
            verify_directory(root)
        else:
            root.mkdir(mode=0o700, parents=False, exist_ok=True)
            if root.stat().st_mode & 0o077:
                raise ValueError("workspace_must_be_private")
        path = root / "workspace.json"
        _check_path(path)
        if not path.exists():
            config = _Configuration(
                schema=1,
                **{
                    key: str(uuid4()) for key in ("agent_id", "device_id", "profile_id", "route_id")
                },
            )
            try:
                _write_new(path, config.model_dump(by_alias=True))
            except FileExistsError:
                pass  # Concurrent first launch uses the one persisted identity.
        if path.stat().st_size > 4096:
            raise ValueError("workspace_invalid")
        config = _Configuration.model_validate(
            json.loads(path.read_bytes(), object_pairs_hook=_unique)
        )
        if config.schema_version != 1:
            raise ValueError("workspace_version_unsupported")
        school = SchoolProfile(
            profile_id=config.profile_id,
            revision="0" * 64,
            campus="synthetic-desktop-only",
            app_package="test.fake",
            app_version="test-1",
            confirmed=True,
            allowed_region=[
                {"latitude": lat, "longitude": lon} for lat, lon in [(0, 0), (0, 1), (1, 1), (1, 0)]
            ],
            rules={
                "minimum_distance_m": 1.0,
                "maximum_duration_seconds": 120.0,
                "minimum_speed_mps": 1.0,
                "maximum_speed_mps": 10.0,
            },
            checkpoint_source="manual_confirmed",
        )
        route = RouteProfile(
            route_id=config.route_id,
            revision="0" * 64,
            input_crs="WGS84",
            points=[{"latitude": 0.2, "longitude": 0.2}, {"latitude": 0.2, "longitude": 0.2002}],
            source_ref="synthetic-desktop-only",
        )
        for folder, identifier, model in (
            ("schools", school.profile_id, school),
            ("routes", route.route_id, route),
        ):
            model.revision = profile_revision(model)
            target = root / "profiles" / folder / identifier / f"{model.revision}.json"
            _check_path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            expected = model.model_dump(mode="json")
            if not target.exists():
                try:
                    _write_new(target, expected)
                except FileExistsError:
                    pass
            if (
                target.stat().st_size > 16384
                or json.loads(target.read_bytes(), object_pairs_hook=_unique) != expected
            ):
                raise ValueError("workspace_profile_changed")
        return cls(root, config.agent_id, config.device_id, school, route)

    def job_spec(self, now=None):
        now = now or datetime.now(UTC)
        return JobSpec(
            protocol_version=1,
            mode="simulation",
            expected_app_version=None,
            profile_id=self.school.profile_id,
            profile_revision=self.school.revision,
            route_id=self.route.route_id,
            route_revision=self.route.revision,
            device_id=self.device_id,
            not_before=now - timedelta(seconds=1),
            deadline=now + timedelta(minutes=5),
        )
