try:
    from openenv.core.env_server.http_server import create_app
except Exception as e:
    raise ImportError(
        "openenv is required. Install with: uv sync"
    ) from e

from models import IdorHuntAction, IdorHuntObservation
from server.idor_hunt_env_environment import IdorHuntEnvironment


app = create_app(
    IdorHuntEnvironment,
    IdorHuntAction,
    IdorHuntObservation,
    env_name="idor_hunt_env",
    max_concurrent_envs=1,
)


def main(host: str = "0.0.0.0", port: int = 8000):
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
