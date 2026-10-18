import json
from datetime import UTC, datetime, timedelta

import pytest
from test_geo import profiles

from swu_happyrun.core.models import JobSpec


def setup_profiles(root):
    school, route = profiles()
    for folder, identifier, model in [
        ("schools", school.profile_id, school),
        ("routes", route.route_id, route),
    ]:
        path = root / folder / identifier / f"{model.revision}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(model.model_dump_json())
    job = JobSpec(
        protocol_version=1,
        expected_app_version=None,
        mode="simulation",
        profile_id=school.profile_id,
        profile_revision=school.revision,
        route_id=route.route_id,
        route_revision=route.revision,
        device_id="00000000-0000-0000-0000-000000000003",
        not_before=datetime.now(UTC),
        deadline=datetime.now(UTC) + timedelta(hours=1),
    )
    return job, school, route


def test_resolve_exact_local_profiles(tmp_path):
    from swu_happyrun.core.profiles import LocalProfileStore

    job, school, route = setup_profiles(tmp_path)
    assert LocalProfileStore(tmp_path).resolve(job, app_version=school.app_version) == (
        school,
        route,
    )


@pytest.mark.parametrize("change", ["missing", "digest", "app", "id", "traversal", "symlink"])
def test_profile_resolution_fail_closed(tmp_path, change):
    from swu_happyrun.core.profiles import LocalProfileStore, ProfileError

    root = tmp_path / "profiles"
    job, school, route = setup_profiles(root)
    path = root / "routes" / route.route_id / f"{route.revision}.json"
    app = school.app_version
    if change == "missing":
        path.unlink()
    elif change == "digest":
        data = json.loads(path.read_text())
        data["source_ref"] = "modified"
        path.write_text(json.dumps(data))
    elif change == "app":
        app = "wrong-version"
    elif change == "id":
        data = json.loads(path.read_text())
        data["route_id"] = school.profile_id
        path.write_text(json.dumps(data))
    elif change == "traversal":
        job = job.model_copy(update={"route_id": "../../outside"})
    elif change == "symlink":
        target = tmp_path / "outside.json"
        target.write_text(path.read_text())
        path.unlink()
        path.symlink_to(target)
    with pytest.raises(ProfileError):
        LocalProfileStore(root).resolve(job, app_version=app)


def test_duplicate_json_key_rejected(tmp_path):
    from swu_happyrun.core.profiles import LocalProfileStore, ProfileError

    job, school, route = setup_profiles(tmp_path)
    path = tmp_path / "routes" / route.route_id / f"{route.revision}.json"
    path.write_text(path.read_text().replace("{", '{"source_ref":"ignored",', 1))
    with pytest.raises(ProfileError, match="duplicate_profile_key"):
        LocalProfileStore(tmp_path).resolve(job, app_version=school.app_version)


def test_profile_source_ref_is_never_fetched(tmp_path):
    from swu_happyrun.core.canonical import profile_revision
    from swu_happyrun.core.profiles import LocalProfileStore

    job, school, route = setup_profiles(tmp_path)
    route.source_ref = "https://invalid.example/must-not-fetch"
    route.revision = profile_revision(route)
    path = tmp_path / "routes" / route.route_id / f"{route.revision}.json"
    path.write_text(route.model_dump_json())
    job.route_revision = route.revision
    assert LocalProfileStore(tmp_path).resolve(job, app_version=school.app_version)[1] == route


def test_device_expected_version_must_match_profile_and_observation(tmp_path):
    from swu_happyrun.core.profiles import LocalProfileStore, ProfileError

    job, school, _ = setup_profiles(tmp_path)
    job = job.model_copy(update={"mode": "device", "expected_app_version": "different"})
    with pytest.raises(ProfileError, match="app_version_mismatch"):
        LocalProfileStore(tmp_path).resolve(job, app_version=school.app_version)
