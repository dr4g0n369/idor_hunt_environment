import json

NB_PATH = "/home/dragon/Hacking/Hackathon/meta/idor_hunt_env/training_kaggle.ipynb"

with open(NB_PATH, "r") as f:
    nb = json.load(f)

for cell in nb["cells"]:
    if cell.get("id") == "01e93173":
        cell["source"] = """from datasets import Dataset
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

SFT_STEPS = 80
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
print("SFT training complete.")"""
        print("Fixed: pre-format dataset with 'text' column, no formatting_func needed")
        break

with open(NB_PATH, "w") as f:
    json.dump(nb, f, indent=1)

print("Saved.")
