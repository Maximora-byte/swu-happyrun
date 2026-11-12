"""Admin-only schedule management."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from swu_happyrun.core.models import ScheduleSpec
from swu_happyrun.server.auth import Principal, administrator

router = APIRouter()
Admin = Annotated[Principal, Depends(administrator)]


@router.post("/schedules", status_code=201)
def create(body: ScheduleSpec, request: Request, principal: Admin):
    return request.app.state.scheduler.create(body)


@router.get("/schedules")
def schedules(request: Request, principal: Admin):
    return request.app.state.scheduler.list()


@router.put("/schedules/{schedule_id}")
def update(schedule_id: str, body: ScheduleSpec, request: Request, principal: Admin):
    return request.app.state.scheduler.update(schedule_id, body)
