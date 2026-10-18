"""Read-only, exact-revision local JSON configuration lookup."""

import json
from pathlib import Path

from pydantic import ValidationError

from swu_happyrun.core.canonical import profile_revision
from swu_happyrun.core.geo import validate_route
from swu_happyrun.core.models import JobSpec, RouteProfile, SchoolProfile


class ProfileError(ValueError):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProfileError("duplicate_profile_key")
        result[key] = value
    return result


class LocalProfileStore:
    """Private, locally controlled files; never fetch source_ref as a URL.

    Layout: schools/<UUID>/<SHA256>.json and routes/<UUID>/<SHA256>.json.
    The configuration directory must not be writable by untrusted users.
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _read(self, folder, identifier, revision, model):
        path = self.root / folder / identifier / f"{revision}.json"
        try:
            # Reject even in-root symlinks: references must be ordinary files.
            if any(p.is_symlink() for p in (path, path.parent, path.parent.parent)):
                raise ProfileError("profile_path_unsafe")
            if not path.resolve(strict=True).is_relative_to(self.root):
                raise ProfileError("profile_path_unsafe")
            if path.stat().st_size > 1_000_000:
                raise ProfileError("profile_too_large")
            with path.open(encoding="utf-8") as handle:
                data = json.load(handle, object_pairs_hook=_unique_keys)
            value = model.model_validate(data)
        except ProfileError:
            raise
        except (OSError, UnicodeError, ValueError, TypeError):
            raise ProfileError("profile_unavailable_or_invalid") from None
        id_field = "profile_id" if model is SchoolProfile else "route_id"
        if getattr(value, id_field) != identifier:
            raise ProfileError("profile_id_mismatch")
        if value.revision != revision or profile_revision(value) != revision:
            raise ProfileError("profile_revision_mismatch")
        return value

    def resolve(
        self, job: JobSpec, *, app_version: str | None
    ) -> tuple[SchoolProfile, RouteProfile]:
        try:
            job = JobSpec.model_validate(job.model_dump(mode="python"))
        except (ValidationError, ValueError, TypeError, AttributeError):
            raise ProfileError("invalid_job") from None
        school = self._read("schools", job.profile_id, job.profile_revision, SchoolProfile)
        route = self._read("routes", job.route_id, job.route_revision, RouteProfile)
        if (
            app_version is None
            or app_version != school.app_version
            or (job.mode == "device" and job.expected_app_version != school.app_version)
        ):
            raise ProfileError("app_version_mismatch")
        reasons = validate_route(route, school)
        if reasons:
            raise ProfileError(reasons[0])
        return school, route
