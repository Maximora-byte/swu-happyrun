"""Versioned schema and fail-closed pre-release data migration."""

import json

from swu_happyrun.core.models import JobView


def initialize(db):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1, 2, 3):
        raise ValueError("Unsupported database schema version")
    db.execute(
        "CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, "
        "view_json TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS job_requests (idempotency_key TEXT PRIMARY KEY, "
        "request_json TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(job_id))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS agents (agent_id TEXT PRIMARY KEY, "
        "hello_json TEXT NOT NULL, received_at TEXT NOT NULL)"
    )
    if version == 1:
        for job_id, raw in db.execute("SELECT job_id, view_json FROM jobs").fetchall():
            view = json.loads(raw)
            if "expected_app_version" not in view["spec"] or "run_session_id" not in view:
                if (
                    view["spec"]["mode"] != "simulation"
                    or view["fence"] != 0
                    or view["agent_id"] is not None
                    or view["state"] != "queued"
                ):
                    raise ValueError(
                        "Unsupported legacy job migration; preserve database for review"
                    )
                view["spec"]["expected_app_version"] = None
                view["run_session_id"] = None
                db.execute("UPDATE jobs SET view_json=? WHERE job_id=?", (json.dumps(view), job_id))
                request = json.dumps(view["spec"], sort_keys=True, separators=(",", ":"))
                db.execute(
                    "UPDATE job_requests SET request_json=? WHERE job_id=?", (request, job_id)
                )
    db.execute(
        "CREATE TABLE IF NOT EXISTS devices (device_id TEXT PRIMARY KEY, "
        "agent_id TEXT NOT NULL, fence INTEGER NOT NULL DEFAULT 0, "
        "reservation TEXT REFERENCES jobs(job_id), current_probe TEXT)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS probes (probe_id TEXT PRIMARY KEY, "
        "device_id TEXT NOT NULL REFERENCES devices(device_id), "
        "payload TEXT NOT NULL, received_at TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS runtime (job_id TEXT PRIMARY KEY REFERENCES jobs(job_id), "
        "started INTEGER NOT NULL DEFAULT 0, pending_action TEXT, active_action TEXT, "
        "token_hash TEXT, expires_at TEXT)"
    )
    db.execute("INSERT OR IGNORE INTO runtime(job_id) SELECT job_id FROM jobs")
    db.execute(
        "CREATE TABLE IF NOT EXISTS events (job_id TEXT NOT NULL REFERENCES jobs(job_id), "
        "event_id TEXT NOT NULL, fingerprint TEXT NOT NULL, result TEXT NOT NULL, "
        "PRIMARY KEY(job_id,event_id))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS records (namespace TEXT NOT NULL, record_id TEXT NOT NULL, "
        "job_id TEXT NOT NULL REFERENCES jobs(job_id), PRIMARY KEY(namespace,record_id))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS record_digests (digest TEXT PRIMARY KEY, "
        "job_id TEXT NOT NULL REFERENCES jobs(job_id))"
    )
    for row in db.execute("SELECT view_json FROM jobs"):
        JobView.model_validate_json(row[0])
    db.execute(
        "CREATE TABLE IF NOT EXISTS schedules (schedule_id TEXT PRIMARY KEY, "
        "spec_json TEXT NOT NULL, created_date TEXT NOT NULL, scan_date TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS occurrences (schedule_id TEXT NOT NULL "
        "REFERENCES schedules(schedule_id), local_date TEXT NOT NULL, status TEXT NOT NULL, "
        "job_id TEXT REFERENCES jobs(job_id), PRIMARY KEY(schedule_id,local_date))"
    )
    db.execute("PRAGMA user_version=3")
