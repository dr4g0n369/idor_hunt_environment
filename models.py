from typing import Optional
from openenv.core.env_server.types import Action, Observation
from pydantic import Field


class IdorHuntAction(Action):
    method: str = Field(..., description="HTTP method (GET or POST)")
    path: str = Field(..., description="URL path (e.g. /api/users/1)")
    body: Optional[str] = Field(default=None, description="JSON request body for POST requests")


class IdorHuntObservation(Observation):
    status_code: int = Field(..., description="HTTP status code")
    body: str = Field(..., description="HTTP response body")
