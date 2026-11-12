"""Single-process scheduler; database uniqueness also protects concurrent ticks."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from swu_happyrun.core.models import ScheduleSpec
from swu_happyrun.server.errors import ApiError

SHANGHAI = ZoneInfo("Asia/Shanghai")


class Scheduler:
    def __init__(self, store, clock):
        self.store = store
        self.clock = clock

    def _validate_window(self, spec):
        # Check that the full time window can be represented for the next weekly occurrence.
        try:
            duration = spec.job_template.deadline - spec.job_template.not_before
            next_week = self.clock.utcnow().astimezone(SHANGHAI).date() + timedelta(days=7)
            begin = datetime.combine(next_week, time.fromisoformat(spec.local_time), SHANGHAI)
            begin.astimezone(UTC) + duration
        except (OverflowError, ValueError):
            raise ApiError(422, "invalid_input", "Schedule window cannot be represented") from None

    def create(self, spec: ScheduleSpec):
        self._validate_window(spec)
        with self.store.connection(write=True) as db:
            if db.execute(
                "SELECT 1 FROM schedules WHERE schedule_id=?", (spec.schedule_id,)
            ).fetchone():
                raise ApiError(409, "schedule_conflict", "Schedule already exists")
            local_date = self.clock.utcnow().astimezone(SHANGHAI).date().isoformat()
            db.execute(
                "INSERT INTO schedules VALUES (?,?,?,?)",
                (spec.schedule_id, spec.model_dump_json(), local_date, local_date),
            )
        return spec

    def list(self):
        with self.store.connection() as db:
            return [
                ScheduleSpec.model_validate_json(row[0])
                for row in db.execute("SELECT spec_json FROM schedules ORDER BY schedule_id")
            ]

    def update(self, schedule_id: str, spec: ScheduleSpec):
        self._validate_window(spec)
        if schedule_id != spec.schedule_id:
            raise ApiError(422, "invalid_input", "Schedule identifier does not match path")
        with self.store.connection(write=True) as db:
            if not db.execute(
                "SELECT 1 FROM schedules WHERE schedule_id=?", (schedule_id,)
            ).fetchone():
                raise ApiError(404, "not_found", "Resource not found")
            # Never backfill dates preceding an explicit template change.
            today = self.clock.utcnow().astimezone(SHANGHAI).date().isoformat()
            db.execute(
                "UPDATE schedules SET spec_json=?,scan_date=? WHERE schedule_id=?",
                (spec.model_dump_json(), today, schedule_id),
            )
        return spec

    def tick(self) -> int:
        created = 0
        with self.store.connection(write=True) as db:
            now = self.clock.utcnow()
            today = now.astimezone(SHANGHAI).date()
            self.store._expire(db)
            for row in db.execute("SELECT * FROM schedules").fetchall():
                spec = ScheduleSpec.model_validate_json(row["spec_json"])
                start = max(
                    date.fromisoformat(row["created_date"]), date.fromisoformat(row["scan_date"])
                )
                if not spec.enabled:
                    db.execute(
                        "UPDATE schedules SET scan_date=? WHERE schedule_id=?",
                        (today.isoformat(), spec.schedule_id),
                    )
                    continue
                duration = spec.job_template.deadline - spec.job_template.not_before
                current = start
                while current <= today:
                    key = (spec.schedule_id, current.isoformat())
                    if (
                        current.isoweekday() in spec.weekdays
                        and not db.execute(
                            "SELECT 1 FROM occurrences WHERE schedule_id=? AND local_date=?", key
                        ).fetchone()
                    ):
                        local = datetime.combine(
                            current, time.fromisoformat(spec.local_time), SHANGHAI
                        )
                        begin = local.astimezone(UTC)
                        deadline = begin + duration
                        if now >= deadline:
                            db.execute(
                                "INSERT INTO occurrences VALUES (?,?,?,NULL)", (*key, "skipped")
                            )
                        elif now >= begin:
                            payload = spec.job_template.model_dump() | {
                                "not_before": begin,
                                "deadline": deadline,
                            }
                            job_spec = type(spec.job_template).model_validate(payload)
                            job = self.store._insert_job(db, job_spec)
                            db.execute(
                                "INSERT INTO occurrences VALUES (?,?,?,?)",
                                (*key, "created", job.job_id),
                            )
                            created += 1
                    current += timedelta(days=1)
                # Include today's date on the next scan: a future local_time may become due later.
                if today >= start:
                    db.execute(
                        "UPDATE schedules SET scan_date=? WHERE schedule_id=?",
                        (today.isoformat(), spec.schedule_id),
                    )
        return created
