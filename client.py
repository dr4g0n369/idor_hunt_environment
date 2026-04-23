from typing import Dict

from openenv.core import EnvClient
from openenv.core.client_types import StepResult
from openenv.core.env_server.types import State

from models import IdorHuntAction, IdorHuntObservation


class IdorHuntEnv(
    EnvClient[IdorHuntAction, IdorHuntObservation, State]
):
    def _step_payload(self, action: IdorHuntAction) -> Dict:
        payload = {"method": action.method, "path": action.path}
        if action.body is not None:
            payload["body"] = action.body
        return payload

    def _parse_result(self, payload: Dict) -> StepResult[IdorHuntObservation]:
        obs_data = payload.get("observation", {})
        observation = IdorHuntObservation(
            status_code=obs_data.get("status_code", 404),
            body=obs_data.get("body", ""),
            done=payload.get("done", False),
            reward=payload.get("reward"),
            metadata=obs_data.get("metadata", {}),
        )
        return StepResult(
            observation=observation,
            reward=payload.get("reward"),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: Dict) -> State:
        return State(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
        )
