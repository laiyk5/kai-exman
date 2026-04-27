"""Configuration management for Kai-Exman.

Provides the ConfigManager class, which merges settings from defaults,
pyproject.toml, and CLI flags in strict precedence order.
"""

import tomllib
from pathlib import Path
from typing import Any


class ConfigManager:
    """Multi-layered configuration merging defaults, pyproject.toml, and CLI flags.

    Precedence (lowest to highest):
        1. Built-in defaults
        2. ``[tool.kaiexman]`` section in ``pyproject.toml``
        3. CLI flags passed at runtime

    Attributes:
        DEFAULTS: Mapping of built-in default values.
    """

    DEFAULTS: dict[str, Any] = {
        "critical_paths": ["src/", "pyproject.toml"],
        "ignore_paths": ["docs/", "tests/", "README.md", "*.md", ".gitignore"],
        "short_id_length": 8,
        "strict_mode": False,
        "trash_max_count": 50,
        "trash_max_size_gb": 5.0,
        "cluster_threshold": 0.5,
    }

    def __init__(self, cli_overrides: dict[str, Any] | None = None) -> None:
        """Initialize the configuration manager.

        Loads defaults, then merges pyproject.toml settings, then applies
        any CLI overrides.

        Args:
            cli_overrides: Dictionary of options passed via CLI flags.
        """
        self._config: dict[str, Any] = dict(self.DEFAULTS)
        self._load_pyproject()
        if cli_overrides:
            self._config.update(cli_overrides)

    def _load_pyproject(self) -> None:
        """Read ``[tool.kaiexman]`` from ``pyproject.toml`` if it exists.

        Missing or malformed files are silently ignored so the system
        falls back to defaults gracefully.
        """
        pyproject = Path("pyproject.toml")
        if not pyproject.exists():
            return
        try:
            with pyproject.open("rb") as f:
                data = tomllib.load(f)
            user = data.get("tool", {}).get("kaiexman", {})
            for key in self.DEFAULTS:
                if key in user:
                    self._config[key] = user[key]
        except Exception:
            return

    def __getitem__(self, key: str) -> Any:
        """Return a configuration value by key.

        Args:
            key: Configuration key name.

        Returns:
            The value associated with the key.
        """
        return self._config[key]

    def get(self, key: str, default: Any = None) -> Any:
        """Return a configuration value with an optional fallback.

        Args:
            key: Configuration key name.
            default: Value to return if the key is absent.

        Returns:
            The stored value or the provided default.
        """
        return self._config.get(key, default)
