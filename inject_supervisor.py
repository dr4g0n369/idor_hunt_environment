import json

NB_PATH = "/home/dragon/Hacking/Hackathon/meta/idor_hunt_env/training_kaggle.ipynb"

with open(NB_PATH, "r") as f:
    nb = json.load(f)

cells = nb["cells"]

for cell in cells:
    if cell.get("id") == "01e93173":
        cell["source"] = """from datasets import Dataset
from trl import SFTTrainer, SFTConfig
from sft_data import get_sft_conversations, SFT_EXAMPLES

sft_conversations = get_sft_conversations()
sft_dataset = Dataset.from_dict({"messages": sft_conversations})

print(f"SFT dataset: {len(sft_dataset)} examples")
print(f"Sample actions: {[ex['action'] for ex in SFT_EXAMPLES[:5]]}")

SFT_STEPS = 80
SFT_LR = 2e-5
SFT_BATCH = 4

def sft_formatting_func(example):
    return tokenizer.apply_chat_template(
        example["messages"], tokenize=False, add_generation_prompt=False,
        enable_thinking=False,
    )

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
    fp16=not torch.cuda.is_bf16_supported(),
    bf16=torch.cuda.is_bf16_supported(),
    report_to="none",
    dataset_text_field=None,
)

FastLanguageModel.for_training(model)
sft_trainer = SFTTrainer(
    model=model,
    args=sft_config,
    train_dataset=sft_dataset,
    processing_class=tokenizer,
    formatting_func=sft_formatting_func,
)

print(f"Starting SFT training — {SFT_STEPS} steps, lr={SFT_LR}, batch={SFT_BATCH}...")
sft_trainer.train()
print("SFT training complete.")"""
        print("  Fixed SFT cell: added formatting_func")
        break

for cell in cells:
    if cell.get("id") == "679b3ce9":
        old_src = "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
        new_src = old_src.replace(
            '''config = GRPOConfig(
    output_dir=OUTPUT_DIR,
    num_train_epochs=1,
    max_steps=TRAINING_STEPS,
    per_device_train_batch_size=BATCH_SIZE,
    num_generations=NUM_GENERATIONS,
    max_completion_length=512,
    learning_rate=5e-6,
    warmup_steps=5,
    logging_steps=5,
    save_steps=TRAINING_STEPS,
    temperature=0.9,
    report_to="none",
    remove_unused_columns=False,
)''',
            '''config = GRPOConfig(
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
    push_to_hub=True,
    hub_model_id="dr4g0n369/idor-hunt-qwen3-4b-grpo",
    hub_token=HF_TOKEN,
    hub_private_repo=True,
)'''
        )
        if new_src != old_src:
            cell["source"] = new_src.split("\n")
            cell["source"] = [line + "\n" for line in new_src.split("\n")]
            cell["source"][-1] = cell["source"][-1].rstrip("\n")
            print("  Fixed GRPO cell: added push_to_hub config")
        else:
            print("  WARNING: Could not find GRPOConfig block to replace")
        break

for cell in cells:
    if cell.get("id") == "e6be815c":
        cell["source"] = """import os
os.makedirs(OUTPUT_DIR, exist_ok=True)

model.save_pretrained(os.path.join(OUTPUT_DIR, "lora_weights"))
tokenizer.save_pretrained(os.path.join(OUTPUT_DIR, "lora_weights"))
print(f"LoRA weights saved to {OUTPUT_DIR}/lora_weights")

fig.savefig(os.path.join(OUTPUT_DIR, "training_results.png"), dpi=150, bbox_inches="tight")
print(f"Plot saved to {OUTPUT_DIR}/training_results.png")"""
        print("  Fixed save cell: uncommented model save + plot save")
        break

for cell in cells:
    if cell.get("id") == "9c0e30c9":
        cell["source"] = """from huggingface_hub import login
login(token=HF_TOKEN)

model.push_to_hub("dr4g0n369/idor-hunt-qwen3-4b-grpo", private=True)
tokenizer.push_to_hub("dr4g0n369/idor-hunt-qwen3-4b-grpo", private=True)
print("Model pushed to HF Hub!")"""
        print("  Fixed HF push cell: uncommented and using HF_TOKEN")
        break

for cell in cells:
    if cell.get("id") == "dd14ae79":
        old_src = "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
        if "HF_TOKEN" not in old_src:
            hf_line = '\nHF_TOKEN = os.environ.get("HF_TOKEN", "")\n'
            if "import" not in old_src:
                hf_line = 'import os\n' + hf_line
            new_src = old_src + hf_line
            cell["source"] = [line + "\n" for line in new_src.split("\n")]
            cell["source"][-1] = cell["source"][-1].rstrip("\n")
            print("  Added HF_TOKEN to config cell")
        break

nb["cells"] = cells

with open(NB_PATH, "w") as f:
    json.dump(nb, f, indent=1)

with open(NB_PATH, "r") as f:
    validation = json.load(f)
print(f"\nNotebook saved and validated: {len(validation['cells'])} cells")
