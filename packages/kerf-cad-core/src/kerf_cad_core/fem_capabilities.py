"""
kerf_cad_core.fem_capabilities — FEM capability advertisement (T-100h).

Provides:
  list_capabilities() -> dict
      Returns a JSON-serialisable dict of every AnalysisType in the public
      enum together with its capability requirements and a human description.
      Suitable for inclusion in ``GET /health/capabilities``.

  fem_list_capabilities_tool — LLM tool stub (ToolSpec-compatible) that
      wraps list_capabilities() for use in the Kerf agent tool registry.
      It is a *stub*: the full async @register handler is wired in
      kerf_cad_core.fea.tools when the registry is available.  Tests and
      downstream callers can invoke the pure function directly without
      needing the registry at import time.

Author: imranparuk
"""

from __future__ import annotations

import json
from typing import Any

from kerf_cad_core.analysis import AnalysisType


# ---------------------------------------------------------------------------
# Pure function — no registry dependency
# ---------------------------------------------------------------------------

def list_capabilities() -> dict[str, Any]:
    """Return a dict describing every FEM analysis type available in Kerf.

    The returned structure is JSON-serialisable.  Top-level key is
    ``"analysis_types"`` — a list of objects, one per :class:`AnalysisType`
    member, with fields:

      ``id``          — enum value string (e.g. ``"linear_static"``)
      ``requires``    — sorted list of capability tag strings
      ``description`` — first non-blank line from the enum member's docstring

    Example
    -------
    >>> caps = list_capabilities()
    >>> caps["analysis_types"][0]["id"]
    'acoustics_fem'

    Returns
    -------
    dict
        ``{"analysis_types": [...], "n_types": <int>}``
    """
    entries: list[dict[str, Any]] = []
    for member in AnalysisType:
        # First non-blank, non-whitespace line of the docstring
        raw_doc: str = (member.__doc__ or "").strip()
        first_line = next(
            (ln.strip() for ln in raw_doc.splitlines() if ln.strip()),
            member.value,
        )
        entries.append(
            {
                "id": member.value,
                "requires": sorted(member.requires),
                "description": first_line,
            }
        )

    # Sort alphabetically by id for deterministic output
    entries.sort(key=lambda e: e["id"])

    return {
        "analysis_types": entries,
        "n_types": len(entries),
    }


# ---------------------------------------------------------------------------
# LLM tool stub — ToolSpec-compatible descriptor
# ---------------------------------------------------------------------------

_FEM_CAPABILITIES_SPEC: dict[str, Any] = {
    "name": "fem_list_capabilities",
    "description": (
        "List all FEM / CAE analysis types supported by the Kerf FEM engine, "
        "together with the solver capability tags each type requires.\n"
        "\n"
        "Returns a JSON object with a list of analysis types.  Each entry "
        "includes:\n"
        "  id          — canonical analysis type string (use as analysis_type param)\n"
        "  requires    — solver capabilities needed before this analysis can run\n"
        "  description — one-line human description\n"
        "\n"
        "Use this tool to discover which analysis types are available before "
        "calling fea_solve_truss or any FEM solver tool.  No parameters required.\n"
        "\n"
        "Errors: {ok:false, reason} if the capability list cannot be built.  "
        "Never raises."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


async def _run_fem_list_capabilities(ctx: Any, args: bytes) -> str:  # noqa: ARG001
    """Async handler — wraps list_capabilities() for the tool registry.

    This is the handler function; it is registered in kerf_cad_core.fea.tools
    once the registry is available.  It can also be called directly in tests
    by passing a stub ctx and empty args.
    """
    try:
        result = list_capabilities()
        return json.dumps({"ok": True, **result})
    except Exception as exc:  # pragma: no cover — defensive
        return json.dumps({"ok": False, "reason": str(exc)})


__all__ = [
    "list_capabilities",
    "_FEM_CAPABILITIES_SPEC",
    "_run_fem_list_capabilities",
]
