"""Shared types for upload wrappers."""
from __future__ import annotations

from typing import NamedTuple


class UploadResult(NamedTuple):
    """Return type for all upload wrappers.

    Attributes
    ----------
    ok : bool
        True when the upload succeeded (tool exited 0).
    stdout : str
        Captured standard output from the upload tool.
    stderr : str
        Captured standard error from the upload tool.
    status : str
        One of "ok" | "error" | "pending".
        - "ok"      — upload succeeded.
        - "error"   — tool was found but exited non-zero.
        - "pending" — tool binary not found on PATH; upload was not attempted.
    reason : str
        Human-readable explanation when status != "ok", empty otherwise.
    """

    ok: bool
    stdout: str
    stderr: str
    status: str  # "ok" | "error" | "pending"
    reason: str
