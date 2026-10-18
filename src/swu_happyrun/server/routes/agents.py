"""Authenticated agent observations; they do not establish device ownership."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from swu_happyrun.core.models import AgentHello
from swu_happyrun.server.auth import Principal, agent
from swu_happyrun.server.errors import ApiError

router = APIRouter()


def observe(
    hello: AgentHello, principal: Principal, request: Request, *, heartbeat: bool = False
) -> None:
    if hello.agent_id != principal.agent_id:
        raise ApiError(403, "identity_mismatch", "Agent identity does not match credentials")
    request.app.state.store.observe_agent(hello, heartbeat=heartbeat)


@router.post("/agents/hello")
def hello_agent(
    hello: AgentHello, request: Request, principal: Annotated[Principal, Depends(agent)]
) -> dict:
    observe(hello, principal, request)
    return {"agent_id": principal.agent_id, "heartbeat_seconds": 10, "lease_seconds": 30}


@router.post("/agents/heartbeat")
def heartbeat(
    hello: AgentHello, request: Request, principal: Annotated[Principal, Depends(agent)]
) -> dict:
    observe(hello, principal, request, heartbeat=True)
    return {"server_time": request.app.state.clock.utcnow().isoformat().replace("+00:00", "Z")}
