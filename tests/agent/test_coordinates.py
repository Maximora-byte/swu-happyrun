"""Public algorithm vectors, not surveyed positions or campus/device evidence."""

import pytest

from swu_happyrun.core import coordinates
from swu_happyrun.core.models import RouteProfile


def test_wgs84_is_explicit_and_global():
    point = coordinates.to_wgs84(longitude=-180, latitude=90, source_crs="WGS84")
    assert (point.longitude, point.latitude) == (-180, 90)


@pytest.mark.parametrize("crs", ["", "wgs84", "WGS-84", "EPSG:4326", None, 1])
def test_unknown_crs_is_rejected(crs):
    with pytest.raises(ValueError, match="unknown_coordinate_system"):
        coordinates.to_wgs84(longitude=116.404, latitude=39.915, source_crs=crs)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, "39", None])
@pytest.mark.parametrize("axis", ["longitude", "latitude"])
def test_invalid_coordinate_types_rejected(value, axis):
    values = dict(longitude=116.404, latitude=39.915, source_crs="WGS84")
    values[axis] = value
    with pytest.raises(ValueError, match="invalid_coordinate"):
        coordinates.to_wgs84(**values)


@pytest.mark.parametrize("lon,lat", [(181, 0), (-181, 0), (0, 91), (0, -91), (39, 116)])
def test_global_bounds_and_detectable_swaps_rejected(lon, lat):
    with pytest.raises(ValueError, match="invalid_coordinate"):
        coordinates.to_wgs84(longitude=lon, latitude=lat, source_crs="WGS84")


@pytest.mark.parametrize("crs", ["GCJ02", "BD09"])
@pytest.mark.parametrize("lon,lat", [(0, 0), (73.66, 30), (135.05, 30), (110, 3.86), (110, 53.55)])
def test_non_wgs_domain_is_open_and_rejects_outside(crs, lon, lat):
    with pytest.raises(ValueError, match="coordinate_outside_conversion_domain"):
        coordinates.to_wgs84(longitude=lon, latitude=lat, source_crs=crs)


def test_gcj_inverse_against_independent_forward_vector():
    # wandergis README WGS84 -> GCJ02 vector; not a locally generated roundtrip.
    point = coordinates.to_wgs84(
        longitude=116.41024449916938, latitude=39.91640428150164, source_crs="GCJ02"
    )
    assert (point.longitude, point.latitude) == pytest.approx((116.404, 39.915), abs=1e-9)


def test_bd_inverse_against_independent_component_vectors():
    # Independent README BD09 -> GCJ02 vector, then the separately checked inverse.
    point = coordinates.to_wgs84(longitude=116.404, latitude=39.915, source_crs="BD09")
    expected = coordinates.to_wgs84(
        longitude=116.39762729119315, latitude=39.90865673957631, source_crs="GCJ02"
    )
    assert (point.longitude, point.latitude) == pytest.approx(
        (expected.longitude, expected.latitude), abs=1e-10
    )


def test_bd_intermediate_outside_domain_rejected():
    with pytest.raises(ValueError, match="coordinate_outside_conversion_domain"):
        coordinates.to_wgs84(longitude=73.6601, latitude=30, source_crs="BD09")


def test_normalize_points_preserves_original_profile_and_no_double_conversion():
    route = RouteProfile.model_validate(
        dict(
            route_id="00000000-0000-0000-0000-000000000001",
            revision="0" * 64,
            input_crs="GCJ02",
            source_ref="public_algorithm_vector",
            points=[dict(longitude=116.41024449916938, latitude=39.91640428150164)] * 2,
        )
    )
    before = route.model_dump()
    points = coordinates.normalize_points(route)
    assert isinstance(points, tuple)
    assert points[0].longitude == pytest.approx(116.404, abs=1e-9)
    assert route.model_dump() == before
    assert points[0] is not points[1]
    wgs = route.model_copy(update={"input_crs": "WGS84", "points": list(points)})
    assert coordinates.normalize_points(wgs) == points


def test_normalize_points_revalidates_bypassed_model():
    route = RouteProfile.model_construct(input_crs="UNKNOWN", points=[])
    with pytest.raises(ValueError):
        coordinates.normalize_points(route)


@pytest.mark.parametrize("crs", ["GCJ02", "BD09"])
def test_route_checks_use_normalized_wgs84_without_mutation(crs):
    from swu_happyrun.core.geo import route_distance_m, validate_route
    from swu_happyrun.core.models import GeoPoint, SchoolProfile

    # Public numeric vector and artificial test region, not a campus route.
    lon, lat = (
        (116.41024449916938, 39.91640428150164)
        if crs == "GCJ02"
        else (116.41662724378733, 39.922699552216216)
    )
    route = RouteProfile.model_validate(
        dict(
            route_id="00000000-0000-0000-0000-000000000001",
            revision="0" * 64,
            input_crs=crs,
            source_ref="synthetic_conversion_check",
            points=[dict(longitude=lon, latitude=lat), dict(longitude=lon + 0.0001, latitude=lat)],
        )
    )
    school = SchoolProfile.model_validate(
        dict(
            profile_id="00000000-0000-0000-0000-000000000002",
            revision="0" * 64,
            campus="synthetic",
            app_package="test.fake",
            app_version="test",
            confirmed=True,
            checkpoint_source="manual_confirmed",
            allowed_region=[
                dict(longitude=x, latitude=y)
                for x, y in [
                    (116.403, 39.914),
                    (116.405, 39.914),
                    (116.405, 39.916),
                    (116.403, 39.916),
                ]
            ],
            rules=dict(
                minimum_distance_m=1.0,
                maximum_duration_seconds=100.0,
                minimum_speed_mps=0.0,
                maximum_speed_mps=10.0,
            ),
        )
    )
    before = route.model_dump()
    assert validate_route(route, school) == []
    assert 7 < route_distance_m(route) < 10
    assert route.model_dump() == before
    school.allowed_region = [
        GeoPoint(longitude=p.longitude + 1, latitude=p.latitude) for p in school.allowed_region
    ]
    assert "route_outside_boundary" in validate_route(route, school)


def test_distance_between_wgs84_points_known_arc_and_validation():
    from swu_happyrun.core import geo
    from swu_happyrun.core.models import GeoPoint

    a = GeoPoint(longitude=0.0, latitude=0.0)
    b = GeoPoint(longitude=1.0, latitude=0.0)
    assert geo.distance_between_points_m(a, b) == pytest.approx(111195.080, abs=0.01)
    with pytest.raises(ValueError):
        geo.distance_between_points_m(a.model_copy(update={"latitude": float("nan")}), b)
