from typing import Optional
from openenv.core.env_server.types import Action, Observation
from pydantic import Field


class IdorHuntAction(Action):
    method: str = Field(..., description="HTTP method (GET, POST, PUT, DELETE)")
    path: str = Field(..., description="URL path (e.g. /api/orders/1)")
    body: Optional[str] = Field(default=None, description="JSON request body")
    account: str = Field(default="alice", description="Account to act as (e.g. alice, bob, manager1, guest)")


class IdorHuntObservation(Observation):
    status_code: int = Field(..., description="HTTP status code")
    body: str = Field(..., description="HTTP response body")
