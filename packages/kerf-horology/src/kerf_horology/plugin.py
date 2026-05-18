"""Kerf plugin registration for kerf-horology."""

from __future__ import annotations


def register(registry) -> None:  # pragma: no cover
    """Register horology tools with the Kerf plugin registry."""
    from kerf_horology.tools import TOOLS
    for tool in TOOLS:
        registry.register(tool)
