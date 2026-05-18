"""Persistent user credentials for the kerf CLI.

Stores API token and server URL in a plain-text config file under the
user's home directory so that `kerf login` only needs to be run once.

File location: ~/.config/kerf/credentials   (XDG-style, cross-platform)

Format (newline-separated key=value, order not significant)::

    api_url=https://app.kerf.io
    api_token=kerf_sk_...

The file is created with mode 0600 (user-read-write only).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Optional

_DEFAULT_API_URL = "https://app.kerf.io"


def _credentials_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".config"
    return base / "kerf" / "credentials"


def load_credentials() -> dict[str, str]:
    """Return saved credentials as a dict with keys ``api_url`` and ``api_token``.

    Missing keys default to empty string (token) or the cloud URL (api_url).
    """
    path = _credentials_path()
    result: dict[str, str] = {"api_url": _DEFAULT_API_URL, "api_token": ""}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    return result


def save_credentials(*, api_url: str, api_token: str) -> Path:
    """Persist credentials and return the path of the written file."""
    path = _credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"api_url={api_url}\napi_token={api_token}\n"
    path.write_text(content, encoding="utf-8")
    # Restrict permissions to owner only (rw-------)
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def get_api_url() -> str:
    """Return the configured API URL (env var overrides saved value)."""
    env = os.environ.get("KERF_API_URL", "").strip()
    if env:
        return env.rstrip("/")
    return load_credentials().get("api_url", _DEFAULT_API_URL).rstrip("/")


def get_api_token() -> Optional[str]:
    """Return the configured API token (env var overrides saved value), or None."""
    env = os.environ.get("KERF_API_TOKEN", "").strip()
    if env:
        return env
    token = load_credentials().get("api_token", "").strip()
    return token or None
