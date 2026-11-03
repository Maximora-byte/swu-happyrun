import pytest

from swu_happyrun.core.coordinates import to_wgs84
from swu_happyrun.core.geo import distance_between_points_m
from swu_happyrun.core.models import GeoPoint
from swu_happyrun.desktop.mumu_mapping import vendor_point


@pytest.mark.parametrize("latitude,longitude", [(30.0, 110.0), (31.0, 121.0), (40.0, 116.0)])
def test_bd09_vendor_input_round_trips_to_wgs84(latitude, longitude):
    # Synthetic mathematical fixtures, not campus points or device evidence.
    source = GeoPoint(latitude=latitude, longitude=longitude)
    raw = vendor_point(source)
    assert distance_between_points_m(raw, source) > 500
    result = to_wgs84(longitude=raw.longitude, latitude=raw.latitude, source_crs="BD09")
    assert distance_between_points_m(source, result) < 0.2


def test_unsupported_conversion_domain_is_rejected():
    with pytest.raises(ValueError, match="coordinate_outside_conversion_domain"):
        vendor_point(GeoPoint(latitude=0.2, longitude=0.2))
