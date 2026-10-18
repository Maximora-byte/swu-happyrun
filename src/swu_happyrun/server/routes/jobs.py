"""S0 create/query endpoints; mutation commands are deliberately not registered."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response

from swu_happyrun.core.models import JobSpec, JobView
from swu_happyrun.server.auth import Principal, administrator, authenticated
from swu_happyrun.server.errors import ApiError

router = APIRouter()


@router.post("/jobs", response_model=JobView)
def create_job(
    spec: JobSpec,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(administrator)],
    idempotency_key: Annotated[str | None, Header()] = None,
) -> JobView:
    view, created = request.app.state.store.create(spec, idempotency_key or "")
    response.status_code = 201 if created else 200
    return view


@router.get("/jobs/{job_id}", response_model=JobView)
def get_job(
    job_id: str, request: Request, principal: Annotated[Principal, Depends(authenticated)]
) -> JobView:
    view = request.app.state.store.get(job_id)
    if view is None or (principal.role == "AGENT" and view.agent_id != principal.agent_id):
        raise ApiError(404, "not_found", "Resource not found")
    return view
