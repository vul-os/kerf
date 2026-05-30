"""
kerf-plm plugin entry-point.

Registers:
  - LLM tool  plm_configure  (via ctx.tools.register)
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_plm.tools import plm_configure_spec, run_plm_configure
    ctx.tools.register("plm_configure", plm_configure_spec, run_plm_configure)

    from kerf_plm.tools import plm_change_management_spec, plm_change_management as _plm_cm

    async def _run_plm_change_management(ctx, args: bytes) -> str:
        import json as _json
        try:
            a = _json.loads(args)
        except Exception as e:
            from kerf_plm._compat import err_payload
            return err_payload(f"invalid args: {e}", "BAD_ARGS")
        result = _plm_cm(**a)
        import json as _json2
        return _json2.dumps(result)

    ctx.tools.register("plm_change_management", plm_change_management_spec, _run_plm_change_management)

    # KBE↔configurator bridge — kerf-rules KBE engine + kerf-plm configurator
    # in one call. Per the KBE-PLM-BRIDGE work (commit 6de5658f).
    try:
        from kerf_plm.tools.plm_kbe_configure_tool import TOOLS as _KBE_BRIDGE_TOOLS
        for name, spec, handler in _KBE_BRIDGE_TOOLS:
            ctx.tools.register(name, spec, handler)
    except Exception:
        pass  # KBE bridge optional — fail silently if kerf-rules KBE unavailable.

    # MBSE / SysML 1.x XMI digital-thread tools (Wave 4P).
    try:
        from kerf_plm.sysml_tools import TOOLS as _SYSML_TOOLS
        for name, spec, handler in _SYSML_TOOLS:
            ctx.tools.register(name, spec, handler)
    except Exception:
        pass  # sysml tools optional — fail silently if XMI deps unavailable.

    # Change-impact analyzer (PROSTEP-iViP SIG) — Wave 4NN.
    try:
        from kerf_plm.tools import (
            plm_change_impact_spec, run_plm_change_impact,
            plm_propose_co_changes_spec, run_plm_propose_co_changes,
        )
        ctx.tools.register("plm_change_impact", plm_change_impact_spec, run_plm_change_impact)
        ctx.tools.register("plm_propose_co_changes", plm_propose_co_changes_spec, run_plm_propose_co_changes)
    except Exception:
        pass  # change-impact tools optional — fail silently if symbols missing.

    # Where-Used analysis (PROSTEP-iViP SIG §5.2) — inverse BOM traversal.
    try:
        from kerf_plm.tools import plm_where_used_spec, run_plm_where_used
        ctx.tools.register("plm_where_used", plm_where_used_spec, run_plm_where_used)
    except Exception:
        pass  # where-used tool optional — fail silently if symbol missing.

    # Effectivity BOM expansion (ISO 10303-44 + Borst-Lahti §7.4) — 150% → 100% BOM.
    try:
        from kerf_plm.tools import (
            plm_expand_effectivity_bom_spec,
            run_plm_expand_effectivity_bom,
        )
        ctx.tools.register(
            "plm_expand_effectivity_bom",
            plm_expand_effectivity_bom_spec,
            run_plm_expand_effectivity_bom,
        )
    except Exception:
        pass  # effectivity-bom tool optional — fail silently if symbol missing.

    # Document version diff (ISO 10303-44 §5.2 + Borst-Lahti §6.3).
    try:
        from kerf_plm.tools import (
            plm_document_version_diff_spec,
            run_plm_document_version_diff,
        )
        ctx.tools.register(
            "plm_document_version_diff",
            plm_document_version_diff_spec,
            run_plm_document_version_diff,
        )
    except Exception:
        pass  # document-version-diff tool optional — fail silently if symbol missing.

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="plm",
            version="0.1.0",
            provides=["plm.configurator", "plm.effectivity-bom", "plm.change-management", "plm.kbe-bridge", "plm.sysml-traceability", "plm.xmi-export", "plm.where-used", "plm.document-version-diff"],
            depends=[],
        )
    except ImportError:
        return {
            "name": "plm",
            "version": "0.1.0",
            "provides": ["plm.configurator", "plm.effectivity-bom", "plm.change-management", "plm.kbe-bridge"],
            "depends": [],
        }
