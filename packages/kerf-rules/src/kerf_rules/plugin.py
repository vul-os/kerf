"""
kerf-rules plugin entry-point.

The rules engine is a pure library used by other plugins (BIM, structural,
mechanical) to evaluate compliance rule packs. Registers the
`validate_against_rules` LLM tool so the agent can check project models
against AISC 360, Eurocode 2, and ASME B18 rule packs directly.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def register(app: FastAPI, ctx):
    # ── LLM tools ────────────────────────────────────────────────────────────
    _all_tools = []
    for _module in (
        "kerf_rules.tools.validate_against_rules",
        "kerf_rules.tools.kbe_apply_rules",
    ):
        try:
            import importlib
            mod = importlib.import_module(_module)
            for name, spec, handler in getattr(mod, "TOOLS", []):
                ctx.tools.register(name, spec, handler)
                _all_tools.append(name)
        except Exception as exc:
            logger.warning("kerf-rules: failed to register tools from %s: %s", _module, exc)
    logger.info("kerf-rules: registered %d tool(s): %s", len(_all_tools), _all_tools)

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="rules",
            version="0.1.0",
            provides=["rules.engine", "rules.validate"],
            depends=[],
        )
    except ImportError:
        return {
            "name": "rules",
            "version": "0.1.0",
            "provides": ["rules.engine", "rules.validate"],
            "depends": [],
        }
