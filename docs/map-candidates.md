# Offline map candidates for Issue 64

This optional module reviews local OSM snapshots for Beibei fields 1, 2 and 4.
It produces the existing `RouteProfile` and a separate, coordinate-free provenance
report. It never creates a SchoolProfile, registers a device capability, creates
jobs, calls maps APIs, or verifies a school record. No dependency or wire changes.

Public object identities and frozen way versions come from
[Issue 64](https://github.com/Maximora-byte/swu-happyrun/issues/64) and
[PR 66](https://github.com/Maximora-byte/swu-happyrun/pull/66).
Those reports do **not** supply the original private geometry to this module.
Use the original private snapshot or independently retrieve and review an official
OSM snapshot. A changed campus/naming/track version requires a new independent
review and catalog update, not silent use of a newer way. Node changes can occur
without a way-version change: pin and check the **entire file SHA256**, and compare
the ordered node/version/geometry digest across reviews. The exported ordered node
versions preserve node identity and order, including the repeated closing node.
A locally supplied digest is an integrity assertion, not proof of authenticity.
Do not label a newly downloaded file as the original frozen source.

Data attribution: **© OpenStreetMap contributors**, **ODbL-1.0**;
[license and attribution](https://www.openstreetmap.org/copyright).
Keep this attribution with derived data and review applicable database obligations
before redistributing it. Code licensing does not replace source-data licensing.

## Private local inputs

Store inputs and generated precise profiles outside version control, in an
operator-owned private directory. The CLI never fetches URLs or reads API keys.
Use an OSM 0.6 XML export containing the campus way, the named field object,
the track way, and all referenced nodes, including node versions. Limits:
2,000,000 bytes per file and 1,000 nodes per selected ring. UTF-8 only, no DTD,
ENTITY or NUL. Symlinks, special files, duplicate object IDs/tags, missing nodes,
open/degenerate/self-intersecting rings and wrong source identities are rejected.
Input directories must not be concurrently modified by untrusted users; these
file checks are not a filesystem sandbox. Windows users must set private ACLs;
POSIX new files use mode 0600, which is not a Windows ACL guarantee.

A private metadata JSON must contain exactly these fields (replace placeholders
with independently reviewed facts; do not copy the example hash):

```json
{
  "crs": "WGS84",
  "axis_order": "longitude,latitude",
  "retrieved_at": "2026-10-19T09:00:00Z",
  "source_sha256": "REVIEWED_SHA256_OF_THE_EXACT_LOCAL_INPUT_FILE",
  "amap_status": "precision_limited",
  "tencent_status": "empty"
}
```

The metadata must reflect actual observations. Each additional provider accepts
only `not_configured`, `not_cross_verified`, `timeout`, `empty`, or
`precision_limited`. A conflict or claimed `verified` state rejects import; there
is no cross-source verification algorithm in this first increment. Empty results
never pass. There are no network/provider adapters or credential configuration yet.
Authorized SDK/API result ingestion remains separate follow-up work for #64.

OSM-derived GeoJSON is deliberately narrow: a FeatureCollection with no implicit
CRS, Feature `properties` containing `osm_type`, numeric `id`, numeric `version`,
`tags`, and (for ways) ordered numeric `nodes`. Nodes have Point geometry; ways
have LineString geometry, with coordinates exactly matching the referenced node
features. All positions are explicit `[longitude,latitude]` in WGS84, independently
declared in the metadata. Arbitrary POI GeoJSON, Polygon convenience exports,
missing provenance, or different CRS are rejected rather than guessed. Convert
other formats explicitly and preserve their original source separately. The
existing `core.coordinates` conversion remains unchanged; this importer does not
relabel domestic coordinates WGS84 or project OSM onto a domestic basemap.

```sh
python -m swu_happyrun.core.map_candidates \
  --input /PRIVATE_OUTSIDE_REPOSITORY/campus.osm --format osm --field 4 \
  --metadata /PRIVATE_OUTSIDE_REPOSITORY/source.json \
  --private-route-output /PRIVATE_OUTSIDE_REPOSITORY/new-route.json \
  --report-output /PRIVATE_OUTSIDE_REPOSITORY/new-report.json
```

Both outputs must be new files; existing files are never overwritten. Exit 0 means
only `map_candidate_only`; exit 2 is rejection. Errors do not echo raw source text
or coordinates. Outputs are sequential: if report creation fails, the new private
route file may already exist; inspect it locally and choose new names before retry.
The route UUID is newly generated for each import; its canonical revision uses the
shared model. The report contains no private UUID/profile revision or coordinates.
Retain the original snapshot privately so provenance can be independently replayed.

## Review boundaries and next acceptance

Name normalization preserves original text and converts full-width digits and
1/2/4 names. Identity still requires the separately pinned campus, named object,
and actual leisure=track way. A named point is never expanded into a route.
Campus and named-area checks are **vertices only**. The report explicitly does
not establish whole-segment containment, current access, official centerlines,
400 m length, safety, or school-recognized running areas. Existing full route and
school-rule validation remains mandatory; missing or unconfirmed rules block it.
`school_rules_confirmed`, `device_execution_enabled`, and `record_verified` remain
false regardless of map structure. No speeds, repetitions or dynamic checkpoints
are inferred.

Next, local Codex can replay all three private snapshots, compare the known
source hash and ordered node versions/digest, and independently review actual
geometry and provider differences. Device/physical transport, app-version rules,
and accepted records remain separate acceptance stages. No real route, device,
Windows or provider API validation is claimed by synthetic Linux tests.

Tests: `python -m pytest tests/agent/test_map_candidates.py tests/contracts -q`.
