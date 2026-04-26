# Teaching a 4B LLM to Find Security Vulnerabilities: Building IdorHuntEnv

*I tried to train a small language model to think like a penetration tester. Nobody had done it before. Here's what happened.*

---

## Why I Picked This Problem

I'm a security engineer. Most of my work involves testing applications — web apps, APIs, internal services. And across all of that, broken access control and IDOR bugs come up constantly. Not occasionally. Constantly. They're among the most common findings in any real engagement.

The frustrating part isn't finding them — it's the time it takes. On a small application, you can cover the attack surface in a few hours. You enumerate the endpoints, map out which accounts exist at which privilege levels, and methodically test cross-account access. Tedious, but manageable. The problem is that production-grade applications don't look like that. They have hundreds of endpoints, dozens of object types, multiple account tiers, and complex ownership models. Testing all of it properly — not just scanning, but actually reasoning about whether each endpoint correctly enforces authorization — takes days. Sometimes weeks. And a lot of that time is mechanical: repeating the same pattern of "who owns this object, can account X access it, what about account Y" across every resource type in the application.

That's when the idea formed: what if I could train an agent to handle exactly this one bug class? Not every vulnerability — just this one. The scope constraint was intentional. A general-purpose security agent is a research problem that requires a massive model and years of work. But an agent that's been specifically trained to think about authorization — to enumerate resources, infer ownership, and test cross-account boundaries — could be small enough to actually deploy. A 4B parameter model running on a laptop could cover the mechanical parts of an IDOR audit while the human focuses on the logic that requires deeper application context.

That's the problem I built this for: take the most time-consuming, most repetitive part of access control testing and teach a small model to do it reliably. Consider what that test actually looks like:

```http
GET /api/orders/3 HTTP/1.1
Authorization: Bearer alice_token
```

Is that a vulnerability? It depends entirely on whether order #3 belongs to Alice or Bob. A scanner can't tell you. A static analysis tool can't tell you. You have to reason about the application's authorization model — understand who owns what, form a hypothesis, test it, and interpret the response.

And that's actually the deeper reason this bug class is hard to automate — harder than almost any other. With SQLi, SSTI, or SSRF, there's a clear signal: you get an error, a time delay, an out-of-band callback, something that definitively tells you the injection worked. The vulnerability is self-evident in the response. IDOR doesn't work that way. You get a `200 OK` and a JSON body, and now you have to *decide* whether that's a bug. Just because a non-admin account can successfully call an endpoint that an admin also uses doesn't make it a vulnerability — it might be entirely intended. Maybe that endpoint is public by design. Maybe that data is supposed to be shared. Maybe the business explicitly wants all users to see each other's orders. You can't know without understanding the context: what the endpoint does, who it's meant to serve, what the application's authorization intent is. That judgment call is what separates a real finding from a false positive, and it's exactly what makes this bug resistant to the kind of automated detection that works well for injection vulnerabilities.

That's exactly the kind of reasoning I wanted to train into a model, and exactly the kind of reasoning that makes IDOR testing slow when you're doing it manually across a large API.

---

## Architecture Overview

Before diving into decisions, here's the full pipeline — and how each step in the GRPO loop connects:

![Training Pipeline](https://raw.githubusercontent.com/dr4g0n369/idor_hunt_environment/main/assets/training_pipeline.png)
*Figure 1: Full training pipeline — Qwen3-4B goes through SFT on expert demonstrations, then GRPO against a live Flask API with a Gemma 3 12B supervisor shaping the reward.*

![GRPO Environment Loop](https://raw.githubusercontent.com/dr4g0n369/idor_hunt_environment/main/assets/grpo_loop.png)
*Figure 2: Per-step GRPO loop — the model generates an HTTP request, it's parsed and executed against the real API, the deterministic reward is blended with the supervisor's strategy score, and a gradient update follows.*

---

## Building the Environment

This was harder than it sounds.

### The Target API

I built a realistic fake corporate API — `CorpAPI v2.1.0` — running inside the training process as a live Flask server. It has 22 endpoints across orders, reports, documents, announcements, and admin config. Four test accounts at different privilege levels. Three deliberately planted vulnerabilities:

| Vulnerability | Type | Endpoint |
|---|---|---|
| Cross-user order access | Horizontal IDOR | `GET /api/orders/<id>` |
| Reports accessible to regular users | Vertical Privesc | `GET /api/reports` |
| Admin config accessible to non-admins | Vertical Privesc | `GET /api/admin/config` |

The API had to be realistic enough that the model would learn *transferable* reasoning, not just memorize endpoint names.

### The Reward Function — My Hardest Design Problem

Early versions of the reward function gave 0 or 1 at the end of each episode. The model learned nothing. Zero gradient signal until the last step meant it was essentially random exploration. I spent a week on reward shaping, arriving at a **dense signal that rewards each step in the attack chain**:

```python
def _compute_reward(self, action, response) -> float:
    reward = 0.0

    # Reconnaissance: discovering the user list
    if action.path == "/api/users" and response.status_code == 200:
        if "idor_recon" not in self.flags:
            self.flags.add("idor_recon")
            reward += 0.1                       # +0.1 first step

    # Foothold: accessing your own data
    if action.path == f"/api/orders/{self.own_order_id}":
        if response.status_code == 200 and "own_order" not in self.flags:
            self.flags.add("own_order")
            reward += 0.1                       # +0.1 baseline established

    # IDOR: accessing another user's order as yourself
    if re.match(r"/api/orders/\d+", action.path):
        order_id = int(action.path.split("/")[-1])
        if order_id in self.other_user_orders and response.status_code == 200:
            owner = self.order_owners[order_id]
            reward += 1.0 if owner == "admin" else 0.5   # +0.5/+1.0 IDOR

    # Privesc: restricted endpoint as wrong role
    if action.path == "/api/reports" and response.status_code == 200:
        if action.account in ("alice", "bob", "guest"):
            reward += 0.8                       # +0.8 privilege escalation

    if action.path == "/api/admin/config" and response.status_code == 200:
        if action.account != "admin":
            reward += 1.0                       # +1.0 critical privesc

    # Penalties
    if request_key in self.seen_requests:
        reward -= 0.1                           # -0.1 repeated request
    if response.status_code == 404:
        reward -= 0.05                          # -0.05 wrong path

    return reward
```

The flags prevent double-counting — each milestone rewards exactly once.

### The False Positive Problem — My Most Important Design Decision

This is the part I'm most proud of. Endpoints like `/api/announcements`, `/api/catalog`, and `/api/teams` return `200` for any authenticated user — not because they're vulnerable but because they're *supposed to be public*. A naive model that hammers endpoints until something returns 200 would get rewarded for "finding" these. That model would be useless in practice, so I explicitly penalized it:

```python
SAFE_ENDPOINTS = ["/api/announcements", "/api/catalog", "/api/teams", "/api/shared-files"]

def verify_env_state(obs, action, task_id) -> float:
    if any(action.path.startswith(ep) for ep in SAFE_ENDPOINTS):
        if task_id in ("idor_horizontal", "privesc"):
            return -0.15    # you should know these aren't vulnerabilities
    return 0.0
```

This forced the model to reason about *intent*, not just status codes. A `200` on a public endpoint is noise. A `200` on an endpoint that should return `403` is signal. The model had to learn the difference.

### The Supervisor: Adding a Strategic Layer

Even with a dense reward signal, there's a gap: the environment rewards outcomes, not reasoning quality. A model could stumble onto a vulnerability through dumb luck and get the same reward as a model that reasoned correctly to the same answer. I added a second LLM — **Gemma 3 12B** — as an LLM-as-a-judge supervisor. After each step it evaluates the *strategy* behind the action and returns a score from -1.0 to +1.0. I blend the two signals:

```python
def hybrid_reward(env_reward: float, supervisor_score: float) -> float:
    if env_reward < 0:
        return env_reward           # hard veto — ground truth always wins

    return (env_reward * 0.7) + (supervisor_score * 0.3)
```

The critical invariant: **the supervisor can never override a failed environment check.** If the deterministic API says the action was wrong, that's final. The supervisor only adjusts rewards on positive or neutral outcomes — boosting well-reasoned moves and dampening lucky ones. This prevents the model from learning to fool the judge instead of actually finding vulnerabilities.

---

## Training: Two Phases

### Phase 1 — SFT: Teaching HTTP Literacy

Before any RL, Qwen3-4B had no idea how to structure an attack. I hand-crafted **76 expert demonstrations** in conversation format, covering six distinct attack patterns:

```
Pattern 1 — Reconnaissance first:
  GET /api/users @alice          # enumerate who exists
  GET /api/orders @alice         # see your own data
  GET /api/orders/3 @alice       # try IDs that belong to others → IDOR

Pattern 2 — Privilege escalation probe:
  GET /api/reports @alice        # try restricted endpoint as user → 200 = vuln
  GET /api/admin/config @guest   # try admin endpoint as guest → 200 = vuln

Pattern 3 — False positive recognition:
  GET /api/announcements @alice  # returns 200 — but it's PUBLIC, move on
  GET /api/catalog @guest        # also public — skip it

Pattern 4 — Error code interpretation:
  GET /api/reports @alice → 403  # endpoint EXISTS and is protected
  GET /api/reports @guest → 200  # guest can read manager reports?! FLAG IT

Pattern 5 — Cross-account comparison:
  GET /api/orders/4 @alice → 200 # alice can read bob's order — IDOR confirmed
  GET /api/orders/1 @bob → 200   # bob can read alice's order — bidirectional

Pattern 6 — Systematic coverage:
  # After finding one vuln, keep probing — don't stop at the first hit
```

These map directly to PortSwigger Web Security Academy's access control lab categories. I was essentially distilling penetration tester methodology into 76 conversations.

### Phase 2 — GRPO: Practice Against a Live API

With 13 seeded starting states covering all three task types at various stages of completion, I run GRPO against the live Flask environment:

```
for each training step:
    sample batch of seeded starting states

    for each state:
        generate NUM_GENERATIONS=4 independent rollouts

        for each rollout:
            parse action from model output
            execute against live Flask API → env_reward
            query Gemma 3 12B supervisor → supervisor_score
            final_reward = hybrid(env_reward, supervisor_score)

        compute group-relative advantage:
            advantage[i] = (reward[i] - mean(rewards)) / std(rewards)

        gradient step: increase probability of high-advantage actions
```

The **seeded states** were a crucial design choice. Rather than always starting cold, I give the model mid-game positions — places where the interesting decision is one step away:

```python
SEEDED_STATES = [
    # Cold start
    {"task": "idor_horizontal", "pre_actions": [], "obs": INITIAL_API_INFO},

    # User list already found — what next?
    {"task": "idor_horizontal",
     "pre_actions": [("GET", "/api/users", None, "alice")],
     "obs": '[{"id":1,"username":"admin"}, {"id":3,"username":"alice"}, {"id":4,"username":"bob"}]',
     "hint": "Users found. Alice has orders 1-2, bob has 3-4. Test cross-account access."},

    # Own orders found — one decision away from IDOR
    {"task": "idor_horizontal",
     "pre_actions": [("GET", "/api/users", None, "alice"),
                     ("GET", "/api/orders", None, "alice")],
     "obs": '[{"id":1,"product":"Laptop"},{"id":2,"product":"USB Hub"}]',
     "hint": "Alice has orders 1-2. Try /api/orders/3 as alice — that belongs to bob."},

    # ... 10 more states across all three task types and difficulty levels
]
```

Starting from mid-game means the model spends training steps at the *interesting* decision points, not re-learning reconnaissance every episode.

---

## The Failures (There Were Many)

Getting to a working training run was not smooth. Here's the honest account.

### Bug #1: The Supervisor Was Silently Disabled for an Entire Run

I ran training. Loss moved. Rewards were non-zero. I thought everything was working. Then I added one debug line:

```
Supervisor Scores:   min=0.000  max=0.000  mean=0.000
Supervisor cache hits: 0 unique action-states cached
```

Every supervisor score was exactly 0.0. The hybrid reward had silently degraded to `env_reward × 0.7` the entire time. I'd trained without the supervisor and had no idea. The cause was a scoping bug — subtle enough that I missed it on first review:

```python
# Config cell — loaded correctly via Kaggle's secret manager
HF_TOKEN = UserSecretsClient().get_secret("HF_TOKEN")

# Supervisor cell — ran in a different scope, re-fetched independently
HF_TOKEN = os.environ.get("HF_TOKEN", "")  # ← returns "" on Kaggle!
```

Kaggle secrets aren't exported to `os.environ`. The supervisor was firing 401 errors to the Gemma API, hitting the `except` block, returning 0.0 silently, and nothing in the training output showed anything wrong. One token assignment at the top, never re-fetched downstream, fixed it.

### Bug #2: 42.5% of Rollouts Were Wasted on Parse Failures

In my smoke test, 17 out of 40 GRPO rollouts returned −0.3 — the parse failure penalty. Nearly half my training signal was noise. The model was generating outputs like this:

```
<think>
Okay, so I've confirmed alice can access her own orders. Now I should try
accessing Bob's orders. Bob has user ID 4, so his orders probably have higher
IDs. Let me try order ID 3, which wasn't in Alice's order list...
```

No closing `</think>`. My `strip_thinking` function used `re.compile(r"<think>.*", re.DOTALL)` — which, when there's no closing tag, strips *everything from `<think>` to end-of-string*, leaving nothing to parse. The model was doing the right *reasoning*. The action was buried inside the think block. I just couldn't see it.

The fix was a fallback regex that searches the raw output for an embedded action before giving up:

```python
ACTION_RE = re.compile(r'\b(GET|POST|PUT|DELETE)\s+(/\S*)\s*(@\w+)?', re.IGNORECASE)

def parse_action(text: str):
    raw = text
    stripped = strip_thinking(text)

    if not stripped:
        # <think> was never closed — mine the raw text for any action pattern
        m = ACTION_RE.search(raw)
        if m:
            return _Action(
                method=m.group(1).upper(),
                path=m.group(2),
                account=(m.group(3) or "@alice").lstrip("@").lower()
            )
        return None     # genuinely malformed — -0.3 penalty applies

    for line in stripped.splitlines():
        # ... normal parsing
```

This cut parse failures from 42.5% to near zero.

### Bug #3: The Looping Problem

In baseline evaluation, the untrained model found that `GET /api/admin/config @manager1` returns `200`. Then it got completely stuck:

```
[step 26] GET /api/admin/config @manager1 → 200  r=-0.100  (repeated)
[step 27] GET /api/admin/users  @manager1 → 403  r=-0.100  (repeated)
[step 28] GET /api/admin/config @manager1 → 200  r=-0.100  (repeated)
[step 29] GET /api/admin/users  @manager1 → 403  r=-0.100  (repeated)
```

All 30 steps. It understood `200 = something works here` and `403 = blocked`, but it couldn't figure out the next move: try the *same endpoint* with a *different account*. That's the key insight of privilege escalation testing — and the model had no way to derive it without being shown. This wasn't a bug to fix. It was proof the problem was worth solving.

### Bug #4: A Dependency That Silently Broke Between Sessions

After a clean successful run, a fresh Kaggle session broke immediately on import:

```
ImportError: cannot import name 'KernelInfo' from 'huggingface_hub.hf_api'
```

Between sessions, `unsloth_zoo` had released an update that required `huggingface_hub>=0.27.0`. Kaggle's pre-installed version was older. I added the upgrade to the install cell — and it still failed. Python had already loaded the old `huggingface_hub` into `sys.modules`. Pip updated the files on disk but didn't touch the already-running process. The fix was to force a kernel restart after installation:

```python
!pip install -q --upgrade "unsloth[kaggle]" trl>=0.16 datasets flask werkzeug \
    requests openenv-core "huggingface_hub>=0.27.0"

import IPython
IPython.Application.instance().kernel.do_shutdown(restart=True)
# Kaggle re-runs from the next cell automatically
```

This one cost us a training session I could not get back.

---

## What Actually Happened

Results from my smoke test (80 SFT steps, 10 GRPO steps, T4 GPU — supervisor disabled due to Bug #1):

| Task | Baseline | After SFT | After GRPO (10 steps) | Δ Total |
|---|---|---|---|---|
| Horizontal IDOR | 0.10 | 0.10 | 0.10 | +0.000 |
| Privilege Escalation | 0.50 | 0.50 | 0.50 | +0.000 |
| Full Audit | 0.10 | **0.40** | 0.40 | **+0.300** |

### The SFT phase delivered.

On the hardest task — find all three vulnerabilities in 30 steps — the model jumped from 0.10 to 0.40. The behavioral change was dramatic. Here is what the baseline model did on `full_audit`:

```
[01] GET /api/announcements @alice      → 200  r= 0.000
[02] GET /api/announcements/1 @alice    → 200  r= 0.000
[03] GET /api/catalog @alice            → 200  r= 0.000
[04] GET /api/catalog/1 @alice          → 200  r= 0.000
[05] GET /api/teams @alice              → 200  r= 0.000
...
[30] GET /api/shared-files @alice       → 200  r= 0.000
Final grade: 0.10
```

Thirty steps. All public endpoints. Never once touched orders, reports, or admin config. Here is what the SFT model did on the same task:

```
[01] GET /api/users @alice              → 200  r=+0.100  ✓ recon
[02] GET /api/reports @alice            → 200  r=+0.800  ✓ privesc found
[03] GET /api/admin/config @guest       → 200  r=+1.000  ✓ critical privesc
Final grade: 0.40
```

Three requests. Two vulnerabilities. It learned that you start with reconnaissance, you immediately probe restricted endpoints with wrong-role accounts, and you move on from public endpoints. That is the core methodology of privilege escalation testing — absorbed from 76 demonstrations.

### GRPO with 10 steps did nothing — and that was expected.

10 steps is a smoke test to verify the loop runs without crashing. Real RL needs hundreds of gradient steps to shift policy. The full run — 300 GRPO steps, 200 SFT steps, supervisor enabled on A100 — is running now. I expect the biggest gain on horizontal IDOR, which is currently stuck at 0.10. That task requires multi-step attacker reasoning: *enumerate your own IDs → infer others' IDs → test cross-account access*. SFT alone can't teach that chain — it needs reward signal from actually pulling it off.

---

## Did I Succeed?

Partially — and I'll say it plainly.

SFT transferred genuine penetration testing methodology into a 4B model in 80 training steps. The behavioral change from baseline to post-SFT was not subtle. The model stopped being lost and started acting like it understood what it was looking for. That's a real result.

What I're still trying to get is horizontal IDOR. The model needs to learn to correlate "my order IDs are 1-2, so 3-4 probably belong to someone else" — and then deliberately cross those account boundaries. That requires RL-level planning across multiple steps, not just mimicking demonstrations. That's what the full 300-step GRPO run should produce.

The bet I'm making is on the supervisor. My hypothesis is that Gemma 3 12B evaluating *strategy quality* — not just outcomes — will help the model learn the *reasoning chain* behind a good IDOR test, not just the lucky sequence of requests that happened to find one. I'll know if that bet pays off when the A100 run finishes.

I'll update this post with the full results and reward curves when it does.

---

## What I'd Do Differently: Task Design as a Training Hyperparameter

One of the quieter lessons from this build is that the task taxonomy isn't just a UX decision — it's a training hyperparameter, and I got it wrong the first time.

The current environment has three tasks: `idor_horizontal`, `privesc`, and `full_audit`. They were a reasonable starting point, but after watching the GRPO run collapse, it's clear they have a structural problem. `full_audit` is the most obvious one — it's essentially "find everything," which means the reward signal is diffuse and the model never learns to commit to a particular strategy. A model that earns partial credit for doing a bit of reconnaissance, finding one IDOR, and stumbling into a privesc isn't learning a coherent skill; it's learning to hedge. And `idor_horizontal` and `privesc`, while more focused, are still broad enough that the reward function can't distinguish a model that genuinely understands cross-account authorization from one that's just memorized that `GET /api/admin/config @guest` returns a 1.0 reward in any task.

The deeper problem is what's missing. The `/api/documents/<id>` endpoint exists in the target application. It has an `owner_id` field. Confidential documents (Security Policy, Incident Response Plan) are accessible via the API. There is an IDOR there — but it's never tested, because no task asks for it. The model will never learn to probe document access because the reward function never rewards it. Whatever the agent learns about IDOR, it learns only from the `/api/orders/<id>` surface. That's a brittle foundation.

The direction I want to move toward is something like a 12-task taxonomy organized by specificity and difficulty. The first tier would be concrete IDOR cases: `idor_orders_horizontal` (can Alice read Bob's orders?), `idor_documents_horizontal` (can a regular user read another's documents?), `idor_documents_confidential` (specifically, can they read documents classified as confidential?). Each of these has a precise success condition and a precise reward target. The second tier would split privilege escalation into its actual components — manager-level access to `/api/reports` is a different finding than admin-level access to `/api/admin/config`, which contains live database credentials, API keys, and JWT secrets. Treating them as one `privesc` task obscures that difference. The third tier would introduce access control coverage: mapping all 22 endpoints systematically, testing write operations, verifying that endpoints which appear public are actually intended to be public. The fourth tier — the hardest and most novel — would be severity and business context tasks: finding a vulnerability and then reasoning through whether it's a HIGH or a CRITICAL, based on what data is exposed and what the application's evident purpose is.

That last tier is where the real capability gain lives, but it's also where a 4B model running 300 GRPO steps would hit a wall. The honest tradeoff with more tasks is gradient dilution: when a training run samples across 12 tasks and produces 4 rollouts per step, each task sees roughly 8-10 gradient updates in 300 steps. That's not enough to learn anything stable. Expanding the task set without expanding compute will likely produce a model that's mediocre at everything rather than good at a few things. The 3-task model I've been training isn't suffering from a lack of task diversity — it's suffering from reward hacking and a broken supervisor. Fixing those bugs is more valuable than adding tasks right now.

The approach I'm planning is staged. The immediate fix is going from 3 to 4 tasks: keep `idor_horizontal` and `privesc`, split `full_audit` into `idor_documents_horizontal` and `access_control_coverage`. That's a small change but a meaningful one — it tests a new attack surface (documents) and replaces the vague "find everything" task with something the reward function can actually grade. At 8 tasks — which requires either more compute or fewer steps per task — I'd add the confidential document case, split privesc by severity tier, and add a false-positive discrimination task. The full 12-task set is aspirational: it belongs to a larger model, or to a 4B model with a much longer training run.

The principle here is simple but easy to miss: a task that's too broad teaches the model to be opportunistic rather than systematic. `full_audit` doesn't teach the model to audit; it teaches the model to wander until something rewards it. Specific tasks with specific reward conditions are what push a small model toward the deliberate, hypothesis-driven behavior that makes an IDOR agent actually useful. Task specificity is as important as any choice of learning rate or KL penalty — and it's the part that took me the longest to understand.

---

## Why This Matters Beyond the Numbers

I picked this problem because it sits at the intersection of two things that aren't studied together: LLM reasoning under uncertainty, and adversarial security testing.

The OWASP #1 vulnerability class has no automated solution. Every existing tool either does pattern matching (misses logic bugs by design) or requires a human analyst who understands the application's authorization model. An agent that can learn to reason about authorization — to form hypotheses about what *should* be restricted, test them against a live API, and distinguish real vulnerabilities from expected behavior — would be a genuine new capability.

I don't claim I've built that agent yet. I've built the environment that could train it, shown that the SFT phase works, and I'm mid-run on the RL phase. But the direction is right, the problem is real, and nobody else is working on it. If even a 4B model can learn reliable broken access control testing through RL, the implications for security tooling are significant. And if it can't — that's also a meaningful result, pointing toward what a larger model or a better reward signal would need to do differently. Either way, this is worth knowing.

---

*Environment: [IdorHuntEnv on HF Spaces](https://huggingface.co/spaces/r4nd0m098/idor-hunt-env)*
*Model: [r4nd0m098/idor-hunt-qwen3-4b-grpo](https://huggingface.co/r4nd0m098/idor-hunt-qwen3-4b-grpo)*
*Training notebook: [Kaggle](https://www.kaggle.com/code/r4nd0m098/idor-hunt-sft-grpo-training)*
