---
title: Idor Hunt Env Environment Server
emoji: 🔓
colorFrom: red
colorTo: red
sdk: docker
pinned: false
app_port: 8000
base_path: /web
tags:
  - openenv
  - security
  - idor
  - reinforcement-learning
---

# IdorHuntEnv — Teaching LLMs to Find Broken Access Control

> **Can we train a small LLM to autonomously discover IDOR and privilege escalation vulnerabilities in a corporate API?**

[![HF Space](https://img.shields.io/badge/🤗%20Space-r4nd0m098%2Fidor--hunt--env-blue)](https://huggingface.co/spaces/r4nd0m098/idor-hunt-env)
[![Model](https://img.shields.io/badge/🤗%20Model-r4nd0m098%2Fidor--hunt--qwen3--4b--grpo-green)](https://huggingface.co/r4nd0m098/idor-hunt-qwen3-4b-grpo)
[![Blog](https://img.shields.io/badge/📝%20Blog-Read%20the%20Story-orange)](https://huggingface.co/blog/r4nd0m098/idor-hunt-llm-security-training)
[![Notebook](https://img.shields.io/badge/📓%20Kaggle-Training%20Notebook-teal)](https://www.kaggle.com/code/r4nd0m098/idor-hunt-sft-grpo-training)

---

## The Problem

Web security testing — specifically **Broken Access Control** — is one of the most prevalent and damaging vulnerability classes. It sits at #1 on the OWASP Top 10. Yet it requires exactly the kind of multi-step, context-aware reasoning that LLMs are theoretically good at:

- Understand what API endpoints exist
- Know which accounts have which privilege levels
- Form hypotheses about what access *should* be restricted
- Send targeted HTTP requests to test those hypotheses
- Interpret responses to confirm or deny findings

No benchmark exists for this. No RL environment trains on it. We built one.

---

## The Environment

**IdorHuntEnv** is a live Flask corporate API running inside the environment process, with three intentional broken access control vulnerabilities:

| Vulnerability | Type | Endpoint |
|---|---|---|
| Cross-user order access | Horizontal IDOR | `GET /api/orders/<id>` |
| Reports accessible to regular users | Vertical Privesc | `GET /api/reports` |
| Admin config accessible to non-admins | Vertical Privesc | `GET /api/admin/config` |

The agent has four test accounts (`alice` user, `bob` user, `manager1` manager, `guest` guest) and 22 API endpoints to explore. The challenge includes **deliberate false positives** — public endpoints like `/api/announcements`, `/api/catalog`, and `/api/teams` that return 200 but are *not* vulnerabilities.

### Three Tasks

| Task | Description | Max Steps | Difficulty |
|---|---|---|---|
| `idor_horizontal` | Find cross-user data access on orders | 15 | Easy |
| `privesc` | Find endpoints accessible above privilege level | 20 | Medium |
| `full_audit` | Find all three vulnerabilities | 30 | Hard |

### Agent Interface

Each turn the agent receives an HTTP response and outputs a single request line:

```
GET /api/orders/3 @alice
POST /api/data {"key": "val"} @manager1
```

### Reward Signal

The reward is **dense and shaped** — not just 0/1 at the end:

```
+0.1   Enumerate users (reconnaissance)
+0.1   Access your own orders (baseline)
+0.5   Access another user's order (IDOR found!)
+1.0   Access admin's order as a regular user (high-severity IDOR)
+0.8   Access manager-only reports as a regular user (privesc)
+1.0   Access admin config as non-admin (critical privesc)
-0.1   Repeated requests (wasted steps)
-0.05  404 responses (wrong path)
-0.5   Hitting step limit without solving task
```

A **hybrid reward** combines the deterministic environment signal with a Gemma 3 12B supervisor (LLM-as-a-judge) that evaluates strategy quality:

```python
if env_reward < 0:
    final_reward = env_reward          # hard veto — ground truth wins
else:
    final_reward = env_reward * 0.7 + supervisor_score * 0.3
```

---

## Training Approach

We use a two-phase pipeline on **Qwen3-4B** with Unsloth 4-bit quantization:

### Phase 1: SFT — Teaching HTTP Literacy

76 hand-crafted expert demonstrations covering:
- Reconnaissance patterns (list users → explore their data)
- IDOR testing (enumerate IDs, try cross-account access)
- Privilege escalation probing (access restricted endpoints as low-priv users)
- False positive recognition (public endpoints → move on)
- Error code interpretation (403 = protected, 404 = wrong ID)

### Phase 2: GRPO — Reinforcement Against the Live Environment

13 seeded starting states covering all three tasks at various stages of progress. The model generates 4 rollouts per state, executes them against the live Flask API, and receives shaped rewards.

**Anti-reward-hacking safeguards:**
1. Deterministic flag gating — supervisor cannot override a failed environment check
2. State penalty for probing safe/public endpoints
3. Penalty for repeated requests
4. Parse failure penalty (−0.3) for malformed outputs

---

## Results

Results from our smoke-test run (10 GRPO steps, 80 SFT steps, T4 GPU):

| Task | Baseline | After SFT | After GRPO | Δ Total |
|---|---|---|---|---|
| Horizontal IDOR | 0.100 | 0.100 | 0.100 | +0.000 |
| Privilege Escalation | 0.500 | 0.500 | 0.500 | +0.000 |
| Full Audit | 0.100 | **0.400** | 0.400 | **+0.300** |

**SFT alone gave a +0.3 jump on the hardest task.** The baseline model stumbled around, wasting all 30 steps testing irrelevant endpoints. After SFT, it immediately targeted `/api/admin/config` and `/api/reports` — demonstrating that the expert demonstrations successfully transferred HTTP security testing methodology.

GRPO with only 10 steps didn't move the needle (expected — that's a smoke test). A full 300-step run with the supervisor enabled is in progress; results will be updated here.

> **Training plots and full run logs:** see the [Kaggle notebook](https://www.kaggle.com/code/r4nd0m098/idor-hunt-sft-grpo-training)

---

## Why This Matters

Broken access control vulnerabilities are:
- **#1 on OWASP Top 10** by prevalence
- **Frequently missed** by automated scanners (logic bugs, not injection)
- **Expensive to find manually** — requires understanding the application's authorization model

A trained LLM agent that reliably discovers IDOR and privilege escalation would be a meaningful contribution to the security tooling ecosystem — and this environment is the first step toward training one.

---

## Quick Start

```python
from server.idor_hunt_env_environment import IdorHuntEnvironment

class Action:
    def __init__(self, method, path, body=None, account="alice"):
        self.method, self.path, self.body, self.account = method, path, body, account

env = IdorHuntEnvironment()
obs = env.reset(task_id="idor_horizontal")

obs = env.step(Action("GET", "/api/orders/3", account="alice"))
print(f"Status: {obs.status_code}, Reward: {obs.reward}")

print(f"Grade: {env.get_grade()}")
env.close()
```

---

## Running the Training

```bash
# Kaggle notebook (recommended — handles GPU + unsloth)
# Open training_kaggle.ipynb on Kaggle with T4/P100 GPU

# Or via HF Jobs
hf jobs uv run --flavor a100-large --timeout 6h training_kaggle.py
```

---

## Project Structure

```
idor_hunt_env/
├── server/
│   ├── idor_hunt_env_environment.py  # Core environment + reward logic
│   ├── target_app.py                 # Flask corporate API with intentional vulns
│   └── app.py                        # OpenEnv FastAPI wrapper
├── sft_data.py                       # 76 expert SFT demonstrations
├── inject_supervisor.py              # Gemma 3 supervisor integration
├── training_kaggle.ipynb             # Full training notebook
├── training_kaggle.py                # HF Jobs training script
└── openenv.yaml                      # Environment manifest
```

---

## Links

| Resource | URL |
|---|---|
| 🤗 HF Space (live environment) | https://huggingface.co/spaces/r4nd0m098/idor-hunt-env |
| 🤗 Trained model | https://huggingface.co/r4nd0m098/idor-hunt-qwen3-4b-grpo |
| 📝 Blog post | https://huggingface.co/blog/r4nd0m098/idor-hunt-llm-security-training |
| 📓 Training notebook (Kaggle) | https://www.kaggle.com/code/r4nd0m098/idor-hunt-sft-grpo-training |
