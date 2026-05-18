"""Compatibility shims for running kerf_interior outside of the Kerf runtime.

When ``kerf_chat`` and ``kerf_core`` are not importable (e.g. during isolated
unit tests or in a standalone installation), this module provides lightweight
drop-in replacements so all interior-package code can import from one place
without complex try/except chains in every module.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

_logger = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    """Minimal tool-spec descriptor used by the Kerf LLM tool registry."""
    name: str
    description: str
    input_schema: dict


_registry: list[dict] = []


def register(spec: "ToolSpec", write: bool = False):
    """Decorator that records a tool handler in the local shim registry."""
    def decorator(fn: Callable) -> Callable:
        _registry.append({"spec": spec, "write": write, "fn": fn})
        return fn
    return decorator


def ok_payload(value: Any) -> str:
    """Serialise a successful result to JSON string."""
    return json.dumps(value)


def err_payload(message: str, code: str) -> str:
    """Serialise an error result to JSON string."""
    return json.dumps({"error": message, "code": code})


class ProjectCtx:
    """Stub project context used in tests and standalone scripts."""

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
