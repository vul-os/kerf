"""
Compatibility shims for running kerf_microfluidics outside of the live backend.

When kerf_microfluidics is imported standalone (e.g. during unit tests) and
`kerf_chat.tools.registry` or `kerf_core.utils.context` are not installed,
these thin replacements allow the module to load cleanly.  At runtime the
real implementations from kerf-core are used instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable


# ---------------------------------------------------------------------------
# ToolSpec / registry shims
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# ProjectCtx shim
# ---------------------------------------------------------------------------

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
