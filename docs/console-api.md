# Local console serving and job pagination

This is an additive ADMIN read endpoint. Shared `JobView` models, exported schemas,
lease commands, job transitions, and authentication rules are unchanged.

## GET /api/v1/jobs

Requires the existing ADMIN bearer credential; unauthenticated requests return 401,
AGENT credentials return 403. Query parameters:

- `limit`: integer, default 25, inclusive range 1–100.
- `before`: optional job UUID returned as the previous page's `next_cursor`.

Response: `{"items": [JobView, ...], "next_cursor": "job UUID or null"}`.
Each item is the existing public `JobView`; no lease token or token digest is
returned. A non-null cursor is the final returned job's ID and means another
page existed at read time. Empty/final pages have `next_cursor: null`.

Order is descending `(created_at, job_id)`; the next page excludes its cursor.
The immutable insertion timestamp and UUID break ties consistently across restart.
A new job inserted ahead of the cursor does not duplicate jobs on subsequent pages.
Each page reads its cursor and rows in one SQLite snapshot. This is keyset
pagination, not a frozen snapshot of all pages; state may change between requests.
Normal expiry processing runs before listing, as it does for a single job read.

Malformed parameters return 422 `invalid_input`; a well-formed but unknown cursor
returns 422 `invalid_cursor` rather than silently restarting at page one.

## Static entry and security

`GET /` returns 307 to `/console/`. The only static routes are `/console/`,
`/console/app.js`, and `/console/styles.css`. Assets ship inside the Python wheel,
with no runtime downloads or additional frontend dependencies. The shell is public
and contains no configured credentials or private job data. API reads still require
bearer authentication. No CORS access is enabled.

Every response, including API errors, carries `Cache-Control: no-store`,
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and
`Referrer-Policy: no-referrer`. CSP restricts scripts, styles, images and connections
to self; forbids plugins, base URL overrides, and framing; and permits no inline
script/style or eval exceptions.

`swu-happyrun server --open-browser` opens `/console/` only after Uvicorn completes
startup and has a listening socket. It is opt-in, and accepts only `127.0.0.1`,
`localhost`, or `::1`; wildcard/public listeners are rejected for this flag. It does
not change the requested bind address. Browser launch failure leaves the server
running; open the URL manually. No credential is added to the URL. This convenience
option is intended for a local interactive server, not an unattended deployment.

The console is not evidence of real device support or accepted running records.
