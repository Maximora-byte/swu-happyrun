"""Only synthetic coordinates: these are not campus geometry."""

import hashlib
import json
from copy import deepcopy

import pytest

from swu_happyrun.core.canonical import profile_revision
from swu_happyrun.core.geo import validate_route
from swu_happyrun.core.map_candidates import MapInputError, import_candidate
from swu_happyrun.core.models import SchoolProfile


def sample(field=4):
    nodes = [
        (1, 0.0, 0.0),
        (2, 4.0, 0.0),
        (3, 4.0, 4.0),
        (4, 0.0, 4.0),
        (5, 1.0, 1.0),
        (6, 3.0, 1.0),
        (7, 3.0, 3.0),
        (8, 1.0, 3.0),
        (3724521740, 2.0, 2.0),
    ]
    parts = ['<osm version="0.6">']
    for i, x, y in nodes:
        tag = '<tag k="name" v="西南大学第４运动场"/>' if i == 3724521740 else ""
        parts.append(f'<node id="{i}" version="1" lon="{x}" lat="{y}">{tag}</node>')
    parts += [
        '<way id="413071891" version="21">',
        *[f'<nd ref="{i}"/>' for i in [1, 2, 3, 4, 1]],
        '<tag k="amenity" v="university"/><tag k="name" v="西南大学"/></way>',
        '<way id="368577141" version="3">',
        *[f'<nd ref="{i}"/>' for i in [5, 6, 7, 8, 5]],
        '<tag k="leisure" v="track"/></way>',
        "</osm>",
    ]
    return "".join(parts).encode()


def meta(data):
    return dict(
        crs="WGS84",
        axis_order="longitude,latitude",
        retrieved_at="2026-10-19T09:00:00Z",
        source_sha256=hashlib.sha256(data).hexdigest(),
        amap_status="not_configured",
        tencent_status="empty",
    )


def run(tmp_path, data=None, metadata=None, fmt="osm"):
    data = sample() if data is None else data
    path = tmp_path / ("input." + fmt)
    path.write_bytes(data)
    return import_candidate(
        path, format=fmt, field=4, metadata=meta(data) if metadata is None else metadata
    )


def test_candidate_preserves_order_revision_and_private_boundary(tmp_path):
    result = run(tmp_path)
    assert [(p.longitude, p.latitude) for p in result.route.points] == [
        (1.0, 1.0),
        (3.0, 1.0),
        (3.0, 3.0),
        (1.0, 3.0),
        (1.0, 1.0),
    ]
    assert result.route.revision == profile_revision(result.route)
    report = result.report
    assert report["original_name"] == "西南大学第４运动场"
    assert report["normalized_name"] == "西南大学第四运动场"
    assert report["status"] == "map_candidate_only"
    assert report["relationship_scope"] == "vertices_only"
    assert report["attribution"] == "© OpenStreetMap contributors"
    assert not report["device_execution_enabled"] and not report["record_verified"]
    public = json.dumps(report)
    assert result.route.route_id not in public and result.route.revision not in public
    assert "coordinates" not in public and "latitude" not in report
    school = SchoolProfile(
        profile_id="00000000-0000-0000-0000-000000000001",
        revision="0" * 64,
        campus="synthetic",
        app_package="example.test",
        app_version="1",
        confirmed=False,
        allowed_region=[dict(latitude=y, longitude=x) for x, y in [(0, 0), (4, 0), (4, 4), (0, 4)]],
        rules={},
        checkpoint_source="manual_confirmed",
    )
    assert {"school_unconfirmed", "rules_incomplete"} <= set(validate_route(result.route, school))


@pytest.mark.parametrize(
    "old,new",
    [
        (b'<nd ref="8"/>', b'<nd ref="999"/>'),
        (b'<nd ref="8"/><nd ref="5"/>', b'<nd ref="8"/>'),
        (b'id="368577141" version="3"', b'id="368577141" version="4"'),
        (b'id="413071891"', b'id="413071892"'),
        (b'leisure" v="track', b'leisure" v="pitch'),
        ("第４".encode(), "第３".encode()),
        (b'lon="2.0"', b'lon="8.0"'),
        (b'lon="1.0"', b'lon="181"'),
    ],
)
def test_structural_or_identity_rejection(tmp_path, old, new):
    with pytest.raises(MapInputError):
        run(tmp_path, sample().replace(old, new))


@pytest.mark.parametrize(
    "key,value",
    [
        ("crs", "GCJ02"),
        ("axis_order", "latitude,longitude"),
        ("source_sha256", "0" * 64),
        ("retrieved_at", "yesterday"),
        ("amap_status", "verified"),
        ("tencent_status", "conflict"),
    ],
)
def test_bad_metadata(tmp_path, key, value):
    data = sample()
    m = meta(data)
    m[key] = value
    with pytest.raises(MapInputError):
        run(tmp_path, data, m)


@pytest.mark.parametrize(
    "data",
    [
        b"<!DOCTYPE osm><osm/>",
        b'<!ENTITY a "x"><osm/>',
        b"\xff<osm/>",
        b"<osm>\x00</osm>",
        None,
    ],
    ids=["doctype", "entity", "non_utf8", "nul", "oversized"],
)
def test_hostile_input(tmp_path, data):
    if data is None:
        from swu_happyrun.core.map_candidates import MAX_BYTES

        data = b"x" * (MAX_BYTES + 1)
    with pytest.raises(MapInputError):
        run(tmp_path, data)


def test_node_drift_fails_even_when_way_unchanged(tmp_path):
    data = sample()
    changed = data.replace(b'id="5" version="1"', b'id="5" version="2"')
    with pytest.raises(MapInputError, match="source_digest_mismatch"):
        run(tmp_path, changed, meta(data))


def test_duplicate_and_nonregular(tmp_path):
    data = sample().replace(b"</osm>", b'<node id="1" version="1" lon="0" lat="0"/></osm>')
    with pytest.raises(MapInputError):
        run(tmp_path, data)
    with pytest.raises(MapInputError):
        import_candidate(tmp_path, format="osm", field=4, metadata=meta(sample()))


def test_geojson_requires_nodes_and_explicit_axis(tmp_path):
    # OSM-derived GeoJSON carries node features as well as way ordered references.
    import xml.etree.ElementTree as ET

    root = ET.fromstring(sample())
    features = []
    coords = {}
    for el in root:
        p = dict(
            osm_type=el.tag,
            id=int(el.attrib["id"]),
            version=int(el.attrib["version"]),
            tags={t.attrib["k"]: t.attrib["v"] for t in el.findall("tag")},
        )
        if el.tag == "node":
            xy = [float(el.attrib["lon"]), float(el.attrib["lat"])]
            coords[p["id"]] = xy
            g = dict(type="Point", coordinates=xy)
        else:
            p["nodes"] = [int(n.attrib["ref"]) for n in el.findall("nd")]
            g = dict(type="LineString", coordinates=[coords[n] for n in p["nodes"]])
        features.append(dict(type="Feature", properties=p, geometry=g))
    obj = dict(type="FeatureCollection", features=features)
    data = json.dumps(obj).encode()
    result = run(tmp_path, data, fmt="geojson")
    assert result.route.revision == profile_revision(result.route)
    broken = deepcopy(obj)
    broken["features"][-1]["geometry"]["type"] = "Point"
    with pytest.raises(MapInputError):
        run(tmp_path, json.dumps(broken).encode(), fmt="geojson")
    broken = deepcopy(obj)
    broken["features"][-1]["geometry"]["coordinates"][0] = [8, 8]
    with pytest.raises(MapInputError):
        run(tmp_path, json.dumps(broken).encode(), fmt="geojson")
    with pytest.raises(MapInputError):
        run(
            tmp_path,
            data,
            {k: v for k, v in meta(data).items() if k != "axis_order"},
            fmt="geojson",
        )


@pytest.mark.parametrize(
    "field,naming,track,version,name",
    [
        (1, 843421786, 843421789, 1, "西南大学第１运动场"),
        (2, 368605818, 846878928, 2, "西南大学第2运动场"),
    ],
)
def test_named_polygons_for_first_second(tmp_path, field, naming, track, version, name):
    data = (
        sample().decode().replace('id="368577141" version="3"', f'id="{track}" version="{version}"')
    )
    named = (
        f'<way id="{naming}" version="{2 if field == 1 else 4}">'
        + "".join(f'<nd ref="{n}"/>' for n in [1, 2, 3, 4, 1])
        + f'<tag k="name" v="{name}"/></way>'
    )
    data = data.replace("</osm>", named + "</osm>").encode()
    p = tmp_path / "in.osm"
    p.write_bytes(data)
    result = import_candidate(p, format="osm", field=field, metadata=meta(data))
    assert result.report["original_name"] == name
    assert result.report["naming_relationship"] == "track_vertices_in_named_polygon"
    # The campus name alone cannot substitute the separate named field polygon.
    data = data.replace(named.encode(), b"")
    p.write_bytes(data)
    with pytest.raises(MapInputError):
        import_candidate(p, format="osm", field=field, metadata=meta(data))


def test_self_intersection_and_campus_escape(tmp_path):
    data = sample().replace(b'<nd ref="6"/><nd ref="7"/>', b'<nd ref="7"/><nd ref="6"/>')
    with pytest.raises(MapInputError):
        run(tmp_path, data)
    data = sample().replace(b'id="6" version="1" lon="3.0"', b'id="6" version="1" lon="5.0"')
    with pytest.raises(MapInputError):
        run(tmp_path, data)


def test_cli_new_files_private_and_redacted(tmp_path, capsys):
    from swu_happyrun.core.map_candidates import main

    source = tmp_path / "in.osm"
    source.write_bytes(sample())
    m = tmp_path / "meta.json"
    m.write_text(json.dumps(meta(sample())), encoding="utf-8")
    private = tmp_path / "private.json"
    report = tmp_path / "report.json"
    args = [
        "--input",
        str(source),
        "--format",
        "osm",
        "--field",
        "4",
        "--metadata",
        str(m),
        "--private-route-output",
        str(private),
        "--report-output",
        str(report),
    ]
    assert main(args) == 0
    route = json.loads(private.read_text(encoding="utf-8"))
    public = report.read_text(encoding="utf-8")
    assert route["route_id"] not in public and "points" not in public
    assert "points" not in capsys.readouterr().out
    before = private.read_bytes()
    assert main(args) == 2 and private.read_bytes() == before
    assert str(tmp_path) not in capsys.readouterr().err


def test_symlinks_and_fifo_rejected_before_read(tmp_path, symlink_or_skip):
    import os

    source = tmp_path / "source"
    source.write_bytes(sample())
    link = tmp_path / "link"
    symlink_or_skip(link, source)
    with pytest.raises(MapInputError):
        import_candidate(link, format="osm", field=4, metadata=meta(sample()))
    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)
        with pytest.raises(MapInputError):
            import_candidate(fifo, format="osm", field=4, metadata=meta(sample()))


@pytest.mark.parametrize(
    "status", ["not_configured", "not_cross_verified", "timeout", "empty", "precision_limited"]
)
def test_missing_provider_status_never_becomes_verified(tmp_path, status):
    data = sample()
    m = meta(data)
    m["amap_status"] = m["tencent_status"] = status
    result = run(tmp_path, data, m)
    assert result.report["cross_source_status"] == "not_cross_verified"
    assert result.report["amap_status"] == status and result.report["tencent_status"] == status


def test_no_implicit_metadata_defaults(tmp_path):
    data = sample()
    for key in meta(data):
        m = meta(data)
        del m[key]
        with pytest.raises(MapInputError):
            run(tmp_path, data, m)


@pytest.mark.parametrize(
    "prefix",
    [
        b'<?xml version="1.0" encoding="iso-8859-1"?>',
        b'<?xml version="1.0" encoding = "utf-16"?>',
        b'\xef\xbb\xbf<?xml version="1.0" encoding="utf-16"?>',
    ],
)
def test_non_utf8_declaration_rejected(tmp_path, prefix):
    with pytest.raises(MapInputError):
        run(tmp_path, prefix + sample())


@pytest.mark.parametrize(
    "size", [2898661, 4 * 1024 * 1024], ids=["original_snapshot_size", "exact_4mib"]
)
def test_bounded_whole_snapshot_supported(tmp_path, size):
    data = sample()
    data = data.replace(b"</osm>", b" " * (size - len(data)) + b"</osm>")
    assert len(data) == size
    result = run(tmp_path, data)
    assert result.report["source_sha256"] == hashlib.sha256(data).hexdigest()
    assert result.route.source_ref.endswith(hashlib.sha256(data).hexdigest())
    with pytest.raises(MapInputError, match="source_digest_mismatch"):
        run(tmp_path, data, meta(sample()))


def test_fixed_limit_plus_one_rejected(tmp_path):
    from swu_happyrun.core.map_candidates import MAX_BYTES

    assert MAX_BYTES == 4 * 1024 * 1024
    data = b"x" * (MAX_BYTES + 1)
    with pytest.raises(MapInputError, match="input_too_large"):
        run(tmp_path, data)


def test_map_collection_ids_fit_windows_environment(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, PYTHONPATH=str(root / "src"))
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(Path(__file__).resolve())],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=30,
    )
    assert collected.returncode == 0
    ids = [line for line in collected.stdout.splitlines() if b"::test_" in line]
    assert ids
    assert max(map(len, ids)) < 512


def test_cli_text_reads_under_gbk_default(tmp_path, capsys, monkeypatch):
    from pathlib import Path

    original_read = Path.read_text
    original_write = Path.write_text

    def locale_read(path, encoding=None, errors=None, **kwargs):
        return original_read(path, encoding=encoding or "gbk", errors=errors, **kwargs)

    def locale_write(path, data, encoding=None, errors=None, **kwargs):
        return original_write(path, data, encoding=encoding or "gbk", errors=errors, **kwargs)

    monkeypatch.setattr(Path, "read_text", locale_read)
    monkeypatch.setattr(Path, "write_text", locale_write)
    test_cli_new_files_private_and_redacted(tmp_path, capsys)
