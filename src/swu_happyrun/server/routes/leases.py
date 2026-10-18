"""Authenticated fenced commands using the single shared request models."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from swu_happyrun.core.models import (
    ClaimRequest,
    DeviceRegistration,
    EventRequest,
    LeaseCommand,
    ResumeRequest,
    StopAckRequest,
)
from swu_happyrun.server.auth import Principal, administrator, agent

router = APIRouter()
Admin = Annotated[Principal, Depends(administrator)]
Agent = Annotated[Principal, Depends(agent)]


@router.post("/devices", status_code=201)
def register_device(body: DeviceRegistration, request: Request, principal: Admin):
    return request.app.state.store.register_device(body)


@router.get("/devices")
def devices(request: Request, principal: Admin):
    return request.app.state.store.list_devices()


@router.post("/leases/claim")
def claim(body: ClaimRequest, request: Request, principal: Agent):
    grant = request.app.state.store.claim(principal.agent_id, body.device_id)
    return grant if grant is not None else Response(status_code=204)


@router.post("/jobs/{job_id}/renew")
def renew(job_id: str, body: LeaseCommand, request: Request, principal: Agent):
    return request.app.state.store.renew(job_id, principal.agent_id, body)


@router.post("/jobs/{job_id}/events")
def event(job_id: str, body: EventRequest, request: Request, principal: Agent):
    return request.app.state.store.event(job_id, principal.agent_id, body.lease, body.event)


@router.post("/jobs/{job_id}/stop-ack")
def stop_ack(job_id: str, body: StopAckRequest, request: Request, principal: Agent):
    return request.app.state.store.stop_ack(job_id, principal.agent_id, body)


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str, request: Request, principal: Admin):
    return request.app.state.store.cancel(job_id)


@router.post("/jobs/{job_id}/resume")
def resume(job_id: str, body: ResumeRequest, request: Request, principal: Admin):
    return request.app.state.store.resume(job_id, body.expected_revision, body.action)
