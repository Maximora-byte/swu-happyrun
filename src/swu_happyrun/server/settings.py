"""Explicit server configuration; credentials never participate in repr."""

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID


@dataclass(frozen=True)
class ServerSettings:
    database_path: Path
    admin_token: str = field(repr=False)
    agent_tokens: dict[str, str] = field(repr=False)
    bind_host: str = "127.0.0.1"
    port: int = 8080

    def __post_init__(self) -> None:
        tokens = [self.admin_token, *self.agent_tokens.values()]
        if any(
            not isinstance(token, str)
            or not token
            or len(token) > 4096
            or any(char.isspace() for char in token)
            for token in tokens
        ):
            raise ValueError("credentials must be nonempty bounded bearer values")
        if len(set(tokens)) != len(tokens):
            raise ValueError("credentials must be distinct")
        for agent_id in self.agent_tokens:
            if str(UUID(agent_id)) != agent_id:
                raise ValueError("agent identity must be a canonical UUID")
        if not 1 <= self.port <= 65535:
            raise ValueError("port outside allowed range")
        object.__setattr__(self, "database_path", Path(self.database_path))
