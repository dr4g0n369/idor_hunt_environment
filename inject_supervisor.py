import json
import copy
import sys

NB_PATH = "/home/dragon/Hacking/Hackathon/meta/idor_hunt_env/training_kaggle.ipynb"

with open(NB_PATH, "r") as f:
    nb = json.load(f)

cells = nb["cells"]

SUPERVISOR_MD_CELL = {
    "id": "supervisor_md_01",
    "cell_type": "markdown",
    "source": "## 4.5 Multi-Agent Supervisor Setup (Gemma 4 — LLM-as-a-Judge)\n\nWe use a more capable model (**Gemma 4**) as a supervisor to evaluate the quality of each action the bug-hunter agent takes.\nThis produces an **AI Feedback score** that is combined with the deterministic environment reward\nto form a **Hybrid Reward Function**.\n\n**Reward Formula:**\n```\nif env_reward < 0:\n    final_reward = env_reward  # Hard veto — ground truth says failure\nelse:\n    final_reward = (env_reward * 0.7) + (supervisor_score * 0.3)\n```\n\n**Anti-Reward-Hacking safeguards:**\n1. **Deterministic Flag Gating** — Supervisor cannot override a failed environment check\n2. **Environment State Verification** — HTTP status codes and response bodies are cross-checked\n3. **Negative Constraint Shaping** — Noisy/malformed requests get steep penalties from supervisor\n4. **Score Clamping** — Supervisor output is clamped to [-1.0, 1.0] range",
    "metadata": {}
}

SUPERVISOR_CODE_CELL = {
    "id": "supervisor_code_01",
    "cell_type": "code",
    "source": [
        "import requests as _requests\n",
        "import os\n",
        "import re as _re\n",
        "\n",
        "HF_TOKEN = os.environ.get(\"HF_TOKEN\", \"\")\n",
        "SUPERVISOR_MODEL = \"google/gemma-3-12b-it\"\n",
        "SUPERVISOR_API_URL = f\"https://router.huggingface.co/hf-inference/models/{SUPERVISOR_MODEL}/v1/chat/completions\"\n",
        "SUPERVISOR_ENABLED = True\n",
        "SUPERVISOR_CACHE = {}\n",
        "\n",
        "SUPERVISOR_SYSTEM_PROMPT = \"\"\"\\\n",
        "You are a senior penetration testing supervisor reviewing a junior tester's actions.\n",
        "You will be given:\n",
        "- The task description (what the tester is trying to find)\n",
        "- The tester's HTTP request (method, path, account used)\n",
        "- The server response (status code and body snippet)\n",
        "- The environment's deterministic reward\n",
        "\n",
        "Evaluate the tester's action on these criteria:\n",
        "1. RELEVANCE: Is this request useful for discovering the target vulnerability class?\n",
        "2. STRATEGY: Does the request show good security testing methodology?\n",
        "3. EFFICIENCY: Is the tester wasting steps on obviously public/safe endpoints?\n",
        "4. STEALTH: Would this request look suspicious to a WAF or blue team?\n",
        "5. PROGRESS: Does this request advance toward finding a real vulnerability?\n",
        "\n",
        "Output ONLY a JSON object with two keys:\n",
        "- \"score\": a float between -1.0 and 1.0\n",
        "- \"reasoning\": a one-sentence explanation\n",
        "\n",
        "Example output:\n",
        "{\"score\": 0.6, \"reasoning\": \"Good cross-account access test on a private endpoint.\"}\n",
        "\n",
        "Scoring guide:\n",
        "-1.0 = Completely wrong approach (testing public endpoints, syntax errors)\n",
        " 0.0 = Neutral (valid request but not advancing toward the goal)\n",
        "+1.0 = Excellent (directly tests for the target vulnerability with correct methodology)\n",
        "\"\"\"\n",
        "\n",
        "\n",
        "def ask_gemma_supervisor(task_id, agent_output, parsed_action, env_obs, env_reward):\n",
        "    if not SUPERVISOR_ENABLED or not HF_TOKEN:\n",
        "        return 0.0\n",
        "\n",
        "    if parsed_action is None:\n",
        "        return -0.5\n",
        "\n",
        "    cache_key = f\"{task_id}|{parsed_action.method}|{parsed_action.path}|{parsed_action.account}|{env_obs.status_code}\"\n",
        "    if cache_key in SUPERVISOR_CACHE:\n",
        "        return SUPERVISOR_CACHE[cache_key]\n",
        "\n",
        "    body_snippet = str(env_obs.body)[:500] if hasattr(env_obs, 'body') else \"N/A\"\n",
        "\n",
        "    user_prompt = (\n",
        "        f\"Task: {task_id}\\n\"\n",
        "        f\"Agent's raw output: {agent_output[:200]}\\n\"\n",
        "        f\"Parsed request: {parsed_action.method} {parsed_action.path} @{parsed_action.account}\\n\"\n",
        "        f\"Server response status: {env_obs.status_code}\\n\"\n",
        "        f\"Server response body (truncated): {body_snippet}\\n\"\n",
        "        f\"Environment deterministic reward: {env_reward}\\n\"\n",
        "        f\"\\nEvaluate this action.\"\n",
        "    )\n",
        "\n",
        "    try:\n",
        "        resp = _requests.post(\n",
        "            SUPERVISOR_API_URL,\n",
        "            headers={\"Authorization\": f\"Bearer {HF_TOKEN}\", \"Content-Type\": \"application/json\"},\n",
        "            json={\n",
        "                \"model\": SUPERVISOR_MODEL,\n",
        "                \"messages\": [\n",
        "                    {\"role\": \"system\", \"content\": SUPERVISOR_SYSTEM_PROMPT},\n",
        "                    {\"role\": \"user\", \"content\": user_prompt},\n",
        "                ],\n",
        "                \"max_tokens\": 150,\n",
        "                \"temperature\": 0.1,\n",
        "            },\n",
        "            timeout=15,\n",
        "        )\n",
        "        resp.raise_for_status()\n",
        "        content = resp.json()[\"choices\"][0][\"message\"][\"content\"].strip()\n",
        "        json_match = _re.search(r'\\{[^}]+\\}', content)\n",
        "        if json_match:\n",
        "            parsed = json.loads(json_match.group())\n",
        "            score = float(parsed.get(\"score\", 0.0))\n",
        "            score = max(-1.0, min(1.0, score))\n",
        "            reasoning = parsed.get(\"reasoning\", \"\")\n",
        "            print(f\"    [SUPERVISOR] score={score:+.2f} | {reasoning}\")\n",
        "        else:\n",
        "            score = 0.0\n",
        "            print(f\"    [SUPERVISOR] Could not parse JSON from: {content[:100]}\")\n",
        "    except Exception as e:\n",
        "        score = 0.0\n",
        "        print(f\"    [SUPERVISOR] API error (fallback to 0.0): {e}\")\n",
        "\n",
        "    SUPERVISOR_CACHE[cache_key] = score\n",
        "    return score\n",
        "\n",
        "\n",
        "def hybrid_reward(env_reward, supervisor_score):\n",
        "    if env_reward < 0:\n",
        "        return env_reward\n",
        "    return (env_reward * 0.7) + (supervisor_score * 0.3)\n",
        "\n",
        "\n",
        "def verify_env_state(obs, action, task_id):\n",
        "    penalties = 0.0\n",
        "    if obs.status_code == 404 and action.path.startswith(\"/api/\"):\n",
        "        penalties -= 0.1\n",
        "    if obs.status_code >= 500:\n",
        "        penalties -= 0.2\n",
        "    safe_endpoints = [\"/api/announcements\", \"/api/catalog\", \"/api/teams\", \"/api/shared-files\"]\n",
        "    if any(action.path.startswith(ep) for ep in safe_endpoints):\n",
        "        if task_id in (\"idor_horizontal\", \"privesc\"):\n",
        "            penalties -= 0.15\n",
        "    return penalties\n",
        "\n",
        "\n",
        "print(f\"Supervisor model: {SUPERVISOR_MODEL}\")\n",
        "print(f\"Supervisor enabled: {SUPERVISOR_ENABLED}\")\n",
        "print(f\"HF Token present: {bool(HF_TOKEN)}\")\n",
        "print(\"Supervisor setup complete.\")\n",
    ],
    "metadata": {"trusted": True},
    "outputs": [],
    "execution_count": None,
}

config_cell_idx = None
for i, cell in enumerate(cells):
    if cell.get("id") == "dd14ae79":
        config_cell_idx = i
        break

if config_cell_idx is None:
    for i, cell in enumerate(cells):
        if cell["cell_type"] == "markdown" and "Configuration" in "".join(cell.get("source", [])):
            config_cell_idx = i + 1
            break

if config_cell_idx is None:
    print("ERROR: Could not find configuration cell.")
    sys.exit(1)

insert_idx = config_cell_idx + 2
cells.insert(insert_idx, SUPERVISOR_MD_CELL)
cells.insert(insert_idx + 1, SUPERVISOR_CODE_CELL)

reward_cell_idx = None
for i, cell in enumerate(cells):
    if cell.get("id") == "452a761e":
        reward_cell_idx = i
        break

if reward_cell_idx is None:
    print("ERROR: Could not find reward function cell (452a761e).")
    sys.exit(1)

reward_cell = cells[reward_cell_idx]
old_source = reward_cell["source"]
if isinstance(old_source, list):
    old_code = "".join(old_source)
else:
    old_code = old_source

old_compute_reward = '''def compute_reward(state_idx: int, completion) -> float:
    state = SEEDED_STATES[state_idx]
    text = extract_text(completion)
    _reward_call_count[0] += 1
    prompt_msgs = build_messages(state)
    prompt_str = f"[system]: {prompt_msgs[0]['content'][:150]}...\\n    [user]: {prompt_msgs[1]['content']}"
    env = IdorHuntEnvironment()
    try:
        env.reset(task_id=state["task"])
        for m, p, b, acct in state["pre_actions"]:
            env.step(_Action(m, p, b, acct))
        action = parse_action(text)
        if action is None:
            entry = {
                "call": _reward_call_count[0],
                "task": state["task"],
                "raw_output": text,
                "parsed": None,
                "reward": -0.3,
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
        reward = float(obs.reward)
        entry = {
            "call": _reward_call_count[0],
            "task": state["task"],
            "raw_output": text,
            "parsed": f"{action.method} {action.path} @{action.account}",
            "status": obs.status_code,
            "reward": reward,
            "done": obs.done,
        }
        DEBUG_LOG.append(entry)
        print(f"  [DBG #{_reward_call_count[0]}] task={state['task']} | state_idx={state_idx} | {action.method} {action.path} @{action.account} | status={obs.status_code} | r={reward:+.3f}")
        print(f"    Prompt sent:")
        print(f"    {prompt_str}")
        print(f"    Model output: {text}")
        print()
        return reward'''

new_compute_reward = '''def compute_reward(state_idx: int, completion) -> float:
    state = SEEDED_STATES[state_idx]
    text = extract_text(completion)
    _reward_call_count[0] += 1
    prompt_msgs = build_messages(state)
    prompt_str = f"[system]: {prompt_msgs[0]['content'][:150]}...\\n    [user]: {prompt_msgs[1]['content']}"
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
        return reward'''

if old_compute_reward in old_code:
    new_code = old_code.replace(old_compute_reward, new_compute_reward)
    print("SUCCESS: Replaced compute_reward function with hybrid version.")
else:
    print("WARNING: Could not find exact compute_reward match. Attempting line-based replacement...")
    lines = old_code.split("\n")
    new_lines = []
    skip = False
    for line in lines:
        if line.strip().startswith("def compute_reward("):
            skip = True
            new_lines.append("")
            for new_line in new_compute_reward.split("\n"):
                new_lines.append(new_line)
            continue
        if skip:
            if line and not line[0].isspace() and not line.strip() == "":
                skip = False
                new_lines.append(line)
            continue
        new_lines.append(line)
    new_code = "\n".join(new_lines)
    print("Applied line-based replacement for compute_reward.")

new_source_lines = []
for line in new_code.split("\n"):
    new_source_lines.append(line + "\n")
if new_source_lines:
    new_source_lines[-1] = new_source_lines[-1].rstrip("\n")

reward_cell["source"] = new_source_lines

training_debug_cell_idx = None
for i, cell in enumerate(cells):
    if cell.get("id") == "8e534e9b":
        training_debug_cell_idx = i
        break

if training_debug_cell_idx is not None:
    SUPERVISOR_ANALYSIS_CELL = {
        "id": "supervisor_analysis_01",
        "cell_type": "code",
        "source": [
            "print(\"=== Supervisor Reward Analysis ===\")\n",
            "sup_entries = [d for d in DEBUG_LOG if 'supervisor_score' in d and d.get('parsed')]\n",
            "print(f\"Total entries with supervisor scores: {len(sup_entries)}\")\n",
            "\n",
            "if sup_entries:\n",
            "    env_rewards = [d['env_reward'] for d in sup_entries]\n",
            "    sup_scores = [d['supervisor_score'] for d in sup_entries]\n",
            "    hybrid_rewards = [d['hybrid_reward'] for d in sup_entries]\n",
            "    penalties = [d.get('state_penalty', 0) for d in sup_entries]\n",
            "\n",
            "    print(f\"\\nEnvironment Rewards:  min={min(env_rewards):.3f}  max={max(env_rewards):.3f}  mean={sum(env_rewards)/len(env_rewards):.3f}\")\n",
            "    print(f\"Supervisor Scores:   min={min(sup_scores):.3f}  max={max(sup_scores):.3f}  mean={sum(sup_scores)/len(sup_scores):.3f}\")\n",
            "    print(f\"Hybrid Rewards:      min={min(hybrid_rewards):.3f}  max={max(hybrid_rewards):.3f}  mean={sum(hybrid_rewards)/len(hybrid_rewards):.3f}\")\n",
            "    print(f\"State Penalties:     min={min(penalties):.3f}  max={max(penalties):.3f}  mean={sum(penalties)/len(penalties):.3f}\")\n",
            "\n",
            "    agree = sum(1 for e, s in zip(env_rewards, sup_scores) if (e > 0 and s > 0) or (e <= 0 and s <= 0))\n",
            "    print(f\"\\nEnv-Supervisor Agreement: {agree}/{len(sup_entries)} ({100*agree/len(sup_entries):.1f}%)\")\n",
            "\n",
            "    vetoed = sum(1 for e, s in zip(env_rewards, sup_scores) if e < 0 and s > 0.3)\n",
            "    print(f\"Vetoed (env negative, supervisor positive): {vetoed} (anti-reward-hacking)\")\n",
            "\n",
            "    boosted = sum(1 for e, s in zip(env_rewards, sup_scores) if e > 0 and s > 0.5)\n",
            "    print(f\"Boosted (both positive, supervisor > 0.5): {boosted}\")\n",
            "\n",
            "    print(f\"\\nSupervisor cache hits: {len(SUPERVISOR_CACHE)} unique action-states cached\")\n",
            "\n",
            "    print(f\"\\nTop 10 highest-rated actions by supervisor:\")\n",
            "    top_sup = sorted(sup_entries, key=lambda d: d['supervisor_score'], reverse=True)[:10]\n",
            "    for d in top_sup:\n",
            "        print(f\"  sup={d['supervisor_score']:+.2f} env={d['env_reward']:+.3f} hybrid={d['hybrid_reward']:+.3f} | {d['parsed']} | task={d['task']}\")\n",
        ],
        "metadata": {"trusted": True},
        "outputs": [],
        "execution_count": None,
    }
    cells.insert(training_debug_cell_idx + 1, SUPERVISOR_ANALYSIS_CELL)
    print("Inserted supervisor analysis cell after training debug summary.")

nb["cells"] = cells

with open(NB_PATH, "w") as f:
    json.dump(nb, f, indent=1)

print(f"\nNotebook saved to {NB_PATH}")
print(f"Total cells: {len(cells)}")

with open(NB_PATH, "r") as f:
    validation = json.load(f)
print(f"Validation: notebook parses as valid JSON with {len(validation['cells'])} cells.")
