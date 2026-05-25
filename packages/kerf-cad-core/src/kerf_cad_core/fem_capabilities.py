"""
kerf_cad_core.fem_capabilities — FEM capability advertisement (T-100h).

Provides:
  list_capabilities() -> dict
      Returns a JSON-serialisable dict of every AnalysisType in the public
      enum together with its capability requirements and a human description.
      Suitable for inclusion in ``GET /health/capabilities``.

  fem_list_capabilities_spec — ToolSpec registered with @register so the
      module self-wires when imported by plugin._register_tools().
      Tests and downstream callers can invoke the pure function directly
      without needing the registry at import time.

Author: imranparuk
"""

from __future__ import annotations

import json
from typing import Any

from kerf_cad_core.analysis import AnalysisType

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cad_core._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx  # type: ignore[no-redef]


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
# LLM tool — ToolSpec + @register (self-wires on import)
# ---------------------------------------------------------------------------

fem_list_capabilities_spec = ToolSpec(
    name="fem_list_capabilities",
    description=(
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
    input_schema={
        "type": "object",
        "properties": {},
        "required": [],
    },
)

# Keep the old dict alias for backward-compat with existing tests.
_FEM_CAPABILITIES_SPEC: dict[str, Any] = {
    "name": fem_list_capabilities_spec.name,
    "description": fem_list_capabilities_spec.description,
    "input_schema": fem_list_capabilities_spec.input_schema,
}


@register(fem_list_capabilities_spec, write=False)
async def _run_fem_list_capabilities(ctx: Any, args: bytes) -> str:  # noqa: ARG001
    """Async handler — wraps list_capabilities() for the tool registry."""
    try:
        result = list_capabilities()
        return ok_payload({"ok": True, **result})
    except Exception as exc:  # pragma: no cover — defensive
        return err_payload(str(exc), "ERROR")


__all__ = [
    "list_capabilities",
    "fem_list_capabilities_spec",
    "_FEM_CAPABILITIES_SPEC",
    "_run_fem_list_capabilities",
]
