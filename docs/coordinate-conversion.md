# Offline explicit coordinate normalization

`core.coordinates.to_wgs84(longitude=..., latitude=..., source_crs=...)` returns a
new shared `GeoPoint`. Longitude/latitude are keyword-only angular degrees.
Accepted labels are exactly `WGS84`, `GCJ02`, and `BD09`; there is no default,
CRS inference, alias, or coordinate-order guessing. BD09 is longitude/latitude,
not projected BD09MC. WGS84 accepts the closed global coordinate bounds.

GCJ02 and BD09 use open mathematical bounds `73.66 < longitude < 135.05` and
`3.86 < latitude < 53.55`. Inputs, BD-to-GCJ intermediate points and inverse
iterates/results must stay inside; otherwise conversion fails. This rectangle
comes from the pinned upstream and is **not a country/border polygon**. It
includes areas where GCJ02 is not applicable. Only use this conversion when the
source is independently known to be genuinely GCJ02/BD09; don't relabel foreign,
Hong Kong, Macao or Taiwan WGS84 data because they fall inside the rectangle.
Outside the rectangle we reject rather than silently treating the input as WGS84.
Near the edge a valid input may be conservatively rejected when an iterate exits.

Only built-in int/float finite values are accepted; bool, strings, null,
NaN/infinities and out-of-range values are rejected. Detectable swapped axes are
rejected by range checks; ambiguous swaps cannot be inferred. Errors expose
stable reason codes without logging coordinate values.

The inverse uses at most 8 iterations and a `1e-11` degree forward residual.
Failure to converge raises an error, never returns the last unchecked estimate.
This is numerical consistency, **not surveyed physical accuracy**. BD09 inverse
is itself approximate. There is no centimeter/meter accuracy guarantee. Tests
check published vectors from the separate MIT `wandergis/coordtransform` project
(commit `606c6f3b57b6f1d60458793fea39928d2b11b637`) plus invalid inputs and domain
edges. The forward WGS-to-GCJ vector is inverted to its published input; the
published BD-to-GCJ vector checks the BD component. Those projects share common
formula ancestry and are not independent mapping-provider or survey benchmarks.
No local self-roundtrip or upstream MuMu accuracy claim is treated as ground truth.

`normalize_points(route)` revalidates the shared RouteProfile and returns a tuple
of detached WGS84 points. It never mutates the source profile, its CRS or revision.
It deliberately does not create a new RouteProfile retaining an invalid old hash.
The caller must verify the original profile revision before deriving points.
Passing a WGS84 route is an identity conversion of values, so normalization does
not apply GCJ offsets twice.

## Integration boundary

`geo.validate_route` and `geo.route_distance_m` normalize the explicit source CRS
before boundary and distance checks. Validation uses the same derived WGS84 tuple
for both checks and never changes the source route or its content revision.
`distance_between_points_m(a, b)` is the shared great-circle calculation for
already-normalized WGS84 points; it revalidates finite coordinates but cannot
infer a CRS from a GeoPoint. Route engines must call normalization before it.

The existing LocalProfileStore verifies source revision before route validation;
that hash validation is preserved unchanged. Direct mathematical utilities do
not establish profile identity or authorize execution. Preserve the original
route for JobSpec route_revision binding. Tests exercise synthetic converted
GCJ02/BD09 routes inside/outside a WGS84 boundary and source non-mutation.
Fake engine integration remains a separate change and physical backends remain
closed until their existing calibration and capability gates pass.

No device capability is enabled by these functions. MuMu input CRS still requires
an actual version-specific probe; school points/rules, device writes and accepted
records remain unverified. No map service, school server, network or device is
contacted at conversion runtime. Attribution and complete licenses are retained
in THIRD_PARTY_NOTICES.md.
