"""Digest-only authentication and role dependencies."""

import hashlib
import hmac
from dataclasses import dataclass

from fastapi import Request

from swu_happyrun.server.errors import ApiError
from swu_happyrun.server.settings import ServerSettings


@dataclass(frozen=True)
class Principal:
    role: str
    agent_id: str | None = None


class Authenticator:
    def __init__(self, settings: ServerSettings):
        self._principals = [(self._digest(settings.admin_token), Principal("ADMIN"))]
        self._principals.extend(
            (self._digest(token), Principal("AGENT", agent_id))
            for agent_id, token in settings.agent_tokens.items()
        )

    @staticmethod
    def _digest(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8")).digest()

    def authenticate(self, request: Request) -> Principal:
        headers = request.headers.getlist("authorization")
        if len(headers) != 1:
            raise ApiError(401, "unauthorized", "Authentication required")
        parts = headers[0].split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise ApiError(401, "unauthorized", "Authentication required")
        digest = self._digest(parts[1])
        principal = None
        for expected, candidate in self._principals:
            if hmac.compare_digest(digest, expected):
                principal = candidate
        if principal is None:
            raise ApiError(401, "unauthorized", "Authentication required")
        return principal


def authenticated(request: Request) -> Principal:
    return request.app.state.auth.authenticate(request)


def administrator(request: Request) -> Principal:
    principal = authenticated(request)
    if principal.role != "ADMIN":
        raise ApiError(403, "forbidden", "Role not permitted")
    return principal


def agent(request: Request) -> Principal:
    principal = authenticated(request)
    if principal.role != "AGENT":
        raise ApiError(403, "forbidden", "Role not permitted")
    return principal
