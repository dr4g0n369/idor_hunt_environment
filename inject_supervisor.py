import json

NB_PATH = "/home/dragon/Hacking/Hackathon/meta/idor_hunt_env/training_kaggle.ipynb"

with open(NB_PATH, "r") as f:
    nb = json.load(f)

for cell in nb["cells"]:
    if cell.get("id") == "dd14ae79":
        old_src = cell["source"] if isinstance(cell["source"], str) else "".join(cell["source"])
        old_src = old_src.replace(
            'HF_TOKEN = os.environ.get("HF_TOKEN", "")',
            '''try:
    from kaggle_secrets import UserSecretsClient
    HF_TOKEN = UserSecretsClient().get_secret("HF_TOKEN")
except Exception:
    HF_TOKEN = os.environ.get("HF_TOKEN", "")

print(f"HF Token present: {bool(HF_TOKEN)}")'''
        )
        cell["source"] = old_src
        print("Fixed config cell: added Kaggle secrets fallback for HF_TOKEN")
        break

for cell in nb["cells"]:
    if cell.get("id") == "679b3ce9":
        old_src = cell["source"] if isinstance(cell["source"], str) else "".join(cell["source"])
        old_src = old_src.replace(
            "    push_to_hub=True,",
            "    push_to_hub=bool(HF_TOKEN),"
        )
        cell["source"] = old_src
        print("Fixed GRPO cell: push_to_hub conditional on HF_TOKEN")
        break

with open(NB_PATH, "w") as f:
    json.dump(nb, f, indent=1)

print("Saved.")
