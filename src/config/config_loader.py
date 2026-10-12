"""Configuration loader for LLMs and data-sources."""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml  # type: ignore[import-untyped]

logger = logging.getLogger("text2sql")


class ConfigLoader:
    """Simple YAML configuration loader.

    - Loads the config file once via `initialize()`.
    - Access from anywhere in the project using `get()`
    - No implicit defaults or directories — fully explicit paths.
    """

    _config: Dict[str, Any] = {}
    _initialized: bool = False

    @classmethod
    def initialize(
        cls,
        config_path: Optional[str] = None,
    ):
        """Load configuration files into memory.

        Args:
            config_path: Path to the config YAML file.

        """
        if cls._initialized:
            logger.info("ConfigLoader already initialized — skipping reload.")
            return

        if not config_path:
            raise ValueError("You must provide a config file path.")

        cls._config = cls._load_yaml(Path(config_path))
        cls._initialized = True
        logger.info("ConfigLoader initialized")

    @staticmethod
    def _load_yaml(path: Path) -> Dict[str, Any]:
        """Load a YAML file safely."""
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    @classmethod
    def get(cls) -> Dict[str, Any]:
        """Retrieve the loaded configuration."""
        if not cls._initialized:
            raise RuntimeError("⚠️ ConfigLoader not initialized. Call initialize() first.")
        return cls._config
