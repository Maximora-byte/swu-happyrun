"""Native fake fixture uses the sole Python schema/canonical rules, no school data."""

import json
from pathlib import Path

import pytest

from swu_happyrun.core.canonical import canonical_profile_json, profile_revision
from swu_happyrun.core.geo import validate_route
from swu_happyrun.core.models import RouteProfile, SchoolProfile

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "android/app/src/main/resources/remote-simulation"


@pytest.mark.parametrize("name,model", [("school", SchoolProfile), ("route", RouteProfile)])
def test_native_bundled_profiles_are_exact_python_canonical(name, model):
    value = model.model_validate(json.loads((ASSETS / f"{name}.json").read_text()))
    assert value.revision == profile_revision(value)
    assert (ASSETS / f"{name}.canonical.json").read_bytes() == canonical_profile_json(value)


def test_native_fixture_is_valid_explicit_synthetic_short_route():
    school = SchoolProfile.model_validate_json((ASSETS / "school.json").read_bytes())
    route = RouteProfile.model_validate_json((ASSETS / "route.json").read_bytes())
    assert validate_route(route, school) == []
    assert school.campus == route.source_ref == "synthetic-only"
    assert school.app_package == "test.fake"
    assert route.input_crs == "WGS84"
