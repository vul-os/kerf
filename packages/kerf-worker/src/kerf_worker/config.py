"""kerf-worker local configuration.

Config is stored at ``~/.config/kerf/worker.json``:

    {
        "worker_id":  "<uuid>",
        "token":      "kerf_wk_<hex>",
        "api_base":   "https://kerf.sh",
        "name":       "my-rtx-4090",
        "capabilities": { ... }
    }

The file is chmod 0600 on creation to limit read access.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

_DEFAULT_API_BASE = "https://kerf.sh"
_CONFIG_DIR = Path(os.environ.get("KERF_CONFIG_DIR", Path.home() / ".config" / "kerf"))
_CONFIG_PATH = _CONFIG_DIR / "worker.json"


def _config_path() -> Path:
    """Return the effective config path (can be overridden via env for tests)."""
    env = os.environ.get("KERF_WORKER_CONFIG")
    return Path(env) if env else _CONFIG_PATH


class WorkerConfig(BaseModel):
    worker_id: str
    token: str
    api_base: str = Field(default=_DEFAULT_API_BASE)
    name: str = ""
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    last_heartbeat: Optional[str] = None
    current_job: Optional[str] = None


def load() -> Optional[WorkerConfig]:
    """Return config or None if not enrolled."""
    path = _config_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return WorkerConfig(**data)
    except Exception:
        return None


def save(cfg: WorkerConfig) -> None:
    """Persist config; create parent dirs; restrict file permissions."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cfg.model_dump_json(indent=2))
    # 0600: owner read/write only
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # Windows / some filesystems don't support chmod


def delete() -> None:
    """Remove the local config file (used by `revoke`)."""
    path = _config_path()
    if path.exists():
        path.unlink()


def api_base() -> str:
    """Effective API base URL — KERF_API_URL env overrides the stored value."""
    env = os.environ.get("KERF_API_URL")
    if env:
        return env.rstrip("/")
    cfg = load()
    if cfg:
        return cfg.api_base.rstrip("/")
    return _DEFAULT_API_BASE.rstrip("/")
