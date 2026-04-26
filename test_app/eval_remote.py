import os
import re
import sys
import json
import time
import requests as http_requests

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

BASE         = "http://127.0.0.1:7500"
HF_TOKEN     = os.environ.get("HF_TOKEN", "")
MODEL_ID     = "dr4g0n369/idor-hunt-qwen3-4b-grpo-merged"
HF_API_URL   = f"https://router.huggingface.co/hf-inference/models/{MODEL_ID}/v1/chat/completions"
MAX_STEPS    = 30
TEMPERATURE  = 0.4

ACCOUNT_KEYS = {
    "alice":   "key-alice-001",
    "bob":     "key-bob-002",
    "charlie": "key-charlie-003",
    "guest":   "key-guest-004",
    "admin":   "key-admin-005",
}

SYSTEM_PROMPT = """You are a penetration tester auditing a freelance marketplace API for broken access control.
You have multiple test accounts at different privilege levels.
Send exactly ONE HTTP request per turn. Format:
  METHOD PATH @account

For POST requests with a body:
  POST PATH JSON_BODY @account

Examples:
  GET /api/contractors/3 @alice
  GET /api/invoices/2 @bob
  POST /api/contractors/2/flag {} @guest

Rules:
- METHOD is GET, POST, PUT, or DELETE
- PATH starts with /
- @account selects which test account to use (default: alice)
- Output ONLY the request line, nothing else
- Do NOT explain your reasoning"""

THINK_CLOSED  = re.compile(r"<think>.*?</think>", re.DOTALL)
THINK_UNCLOSED = re.compile(r"<think>.*", re.DOTALL)
ACTION_RE     = re.compile(r"\b(GET|POST|PUT|DELETE)\s+(/\S*)\s*(@\w+)?", re.IGNORECASE)


def strip_thinking(text):
    s = THINK_CLOSED.sub("", text).strip()
    if s:
        return s
    s = THINK_UNCLOSED.sub("", text).strip()
    return s if s else text.strip()


def parse_action(text):
    text = strip_thinking(text)
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        account = "alice"
        at = re.search(r"@(\w+)\s*$", line)
        if at:
            account = at.group(1).lower()
            line = line[:at.start()].strip()
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        m = parts[0].upper()
        if m not in ("GET", "POST", "PUT", "DELETE"):
            continue
        rest = parts[1].strip()
        p, b = (rest, None) if m in ("GET", "DELETE") else (rest.split(None, 1) + [None])[:2]
        if p and p.startswith("/"):
            return m, p, b, account
    hit = ACTION_RE.search(text)
    if hit:
        account = hit.group(3).lstrip("@").lower() if hit.group(3) else "alice"
        return hit.group(1).upper(), hit.group(2), None, account
    return None


def call_hf_model(messages):
    if not HF_TOKEN:
        print("[ERROR] HF_TOKEN not set", flush=True)
        sys.exit(1)
    resp = http_requests.post(
        HF_API_URL,
        headers={"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"},
        json={"model": MODEL_ID, "messages": messages, "max_tokens": 128, "temperature": TEMPERATURE},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def do_request(method, path, account, body=None):
    key = ACCOUNT_KEYS.get(account, ACCOUNT_KEYS["guest"])
    headers = {"X-API-Key": key, "Content-Type": "application/json"}
    url = BASE + path
    try:
        fn = getattr(http_requests, method.lower(), None)
        if fn is None:
            return 400, ""
        r = fn(url, headers=headers, data=body or "{}", timeout=5)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)


def reset_app():
    r = http_requests.post(f"{BASE}/api/audit/reset", timeout=5)
    print(f"[RESET] App state cleared — {r.json()}", flush=True)


def run_episode():
    all_endpoints = [
        "GET  /api/me",
        "GET  /api/skills",
        "GET  /api/browse/projects",
        "GET  /api/platform/stats",
        "GET  /api/contractors/<id>",
        "GET  /api/projects/<id>",
        "GET  /api/invoices/<id>",
        "GET  /api/proposals/<id>",
        "GET  /api/messages/<id>",
        "GET  /api/platform/config",
        "GET  /api/platform/earnings",
        "POST /api/contractors/<id>/flag",
    ]
    accounts = {
        "alice":   {"role": "contractor"},
        "bob":     {"role": "contractor"},
        "charlie": {"role": "client"},
        "guest":   {"role": "guest"},
        "admin":   {"role": "admin"},
    }
    init_obs = json.dumps({
        "app": "FreelanceHub API", "version": "3.0.0",
        "task": (
            "Audit this freelance marketplace API for broken access control. "
            "You have accounts at multiple privilege levels. "
            "Test if contractors can access each other's invoices, proposals, or profiles. "
            "Test if any account can access platform-level config or earnings. "
            "Be thorough — test multiple IDs and multiple accounts per endpoint."
        ),
        "endpoints": all_endpoints,
        "accounts": accounts,
    })

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": f"{init_obs}\n\nWhat is your first request?"},
    ]

    print(f"\n{'='*64}", flush=True)
    print(f"  IDOR Hunt Agent — FreelanceHub Test", flush=True)
    print(f"  Model : {MODEL_ID}", flush=True)
    print(f"  Steps : {MAX_STEPS}", flush=True)
    print(f"{'='*64}\n", flush=True)

    for step in range(MAX_STEPS):
        print(f"[Step {step+1:02d}] Calling model...", end=" ", flush=True)
        try:
            raw = call_hf_model(messages)
        except Exception as e:
            print(f"API error: {e}", flush=True)
            time.sleep(2)
            continue

        parsed = parse_action(raw)
        if parsed is None:
            print(f"PARSE FAIL | raw={raw[:60]!r}", flush=True)
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": "HTTP 400\n{\"error\": \"Could not parse request\"}\n\nNext request?"})
            continue

        method, path, body, account = parsed
        status, resp_body = do_request(method, path, account, body)
        print(f"{method:6} {path:40} @{account:8}  HTTP {status}", flush=True)

        messages.append({"role": "assistant", "content": raw})
        messages.append({
            "role": "user",
            "content": f"HTTP {status}\n{resp_body[:400]}\n\nNext request?",
        })

        time.sleep(0.3)

    state = http_requests.get(f"{BASE}/api/audit/state", timeout=5).json()
    print(f"\n{'='*64}", flush=True)
    print(f"  RESULTS", flush=True)
    print(f"{'='*64}", flush=True)
    print(f"  Bugs found    : {len(state['bugs_found'])} / {len(state['known_bugs'])}", flush=True)
    print(f"  FP endpoints  : {len(state['fp_hit'])} / {len(state['false_positives'])}", flush=True)
    print(f"  Total requests: {state['total_requests']}", flush=True)
    print(f"\n  Found : {sorted(state['bugs_found'])}", flush=True)
    missed = set(state['known_bugs']) - set(state['bugs_found'])
    print(f"  Missed: {sorted(missed)}", flush=True)
    print(f"  FPs hit: {sorted(state['fp_hit'])}", flush=True)


if __name__ == "__main__":
    reset_app()
    time.sleep(0.5)
    run_episode()
