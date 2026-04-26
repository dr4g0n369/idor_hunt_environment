import json

NB_PATH = "/home/dragon/Hacking/Hackathon/meta/idor_hunt_env/training_kaggle.ipynb"

with open(NB_PATH, "r") as f:
    nb = json.load(f)

for cell in nb["cells"]:
    if cell.get("id") == "supervisor_code_01":
        old_src = cell["source"] if isinstance(cell["source"], str) else "".join(cell["source"])
        
        # Replace the hardcoded os.environ check that bypasses the Kaggle Secret
        new_src = old_src.replace(
            'HF_TOKEN = os.environ.get("HF_TOKEN", "")',
            '''try:
    from kaggle_secrets import UserSecretsClient
    HF_TOKEN = UserSecretsClient().get_secret("HF_TOKEN")
except Exception:
    HF_TOKEN = os.environ.get("HF_TOKEN", "")'''
        )
        cell["source"] = new_src
        print("Fixed supervisor cell to use Kaggle Secrets token.")
        break

with open(NB_PATH, "w") as f:
    json.dump(nb, f, indent=1)

print("Saved.")
