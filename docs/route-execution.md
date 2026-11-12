# Offline route execution

The local `core.route.RouteExecution` is a deterministic, single-owner route
state machine. It does not open physical backends, inject real locations, upload
records, or emit `app_record` evidence. All committed test coordinates are synthetic.

## Geometry and timing

- Validate the complete route against the supplied confirmed school boundary and
  complete rule set before starting. No campus coordinates or speed requirements
  are invented.
- Explicit GCJ02/BD09 input is normalized by `core.coordinates.normalize_points`;
  unknown CRS or unsupported conversion domains fail closed. The source profile
  and its content revision are unchanged, and no device calibration is implied.
- Use detached WGS84 working points. Interpolation is linear in longitude/latitude to match
  the polygon-segment boundary validator. Distances use the existing spherical
  great-circle approximation, not survey-grade ellipsoidal distance. The reported
  speed is the chosen distance-parameter speed under that approximation.
- Traverse the supplied polyline once, including every waypoint. Ignore zero-length
  segments; a wholly zero-length route is rejected. No automatic loops or jitter.
- A caller supplies finite positive `speed_mps` within the confirmed rule range.
  Reject a speed whose route duration exceeds `maximum_duration_seconds`.
- `start`, `tick`, `pause`, and `resume` accept optional `now` readings from one
  monotonic clock. Without `now`, use the injected `Clock.monotonic`; wall time is
  never read. Reject negative, nonfinite, boolean, or regressing timestamps before
  mutating progress. Equal timestamps are valid zero-distance samples.
- Late ticks sample one position at the elapsed route time, with no catch-up burst.
  Progress clamps at the final waypoint. Pause excludes paused time. Completion
  and stop are terminal; restart requires a new execution object.
- `stop()` freezes the latest observed position without reading the clock, so
  controlled stop remains available after a clock or lease failure. The caller
  owns locking, cancellation, server lease/fence checks and persistence.

## Fake integration

`FakeDriver` creates an execution only after session/profile validation and the
execution guard. Its existing `tick(job, elapsed_seconds)` uses relative monotonic
seconds since start. The guard runs before changing position. No physical API is
called. `route_progress` exposes a defensive snapshot containing state, WGS84
position, distance, total distance, fractional progress, active elapsed seconds,
current speed and `finished`.

`route_speed_mps` is an optional local fake constructor setting. If omitted, the
simulation uses the supplied maximum-speed rule as a deterministic simulation
policy, not as an inferred user target or an acceptance claim. This does not add a
wire field or remote pause/resume command.

A time budget expiring is not route completion. A partial stopped fake run returns
`simulation_incomplete`; only a finished route returns `simulation_only`. Both
have `status=unknown` and empty evidence, never school acceptance. The owning
runner must report incomplete budget-limited runs as `needs_attention` and take a
final guarded sample at its budget endpoint. Explicit fault scenarios retain their
failure results.

The synthetic state file persists `route_finished` with its existing immutable
job/session binding. Old version-2 state without the marker is treated as incomplete.
After restart, no position is reconstructed and `route_progress` is absent: the
recovered fake may stop and verify the existing session but cannot continue ticks
or restart motion. There is no real route-point trace in persisted state or logs.

## Verification

Run `python -m pytest tests/agent/test_route_engine.py tests/agent/test_driver.py -q`
for synthetic geometry, monotonic-time rejection, pause/resume/stop, final waypoint,
partial/full fake verification, restart, cancellation and lease-guard coverage.
The full repository suite, lint and formatting remain release gates. Real HTTP
completion requires a synthetic route short enough for its configured time budget;
clock-only smoke completion is not evidence of route execution.
