"""Strict offline OSM candidate review. Never grants school/device authority."""

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
import unicodedata
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from swu_happyrun.core.canonical import profile_revision
from swu_happyrun.core.geo import _inside, _valid_polygon
from swu_happyrun.core.models import RouteProfile

# The original frozen campus export is 2,898,661 bytes. Keep a fixed bound.
MAX_BYTES = 4 * 1024 * 1024
# Public identities from Issue 64 / PR 66; no geometry or school IDs.
TARGETS = {
    1: (("way", 843421786, 2), ("way", 843421789, 1)),
    2: (("way", 368605818, 4), ("way", 846878928, 2)),
    4: (("node", 3724521740, 1), ("way", 368577141, 3)),
}
CAMPUS = ("way", 413071891, 21)
MISSING_STATES = {"not_configured", "not_cross_verified", "timeout", "empty", "precision_limited"}


class MapInputError(ValueError):
    """Stable redacted reason, never raw coordinates, paths, or input text."""


@dataclass(frozen=True)
class Candidate:
    route: RouteProfile
    report: dict


def _fail(reason="invalid_map_input"):
    raise MapInputError(reason)


def _read(path):
    """Bounded read; reject symlink components, devices and FIFOs before open."""
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        _fail("unsafe_input_file")
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            _fail("unsafe_input_file")
        fd = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                _fail("unsafe_input_file")
            data = handle.read(MAX_BYTES + 1)
    except OSError:
        _fail("input_unavailable")
    if len(data) > MAX_BYTES:
        _fail("input_too_large")
    return data


def _text(data):
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        _fail("input_not_utf8")
    if "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        _fail("unsafe_input_encoding_or_declaration")
    return text


def _json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail("duplicate_json_key")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=pairs, parse_constant=lambda _: _fail())


def _positive(value):
    if type(value) is not int or value <= 0:
        _fail()
    return value


def _xml_int(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value):
        _fail()
    return int(value)


def _xy(value):
    if not isinstance(value, list) or len(value) != 2:
        _fail("invalid_axis_or_coordinate")
    if any(type(n) not in (int, float) or not math.isfinite(n) for n in value):
        _fail("invalid_axis_or_coordinate")
    x, y = value
    if not -180 <= x <= 180 or not -90 <= y <= 90:
        _fail("invalid_axis_or_coordinate")
    return (float(x), float(y))


def _put(objects, kind, identifier, version, tags, *, xy=None, nodes=None):
    if kind not in {"node", "way"} or not isinstance(tags, dict):
        _fail()
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in tags.items()):
        _fail()
    key = (kind, _positive(identifier))
    if key in objects:
        _fail("duplicate_osm_object")
    objects[key] = dict(version=_positive(version), tags=tags, xy=xy, nodes=nodes)


def _xml(text):
    declaration = re.match(r"\s*<\?xml[^?]*encoding\s*=\s*[\"\']([^\"\']+)", text.lstrip("\ufeff"))
    if declaration and declaration.group(1).lower() not in {"utf-8", "utf8"}:
        _fail("input_not_utf8")
    root = ET.fromstring(text)
    if root.tag != "osm" or root.attrib.get("version") != "0.6":
        _fail("invalid_osm_document")
    objects = {}
    for el in root:
        if el.tag in {"bounds", "note", "meta", "relation"}:
            continue  # Relations are never used as candidate geometry.
        if el.tag not in {"node", "way"}:
            _fail()
        tags = {}
        for t in el.findall("tag"):
            if t.attrib["k"] in tags:
                _fail("duplicate_osm_tag")
            tags[t.attrib["k"]] = t.attrib["v"]
        xy = _xy([float(el.attrib["lon"]), float(el.attrib["lat"])]) if el.tag == "node" else None
        nodes = [_xml_int(n.attrib["ref"]) for n in el.findall("nd")] if el.tag == "way" else None
        _put(
            objects,
            el.tag,
            _xml_int(el.attrib["id"]),
            _xml_int(el.attrib["version"]),
            tags,
            xy=xy,
            nodes=nodes,
        )
    return objects


def _geojson(text):
    doc = _json(text)
    if set(doc) != {"type", "features"} or doc["type"] != "FeatureCollection":
        _fail("invalid_geojson_document")
    if not isinstance(doc["features"], list):
        _fail()
    objects, geometries = {}, {}
    for f in doc["features"]:
        if set(f) != {"type", "geometry", "properties"} or f["type"] != "Feature":
            _fail()
        p, g = f["properties"], f["geometry"]
        kind = p["osm_type"]
        required = {"osm_type", "id", "version", "tags"} | ({"nodes"} if kind == "way" else set())
        if set(p) != required or set(g) != {"type", "coordinates"}:
            _fail()
        if kind == "node" and g["type"] == "Point":
            xy, nodes = _xy(g["coordinates"]), None
        elif kind == "way" and g["type"] == "LineString":
            if not isinstance(p["nodes"], list) or not isinstance(g["coordinates"], list):
                _fail()
            xy, nodes = None, [_positive(n) for n in p["nodes"]]
            geometries[(kind, p["id"])] = [_xy(c) for c in g["coordinates"]]
        else:
            _fail("poi_is_not_route")
        _put(objects, kind, p["id"], p["version"], p["tags"], xy=xy, nodes=nodes)
    for key, coordinates in geometries.items():
        if coordinates != _points(objects[key], objects):
            _fail("geojson_node_geometry_mismatch")
    return objects


def _points(way, objects):
    try:
        return [objects[("node", n)]["xy"] for n in way["nodes"]]
    except KeyError:
        _fail("missing_osm_node")


def _ring(way, objects):
    nodes = way["nodes"]
    if not nodes or len(nodes) > 1000 or nodes[0] != nodes[-1]:
        _fail("unclosed_ring")
    points = _points(way, objects)
    if not _valid_polygon(points[:-1]):
        _fail("invalid_ring")
    return points


def _get(objects, identity):
    kind, identifier, version = identity
    value = objects.get((kind, identifier))
    if value is None:
        _fail("required_osm_object_missing")
    if value["version"] != version:
        _fail("osm_version_drift")
    return value


def _normalize(name):
    name = unicodedata.normalize("NFKC", name)
    for number, word in [(1, "一"), (2, "二"), (4, "四")]:
        name = name.replace(f"第{number}", f"第{word}")
    return name


def _metadata(metadata, data):
    if set(metadata) != {
        "crs",
        "axis_order",
        "retrieved_at",
        "source_sha256",
        "amap_status",
        "tencent_status",
    }:
        _fail("invalid_source_metadata")
    if metadata["crs"] != "WGS84" or metadata["axis_order"] != "longitude,latitude":
        _fail("unsupported_crs_or_axis")
    stamp = metadata["retrieved_at"]
    if not isinstance(stamp, str) or not re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z", stamp
    ):
        _fail("invalid_retrieval_time")
    datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if metadata["source_sha256"] != hashlib.sha256(data).hexdigest():
        _fail("source_digest_mismatch")
    if any(metadata[k] not in MISSING_STATES for k in ("amap_status", "tencent_status")):
        _fail("source_conflict_or_unverified_status")


def import_candidate(path, *, format, field, metadata):
    """Consume a pinned local snapshot; source hashes are supplied before import.

    A hash asserts snapshot integrity, not source authenticity. Public metadata
    never contains geometry, generated UUIDs, or private profile revisions.
    """
    try:
        if type(field) is not int or field not in TARGETS:
            _fail("unsupported_field")
        data = _read(path)
        _metadata(metadata, data)
        text = _text(data)
        if format not in {"osm", "geojson"}:
            _fail("unsupported_format")
        objects = _xml(text) if format == "osm" else _geojson(text)
        naming_id, track_id = TARGETS[field]
        campus, naming, track = [_get(objects, i) for i in (CAMPUS, naming_id, track_id)]
        if (
            campus["tags"].get("amenity") != "university"
            or campus["tags"].get("name") != "西南大学"
        ):
            _fail("campus_identity_mismatch")
        original = naming["tags"].get("name", "")
        normalized = _normalize(original)
        expected = {1: "一", 2: "二", 4: "四"}[field]
        if normalized != f"西南大学第{expected}运动场":
            _fail("field_name_mismatch")
        if track["tags"].get("leisure") != "track":
            _fail("poi_is_not_route")
        boundary, points = _ring(campus, objects), _ring(track, objects)
        if not all(_inside(p, boundary[:-1]) for p in points):
            _fail("track_vertices_outside_campus")
        if naming_id[0] == "way":
            named = _ring(naming, objects)
            if not all(_inside(p, named[:-1]) for p in points):
                _fail("track_vertices_outside_named_field")
            relationship = "track_vertices_in_named_polygon"
        else:
            if not _inside(naming["xy"], points[:-1]):
                _fail("named_marker_outside_track")
            relationship = "named_marker_inside_track"
        route = RouteProfile(
            route_id=str(uuid.uuid4()),
            revision="0" * 64,
            input_crs="WGS84",
            points=[dict(longitude=x, latitude=y) for x, y in points],
            source_ref=f"osm:way/{track_id[1]}:v{track_id[2]}:sha256:{metadata['source_sha256']}",
        )
        route.revision = profile_revision(route)
        # Covers the full ordered selected-way node snapshot, including versions.
        snapshot = [
            [n, objects[("node", n)]["version"], *objects[("node", n)]["xy"]]
            for n in track["nodes"]
        ]
        report = dict(
            metadata,
            field=field,
            original_name=original,
            normalized_name=normalized,
            campus=dict(type=CAMPUS[0], id=CAMPUS[1], version=CAMPUS[2]),
            naming=dict(type=naming_id[0], id=naming_id[1], version=naming_id[2]),
            track=dict(type=track_id[0], id=track_id[1], version=track_id[2]),
            node_count=len(points),
            ordered_node_versions=[dict(id=row[0], version=row[1]) for row in snapshot],
            node_snapshot_sha256=hashlib.sha256(
                json.dumps(snapshot, separators=(",", ":"), allow_nan=False).encode()
            ).hexdigest(),
            closed=True,
            naming_relationship=relationship,
            relationship_scope="vertices_only",
            status="map_candidate_only",
            cross_source_status="not_cross_verified",
            school_rules_confirmed=False,
            device_execution_enabled=False,
            record_verified=False,
            attribution="© OpenStreetMap contributors",
            license="ODbL-1.0",
            license_url="https://www.openstreetmap.org/copyright",
        )
        return Candidate(route, report)
    except MapInputError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,
        RecursionError,
        ET.ParseError,
    ):
        _fail()


def _write_new(path, content):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in path.parents):
        _fail("unsafe_output_path")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content + "\n")
    except OSError:
        _fail("output_unavailable_or_exists")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--format", choices=["osm", "geojson"], required=True)
    parser.add_argument("--field", type=int, choices=[1, 2, 4], required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--private-route-output", required=True)
    parser.add_argument("--report-output", required=True)
    args = parser.parse_args(argv)
    try:
        metadata = _json(_text(_read(args.metadata)))
        result = import_candidate(
            args.input, format=args.format, field=args.field, metadata=metadata
        )
        # Explicit new files only. No profile-store registration, upload or job creation.
        _write_new(args.private_route_output, result.route.model_dump_json(indent=2))
        _write_new(args.report_output, json.dumps(result.report, ensure_ascii=False, indent=2))
    except (MapInputError, ValueError, TypeError, RecursionError):
        print("map_candidate_rejected", file=sys.stderr)
        return 2
    print("map_candidate_only; school/device/record unverified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
