"""Synthetic coordinates only; no school or device acceptance evidence."""

import pytest

from swu_happyrun.core.canonical import profile_revision
from swu_happyrun.core.models import RouteProfile, SchoolProfile


def profiles():
    school = SchoolProfile.model_validate(
        dict(
            profile_id="00000000-0000-0000-0000-000000000001",
            revision="0" * 64,
            campus="synthetic",
            app_package="test.fake",
            app_version="test-1",
            confirmed=True,
            allowed_region=[
                dict(latitude=y, longitude=x) for x, y in [(0, 0), (1, 0), (1, 1), (0, 1)]
            ],
            rules=dict(
                minimum_distance_m=1.0,
                maximum_duration_seconds=100000.0,
                minimum_speed_mps=0.0,
                maximum_speed_mps=10.0,
            ),
            checkpoint_source="manual_confirmed",
        )
    )
    route = RouteProfile.model_validate(
        dict(
            route_id="00000000-0000-0000-0000-000000000002",
            revision="0" * 64,
            input_crs="WGS84",
            points=[dict(latitude=0.2, longitude=0.2), dict(latitude=0.3, longitude=0.3)],
            source_ref="synthetic",
        )
    )
    school.revision = profile_revision(school)
    route.revision = profile_revision(route)
    return school, route


def test_valid_synthetic_route():
    from swu_happyrun.core.geo import validate_route

    school, route = profiles()
    assert validate_route(route, school) == []


@pytest.mark.parametrize(
    "change", ["crs", "nan", "outside", "boundary", "unconfirmed", "rules", "zero"]
)
def test_invalid_route_rejected(change):
    from swu_happyrun.core.geo import validate_route

    school, route = profiles()
    if change == "crs":
        route = route.model_copy(update={"input_crs": ""})
    elif change == "nan":
        route.points[0] = route.points[0].model_copy(update={"latitude": float("nan")})
    elif change == "outside":
        route.points[0].latitude = 2.0
    elif change == "boundary":
        school = school.model_copy(update={"allowed_region": []})
    elif change == "unconfirmed":
        school.confirmed = False
    elif change == "rules":
        school.rules.clear()
    elif change == "zero":
        route.points[1] = route.points[0].model_copy()
    assert validate_route(route, school)


@pytest.mark.parametrize("crs", ["GCJ02", "BD09"])
def test_unverified_conversion_is_rejected(crs):
    from swu_happyrun.core.geo import validate_route

    school, route = profiles()
    route.input_crs = crs
    assert "coordinate_conversion_unverified" in validate_route(route, school)


def test_concave_boundary_rejects_segment_leaving_polygon():
    from swu_happyrun.core.geo import validate_route
    from swu_happyrun.core.models import GeoPoint

    school, route = profiles()
    school.allowed_region = [
        GeoPoint(longitude=x, latitude=y)
        for x, y in [
            (0.0, 0.0),
            (3.0, 0.0),
            (3.0, 3.0),
            (2.0, 3.0),
            (2.0, 1.0),
            (1.0, 1.0),
            (1.0, 3.0),
            (0.0, 3.0),
        ]
    ]
    route.points = [GeoPoint(longitude=0.5, latitude=2.0), GeoPoint(longitude=2.5, latitude=2.0)]
    assert "route_outside_boundary" in validate_route(route, school)


def test_self_intersecting_boundary_rejected():
    from swu_happyrun.core.geo import validate_route

    school, route = profiles()
    school.allowed_region[1], school.allowed_region[2] = (
        school.allowed_region[2],
        school.allowed_region[1],
    )
    assert "invalid_boundary" in validate_route(route, school)


def test_adjacent_boundary_backtracking_is_invalid():
    from swu_happyrun.core.geo import validate_route
    from swu_happyrun.core.models import GeoPoint

    school, route = profiles()
    school.allowed_region = [
        GeoPoint(longitude=x, latitude=y)
        for x, y in [(0.0, 0.0), (1.0, 0.0), (0.5, 0.0), (1.0, 1.0), (0.0, 1.0)]
    ]
    assert "invalid_boundary" in validate_route(route, school)


@pytest.mark.parametrize(
    "rules",
    [
        {"maximum_speed_mps": 0.0},
        {"maximum_duration_seconds": 0.0},
        {"maximum_duration_seconds": 1.0},
        {"minimum_distance_m": 1000000.0},
    ],
)
def test_impossible_rules_reject_route(rules):
    from swu_happyrun.core.geo import validate_route

    school, route = profiles()
    school.rules.update(rules)
    assert validate_route(route, school)


def test_distance_known_equatorial_arc():
    from swu_happyrun.core.geo import route_distance_m
    from swu_happyrun.core.models import GeoPoint

    _, route = profiles()
    route.points = [GeoPoint(latitude=0.0, longitude=0.0), GeoPoint(latitude=0.0, longitude=1.0)]
    assert route_distance_m(route) == pytest.approx(111195.080, abs=0.01)


@pytest.mark.parametrize("crs", ["GCJ02", "BD09"])
def test_distance_does_not_silently_treat_other_crs_as_wgs84(crs):
    from swu_happyrun.core.geo import route_distance_m

    _, route = profiles()
    route.input_crs = crs
    with pytest.raises(ValueError, match="coordinate_conversion_unverified"):
        route_distance_m(route)
