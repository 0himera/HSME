import pathlib
import yaml

def load_prompt(domain: str) -> dict:
    """Loads a prompt configuration dictionary from backend/prompts/{domain}.yaml."""
    base_dir = pathlib.Path(__file__).parent.parent
    prompt_path = base_dir / "prompts" / f"{domain}.yaml"
    
    with open(prompt_path, mode="r", encoding="utf-8") as f:
        return yaml.safe_load(f)
