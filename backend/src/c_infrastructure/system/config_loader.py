from pathlib import Path

import yaml

from b_application.schemas.config import AppConfig


def load_settings(config_path: Path | None = None, instruction_path: Path | None = None) -> AppConfig:
    project_root = get_project_root()

    if config_path is None:
        config_path = project_root / "config" / "appsetting.yaml"
    if instruction_path is None:
        instruction_path = project_root / "config" / "instructions.yaml"
        
    config_dict = {}
    try:
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config_dict = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Warning: Could not load YAML config from {config_path}. Error: {e}")

    try:
        if instruction_path.exists():
            with open(instruction_path, "r", encoding="utf-8") as f:
                instruction_data = yaml.safe_load(f) or {}
                
                # Elegantly merge properties from instructions.yaml directly into the nested ai configuration
                if instruction_data:
                    ai_config = config_dict.setdefault("ai", {})
                    if "system_prompt" in instruction_data:
                        ai_config["system_prompt"] = instruction_data["system_prompt"]
                    if "rag_injection_prompt" in instruction_data:
                        ai_config["rag_injection_prompt"] = instruction_data["rag_injection_prompt"]
                        
    except Exception as e:
        print(f"Warning: Could not load instruction YAML from {instruction_path}. Error: {e}")

    # Pydantic will elegantly instantiate the nested child classes automatically using the dictionary structure!
    return AppConfig(project_root=project_root, **config_dict)


def get_project_root() -> Path:
    """
    Finds the project root by searching upwards for the 'pyproject.toml' file.

    This approach is robust against changes in the directory structure.

    Returns:
        The Path object for the project's root directory.

    Raises:
        FileNotFoundError: If the 'pyproject.toml' file cannot be found.
    """
    current_path = Path(__file__).resolve()
    for parent in current_path.parents:
        if (parent / "justfile").exists() or (parent / ".git").exists():
            return parent
    raise FileNotFoundError("Could not find project root. Make sure 'justfile' or '.git' exists in the root directory.")
