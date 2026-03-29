"""Configuration system with auto-detection and TOML config file support."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass
class Config:
    """cclog configuration."""

    claude_dir: Path = field(default_factory=lambda: Path.home() / ".claude")
    timezone: str = ""
    cache_dir: Path = field(default_factory=lambda: Path.home() / ".cache" / "cclog")
    llm_backend: str = "claude-cli"
    llm_model: str = "sonnet"
    language: str = "en"

    def __post_init__(self):
        if not self.timezone:
            self.timezone = _detect_timezone()
        if self.language == "en":
            self.language = _detect_language(self.claude_dir)

    @property
    def projects_dir(self) -> Path:
        return self.claude_dir / "projects"

    @property
    def db_path(self) -> Path:
        return self.cache_dir / "sessions.db"

    @property
    def session_index_path(self) -> Path:
        return self.claude_dir / "session_index.json"


def load_config(cli_overrides: dict | None = None) -> Config:
    """Load config from file with auto-detection, applying CLI overrides last."""
    file_config = _load_config_file()
    merged = {**file_config, **(cli_overrides or {})}

    # Convert string paths to Path objects
    for key in ("claude_dir", "cache_dir"):
        if key in merged and isinstance(merged[key], str):
            merged[key] = Path(merged[key]).expanduser()

    return Config(**merged)


def _load_config_file() -> dict:
    """Try loading config from standard locations."""
    candidates = [
        Path.home() / ".config" / "cclog" / "config.toml",
        Path.home() / ".claude" / "cclog.toml",
    ]

    for path in candidates:
        if path.exists():
            with open(path, "rb") as f:
                raw = tomllib.load(f)
            # Flatten sections: [core] claude_dir -> claude_dir
            flat = {}
            for section in ("core", "cache", "llm", "output", "site"):
                if section in raw:
                    for k, v in raw[section].items():
                        # Map section-specific keys
                        if section == "cache" and k == "dir":
                            flat["cache_dir"] = v
                        elif section == "llm" and k == "backend":
                            flat["llm_backend"] = v
                        elif section == "llm" and k == "model":
                            flat["llm_model"] = v
                        else:
                            flat[k] = v
            return flat

    return {}


def _detect_timezone() -> str:
    """Detect system timezone."""
    # Try reading /etc/localtime symlink (macOS/Linux)
    try:
        link = os.readlink("/etc/localtime")
        # /var/db/timezone/zoneinfo/Asia/Shanghai -> Asia/Shanghai
        if "zoneinfo/" in link:
            return link.split("zoneinfo/")[-1]
    except OSError:
        pass

    # Try TZ environment variable
    tz = os.environ.get("TZ", "")
    if tz:
        return tz

    return "UTC"


def _detect_language(claude_dir: Path) -> str:
    """Detect language from Claude Code settings."""
    settings_path = claude_dir / "settings.json"
    if settings_path.exists():
        try:
            with open(settings_path) as f:
                settings = json.load(f)
            # Check for Chinese language setting
            lang = settings.get("language", "")
            if "zh" in lang.lower() or "chinese" in lang.lower():
                return "zh"
        except (json.JSONDecodeError, OSError):
            pass

    # Check locale
    locale_str = os.environ.get("LANG", "")
    if "zh" in locale_str.lower():
        return "zh"

    return "en"
