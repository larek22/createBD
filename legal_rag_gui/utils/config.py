"""Configuration helpers for Legal RAG Studio.

The GUI keeps user preferences (API keys, theme, last-used folders) inside
`~/.legal_rag_studio/config.yaml`.  The schema is intentionally simple so it can
be inspected or edited manually when needed.  All access goes through the
:class:`SettingsStore` to ensure defaults are always present.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict

try:  # pragma: no cover - optional dependency
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None
    import json


CONFIG_DIR = Path.home() / ".legal_rag_studio"
CONFIG_PATH = CONFIG_DIR / "config.yaml"


@dataclass
class AppSettings:
    """Serializable settings model.

    Attributes mirror what is exposed in the *Settings* tab.  The idea is to
    keep everything human readable – no secrets are stored in binary form.
    """

    openai_api_key: str = ""
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str = ""
    documents_dir: str = str(Path.home())
    logs_dir: str = str(CONFIG_DIR / "logs")
    theme: str = "dark"
    last_backend_port: int = 8765


class SettingsStore:
    """Simple persistence layer.

    The class is intentionally lightweight – it does not attempt to resolve
    conflicts or handle concurrent writers.  The GUI is the sole writer, so the
    logic boils down to "load on start, update on change".
    """

    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self._path = path
        self._settings = AppSettings()
        self._load()

    # ------------------------------ internals ------------------------------
    def _load(self) -> None:
        if not self._path.exists():
            self._ensure_parent()
            self.save()
            return
        try:
            if yaml:
                raw: Dict[str, Any] = yaml.safe_load(self._path.read_text("utf-8")) or {}
            else:
                raw = json.loads(self._path.read_text("utf-8"))
            self._settings = AppSettings(**{**asdict(AppSettings()), **raw})
        except Exception:
            # Corrupted YAML – move it aside and start fresh so the app still runs.
            backup = self._path.with_suffix(".broken.yaml")
            self._path.rename(backup)
            self._settings = AppSettings()
            self.save()

    def _ensure_parent(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------ public API -----------------------------
    @property
    def data(self) -> AppSettings:
        return self._settings

    def update(self, **kwargs: Any) -> AppSettings:
        for key, value in kwargs.items():
            if hasattr(self._settings, key):
                setattr(self._settings, key, value)
        self.save()
        return self._settings

    def save(self) -> None:
        self._ensure_parent()
        payload: Dict[str, Any] = asdict(self._settings)
        if yaml:
            data = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
        else:
            data = json.dumps(payload, ensure_ascii=False, indent=2)
        self._path.write_text(data, "utf-8")


__all__ = ["AppSettings", "SettingsStore", "CONFIG_PATH"]
