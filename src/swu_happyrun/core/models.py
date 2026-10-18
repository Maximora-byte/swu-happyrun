"""One set of v1 models for both server and agent. No I/O on validation."""

import re
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    WithJsonSchema,
    model_validator,
)

from swu_happyrun.core.states import JobState

UUIDString = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, StringConstraints(min_length=1)]
Counter = Annotated[int, Field(ge=0)]
Phase = Literal["leased", "preflight", "ready", "running", "finishing", "verifying", "cancelling"]
State = Annotated[JobState, Field(strict=False)]
Capability = Literal["location_read", "location_write", "sensor_probe", "app_ui", "record_read"]
RecoveryAction = Literal["retry_preflight", "verify_only", "stop_only"]
Rule = Literal[
    "minimum_distance_m", "maximum_duration_seconds", "minimum_speed_mps", "maximum_speed_mps"
]


def _protocol_version(value: object) -> object:
    # Literal[1] alone normalizes True/1.0 to 1 before after-validators see it.
    if type(value) is not int or value != 1:
        raise ValueError("protocol_version must be integer 1")
    return value


ProtocolVersion = Annotated[Literal[1], BeforeValidator(_protocol_version)]
UTC_PATTERN = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$"


def _parse_wire_time(value: object) -> object:
    if isinstance(value, str):
        if not re.fullmatch(UTC_PATTERN, value):
            raise ValueError("wire timestamp must be UTC RFC3339 ending in Z")
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


UtcTime = Annotated[
    AwareDatetime,
    BeforeValidator(_parse_wire_time),
    AfterValidator(lambda value: value.astimezone(UTC)),
    WithJsonSchema({"type": "string", "format": "date-time", "pattern": UTC_PATTERN}),
]


class ProtocolModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        validate_assignment=True,
        hide_input_in_errors=True,
    )


class JobSpec(ProtocolModel):
    protocol_version: ProtocolVersion
    mode: Literal["simulation", "device"]
    profile_id: UUIDString
    profile_revision: Digest
    route_id: UUIDString
    route_revision: Digest
    device_id: UUIDString
    not_before: UtcTime
    deadline: UtcTime

    @model_validator(mode="after")
    def ordered_window(self) -> Self:
        if self.deadline <= self.not_before:
            raise ValueError("deadline must follow not_before")
        return self


class JobView(ProtocolModel):
    job_id: UUIDString
    spec: JobSpec
    state: State
    revision: Counter
    desired_state: Literal["run", "cancel"]
    fence: Counter
    agent_id: UUIDString | None
    reason_code: Text | None
    resume_phase: Phase | None
    recovery_action: RecoveryAction | None

    @model_validator(mode="after")
    def consistent_state(self) -> Self:
        if self.state == JobState.SUCCEEDED and self.spec.mode != "device":
            raise ValueError("simulation cannot succeed")
        if self.state == JobState.COMPLETED and self.spec.mode != "simulation":
            raise ValueError("device mode requires record verification")
        if self.state == JobState.NEEDS_ATTENTION and self.resume_phase is None:
            raise ValueError("needs_attention requires resume_phase")
        if self.recovery_action == "retry_preflight" and self.resume_phase in {
            "running",
            "finishing",
            "verifying",
            "cancelling",
        }:
            raise ValueError("started jobs cannot retry_preflight")
        if self.desired_state == "cancel" and self.recovery_action not in {None, "stop_only"}:
            raise ValueError("cancelled intent permits only stop_only recovery")
        if self.desired_state == "cancel" and self.state == JobState.QUEUED:
            raise ValueError("cancelled intent cannot be queued")
        return self


class DeviceCapability(ProtocolModel):
    device_id: UUIDString
    backend: Literal["fake", "mumu", "android"]
    app_version: Text | None
    capabilities: list[Capability]
    observed_at: UtcTime


class AgentHello(ProtocolModel):
    protocol_version: ProtocolVersion
    agent_id: UUIDString
    devices: list[DeviceCapability]

    @model_validator(mode="after")
    def unique_devices(self) -> Self:
        if len({d.device_id for d in self.devices}) != len(self.devices):
            raise ValueError("duplicate device_id")
        return self


class LeaseCommand(ProtocolModel):
    lease_token: Text = Field(repr=False)
    fence: Counter


class LeaseGrant(ProtocolModel):
    job: JobView
    lease_token: Text = Field(repr=False)
    fence: Counter
    expires_at: UtcTime

    @model_validator(mode="after")
    def matching_fence(self) -> Self:
        if self.fence != self.job.fence:
            raise ValueError("grant fence must match job fence")
        return self


class EvidenceRef(ProtocolModel):
    kind: Literal["host_check", "device_probe", "app_record"]
    sha256: Digest
    captured_at: UtcTime
    app_version: Text | None
    profile_revision: Digest
    record_status: Literal["valid", "invalid", "pending"] | None

    @model_validator(mode="after")
    def record_fields(self) -> Self:
        if self.kind == "app_record":
            if self.app_version is None or self.record_status is None:
                raise ValueError("app_record requires app_version and record_status")
        elif self.record_status is not None:
            raise ValueError("only app_record can carry record_status")
        return self


class JobEvent(ProtocolModel):
    event_id: UUIDString
    expected_revision: Counter
    state: State
    reason_code: Text | None
    evidence: list[EvidenceRef]
    resume_phase: Phase | None

    @model_validator(mode="after")
    def evidence_gate(self) -> Self:
        if self.state == JobState.SUCCEEDED and not any(
            e.kind == "app_record" and e.record_status == "valid" for e in self.evidence
        ):
            raise ValueError("succeeded requires a valid app_record")
        if self.state == JobState.COMPLETED and any(e.kind == "app_record" for e in self.evidence):
            raise ValueError("simulation cannot attach app_record")
        if self.state == JobState.NEEDS_ATTENTION and self.resume_phase is None:
            raise ValueError("needs_attention requires resume_phase")
        return self


class ScheduleSpec(ProtocolModel):
    schedule_id: UUIDString
    job_template: JobSpec
    timezone: Literal["Asia/Shanghai"]
    local_time: Annotated[str, StringConstraints(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")]
    weekdays: Annotated[list[Annotated[int, Field(ge=1, le=7)]], Field(min_length=1)]
    enabled: bool

    @model_validator(mode="after")
    def unique_days(self) -> Self:
        if len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError("duplicate weekday")
        return self


class GeoPoint(ProtocolModel):
    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]


class RouteProfile(ProtocolModel):
    route_id: UUIDString
    revision: Digest
    input_crs: Literal["WGS84", "GCJ02", "BD09"]
    points: Annotated[list[GeoPoint], Field(min_length=2)]
    source_ref: Text


class SchoolProfile(ProtocolModel):
    profile_id: UUIDString
    revision: Digest
    campus: Text
    app_package: Text
    app_version: Text
    confirmed: bool
    allowed_region: Annotated[list[GeoPoint], Field(min_length=3)]
    rules: dict[Rule, Annotated[float, Field(ge=0)]]
    checkpoint_source: Literal["manual_confirmed", "adapter_verified"]

    @model_validator(mode="after")
    def ordered_speed(self) -> Self:
        low, high = self.rules.get("minimum_speed_mps"), self.rules.get("maximum_speed_mps")
        if low is not None and high is not None and low > high:
            raise ValueError("minimum speed exceeds maximum speed")
        return self


class VerificationResult(ProtocolModel):
    status: Literal["valid", "invalid", "pending", "unknown"]
    evidence: list[EvidenceRef]
    reason_code: Text | None

    @model_validator(mode="after")
    def valid_record(self) -> Self:
        if self.status == "valid" and not any(
            e.kind == "app_record" and e.record_status == "valid" for e in self.evidence
        ):
            raise ValueError("valid result requires valid app_record evidence")
        return self
