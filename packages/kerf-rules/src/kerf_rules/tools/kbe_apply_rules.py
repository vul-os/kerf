"""
kerf_rules.tools.kbe_apply_rules — LLM tool: run the KBE rule engine.

Exposes ``kbe_apply_rules(params, domains?)`` as a registered LLM tool.

Function signature
------------------
kbe_apply_rules(params, domains=None) -> dict

Args:
    params  : dict — engineering parameters (span_m, udl_kN_m2, bearing_load_N, …)
    domains : list[str] | None — restrict to specific domains
              ("structural", "mechanical", "electrical", "plumbing")

Returns:
    {
        "ok":                bool,
        "derived":           dict,     # all values derived by fired rules
        "fired":             list[str],# rule IDs that triggered
        "conflicts_resolved": int,
        "domains_covered":   list[str],# unique domains of fired rules
    }

Example
-------
params = {
    "span_m": 10.0,
    "udl_kN_m2": 8.0,
    "trib_m": 1.5,
}
→ {"section": "W21X68", "Mu_kip_ft": 124.5, "phi_Mn_kip_ft": 160.0, ...}

LLM tool schema (Anthropic tool_use format)
-------------------------------------------
{
  "name": "kbe_apply_rules",
  "description": "Run the Kerf KBE rule engine on engineering parameters ...",
  "input_schema": { ... }
}

Author: imranparuk
"""

from __future__ import annotations

import json
from typing import Any


# ---------------------------------------------------------------------------
# Core function (sync)
# ---------------------------------------------------------------------------

def kbe_apply_rules(
    params: dict[str, Any],
    domains: list[str] | None = None,
) -> dict[str, Any]:
    """
    Apply the KBE starter-pack rules to a set of engineering parameters.

    This is the primary LLM tool entry point for knowledge-based parametric
    design selection (beam sizing, bearing selection, wire gauges, etc.).

    Args:
        params  : Engineering parameters dict.
        domains : Optional list restricting which rule domains to activate.

    Returns:
        Structured result dict — see module docstring.
    """
    from kerf_rules.kbe import apply_rules

    result = apply_rules(params, domains=domains)

    # Collect unique domains of fired rules
    from kerf_rules.kbe import KBELibrary
    lib = KBELibrary.default()
    fired_domains = list({
        lib.get(rid).domain
        for rid in result.fired
        if lib.get(rid) is not None
    })

    return {
        "ok":                 True,
        "derived":            result.derived,
        "fired":              result.fired,
        "conflicts_resolved": result.conflicts_resolved,
        "domains_covered":    fired_domains,
    }


# ---------------------------------------------------------------------------
# Anthropic tool schema
# ---------------------------------------------------------------------------

TOOL_SCHEMA: dict[str, Any] = {
    "name": "kbe_apply_rules",
    "description": (
        "Run the Kerf Knowledge-Based Engineering (KBE) rule engine on a set of "
        "engineering parameters.  Drives parametric design selection — e.g. "
        "'what AISC W-shape for a 10m span carrying 8 kN/m²?' or "
        "'what bearing C rating satisfies 20 000 h life at 1500 rpm, 10 kN?'. "
        "Returns derived design values with citations to AISC/ACI/ASCE/ISO/NEC/IPC "
        "standards.  Supported domains: structural, mechanical, electrical, plumbing."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "params": {
                "type": "object",
                "description": (
                    "Engineering parameters dict.  Common keys by domain:\n"
                    "  structural:  span_m, udl_kN_m2, trib_m, Mu_kip_ft, "
                    "beam_b_in, beam_h_in, fc_psi, fy_psi, "
                    "wind_speed_mph, exposure_category, mean_roof_height_ft\n"
                    "  mechanical:  bearing_load_N, bearing_speed_rpm, "
                    "bearing_L10h_target, bearing_type (ball|roller), "
                    "shaft_M_Nm, shaft_T_Nm, shaft_Se_Pa, shaft_Kf, "
                    "shaft_Kfs, shaft_safety_factor\n"
                    "  electrical:  load_current_A, continuous_load (bool), "
                    "load_kW, power_factor, transformer_margin\n"
                    "  plumbing:    drainage_fixture_units, flow_rate_m3s, "
                    "pipe_length_m, pipe_diameter_m, static_head_m, "
                    "fitting_K_sum, pipe_roughness_m"
                ),
            },
            "domains": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["structural", "mechanical", "electrical", "plumbing"],
                },
                "description": (
                    "Optional list of domains to activate.  If omitted all "
                    "domains are active.  Use to scope the engine to a single "
                    "discipline when parameters overlap."
                ),
            },
        },
        "required": ["params"],
    },
}


# ---------------------------------------------------------------------------
# ToolSpec + async handler for ctx.tools.register
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx  # noqa: F401

    kbe_apply_rules_spec = ToolSpec(
        name="kbe_apply_rules",
        description=TOOL_SCHEMA["description"],
        input_schema=TOOL_SCHEMA["input_schema"],
    )

    async def run_kbe_apply_rules(ctx: "ProjectCtx", args: bytes) -> str:
        """Async handler: parse args JSON, delegate to kbe_apply_rules()."""
        try:
            a = json.loads(args) if args else {}
        except Exception as e:
            return err_payload(f"invalid args JSON: {e}", "BAD_ARGS")

        params = a.get("params")
        if not isinstance(params, dict):
            return err_payload("'params' must be a JSON object", "BAD_ARGS")

        domains = a.get("domains")
        if domains is not None:
            if not isinstance(domains, list):
                return err_payload("'domains' must be a list of strings", "BAD_ARGS")
            valid = {"structural", "mechanical", "electrical", "plumbing"}
            bad = [d for d in domains if d not in valid]
            if bad:
                return err_payload(
                    f"Unknown domains: {bad}. Valid: {sorted(valid)}", "BAD_ARGS"
                )

        try:
            result = kbe_apply_rules(params, domains=domains or None)
        except Exception as exc:
            return err_payload(str(exc), "KBE_ERROR")

        return ok_payload(result)

    TOOLS = [
        (kbe_apply_rules_spec.name, kbe_apply_rules_spec, run_kbe_apply_rules),
    ]

except ImportError:
    TOOLS = []
