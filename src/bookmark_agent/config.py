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