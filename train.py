import argparse
import json
import os
import re
import traceback

from server.idor_hunt_env_environment import IdorHuntEnvironment


class Action:
    def __init__(self, method, path, body=None, account="alice"):
        self.method = method
        self.path = path
        self.body = body
        self.account = account


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


def parse_action(text):
    if not isinstance(text, str):
        text = extract_text(text)
    text = strip_thinking(text)
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        account = "alice"
        at_match = re.search(r"@(\w+)\s*$", line)
        if at_match:
            account = at_match.group(1).lower()
            line = line[: at_match.start()].strip()
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        method = parts[0].upper()
        if method not in ("GET", "POST", "PUT", "DELETE"):
            continue
        rest = parts[1].strip()
        if method in ("GET", "DELETE"):
            path, body = rest, None
        else:
            sub = rest.split(None, 1)
            path = sub[0]
            body = sub[1] if len(sub) > 1 else None
        if path.startswith("/"):
            return Action(method, path, body, account)
    return None


def build_seeded_states():
    endpoints = [
        "GET  /api/users",
        "GET  /api/users/<id>",
        "GET  /api/orders",
        "GET  /api/orders/<id>",
        "GET  /api/documents",
        "GET  /api/documents/<id>",
        "GET  /api/reports",
        "GET  /api/reports/<id>",
        "GET  /api/announcements",
        "GET  /api/announcements/<id>",
        "GET  /api/shared-files",
        "GET  /api/shared-files/<id>",
        "GET  /api/catalog",
        "GET  /api/catalog/<id>",
        "GET  /api/activity",
        "GET  /api/tickets",
        "GET  /api/tickets/<id>",
        "GET  /api/teams",
        "GET  /api/teams/<department>",
        "GET  /api/admin/config",
        "GET  /api/admin/users",
        "DELETE /api/admin/users/<id>",
    ]
    accounts = {
        "alice": {"role": "user", "department": "Engineering"},
        "bob": {"role": "user", "department": "Sales"},
        "manager1": {"role": "manager", "department": "Engineering"},
        "guest": {"role": "guest", "department": "External"},
    }
    return [
        {
            "task": "idor_horizontal",
            "pre_actions": [],
            "obs": json.dumps(
                {
                    "app": "CorpAPI",
                    "version": "2.1.0",
                    "task": "Test this corporate API for horizontal IDOR vulnerabilities.",
                    "endpoints": endpoints,
                    "accounts": accounts,
                    "note": "Use @account_name suffix to act as a specific account. Default: alice.",
                }
            ),
            "hint": "Start with /api/users and /api/orders, then test /api/orders/<id> for cross-user access.",
        },
        {
            "task": "privesc",
            "pre_actions": [("GET", "/api/users", None, "alice")],
            "obs": '[{"id":1,"username":"admin","role":"admin"},{"id":2,"username":"manager1","role":"manager"},{"id":3,"username":"alice","role":"user"}]',
            "hint": "Try manager/admin routes as lower-privileged users.",
        },
        {
            "task": "full_audit",
            "pre_actions": [("GET", "/api/announcements", None, "guest")],
            "obs": '[{"id":2,"title":"Q4 All-Hands Meeting Scheduled","pinned":1}]',
            "hint": "Announcements are intentionally shared; prioritize ownership and role-based checks.",
        },
        {
            "task": "full_audit",
            "pre_actions": [("GET", "/api/catalog", None, "alice")],
            "obs": '[{"id":1,"name":"Laptop Pro X1","price":1299.99}]',
            "hint": "Catalog is shared data and not a vulnerability by itself.",
        },
    ]


def build_messages(state: dict, system_prompt: str) -> list:
    user_content = f"{state['obs']}\nHint: {state['hint']}\n\nWhat is your next request?"
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def run_env_smoke_test():
    env = IdorHuntEnvironment()
    try:
        print("== Env smoke test ==")
        obs = env.reset(task_id="full_audit")
        print("reset:", obs.status_code)
        for action in [
            Action("GET", "/api/orders/3", account="alice"),
            Action("GET", "/api/reports", account="bob"),
            Action("GET", "/api/admin/config", account="alice"),
            Action("GET", "/api/announcements", account="guest"),
            Action("GET", "/api/catalog", account="alice"),
            Action("GET", "/api/tickets/4", account="bob"),
        ]:
            obs = env.step(action)
            print(
                f"{action.method} {action.path} @{action.account} -> "
                f"{obs.status_code} r={obs.reward:+.3f}"
            )
        print("grade:", env.get_grade())
    finally:
        env.close()


def run_episode(model, tokenizer, system_prompt: str, task_id: str, device: str) -> float:
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
                f"HTTP {obs.status_code}\n{obs.body[:600]}"
                + (f"\n\nHistory:\n{history_block}" if history_block else "")
                + "\n\nWhat is your next request?"
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]
            text = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = tokenizer(text=text, return_tensors="pt").to(device)
            with torch.no_grad():
                out = model.generate(
                    **inputs,
                    max_new_tokens=256,
                    temperature=0.4,
                    do_sample=True,
                    pad_token_id=tokenizer.eos_token_id,
                )
            response = tokenizer.decode(
                out[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True
            )
            action = parse_action(response)
            if action is None:
                break
            obs = env.step(action)
            history.append(
                f"[{step+1:02d}] {action.method} {action.path} @{action.account} -> "
                f"{obs.status_code} r={obs.reward:+.3f}"
            )
        return env.get_grade()
    finally:
        env.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-name", default="unsloth/Qwen3-4B")
    parser.add_argument("--output-dir", default="./grpo_idor_hunt")
    parser.add_argument("--train-steps", type=int, default=8)
    parser.add_argument("--eval-episodes", type=int, default=1)
    parser.add_argument("--num-generations", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--max-seq-len", type=int, default=1536)
    parser.add_argument("--lora-rank", type=int, default=16)
    parser.add_argument("--env-only", action="store_true")
    args = parser.parse_args()

    run_env_smoke_test()
    if args.env_only:
        print("Env-only check complete.")
        return

    import torch
    from datasets import Dataset
    from trl import GRPOConfig, GRPOTrainer
    from unsloth import FastLanguageModel

    os.makedirs(args.output_dir, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("Device:", device)
    if device == "cuda":
        print("GPU:", torch.cuda.get_device_name(0))

    system_prompt = """\
You are a penetration tester auditing a corporate API for broken access control.
Send exactly ONE HTTP request per turn as: METHOD PATH @account
Focus on real IDOR/privilege-escalation bugs.
Some endpoints are intentionally shared/public and are not vulnerabilities.
No explanation; output only the request line.\
"""

    seeded_states = build_seeded_states()
    debug_log = []
    reward_call_count = [0]

    def compute_reward(state_idx: int, completion) -> float:
        state = seeded_states[state_idx]
        text = extract_text(completion)
        reward_call_count[0] += 1
        should_log = reward_call_count[0] % 5 == 1
        env = IdorHuntEnvironment()
        try:
            env.reset(task_id=state["task"])
            for method, path, body, acct in state["pre_actions"]:
                env.step(Action(method, path, body, acct))
            action = parse_action(text)
            if action is None:
                return -0.3
            obs = env.step(action)
            reward = float(obs.reward)
            if should_log:
                debug_log.append(
                    {
                        "task": state["task"],
                        "parsed": f"{action.method} {action.path} @{action.account}",
                        "status": obs.status_code,
                        "reward": reward,
                    }
                )
            return reward
        except Exception as exc:
            if should_log:
                debug_log.append({"task": state["task"], "reason": f"exception: {exc}"})
                print(traceback.format_exc()[-500:])
            return -0.2
        finally:
            env.close()

    def reward_fn(completions: list, state_idx=None, **kwargs) -> list:
        if state_idx is None:
            state_idx = [0] * len(completions)
        return [compute_reward(int(idx), c) for idx, c in zip(state_idx, completions)]

    print("Loading model:", args.model_name)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model_name,
        max_seq_length=args.max_seq_len,
        load_in_4bit=(device == "cuda"),
        dtype=None,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.lora_rank,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        lora_alpha=args.lora_rank,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )

    dataset = Dataset.from_dict(
        {
            "prompt": [build_messages(s, system_prompt) for s in seeded_states],
            "state_idx": list(range(len(seeded_states))),
        }
    )
    print("Seeded states:", len(dataset))

    config = GRPOConfig(
        output_dir=args.output_dir,
        num_train_epochs=1,
        max_steps=args.train_steps,
        per_device_train_batch_size=args.batch_size,
        num_generations=args.num_generations,
        max_completion_length=256,
        learning_rate=args.learning_rate,
        warmup_steps=2,
        logging_steps=2,
        save_steps=args.train_steps,
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

    print(f"Training for {args.train_steps} steps...")
    trainer.train()
    print("Training complete.")

    FastLanguageModel.for_inference(model)
    results = {}
    for task in ("idor_horizontal", "privesc", "full_audit"):
        grades = []
        for _ in range(args.eval_episodes):
            grades.append(run_episode(model, tokenizer, system_prompt, task, device))
        results[task] = round(sum(grades) / len(grades), 3)
    print("Eval:", results)

    model.save_pretrained(os.path.join(args.output_dir, "lora_weights"))
    tokenizer.save_pretrained(os.path.join(args.output_dir, "lora_weights"))
    print("Saved:", os.path.join(args.output_dir, "lora_weights"))
    print("Debug samples:", len(debug_log))


if __name__ == "__main__":
    main()
