"""
Compatibility shims for running kerf-manufacturing outside of the full Kerf backend.

When running unit tests or using the package standalone (without kerf-core
installed) these thin replacements stand in for the real registry objects.
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


_registry: list = []


def register(spec: "ToolSpec", write: bool = False):
    def decorator(fn: Callable) -> Callable:
        _registry.append({"spec": spec, "write": write, "fn": fn})
        return fn
    return decorator


def ok_payload(v: Any) -> str:
    return json.dumps(v)


def err_payload(msg: str, code: str) -> str:
    return json.dumps({"error": msg, "code": code})


class ProjectCtx:
    """Minimal stand-in for backend context used in tests."""
    def __init__(self, pool=None, project_id=None, user_id=None, storage=None,
                 http_client=None):
        self.pool = pool
        self.project_id = project_id
        self.user_id = user_id
        self.storage = storage
        self.http_client = http_client
