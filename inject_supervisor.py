import json

NB_PATH = "/home/dragon/Hacking/Hackathon/meta/idor_hunt_env/training_kaggle.ipynb"

with open(NB_PATH, "r") as f:
    nb = json.load(f)

for cell in nb["cells"]:
    if cell.get("id") == "01e93173":
        old_src = cell["source"] if isinstance(cell["source"], str) else "".join(cell["source"])
        old_src = old_src.replace(
            '''def sft_formatting_func(example):
    return tokenizer.apply_chat_template(
        example["messages"], tokenize=False, add_generation_prompt=False,
        enable_thinking=False,
    )''',
            '''def sft_formatting_func(example):
    return [tokenizer.apply_chat_template(
        example["messages"], tokenize=False, add_generation_prompt=False,
        enable_thinking=False,
    )]'''
        )
        cell["source"] = old_src
        print("Fixed: formatting_func now returns a list")
        break

with open(NB_PATH, "w") as f:
    json.dump(nb, f, indent=1)

print("Saved.")
