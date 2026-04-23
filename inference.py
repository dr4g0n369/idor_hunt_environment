import os
import asyncio
from typing import List, Optional

from openai import OpenAI
from client import IdorHuntEnv
from models import IdorHuntAction

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
API_KEY = os.getenv("HF_TOKEN") or os.getenv("API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "meta-llama/Llama-3.1-70B-Instruct")
ENV_URL = os.getenv("ENV_URL", "http://localhost:8000")
LOCAL_IMAGE_NAME = os.getenv("LOCAL_IMAGE_NAME")

TASKS = [
    {"id": "idor_easy", "max_steps": 10},
    {"id": "idor_medium", "max_steps": 15},
]

HISTORY_WINDOW = 6

SYSTEM_PROMPT = """You are a penetration tester checking a corporate API for IDOR (Insecure Direct Object Reference) vulnerabilities.

You MUST respond with EXACTLY one HTTP request:
METHOD PATH [BODY]

Where:
- METHOD is GET or POST
- PATH starts with /
- BODY is optional JSON (only for POST)

Examples:
GET /api/users
GET /api/users/1
POST /api/login {"username": "alice", "password": "alice123"}
GET /api/notes/1

IDOR TESTING STRATEGY:
- List resources to discover IDs and structure
- Try accessing resources belonging to other users by changing IDs
- If an endpoint requires auth, login first with provided credentials
- Check if endpoints properly enforce ownership (can you see other users' data?)
- Try sequential IDs: /api/users/1, /api/users/2, etc.

Respond with ONLY the request. No explanation."""


def parse_action(text: str) -> IdorHuntAction | None:
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) >= 2:
            method = parts[0].upper()
            path = parts[1]
            if method in ("GET", "POST") and path.startswith("/"):
                body = parts[2] if len(parts) > 2 else None
                return IdorHuntAction(method=method, path=path, body=body)
    return None


async def run_task(ai_client: OpenAI, env_client: IdorHuntEnv, task: dict) -> float:
    task_id = task["id"]
    max_steps = task["max_steps"]

    print(f"\n[START] task={task_id}", flush=True)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    result = await env_client.reset(task_id=task_id)

    rewards: List[float] = []
    history: List[str] = []
    last_reward = 0.0

    for step in range(1, max_steps + 1):
        if result.done:
            break

        obs = result.observation

        feedback = ""
        if step > 1:
            if last_reward >= 0.2:
                feedback = f"\nReward: {last_reward:+.3f} (GOOD)"
            elif last_reward < 0:
                feedback = f"\nReward: {last_reward:+.3f} (PENALISED)"
            else:
                feedback = f"\nReward: {last_reward:+.3f}"

        history_block = ""
        if history:
            history_block = "\nHistory:\n" + "\n".join(history[-HISTORY_WINDOW:])

        user_prompt = f"HTTP {obs.status_code}\n{obs.body}{feedback}{history_block}\n\nNext request?"
        messages.append({"role": "user", "content": user_prompt})

        try:
            completion = ai_client.chat.completions.create(
                model=MODEL_NAME, messages=messages, temperature=0.3,
            )
            response_text = completion.choices[0].message.content or ""
        except Exception as exc:
            print(f"  [ERROR] {exc}", flush=True)
            response_text = ""

        messages.append({"role": "assistant", "content": response_text})

        action = parse_action(response_text)
        if not action:
            action = IdorHuntAction(method="GET", path="/api/users")

        result = await env_client.step(action)
        last_reward = result.reward or 0.0
        rewards.append(last_reward)

        action_str = f"{action.method} {action.path}"
        history.append(f"  [{step:02d}] {action_str:<40} HTTP {obs.status_code} r={last_reward:+.3f}")
        print(f"  [STEP] step={step} action={action_str} reward={last_reward:.3f} done={result.done}", flush=True)

    score = sum(rewards) / max(1, len(rewards))
    print(f"[END] task={task_id} steps={len(rewards)} score={score:.3f}", flush=True)
    return score


async def main() -> None:
    if not API_KEY:
        print("ERROR: Set HF_TOKEN or API_KEY environment variable!", flush=True)
        return

    ai_client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)

    if LOCAL_IMAGE_NAME:
        env_client = await IdorHuntEnv.from_docker_image(LOCAL_IMAGE_NAME)
    else:
        env_client = IdorHuntEnv(base_url=ENV_URL)
        await env_client.connect()

    try:
        for task in TASKS:
            await run_task(ai_client, env_client, task)
    finally:
        await env_client.close()


if __name__ == "__main__":
    asyncio.run(main())
