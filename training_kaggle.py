# /// script
# dependencies = [
#   "unsloth[kaggle]",
#   "trl>=0.16",
#   "datasets",
#   "flask",
#   "werkzeug",
#   "requests",
#   "openenv-core",
#   "matplotlib",
#   "huggingface_hub>=0.27.0",
# ]
# ///

import os
import sys
import json
import re
import traceback
import warnings

import requests as _requests

REPO_URL = "https://github.com/dr4g0n369/idor_hunt_environment.git"
REPO_DIR = "/root/idor_hunt_env"

if not os.path.exists(REPO_DIR):
    subprocess.run(["git", "clone", REPO_URL, REPO_DIR], check=True)

os.chdir(REPO_DIR)
sys.path.insert(0, REPO_DIR)

print(f"Working directory: {os.getcwd()}")
print(f"Files: {os.listdir('.')}")

MODEL_NAME      = "unsloth/Qwen3-4B"
MAX_SEQ_LEN     = 2048
LORA_RANK       = 16
NUM_GENERATIONS = 4
TRAINING_STEPS  = 500
BATCH_SIZE      = 2
EVAL_EPISODES   = 3
OUTPUT_DIR      = "/root/grpo_idor_hunt"

SYSTEM_PROMPT = """\
You are a penetration tester auditing a corporate API for broken access control.
You have multiple test accounts at different privilege levels.
Send exactly ONE HTTP request per turn. Format:
  METHOD PATH @account

For POST requests with a body:
  POST PATH JSON_BODY @account

Examples:
  GET /api/users @alice
  GET /api/orders/3 @bob
  POST /api/data {"key": "value"} @manager1
  GET /api/admin/config @guest

Rules:
- METHOD is GET, POST, PUT, or DELETE
- PATH starts with /
- @account selects which test account to use (default: alice)
- Output ONLY the request line, nothing else
- Do NOT explain your reasoning\
"""

HF_TOKEN = "HF_TOKEN_REDACTED"

print(f"HF Token present: {bool(HF_TOKEN)}")

SUPERVISOR_MODEL = "google/gemma-3-12b-it"
SUPERVISOR_API_URL = f"https://router.huggingface.co/hf-inference/models/{SUPERVISOR_MODEL}/v1/chat/completions"
SUPERVISOR_ENABLED = True
SUPERVISOR_CACHE = {}

SUPERVISOR_SYSTEM_PROMPT = """\
You are a senior penetration testing supervisor reviewing a junior tester's actions.
You will be given:
- The task description (what the tester is trying to find)
- The tester's HTTP request (method, path, account used)
- The server response (status code and body snippet)
- The environment's deterministic reward

Evaluate the tester's action on these criteria:
1. RELEVANCE: Is this request useful for discovering the target vulnerability class?
2. STRATEGY: Does the request show good security testing methodology?
3. EFFICIENCY: Is the tester wasting steps on obviously public/safe endpoints?
4. STEALTH: Would this request look suspicious to a WAF or blue team?
5. PROGRESS: Does this request advance toward finding a real vulnerability?

Output ONLY a JSON object with two keys:
- "score": a float between -1.0 and 1.0
- "reasoning": a one-sentence explanation

Example output:
{"score": 0.6, "reasoning": "Good cross-account access test on a private endpoint."}

Scoring guide:
-1.0 = Completely wrong approach (testing public endpoints, syntax errors)
 0.0 = Neutral (valid request but not advancing toward the goal)
+1.0 = Excellent (directly tests for the target vulnerability with correct methodology)
"""

from server.idor_hunt_env_environment import IdorHuntEnvironment


class _Action:
    def __init__(self, method, path, body=None, account="alice"):
        self.method = method
        self.path = path
        self.body = body
        self.account = account


def ask_gemma_supervisor(task_id, agent_output, parsed_action, env_obs, env_reward):
    if not SUPERVISOR_ENABLED or not HF_TOKEN:
        return 0.0

    if parsed_action is None:
        return -0.5

    cache_key = f"{task_id}|{parsed_action.method}|{parsed_action.path}|{parsed_action.account}|{env_obs.status_code}"
    if cache_key in SUPERVISOR_CACHE:
        return SUPERVISOR_CACHE[cache_key]

    body_snippet = str(env_obs.body)[:500] if hasattr(env_obs, 'body') else "N/A"

    user_prompt = (
        f"Task: {task_id}\n"
        f"Agent's raw output: {agent_output[:200]}\n"
        f"Parsed request: {parsed_action.method} {parsed_action.path} @{parsed_action.account}\n"
        f"Server response status: {env_obs.status_code}\n"
        f"Server response body (truncated): {body_snippet}\n"
        f"Environment deterministic reward: {env_reward}\n"
        f"\nEvaluate this action."
    )

    try:
        resp = _requests.post(
            SUPERVISOR_API_URL,
            headers={"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"},
            json={
                "model": SUPERVISOR_MODEL,
                "messages": [
                    {"role": "system", "content": SUPERVISOR_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 150,
                "temperature": 0.1,
            },
            timeout=15,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        json_match = re.search(r'\{[^}]+\}', content)
        if json_match:
            parsed = json.loads(json_match.group())
            score = float(parsed.get("score", 0.0))
            score = max(-1.0, min(1.0, score))
            reasoning = parsed.get("reasoning", "")
            print(f"    [SUPERVISOR] score={score:+.2f} | {reasoning}")
        else:
            score = 0.0
            print(f"    [SUPERVISOR] Could not parse JSON from: {content[:100]}")
    except Exception as e:
        score = 0.0
        print(f"    [SUPERVISOR] API error (fallback to 0.0): {e}")

    SUPERVISOR_CACHE[cache_key] = score
    return score


def hybrid_reward(env_reward, supervisor_score):
    if env_reward < 0:
        return env_reward
    return (env_reward * 0.7) + (supervisor_score * 0.3)


def verify_env_state(obs, action, task_id):
    penalties = 0.0
    if obs.status_code == 404 and action.path.startswith("/api/"):
        penalties -= 0.1
    if obs.status_code >= 500:
        penalties -= 0.2
    safe_endpoints = ["/api/announcements", "/api/catalog", "/api/teams", "/api/shared-files"]
    if any(action.path.startswith(ep) for ep in safe_endpoints):
        if task_id in ("idor_horizontal", "privesc"):
            penalties -= 0.15
    return penalties


print(f"Supervisor model: {SUPERVISOR_MODEL}")
print(f"Supervisor enabled: {SUPERVISOR_ENABLED}")
print(f"HF Token present: {bool(HF_TOKEN)}")
print("Supervisor setup complete.")

env = IdorHuntEnvironment()

print("=== Testing idor_horizontal ===")
obs = env.reset(task_id="idor_horizontal")
print(f"Reset: status={obs.status_code}")
obs = env.step(_Action("GET", "/api/users", account="alice"))
print(f"List users: status={obs.status_code} reward={obs.reward}")
obs = env.step(_Action("GET", "/api/orders", account="alice"))
print(f"Own orders (alice): status={obs.status_code} reward={obs.reward}")
obs = env.step(_Action("GET", "/api/orders/3", account="alice"))
print(f"Bob's order as alice: status={obs.status_code} reward={obs.reward} done={obs.done}")
print(f"Grade: {env.get_grade()}")
env.close()

print("\n=== Testing privesc ===")
env2 = IdorHuntEnvironment()
obs = env2.reset(task_id="privesc")
obs = env2.step(_Action("GET", "/api/reports", account="alice"))
print(f"Reports as alice (user): status={obs.status_code} reward={obs.reward}")
obs = env2.step(_Action("GET", "/api/admin/config", account="guest"))
print(f"Admin config as guest: status={obs.status_code} reward={obs.reward} done={obs.done}")
print(f"Grade: {env2.get_grade()}")
env2.close()

print("\n=== Testing full_audit ===")
env3 = IdorHuntEnvironment()
obs = env3.reset(task_id="full_audit")
obs = env3.step(_Action("GET", "/api/orders/3", account="alice"))
print(f"Orders IDOR: status={obs.status_code} reward={obs.reward}")
obs = env3.step(_Action("GET", "/api/reports", account="bob"))
print(f"Reports privesc: status={obs.status_code} reward={obs.reward}")
obs = env3.step(_Action("GET", "/api/admin/config", account="alice"))
print(f"Admin config privesc: status={obs.status_code} reward={obs.reward} done={obs.done}")
print(f"Grade: {env3.get_grade()}")
env3.close()

print("\n=== Testing false positives (should yield low/no reward) ===")
env4 = IdorHuntEnvironment()
obs = env4.reset(task_id="full_audit")
obs = env4.step(_Action("GET", "/api/announcements", account="alice"))
print(f"Announcements (public, not a vuln): status={obs.status_code} reward={obs.reward}")
obs = env4.step(_Action("GET", "/api/announcements/1", account="guest"))
print(f"Announcement detail as guest (public): status={obs.status_code} reward={obs.reward}")
obs = env4.step(_Action("GET", "/api/catalog", account="guest"))
print(f"Catalog as guest (public): status={obs.status_code} reward={obs.reward}")
obs = env4.step(_Action("GET", "/api/shared-files", account="alice"))
print(f"Shared files (scoped, not a vuln): status={obs.status_code} reward={obs.reward}")
obs = env4.step(_Action("GET", "/api/activity", account="alice"))
print(f"Activity log (own data only): status={obs.status_code} reward={obs.reward}")
obs = env4.step(_Action("GET", "/api/tickets", account="alice"))
print(f"Tickets (public tickets, not a vuln): status={obs.status_code} reward={obs.reward}")
obs = env4.step(_Action("GET", "/api/tickets/4", account="alice"))
print(f"Private ticket (access denied): status={obs.status_code} reward={obs.reward}")
obs = env4.step(_Action("GET", "/api/teams/Engineering", account="guest"))
print(f"Team directory (public org info): status={obs.status_code} reward={obs.reward}")
print(f"False-positive findings: {env4.findings}")
env4.close()

print("\nEnvironment works!")

DEBUG_LOG = []
DEBUG_EVERY_N = 1
_reward_call_count = [0]

ALL_ENDPOINTS = [
    "GET  /api/users", "GET  /api/users/<id>",
    "GET  /api/orders", "GET  /api/orders/<id>",
    "GET  /api/documents", "GET  /api/documents/<id>",
    "GET  /api/reports", "GET  /api/reports/<id>",
    "GET  /api/announcements", "GET  /api/announcements/<id>",
    "GET  /api/shared-files", "GET  /api/shared-files/<id>",
    "GET  /api/catalog", "GET  /api/catalog/<id>",
    "GET  /api/activity",
    "GET  /api/tickets", "GET  /api/tickets/<id>",
    "GET  /api/teams", "GET  /api/teams/<department>",
    "GET  /api/admin/config", "GET  /api/admin/users",
    "DELETE /api/admin/users/<id>",
]

ALL_ACCOUNTS = {
    "alice": {"role": "user", "department": "Engineering"},
    "bob": {"role": "user", "department": "Sales"},
    "manager1": {"role": "manager", "department": "Engineering"},
    "guest": {"role": "guest", "department": "External"},
}


def _reset_obs(task_desc):
    return json.dumps({
        "app": "CorpAPI", "version": "2.1.0",
        "task": task_desc,
        "endpoints": ALL_ENDPOINTS,
        "accounts": ALL_ACCOUNTS,
        "note": "Use @account_name suffix to act as a specific account. Default: alice.",
    })


SEEDED_STATES = [
    {
        "task": "idor_horizontal",
        "pre_actions": [],
        "obs": _reset_obs(
            "Test this corporate API for horizontal IDOR vulnerabilities. "
            "Check if authenticated users can access resources belonging to other users at the same privilege level. "
            "Try accessing other users' data through various endpoints."
        ),
        "hint": "Start by listing users and orders to understand what data exists. Not all endpoints are vulnerable — focus on ones that expose private per-user data.",
    },
    {
        "task": "idor_horizontal",
        "pre_actions": [("GET", "/api/users", None, "alice")],
        "obs": '[{"id":1,"username":"admin","role":"admin","department":"IT"},{"id":2,"username":"manager1","role":"manager","department":"Engineering"},{"id":3,"username":"alice","role":"user","department":"Engineering"},{"id":4,"username":"bob","role":"user","department":"Sales"},{"id":5,"username":"guest","role":"guest","department":"External"}]',
        "hint": "Users listed. Now check /api/orders to see your own orders, then try accessing other users' orders by ID.",
    },
    {
        "task": "idor_horizontal",
        "pre_actions": [("GET", "/api/users", None, "alice"), ("GET", "/api/orders", None, "alice")],
        "obs": '[{"id":1,"product":"Laptop Pro X1","amount":1299.99,"status":"shipped"},{"id":2,"product":"USB-C Hub","amount":49.99,"status":"delivered"}]',
        "hint": "Alice has orders 1-2. Bob likely has other IDs. Try accessing /api/orders/3 or /api/orders/4 as alice — these belong to bob.",
    },
    {
        "task": "idor_horizontal",
        "pre_actions": [
            ("GET", "/api/users", None, "alice"),
            ("GET", "/api/orders", None, "alice"),
            ("GET", "/api/orders", None, "bob"),
        ],
        "obs": '[{"id":3,"product":"Monitor 4K UHD","amount":599.99,"status":"pending"},{"id":4,"product":"Mechanical Keyboard","amount":149.99,"status":"shipped"}]',
        "hint": "Bob has orders 3-4. Try accessing Bob's order /api/orders/3 as alice to test for IDOR.",
    },
    {
        "task": "idor_horizontal",
        "pre_actions": [
            ("GET", "/api/users", None, "alice"),
            ("GET", "/api/announcements", None, "alice"),
        ],
        "obs": '[{"id":1,"title":"System Maintenance Window","published_at":"2024-03-10","pinned":1,"author":"admin"},{"id":2,"title":"Q4 All-Hands Meeting Scheduled","published_at":"2024-12-01","pinned":1,"author":"manager1"}]',
        "hint": "Announcements are public company-wide posts — not a vulnerability. Focus on endpoints with per-user data like /api/orders.",
    },
    {
        "task": "privesc",
        "pre_actions": [],
        "obs": _reset_obs(
            "Test this corporate API for vertical privilege escalation. "
            "Check if lower-privileged users (user, guest) can access endpoints or data "
            "that should be restricted to higher roles (manager, admin)."
        ),
        "hint": "Try accessing admin/manager endpoints with lower-privileged accounts. Endpoints like /api/catalog and /api/announcements are intentionally public — not vulnerabilities.",
    },
    {
        "task": "privesc",
        "pre_actions": [("GET", "/api/users", None, "alice")],
        "obs": '[{"id":1,"username":"admin","role":"admin","department":"IT"},{"id":2,"username":"manager1","role":"manager","department":"Engineering"},{"id":3,"username":"alice","role":"user","department":"Engineering"},{"id":4,"username":"bob","role":"user","department":"Sales"},{"id":5,"username":"guest","role":"guest","department":"External"}]',
        "hint": "User list shows roles. Try accessing /api/reports as a regular user — reports may be restricted to managers. Also try /api/admin/config.",
    },
    {
        "task": "privesc",
        "pre_actions": [
            ("GET", "/api/users", None, "alice"),
            ("GET", "/api/reports", None, "alice"),
        ],
        "obs": '[{"id":1,"title":"Q3 Revenue Report","visibility":"managers"},{"id":2,"title":"Security Audit 2024-Q2","visibility":"admin"},{"id":3,"title":"Team Performance Review","visibility":"managers"}]',
        "hint": "Reports listed as alice (regular user) — this is a privilege escalation! Now try /api/admin/config as alice or guest.",
    },
    {
        "task": "privesc",
        "pre_actions": [
            ("GET", "/api/users", None, "guest"),
            ("GET", "/api/catalog", None, "guest"),
            ("GET", "/api/teams/Engineering", None, "guest"),
        ],
        "obs": '{"department":"Engineering","members":[{"id":2,"username":"manager1","role":"manager"},{"id":3,"username":"alice","role":"user"}]}',
        "hint": "Catalog and team directory are public by design — not privilege escalation. Try /api/reports or /api/admin/config as guest instead.",
    },
    {
        "task": "full_audit",
        "pre_actions": [],
        "obs": _reset_obs(
            "Perform a full access control audit of this corporate API. "
            "Find all broken access control vulnerabilities: "
            "horizontal IDOR (accessing other users' resources) and "
            "vertical privilege escalation (accessing higher-role endpoints). "
            "Test systematically across all accounts and endpoints."
        ),
        "hint": "Test all endpoints with different accounts. Some endpoints (announcements, catalog, teams, shared-files, activity) are intentionally accessible — focus on orders, reports, and admin endpoints.",
    },
    {
        "task": "full_audit",
        "pre_actions": [
            ("GET", "/api/users", None, "alice"),
            ("GET", "/api/orders", None, "alice"),
        ],
        "obs": '[{"id":1,"product":"Laptop Pro X1","amount":1299.99,"status":"shipped"},{"id":2,"product":"USB-C Hub","amount":49.99,"status":"delivered"}]',
        "hint": "Alice's orders are 1-2. Try accessing other order IDs as alice, then test /api/reports and /api/admin/config with lower-privileged accounts.",
    },
    {
        "task": "full_audit",
        "pre_actions": [
            ("GET", "/api/users", None, "alice"),
            ("GET", "/api/orders/3", None, "alice"),
        ],
        "obs": '{"id":3,"user_id":4,"product":"Monitor 4K UHD","amount":599.99,"status":"pending","shipping_address":"456 Oak Ave, Springfield"}',
        "hint": "IDOR confirmed on orders! Alice accessed Bob's order. Now test for privilege escalation: try /api/reports as alice and /api/admin/config as guest.",
    },
    {
        "task": "full_audit",
        "pre_actions": [
            ("GET", "/api/users", None, "alice"),
            ("GET", "/api/activity", None, "alice"),
            ("GET", "/api/tickets", None, "alice"),
            ("GET", "/api/shared-files", None, "alice"),
        ],
        "obs": '[{"id":1,"filename":"employee_handbook_2024.pdf","shared_with":"everyone","uploader":"admin"},{"id":2,"filename":"engineering_onboarding.pdf","shared_with":"engineering","uploader":"manager1"}]',
        "hint": "Shared files, activity logs, and tickets are working as intended — not vulnerabilities. Try /api/orders/<id> across accounts and /api/admin/config as a non-admin.",
    },
]

THINK_CLOSED = re.compile(r"<think>.*?</think>", re.DOTALL)
THINK_UNCLOSED = re.compile(r"<think>.*", re.DOTALL)


def strip_thinking(text: str) -> str:
    stripped = THINK_CLOSED.sub("", text).strip()
    if stripped:
        return stripped
    stripped = THINK_UNCLOSED.sub("", text).strip()
    if stripped:
        return stripped
    return text.strip()


def extract_text(completion) -> str:
    if isinstance(completion, str):
        return completion
    if isinstance(completion, list):
        for msg in completion:
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                return msg.get("content", "")
        if completion and isinstance(completion[0], dict):
            return completion[0].get("content", "")
        return str(completion)
    if isinstance(completion, dict):
        return completion.get("content", str(completion))
    return str(completion)


ACTION_RE = re.compile(r'\b(GET|POST|PUT|DELETE)\s+(/\S*)\s*(@\w+)?', re.IGNORECASE)

def parse_action(text):
    if not isinstance(text, str):
        text = extract_text(text)
    raw = text
    text = strip_thinking(text)
    if not text.strip():
        m = ACTION_RE.search(raw)
        if m:
            method = m.group(1).upper()
            path = m.group(2)
            account = m.group(3).lstrip("@").lower() if m.group(3) else "alice"
            return _Action(method, path, None, account)
        return None
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        account = "alice"
        at_match = re.search(r"@(\w+)\s*$", line)
        if at_match:
            account = at_match.group(1).lower()
            line = line[:at_match.start()].strip()
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        m = parts[0].upper()
        if m not in ("GET", "POST", "PUT", "DELETE"):
            continue
        rest = parts[1].strip()
        if m in ("GET", "DELETE"):
            p, b = rest, None
        else:
            sub = rest.split(None, 1)
            p = sub[0]
            b = sub[1] if len(sub) > 1 else None
        if p.startswith("/"):
            return _Action(m, p, b, account)
    return None


def build_messages(state: dict) -> list:
    user_content = f"{state['obs']}\nHint: {state['hint']}\n\nWhat is your next request?"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def compute_reward(state_idx: int, completion) -> float:
    state = SEEDED_STATES[state_idx]
    text = extract_text(completion)
    _reward_call_count[0] += 1
    prompt_msgs = build_messages(state)
    prompt_str = f"[system]: {prompt_msgs[0]['content'][:150]}...\n    [user]: {prompt_msgs[1]['content']}"
    env = IdorHuntEnvironment()
    try:
        env.reset(task_id=state["task"])
        for m, p, b, acct in state["pre_actions"]:
            env.step(_Action(m, p, b, acct))
        action = parse_action(text)
        if action is None:
            supervisor_score = ask_gemma_supervisor(state["task"], text, None, None, -0.3)
            entry = {
                "call": _reward_call_count[0],
                "task": state["task"],
                "raw_output": text,
                "parsed": None,
                "reward": -0.3,
                "supervisor_score": supervisor_score,
                "reason": "parse_failed",
            }
            DEBUG_LOG.append(entry)
            print(f"  [DBG #{_reward_call_count[0]}] task={state['task']} | state_idx={state_idx} | PARSE FAIL")
            print(f"    Prompt sent:")
            print(f"    {prompt_str}")
            print(f"    Model output ({len(text)} chars):")
            print(f"    {text}")
            print()
            return -0.3
        obs = env.step(action)
        env_reward = float(obs.reward)
        supervisor_score = ask_gemma_supervisor(state["task"], text, action, obs, env_reward)
        state_penalty = verify_env_state(obs, action, state["task"])
        reward = hybrid_reward(env_reward, supervisor_score) + state_penalty
        entry = {
            "call": _reward_call_count[0],
            "task": state["task"],
            "raw_output": text,
            "parsed": f"{action.method} {action.path} @{action.account}",
            "status": obs.status_code,
            "env_reward": env_reward,
            "supervisor_score": supervisor_score,
            "state_penalty": state_penalty,
            "hybrid_reward": reward,
            "reward": reward,
            "done": obs.done,
        }
        DEBUG_LOG.append(entry)
        print(f"  [DBG #{_reward_call_count[0]}] task={state['task']} | state_idx={state_idx} | {action.method} {action.path} @{action.account} | status={obs.status_code} | env_r={env_reward:+.3f} | sup={supervisor_score:+.2f} | penalty={state_penalty:+.2f} | final={reward:+.3f}")
        print(f"    Prompt sent:")
        print(f"    {prompt_str}")
        print(f"    Model output: {text}")
        print()
        return reward
    except Exception as exc:
        entry = {
            "call": _reward_call_count[0],
            "task": state["task"],
            "raw_output": text,
            "reward": -0.2,
            "reason": f"exception: {exc}",
            "traceback": traceback.format_exc(),
        }
        DEBUG_LOG.append(entry)
        print(f"  [DBG #{_reward_call_count[0]}] task={state['task']} | EXCEPTION: {exc}")
        print(f"    Traceback: {traceback.format_exc()}")
        return -0.2
    finally:
        env.close()


def format_reward(completion) -> float:
    text = extract_text(completion)
    text = strip_thinking(text)
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return -0.5
    first = lines[0]
    parts = first.split()
    if len(parts) >= 2 and parts[0].upper() in ("GET", "POST", "PUT", "DELETE") and parts[1].startswith("/"):
        bonus = 0.2 if len(lines) == 1 else 0.0
        return bonus
    return -0.5


def reward_fn(completions: list, state_idx=None, **kwargs) -> list:
    if state_idx is None:
        state_idx = [0] * len(completions)
    env_rewards = [compute_reward(int(idx), c) for idx, c in zip(state_idx, completions)]
    fmt_rewards = [format_reward(c) for c in completions]
    rewards = [e + f for e, f in zip(env_rewards, fmt_rewards)]
    print(f"  [BATCH] env={[f'{r:+.3f}' for r in env_rewards]} fmt={[f'{r:+.3f}' for r in fmt_rewards]} total={[f'{r:+.3f}' for r in rewards]} | mean={sum(rewards)/len(rewards):+.3f} | spread={max(rewards)-min(rewards):.3f}")
    return rewards


print(f"Seeded states: {len(SEEDED_STATES)}")
print(f"Tasks covered: {set(s['task'] for s in SEEDED_STATES)}")

test_closed = "<think>\nLet me try bob's order.\n</think>\nGET /api/orders/3 @bob"
test_unclosed = "<think>\nLet me think about this... I should try accessing the admin"
test_chat = [{"role": "assistant", "content": "<think>\nhmm\n</think>\nGET /api/admin/config @guest"}]
test_account = "GET /api/reports @alice"

a1 = parse_action(test_closed)
a2 = parse_action(test_unclosed)
a3 = parse_action(test_chat)
a4 = parse_action(test_account)
print(f"Closed think:   {a1.method} {a1.path} @{a1.account}" if a1 else "Closed think:   None")
print(f"Unclosed think: {a2}" if not a2 else f"Unclosed think: {a2.method} {a2.path} @{a2.account}")
print(f"Chat format:    {a3.method} {a3.path} @{a3.account}" if a3 else "Chat format:    None")
print(f"Account parse:  {a4.method} {a4.path} @{a4.account}" if a4 else "Account parse:  None")

import torch
from unsloth import FastLanguageModel

print(f"Loading {MODEL_NAME} ...")
print(f"GPU: {torch.cuda.get_device_name(0)}")
print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=MODEL_NAME,
    max_seq_length=MAX_SEQ_LEN,
    load_in_4bit=True,
    dtype=None,
)

if hasattr(tokenizer, "chat_template") and "<think>" in (tokenizer.chat_template or ""):
    tokenizer.chat_template = tokenizer.chat_template.replace(
        "{{- '<think>\n' }}", "{{- '' }}"
    )
    print("Disabled Qwen3 thinking mode in chat template")

model = FastLanguageModel.get_peft_model(
    model,
    r=LORA_RANK,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_alpha=LORA_RANK,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=42,
)

print("Model loaded.")

warnings.filterwarnings("ignore", message=".*max_new_tokens.*max_length.*")
warnings.filterwarnings("ignore", message=".*AttentionMaskConverter.*")
warnings.filterwarnings("ignore", category=FutureWarning, module="transformers.modeling_attn_mask_utils")


def run_episode(model, tokenizer, task_id: str, verbose: bool = True) -> float:
    max_steps = {"idor_horizontal": 15, "privesc": 20, "full_audit": 30}[task_id]
    env = IdorHuntEnvironment()
    try:
        obs = env.reset(task_id=task_id)
        history = []

        for step in range(max_steps):
            if obs.done:
                break

            history_block = "\n".join(history[-4:])
            user_content = (
                f"HTTP {obs.status_code}\n{obs.body}"
                + (f"\n\nHistory:\n{history_block}" if history_block else "")
                + "\n\nWhat is your next request?"
            )
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ]

            if verbose:
                print(f"\n{'='*80}")
                print(f"STEP {step+1}/{max_steps}")
                print(f"{'='*80}")
                print(f"\n--- PROMPT SENT TO MODEL ---")
                print(f"[system]: {SYSTEM_PROMPT[:200]}...")
                print(f"[user]: {user_content}")

            text = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
                enable_thinking=False,
            )
            inputs = tokenizer(text=text, return_tensors="pt").to("cuda")
            input_len = inputs["input_ids"].shape[1]

            if verbose:
                print(f"\n--- TOKENIZED ---")
                print(f"Input tokens: {input_len}")

            with torch.no_grad():
                gen_config = dict(
                    max_new_tokens=512,
                    max_length=None,
                    temperature=0.4,
                    do_sample=True,
                    pad_token_id=tokenizer.eos_token_id,
                )
                out = model.generate(**inputs, **gen_config)
            new_tokens = out[0][input_len:]
            response = tokenizer.decode(new_tokens, skip_special_tokens=True)
            gen_token_count = len(new_tokens)

            if verbose:
                print(f"\n--- MODEL RESPONSE ({gen_token_count} tokens) ---")
                print(response)

            action = parse_action(response)

            if verbose:
                print(f"\n--- PARSED ACTION ---")
            if action is None:
                if verbose:
                    print(f"PARSE FAILED — could not extract valid action from response")
                    stripped = strip_thinking(response)
                    print(f"After stripping think tags: {stripped!r}")
                break

            if verbose:
                print(f"{action.method} {action.path} @{action.account}" + (f" body={action.body}" if action.body else ""))

            obs = env.step(action)

            if verbose:
                print(f"\n--- ENVIRONMENT RESPONSE ---")
                print(f"Status: {obs.status_code}")
                print(f"Reward: {obs.reward:+.3f}")
                print(f"Done: {obs.done}")
                print(f"Body: {obs.body}")

            entry = f"[{step+1:02d}] {action.method} {action.path} @{action.account} -> {obs.status_code} r={obs.reward:+.3f}"
            history.append(entry)

        grade = env.get_grade()
        if verbose:
            print(f"\n{'='*80}")
            print(f"EPISODE COMPLETE")
            print(f"Grade: {grade:.2f}")
            print(f"Findings: {env.findings}")
            print(f"Steps taken: {len(history)}")
            print(f"{'='*80}")
        return grade
    finally:
        env.close()


def evaluate(model, tokenizer, n: int = EVAL_EPISODES) -> dict:
    FastLanguageModel.for_inference(model)
    results = {}
    for task_id in ("idor_horizontal", "privesc", "full_audit"):
        print(f"\n{'#'*80}")
        print(f"# TASK: {task_id}")
        print(f"{'#'*80}")
        grades = []
        for ep in range(n):
            print(f"\n  Episode {ep+1}/{n}:")
            g = run_episode(model, tokenizer, task_id, verbose=True)
            grades.append(g)
        results[task_id] = round(sum(grades) / len(grades), 3)
        print(f"\n  {task_id}  grades={grades}  avg={results[task_id]:.3f}")
    FastLanguageModel.for_training(model)
    return results


print(f"Running baseline evaluation ({EVAL_EPISODES} episodes per task)...")
baseline = evaluate(model, tokenizer)
print(f"\nBaseline: {baseline}")

from datasets import Dataset
from trl import SFTTrainer, SFTConfig
from sft_data import get_sft_conversations, SFT_EXAMPLES

sft_conversations = get_sft_conversations()

formatted_texts = []
for conv in sft_conversations:
    text = tokenizer.apply_chat_template(
        conv, tokenize=False, add_generation_prompt=False,
        enable_thinking=False,
    )
    formatted_texts.append(text)

sft_dataset = Dataset.from_dict({"text": formatted_texts})

print(f"SFT dataset: {len(sft_dataset)} examples")
print(f"Sample text (first 200 chars): {formatted_texts[0][:200]}")
print(f"Sample actions: {[ex['action'] for ex in SFT_EXAMPLES[:5]]}")

SFT_STEPS = 200
SFT_LR = 2e-5
SFT_BATCH = 4

sft_config = SFTConfig(
    output_dir=OUTPUT_DIR + "/sft",
    num_train_epochs=3,
    max_steps=SFT_STEPS,
    per_device_train_batch_size=SFT_BATCH,
    learning_rate=SFT_LR,
    warmup_steps=5,
    logging_steps=10,
    save_steps=SFT_STEPS,
    max_seq_length=MAX_SEQ_LEN,
    dataset_text_field="text",
    fp16=not torch.cuda.is_bf16_supported(),
    bf16=torch.cuda.is_bf16_supported(),
    report_to="none",
)

FastLanguageModel.for_training(model)
sft_trainer = SFTTrainer(
    model=model,
    args=sft_config,
    train_dataset=sft_dataset,
    processing_class=tokenizer,
)

print(f"Starting SFT training — {SFT_STEPS} steps, lr={SFT_LR}, batch={SFT_BATCH}...")
sft_trainer.train()
print("SFT training complete.")

print(f"Post-SFT evaluation ({EVAL_EPISODES} episodes per task)...")
post_sft = evaluate(model, tokenizer)
print(f"\nPost-SFT: {post_sft}")

print("\n" + "=" * 50)
print("SFT IMPACT")
print("=" * 50)
tasks = list(baseline.keys())
task_names = ["Horizontal IDOR", "Privilege Escalation", "Full Audit"]
print(f"{'Task':<22} {'Before':>8} {'After SFT':>10} {'Delta':>8}")
print("-" * 52)
for task, name in zip(tasks, task_names):
    delta = post_sft[task] - baseline[task]
    sign = "+" if delta >= 0 else ""
    print(f"{name:<22} {baseline[task]:>8.3f} {post_sft[task]:>10.3f} {sign}{delta:>7.3f}")

from trl import GRPOTrainer, GRPOConfig

dataset = Dataset.from_dict({
    "prompt": [build_messages(s) for s in SEEDED_STATES],
    "state_idx": list(range(len(SEEDED_STATES))),
})
print(f"Dataset: {len(dataset)} seeded states")

config = GRPOConfig(
    output_dir=OUTPUT_DIR,
    num_train_epochs=1,
    max_steps=TRAINING_STEPS,
    per_device_train_batch_size=BATCH_SIZE,
    num_generations=NUM_GENERATIONS,
    max_completion_length=512,
    learning_rate=5e-6,
    warmup_steps=5,
    logging_steps=5,
    save_steps=50,
    temperature=0.9,
    report_to="none",
    remove_unused_columns=False,
    push_to_hub=bool(HF_TOKEN),
    hub_model_id="r4nd0m098/idor-hunt-qwen3-4b-grpo",
    hub_token=HF_TOKEN,
    hub_private_repo=True,
)

FastLanguageModel.for_training(model)
trainer = GRPOTrainer(
    model=model,
    reward_funcs=[reward_fn],
    args=config,
    train_dataset=dataset,
    processing_class=tokenizer,
)

print(f"Starting GRPO training — {TRAINING_STEPS} steps...")
trainer.train()
print("Training complete.")

print(f"=== Training Debug Summary ===")
print(f"Total reward_fn calls: {_reward_call_count[0]}")
print(f"Debug entries logged: {len(DEBUG_LOG)}")

parse_fails = [d for d in DEBUG_LOG if d.get("reason") == "parse_failed"]
exceptions = [d for d in DEBUG_LOG if "exception" in str(d.get("reason", ""))]
successes = [d for d in DEBUG_LOG if d.get("parsed")]

print(f"\nParse failures: {len(parse_fails)}")
print(f"Exceptions: {len(exceptions)}")
print(f"Successful parses: {len(successes)}")

if successes:
    rewards = [d["reward"] for d in successes]
    print(f"\nReward stats (sampled): min={min(rewards):.3f} max={max(rewards):.3f} mean={sum(rewards)/len(rewards):.3f}")
    actions_seen = {}
    for d in successes:
        a = d["parsed"]
        actions_seen[a] = actions_seen.get(a, 0) + 1
    print(f"\nTop actions generated:")
    for action, count in sorted(actions_seen.items(), key=lambda x: -x[1])[:15]:
        r_vals = [d["reward"] for d in successes if d["parsed"] == action]
        avg_r = sum(r_vals) / len(r_vals)
        print(f"  {count:3d}x  {action:45s}  avg_r={avg_r:+.3f}")

if parse_fails:
    print(f"\nSample parse failures:")
    for d in parse_fails[:5]:
        print(f"  task={d['task']} | raw={d['raw_output'][:100]!r}")

if exceptions:
    print(f"\nSample exceptions:")
    for d in exceptions[:3]:
        print(f"  task={d['task']} | {d['reason']}")

high_reward = [d for d in successes if d["reward"] >= 0.3]
if high_reward:
    print(f"\nHigh-reward actions (>= 0.3):")
    for d in high_reward[:10]:
        print(f"  r={d['reward']:+.3f} | {d['parsed']} | task={d['task']}")

print("=== Supervisor Reward Analysis ===")
sup_entries = [d for d in DEBUG_LOG if 'supervisor_score' in d and d.get('parsed')]
print(f"Total entries with supervisor scores: {len(sup_entries)}")

if sup_entries:
    env_rewards = [d['env_reward'] for d in sup_entries]
    sup_scores = [d['supervisor_score'] for d in sup_entries]
    hybrid_rewards = [d['hybrid_reward'] for d in sup_entries]
    penalties = [d.get('state_penalty', 0) for d in sup_entries]

    print(f"\nEnvironment Rewards:  min={min(env_rewards):.3f}  max={max(env_rewards):.3f}  mean={sum(env_rewards)/len(env_rewards):.3f}")
    print(f"Supervisor Scores:   min={min(sup_scores):.3f}  max={max(sup_scores):.3f}  mean={sum(sup_scores)/len(sup_scores):.3f}")
    print(f"Hybrid Rewards:      min={min(hybrid_rewards):.3f}  max={max(hybrid_rewards):.3f}  mean={sum(hybrid_rewards)/len(hybrid_rewards):.3f}")
    print(f"State Penalties:     min={min(penalties):.3f}  max={max(penalties):.3f}  mean={sum(penalties)/len(penalties):.3f}")

    agree = sum(1 for e, s in zip(env_rewards, sup_scores) if (e > 0 and s > 0) or (e <= 0 and s <= 0))
    print(f"\nEnv-Supervisor Agreement: {agree}/{len(sup_entries)} ({100*agree/len(sup_entries):.1f}%)")

    vetoed = sum(1 for e, s in zip(env_rewards, sup_scores) if e < 0 and s > 0.3)
    print(f"Vetoed (env negative, supervisor positive): {vetoed} (anti-reward-hacking)")

    boosted = sum(1 for e, s in zip(env_rewards, sup_scores) if e > 0 and s > 0.5)
    print(f"Boosted (both positive, supervisor > 0.5): {boosted}")

    print(f"\nSupervisor cache hits: {len(SUPERVISOR_CACHE)} unique action-states cached")

    print(f"\nTop 10 highest-rated actions by supervisor:")
    top_sup = sorted(sup_entries, key=lambda d: d['supervisor_score'], reverse=True)[:10]
    for d in top_sup:
        print(f"  sup={d['supervisor_score']:+.2f} env={d['env_reward']:+.3f} hybrid={d['hybrid_reward']:+.3f} | {d['parsed']} | task={d['task']}")

print(f"Post-GRPO evaluation ({EVAL_EPISODES} episodes per task)...")
final = evaluate(model, tokenizer)
print(f"\nFinal: {final}")

print("\n" + "=" * 60)
print("FULL PIPELINE SUMMARY: Base → SFT → GRPO")
print("=" * 60)
tasks = list(baseline.keys())
task_names = ["Horizontal IDOR", "Privilege Escalation", "Full Audit"]
print(f"{'Task':<22} {'Base':>8} {'SFT':>8} {'GRPO':>8} {'Total Δ':>8}")
print("-" * 60)
for task, name in zip(tasks, task_names):
    sft_val = post_sft.get(task, baseline[task])
    total_delta = final[task] - baseline[task]
    sign = "+" if total_delta >= 0 else ""
    print(f"{name:<22} {baseline[task]:>8.3f} {sft_val:>8.3f} {final[task]:>8.3f} {sign}{total_delta:>7.3f}")

import matplotlib.pyplot as plt

step_rewards = [
    entry["reward"]
    for entry in trainer.state.log_history
    if "reward" in entry
]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
fig.suptitle("IdorHuntEnv — SFT + GRPO Training Results", fontsize=14, fontweight="bold")

if step_rewards:
    window = max(1, len(step_rewards) // 10)
    smoothed = [
        sum(step_rewards[max(0, i - window):i + 1]) / len(step_rewards[max(0, i - window):i + 1])
        for i in range(len(step_rewards))
    ]
    ax1.plot(step_rewards, alpha=0.3, color="steelblue", label="Raw")
    ax1.plot(smoothed, color="steelblue", linewidth=2, label="Smoothed")
    ax1.axhline(0, color="gray", linestyle="--", linewidth=0.8)
    ax1.set_xlabel("GRPO Training Step")
    ax1.set_ylabel("Step Reward")
    ax1.set_title("GRPO Reward Curve (after SFT)")
    ax1.legend()
    ax1.grid(True, alpha=0.3)
else:
    ax1.text(0.5, 0.5, "No reward logs captured", ha="center", va="center",
             transform=ax1.transAxes, fontsize=12, color="gray")
    ax1.set_title("GRPO Reward Curve")

x = range(len(tasks))
w = 0.25
bars_base = ax2.bar([i - w for i in x], [baseline[t] for t in tasks],
                     width=w, label="Baseline", color="#e07070")
bars_sft = ax2.bar([i for i in x], [post_sft.get(t, baseline[t]) for t in tasks],
                    width=w, label="After SFT", color="#f0c040")
bars_grpo = ax2.bar([i + w for i in x], [final[t] for t in tasks],
                     width=w, label="After GRPO", color="#5b9bd5")
for bars in (bars_base, bars_sft, bars_grpo):
    for bar in bars:
        h = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width() / 2, h + 0.02, f"{h:.2f}",
                 ha="center", va="bottom", fontsize=8)
ax2.set_xticks(list(x))
ax2.set_xticklabels(task_names, fontsize=8)
ax2.set_ylabel("Task Grade (0 - 1.0)")
ax2.set_title("Base → SFT → GRPO")
ax2.set_ylim(0, 1.25)
ax2.legend()
ax2.grid(True, alpha=0.3, axis="y")

plt.tight_layout()

os.makedirs(OUTPUT_DIR, exist_ok=True)
model.save_pretrained(os.path.join(OUTPUT_DIR, "lora_weights"))
tokenizer.save_pretrained(os.path.join(OUTPUT_DIR, "lora_weights"))
print(f"LoRA weights saved to {OUTPUT_DIR}/lora_weights")

fig.savefig(os.path.join(OUTPUT_DIR, "training_results.png"), dpi=150, bbox_inches="tight")
print(f"Plot saved to {OUTPUT_DIR}/training_results.png")

from huggingface_hub import login
login(token=HF_TOKEN)

model.push_to_hub("r4nd0m098/idor-hunt-qwen3-4b-grpo", private=True)
tokenizer.push_to_hub("r4nd0m098/idor-hunt-qwen3-4b-grpo", private=True)
print("Model pushed to HF Hub: r4nd0m098/idor-hunt-qwen3-4b-grpo")
