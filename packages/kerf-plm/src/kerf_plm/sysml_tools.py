"""
LLM tool definitions for kerf-plm.

Tools
-----
sysml_trace_coverage  — coverage report for a TraceabilityMatrix
sysml_export_xmi      — export a matrix to SysML 1.x XMI file
sysml_import_xmi      — import a SysML 1.x XMI file → coverage report

Caveat: implements SysML 1.x XMI per OMG 1.6/1.7 namespace URIs.
Not OMG-certified.
"""

from __future__ import annotations

import json
import tempfile
import os

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_plm._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_matrix(params: dict):
    """Construct a TraceabilityMatrix from the canonical JSON payload."""
    from kerf_plm.sysml import (
        Requirement, DesignElement, TestCase, TraceabilityMatrix,
    )

    requirements = [
        Requirement(
            id=r["id"],
            text=r.get("text", ""),
            parent_id=r.get("parent_id"),
            satisfied_by=r.get("satisfied_by", []),
            verified_by=r.get("verified_by", []),
        )
        for r in params.get("requirements", [])
    ]
    design_elements = [
        DesignElement(
            id=d["id"],
            kind=d.get("kind", "block"),
            name=d.get("name", d["id"]),
            properties=d.get("properties", {}),
            allocated_to=d.get("allocated_to", []),
        )
        for d in params.get("design_elements", [])
    ]
    test_cases = [
        TestCase(
            id=t["id"],
            name=t.get("name", t["id"]),
            verifies=t.get("verifies", []),
        )
        for t in params.get("test_cases", [])
    ]
    return TraceabilityMatrix(requirements, design_elements, test_cases)


# ---------------------------------------------------------------------------
# _matrix_payload schema (shared by coverage + export tools)
# ---------------------------------------------------------------------------

_MATRIX_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "requirements": {
            "type": "array",
            "description": "List of requirement objects.",
            "items": {
                "type": "object",
                "properties": {
                    "id":           {"type": "string"},
                    "text":         {"type": "string"},
                    "parent_id":    {"type": "string"},
                    "satisfied_by": {"type": "array", "items": {"type": "string"}},
                    "verified_by":  {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "text"],
            },
        },
        "design_elements": {
            "type": "array",
            "description": "List of design element objects (blocks, parts, connectors).",
            "items": {
                "type": "object",
                "properties": {
                    "id":           {"type": "string"},
                    "kind":         {"type": "string", "enum": ["block", "part", "connector"]},
                    "name":         {"type": "string"},
                    "properties":   {"type": "object"},
                    "allocated_to": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id"],
            },
        },
        "test_cases": {
            "type": "array",
            "description": "List of test case objects.",
            "items": {
                "type": "object",
                "properties": {
                    "id":       {"type": "string"},
                    "name":     {"type": "string"},
                    "verifies": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id"],
            },
        },
    },
    "required": ["requirements"],
}


# ---------------------------------------------------------------------------
# sysml_trace_coverage
# ---------------------------------------------------------------------------

sysml_trace_coverage_spec = ToolSpec(
    name="sysml_trace_coverage",
    description=(
        "Compute a requirements-to-design-to-test traceability coverage report "
        "for an MBSE / SysML 1.x digital thread.\n"
        "\n"
        "Accepts lists of requirements, design elements, and test cases with their "
        "link declarations (satisfied_by, verified_by, verifies) and returns:\n"
        "  covered          : int — requirements satisfied by ≥1 design AND verified by ≥1 test\n"
        "  uncovered        : int\n"
        "  total            : int\n"
        "  coverage_pct     : float — covered / total × 100\n"
        "  orphaned_requirements  : list[str] — no design element satisfies them\n"
        "  unverified_requirements: list[str] — no test case verifies them\n"
        "  orphaned_tests         : list[str] — test cases that verify no requirement\n"
        "\n"
        "Caveat: SysML 1.x traceability semantics (not SysML 2.0, not OMG-certified)."
    ),
    input_schema=_MATRIX_INPUT_SCHEMA,
)


async def run_sysml_trace_coverage(params: dict, ctx: "ProjectCtx") -> str:
    try:
        matrix = _build_matrix(params)
        report = matrix.coverage_report()
        return ok_payload({"ok": True, **report})
    except Exception as exc:
        return err_payload(str(exc), "SYSML_COVERAGE_ERROR")


# ---------------------------------------------------------------------------
# sysml_export_xmi
# ---------------------------------------------------------------------------

_EXPORT_SCHEMA = {
    "type": "object",
    "properties": {
        **_MATRIX_INPUT_SCHEMA["properties"],
        "path": {
            "type": "string",
            "description": "Output file path for the XMI file.",
        },
        "sysml_version": {
            "type": "string",
            "enum": ["1.6", "1.7"],
            "description": "SysML namespace version to use (default '1.7').",
            "default": "1.7",
        },
    },
    "required": ["requirements", "path"],
}

sysml_export_xmi_spec = ToolSpec(
    name="sysml_export_xmi",
    description=(
        "Export a requirements-to-design-to-test traceability matrix to a "
        "SysML 1.x XMI file (OMG SysML 1.6 or 1.7 namespace URIs).\n"
        "\n"
        "Writes a standards-compatible XMI document containing:\n"
        "  - requirements::Requirement elements\n"
        "  - sysml::Block / Part / Connector design elements\n"
        "  - uml::TestCase elements\n"
        "  - sysml::Satisfy links (requirement ← design)\n"
        "  - sysml::Verify links (test → requirement)\n"
        "\n"
        "Uses xml.etree.ElementTree only — no external deps.\n"
        "Caveat: subset of OMG SysML 1.x XMI; not OMG-certified."
    ),
    input_schema=_EXPORT_SCHEMA,
)


async def run_sysml_export_xmi(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_plm.sysml import export_xmi
        path = params.get("path")
        if not path:
            return err_payload("'path' is required", "BAD_ARGS")

        matrix = _build_matrix(params)
        sysml_version = params.get("sysml_version", "1.7")
        export_xmi(matrix, path, sysml_version=sysml_version)
        return ok_payload({
            "ok": True,
            "path": path,
            "sysml_version": sysml_version,
            "n_requirements": len(matrix.requirements),
            "n_design_elements": len(matrix.design_elements),
            "n_test_cases": len(matrix.test_cases),
        })
    except Exception as exc:
        return err_payload(str(exc), "SYSML_EXPORT_ERROR")


# ---------------------------------------------------------------------------
# sysml_import_xmi
# ---------------------------------------------------------------------------

sysml_import_xmi_spec = ToolSpec(
    name="sysml_import_xmi",
    description=(
        "Import a SysML 1.x XMI file and return a traceability coverage report.\n"
        "\n"
        "Auto-detects SysML version (1.6 / 1.7) from namespace URIs.\n"
        "Returns the same coverage report as sysml_trace_coverage plus element counts.\n"
        "\n"
        "Caveat: parses the subset produced by sysml_export_xmi and compatible "
        "SysML 1.x tools; not OMG-certified."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to an existing SysML 1.x XMI file.",
            },
        },
        "required": ["path"],
    },
)


async def run_sysml_import_xmi(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_plm.sysml import import_xmi
        path = params.get("path")
        if not path:
            return err_payload("'path' is required", "BAD_ARGS")

        matrix = import_xmi(path)
        report = matrix.coverage_report()
        return ok_payload({
            "ok": True,
            "n_requirements": len(matrix.requirements),
            "n_design_elements": len(matrix.design_elements),
            "n_test_cases": len(matrix.test_cases),
            **report,
        })
    except ValueError as exc:
        return err_payload(str(exc), "SYSML_VERSION_ERROR")
    except Exception as exc:
        return err_payload(str(exc), "SYSML_IMPORT_ERROR")


# ---------------------------------------------------------------------------
# TOOLS list consumed by plugin
# ---------------------------------------------------------------------------

TOOLS = [
    ("sysml_trace_coverage", sysml_trace_coverage_spec, run_sysml_trace_coverage),
    ("sysml_export_xmi",     sysml_export_xmi_spec,     run_sysml_export_xmi),
    ("sysml_import_xmi",     sysml_import_xmi_spec,     run_sysml_import_xmi),
]
