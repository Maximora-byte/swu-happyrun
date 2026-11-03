"""MuMu 6.8.4.0/API35 offline probe plan and redacted trace validation.

No execution, authentication, calibration, physical transport or capability grant.
The timing validator checks recorded durations; it cannot enforce a runtime timeout.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Phase = Literal["binding", "write", "readback", "stop", "quiescence"]
PHASES = ("binding", "write", "readback", "stop", "quiescence")


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ProbeBudget(_ClosedModel):
    """Proposed ceilings, not measured vendor latency or physical guarantees."""

    call_timeout_ms: int = Field(default=5000, ge=1, le=5000)
    total_timeout_ms: int = Field(default=30000, ge=1, le=30000)
    max_output_bytes: int = Field(default=65536, ge=1, le=65536)


class ProbeStep(_ClosedModel):
    phase: Phase
    outcome: Literal["observed", "failed", "timeout", "unknown", "not_run"]
    started_ms: int = Field(ge=0)
    finished_ms: int = Field(ge=0)
    output_bytes: int = Field(default=0, ge=0)


class ChannelTrace(_ClosedModel):
    """Redacted local offline trace; 'observed' is a claim, never authenticated proof.

    Actual identity/calibration remain in existing private R1/R2 objects; they must
    not be copied into this shareable timing trace. No arbitrary text is accepted.
    """

    channel: Literal["location", "gyro"]
    source: Literal["synthetic", "redacted_field_trace"]
    host_version: Literal["6.8.4.0"]
    android_api: Literal[35]
    steps: list[ProbeStep] = Field(min_length=5, max_length=5)

    @field_validator("android_api", mode="before")
    @classmethod
    def exact_api_type(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("android_api_type_invalid")
        return value

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if tuple(step.phase for step in self.steps) != PHASES:
            raise ValueError("phase_sequence_invalid")
        previous = 0
        for step in self.steps:
            if step.started_ms < previous or step.finished_ms < step.started_ms:
                raise ValueError("trace_time_invalid")
            previous = step.finished_ms
        return self


class ProbeAssessment(_ClosedModel):
    channel: Literal["location", "gyro"]
    status: Literal["unsupported"] = "unsupported"
    capabilities: tuple[()] = ()
    writes_performed: Literal[0] = 0
    trace_result: Literal["consistent", "rejected"]
    reason: Literal[
        "binding_unconfirmed",
        "write_unconfirmed",
        "readback_unconfirmed",
        "stop_unconfirmed",
        "quiescence_unconfirmed",
        "call_budget_exceeded",
        "total_budget_exceeded",
        "output_budget_exceeded",
        "physical_transport_not_implemented",
    ]


def assess_trace(trace: ChannelTrace, budget: ProbeBudget) -> ProbeAssessment:
    """Pure offline inspection, never calls a command or authorizes a write.

    Revalidate mutable nested lists before inspecting. Even a complete trace only
    establishes syntactic/timing consistency, not correct readback or queue empty.
    """
    trace = ChannelTrace.model_validate(trace.model_dump())
    budget = ProbeBudget.model_validate(budget.model_dump())
    reason = "physical_transport_not_implemented"
    if trace.steps[-1].finished_ms - trace.steps[0].started_ms >= budget.total_timeout_ms:
        reason = "total_budget_exceeded"
    else:
        for step in trace.steps:
            if step.finished_ms - step.started_ms >= budget.call_timeout_ms:
                reason = "call_budget_exceeded"
                break
            if step.output_bytes > budget.max_output_bytes:
                reason = "output_budget_exceeded"
                break
            if step.outcome != "observed":
                reason = f"{step.phase}_unconfirmed"
                break
    return ProbeAssessment(
        channel=trace.channel,
        trace_result="consistent" if reason == "physical_transport_not_implemented" else "rejected",
        reason=reason,
    )


def version_plan() -> dict:
    """Fresh data-only copy of actual help facts; unknown commands stay null."""
    prefix = "MuMuManager.exe control --vmindex INDEX tool "
    return {
        "host_version": "6.8.4.0",
        "android_api": 35,
        "source": "https://github.com/Maximora-byte/swu-happyrun/issues/7#issuecomment-6263450120",
        "status": "unsupported",
        "capabilities": [],
        "channels": {
            "location": {
                "help": prefix + "location --longitude LONGITUDE --latitude LATITUDE",
                "longitude_range": [-180, 180],
                "latitude_range": [-90, 90],
                "input_crs": None,
                "readback_command": None,
                "stop_command": None,
                "queue_clear_semantics": None,
            },
            "gyro": {
                "help": prefix + "gyro --gyro_x X --gyro_y Y --gyro_z Z",
                "quantity": "vendor_gravity_sensor_unspecified_units",
                "readback_command": None,
                "stop_command": None,
                "queue_clear_semantics": None,
            },
        },
    }
