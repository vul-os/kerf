"""_compat.py — Compatibility shims for running kerf_hvac outside the Kerf backend.

Mirrors the pattern established in kerf_wiring._compat.  When the full
kerf_chat.tools.registry is not importable (e.g. in tests, CI, or standalone
usage), this module provides lightweight equivalents.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict


_registry: list[dict] = []


def register(spec: ToolSpec, write: bool = False):
    """Decorator: register a tool handler in the local _registry."""
    def decorator(fn: Callable) -> Callable:
        _registry.append({"spec": spec, "write": write, "fn": fn})
        return fn
    return decorator


def ok_payload(v: Any) -> str:
    """Serialise a successful tool response to JSON."""
    return json.dumps(v)


def err_payload(msg: str, code: str) -> str:
    """Serialise an error tool response to JSON."""
    return json.dumps({"error": msg, "code": code})


class ProjectCtx:
    """Minimal stand-in for kerf_core.utils.context.ProjectCtx."""

    def __init__(
        self,
        pool=None,
        project_id=None,
        user_id=None,
        storage=None,
        http_client=None,
        file_revisions_max: int = 200,
    ):
        self.pool = pool
        self.project_id = project_id
        self.user_id = user_id
        self.storage = storage
        self.http_client = http_client
        self.file_revisions_max = file_revisions_max
