"""Schedule API via real TCP; read-only SQL observes durable occurrence uniqueness."""

import sqlite3
import time
from uuid import uuid4


def rows(service, query):
    with sqlite3.connect(service.settings.database_path) as db:
        return db.execute(query).fetchall()


def await_job_count(service, count):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = rows(service, "SELECT job_id FROM jobs")
        if len(result) == count:
            return result
        time.sleep(0.05)
    raise AssertionError("automatic scheduler did not create expected job count")


def schedule(service):
    return dict(
        schedule_id=str(uuid4()),
        job_template=service.spec,
        timezone="Asia/Shanghai",
        local_time="08:01",
        weekdays=[1],
        enabled=True,
    )


def test_automatic_schedule_tick_restart_once(service):
    s = service
    spec = schedule(s)
    response = s.post("schedules", spec, admin=True)
    assert response.status_code == 201, response.text
    assert rows(s, "SELECT job_id FROM jobs") == []
    s.clock.advance(60)
    jobs = await_job_count(s, 1)
    view = s.get("jobs/" + jobs[0][0]).json()
    assert view["spec"]["not_before"] == "2026-10-19T00:01:00Z"
    assert view["spec"]["deadline"] == "2026-10-19T01:01:00Z"
    assert view["state"] == "queued"
    s.restart()
    # Wait for >1 tick: restart and repeated ticks must not create a second occurrence.
    time.sleep(1.3)
    assert rows(s, "SELECT job_id FROM jobs") == jobs
    assert s.get("schedules").json() == [spec]


def test_schedule_expired_occurrence_not_backfilled(service):
    s = service
    spec = schedule(s)
    assert s.post("schedules", spec, admin=True).status_code == 201
    s.clock.advance(3661)
    time.sleep(1.3)
    assert rows(s, "SELECT job_id FROM jobs") == []
    s.restart()
    time.sleep(1.3)
    assert rows(s, "SELECT job_id FROM jobs") == []
