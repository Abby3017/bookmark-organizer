from pathlib import Path
import yaml

from bookmark_agent.domain.errors import ConfigError


def load_settings(config_path: str = "config.yaml") -> dict:
    path = Path(config_path)

    if not path.exists():
        raise ConfigError(
            f"Configuration file not found: {config_path}"
        )

    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def update_setting(key: str, value, config_path: str = "config.yaml") -> None:
    """Set one key and write the config back.
    # shortcut: safe_dump drops comments; use ruamel.yaml if they ever matter
    """
    path = Path(config_path)
    settings = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    settings[key] = value
    path.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")