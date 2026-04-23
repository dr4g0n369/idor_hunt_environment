import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datasets import Dataset
from unsloth import FastLanguageModel
from trl import GRPOTrainer, GRPOConfig

from server.idor_hunt_env_environment import IdorHuntEnvironment

MODEL_NAME      = "unsloth/gemma-4-4b-it"
MAX_SEQ_LEN     = 512
LORA_RANK       = 16
NUM_GENERATIONS = 4
TRAINING_STEPS  = 80
BATCH_SIZE      = 2
EVAL_EPISODES   = 3
OUTPUT_DIR      = "./grpo_idor_hunt"

SYSTEM_PROMPT = """\
You are a penetration tester checking a corporate API for IDOR vulnerabilities.
Send exactly ONE HTTP request per turn. Format:
  METHOD PATH [JSON_BODY]

Examples:
  GET /api/users
  GET /api/users/1
  POST /api/login {"username": "alice", "password": "alice123"}
  GET /api/notes/1

Rules:
- METHOD is GET or POST
- PATH starts with /
- BODY is JSON only for POST
- No explanation — output only the request line\
"""

SEEDED_STATES = [
    {
        "task": "idor_easy",
        "pre_actions": [],
        "obs": (
            'HTTP 200\n{"app":"CorpAPI","task":"Access admin confidential data (SSN, salary) without admin credentials.",'
            '"endpoints":["GET /api/users","GET /api/users/<id>","POST /api/login","GET /api/profile","GET /api/notes","GET /api/notes/<id>"],'
            '"credentials":{"username":"alice","password":"alice123"}}'
        ),
        "hint": "Start by listing users at /api/users to discover user IDs.",
    },
    {
        "task": "idor_easy",
        "pre_actions": [("GET", "/api/users", None)],
        "obs": 'HTTP 200\n[{"id":1,"username":"admin","role":"admin","department":"Executive"},{"id":2,"username":"alice","role":"user","department":"Engineering"},{"id":3,"username":"bob","role":"user","department":"Sales"}]',
        "hint": "Users listed. Try accessing /api/users/1 to see if admin profile is accessible without auth.",
    },
    {
        "task": "idor_easy",
        "pre_actions": [("GET", "/api/users", None), ("GET", "/api/users/2", None)],
        "obs": 'HTTP 200\n{"id":2,"username":"alice","role":"user","email":"alice@corp.internal","ssn":"234-56-7890","salary":75000,"department":"Engineering"}',
        "hint": "IDOR confirmed — sensitive data returned without auth. Now target admin at /api/users/1.",
    },
    {
        "task": "idor_medium",
        "pre_actions": [],
        "obs": (
            'HTTP 200\n{"app":"CorpAPI","task":"Access other users private notes.",'
            '"endpoints":["GET /api/users","GET /api/users/<id>","POST /api/login","GET /api/profile","GET /api/notes","GET /api/notes/<id>"],'
            '"credentials":{"username":"alice","password":"alice123"}}'
        ),
        "hint": "Login first with the provided credentials, then explore /api/notes.",
    },
    {
        "task": "idor_medium",
        "pre_actions": [
            ("POST", "/api/login", '{"username":"alice","password":"alice123"}'),
        ],
        "obs": 'HTTP 200\n{"status":"success","username":"alice","role":"user"}',
        "hint": "Authenticated. List your notes at /api/notes to see your note IDs.",
    },
    {
        "task": "idor_medium",
        "pre_actions": [
            ("POST", "/api/login", '{"username":"alice","password":"alice123"}'),
            ("GET", "/api/notes", None),
        ],
        "obs": 'HTTP 200\n[{"id":3,"title":"Sprint Notes"}]',
        "hint": "Your note is id=3. Try accessing id=1 or id=2 which belong to admin — test if ownership is enforced.",
    },
    {
        "task": "idor_medium",
        "pre_actions": [
            ("POST", "/api/login", '{"username":"alice","password":"alice123"}'),
            ("GET", "/api/notes", None),
            ("GET", "/api/notes/3", None),
        ],
        "obs": 'HTTP 200\n{"id":3,"user_id":2,"title":"Sprint Notes","content":"Working on auth module refactor"}',
        "hint": "You can read your own note (id=3, user_id=2). Now try id=1 — does the API check ownership?",
    },
]


class _Action:
    def __init__(self, method, path, body):
        self.method = method
        self.path = path
        self.body = body


def parse_action(text: str):
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        m = parts[0].upper()
        if m not in ("GET", "POST"):
            continue
        rest = parts[1].strip()
        if m == "GET":
            p, b = rest, None
        else:
            sub = rest.split(None, 1)
            p = sub[0]
            b = sub[1] if len(sub) > 1 else None
        if p.startswith("/"):
            return _Action(m, p, b)
    return None


def build_messages(state: dict) -> list:
    user_content = f"{state['obs']}\nHint: {state['hint']}\n\nWhat is your next request?"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def compute_reward(state_idx: int, completion: str) -> float:
    state = SEEDED_STATES[state_idx]
    env = IdorHuntEnvironment()
    try:
        env.reset(task_id=state["task"])
        for m, p, b in state["pre_actions"]:
            env.step(_Action(m, p, b))
        action = parse_action(completion)
        if action is None:
            return -0.3
        obs = env.step(action)
        return float(obs.reward)
    except Exception:
        return -0.2
    finally:
        env.close()


def reward_fn(completions: list, state_idx=None, **kwargs) -> list:
    if state_idx is None:
        state_idx = [0] * len(completions)
    return [compute_reward(int(idx), c) for idx, c in zip(state_idx, completions)]


def run_episode(model, tokenizer, task_id: str) -> float:
    max_steps = {"idor_easy": 10, "idor_medium": 15}[task_id]
    env = IdorHuntEnvironment()
    try:
        obs = env.reset(task_id=task_id)
        history = []

        for step in range(max_steps):
            if obs.done:
                break

            history_block = "\n".join(history[-4:])
            user_content = (
                f"HTTP {obs.status_code}\n{obs.body[:600]}"
                + (f"\n\nHistory:\n{history_block}" if history_block else "")
                + "\n\nWhat is your next request?"
            )
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ]
            text = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = tokenizer(text, return_tensors="pt").to("cuda")
            with torch.no_grad():
                out = model.generate(
                    **inputs, max_new_tokens=64,
                    temperature=0.4, do_sample=True,
                    pad_token_id=tokenizer.eos_token_id,
                )
            response = tokenizer.decode(
                out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
            )
            action = parse_action(response)
            if action is None:
                break
            obs = env.step(action)
            history.append(f"[{step+1:02d}] {action.method} {action.path} -> {obs.status_code} r={obs.reward:+.3f}")

        return env.get_grade()
    finally:
        env.close()


def evaluate(model, tokenizer, n: int = EVAL_EPISODES) -> dict:
    FastLanguageModel.for_inference(model)
    results = {}
    for task_id in ("idor_easy", "idor_medium"):
        grades = [run_episode(model, tokenizer, task_id) for _ in range(n)]
        results[task_id] = round(sum(grades) / len(grades), 3)
        print(f"  {task_id:20s}  grades={grades}  avg={results[task_id]:.3f}")
    FastLanguageModel.for_training(model)
    return results


def main():
    print("=" * 60)
    print("IdorHuntEnv — GRPO Training")
    print("=" * 60)
    print(f"\nLoading {MODEL_NAME} ...")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL_NAME,
        max_seq_length=MAX_SEQ_LEN,
        load_in_4bit=True,
        dtype=None,
    )
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

    print(f"\n[1/4] Baseline evaluation ({EVAL_EPISODES} episodes/task) ...")
    baseline = evaluate(model, tokenizer)
    print(f"Baseline: {baseline}")

    print("\n[2/4] Building training dataset ...")
    dataset = Dataset.from_dict({
        "prompt": [build_messages(s) for s in SEEDED_STATES],
        "state_idx": list(range(len(SEEDED_STATES))),
    })
    print(f"  {len(dataset)} seeded states across 2 tasks")

    print(f"\n[3/4] GRPO training — {TRAINING_STEPS} steps ...")
    config = GRPOConfig(
        output_dir=OUTPUT_DIR,
        num_train_epochs=1,
        max_steps=TRAINING_STEPS,
        per_device_train_batch_size=BATCH_SIZE,
        num_generations=NUM_GENERATIONS,
        max_completion_length=80,
        learning_rate=5e-6,
        warmup_steps=5,
        logging_steps=5,
        save_steps=TRAINING_STEPS,
        temperature=0.9,
        report_to="none",
        remove_unused_columns=False,
    )

    FastLanguageModel.for_training(model)
    trainer = GRPOTrainer(
        model=model,
        reward_funcs=[reward_fn],
        args=config,
        train_dataset=dataset,
        processing_class=tokenizer,
    )
    trainer.train()

    step_rewards = [
        entry["reward"]
        for entry in trainer.state.log_history
        if "reward" in entry
    ]

    print(f"\n[4/4] Post-training evaluation ({EVAL_EPISODES} episodes/task) ...")
    final = evaluate(model, tokenizer)
    print(f"Final: {final}")

    model.save_pretrained(os.path.join(OUTPUT_DIR, "lora_weights"))
    tokenizer.save_pretrained(os.path.join(OUTPUT_DIR, "lora_weights"))
    print(f"  Model saved to {OUTPUT_DIR}/lora_weights")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("IdorHuntEnv — GRPO Training Results", fontsize=14, fontweight="bold")

    if step_rewards:
        window = max(1, len(step_rewards) // 10)
        smoothed = [
            sum(step_rewards[max(0, i - window):i + 1]) / len(step_rewards[max(0, i - window):i + 1])
            for i in range(len(step_rewards))
        ]
        ax1.plot(step_rewards, alpha=0.3, color="steelblue", label="Raw")
        ax1.plot(smoothed, color="steelblue", linewidth=2, label="Smoothed")
        ax1.axhline(0, color="gray", linestyle="--", linewidth=0.8)
        ax1.set_xlabel("Training Step")
        ax1.set_ylabel("Step Reward")
        ax1.set_title("Training Reward Curve")
        ax1.legend()
        ax1.grid(True, alpha=0.3)
    else:
        ax1.text(0.5, 0.5, "No reward logs captured", ha="center", va="center",
                 transform=ax1.transAxes, fontsize=12, color="gray")
        ax1.set_title("Training Reward Curve")

    tasks = list(baseline.keys())
    task_names = ["Direct IDOR", "Notes IDOR"]
    x = range(len(tasks))
    bars_before = ax2.bar([i - 0.2 for i in x], [baseline[t] for t in tasks],
                          width=0.38, label="Before Training", color="#e07070")
    bars_after = ax2.bar([i + 0.2 for i in x], [final[t] for t in tasks],
                         width=0.38, label="After Training", color="#5b9bd5")
    for bar in bars_before:
        h = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width() / 2, h + 0.02, f"{h:.2f}",
                 ha="center", va="bottom", fontsize=9)
    for bar in bars_after:
        h = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width() / 2, h + 0.02, f"{h:.2f}",
                 ha="center", va="bottom", fontsize=9)
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(task_names)
    ax2.set_ylabel("Task Grade (0 - 1.0)")
    ax2.set_title("Task Performance: Before vs After")
    ax2.set_ylim(0, 1.25)
    ax2.legend()
    ax2.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    out_path = os.path.join(OUTPUT_DIR, "training_results.png")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"\nPlot saved: {out_path}")

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"{'Task':<22} {'Before':>8} {'After':>8} {'Delta':>8}")
    print("-" * 50)
    for task, name in zip(tasks, task_names):
        delta = final[task] - baseline[task]
        sign = "+" if delta >= 0 else ""
        print(f"{name:<22} {baseline[task]:>8.3f} {final[task]:>8.3f} {sign}{delta:>7.3f}")


if __name__ == "__main__":
    main()
