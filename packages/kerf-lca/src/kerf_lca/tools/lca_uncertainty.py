"""
LLM tool: lca_uncertainty

ISO 14044 §4.3.3 / §4.5 — lognormal Monte Carlo uncertainty propagation
for LCA impact values.

Exposes two tools:

1. lca_impact_uncertainty_bounds
   Quick ±90% CI for a single pre-computed impact value, given its category
   (gwp100 | ap | ep | htp | water | pm25).  Uses GSD² from the Ecoinvent
   pedigree matrix (Weidema et al., 2013).

2. lca_monte_carlo_uncertainty
   Full Monte Carlo (N=10 000) propagation across multiple uncertain parameters.
   Model function is defined symbolically (product of factor × mass for each
   input).
"""

from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_lca._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx

from kerf_lca.uncertainty import impact_uncertainty_bounds, monte_carlo_uncertainty

# ---------------------------------------------------------------------------
# Tool 1: lca_impact_uncertainty_bounds
# ---------------------------------------------------------------------------

lca_impact_uncertainty_bounds_spec = ToolSpec(
    name="lca_impact_uncertainty_bounds",
    description=(
        "Compute a ±90% lognormal confidence interval for a single LCA impact value "
        "given the impact category. Uses GSD² (geometric standard deviation squared) "
        "from the Ecoinvent pedigree matrix (Weidema et al., 2013) per ISO 14044 §4.5. "
        "GSD² values: gwp100=1.05, ap=1.20, ep=1.25, htp=2.00, water=1.50, pm25=1.30. "
        "Returns {mean, ci_low, ci_high, gsd2} — all in the same units as impact_value. "
        "Reference: ISO 14044:2006 §4.3.3 (uncertainty analysis)."
    ),
    input_schema={
        "type": "object",
        "required": ["impact_value", "category"],
        "properties": {
            "impact_value": {
                "type": "number",
                "description": "Central estimate of the impact (e.g. kg CO₂-eq, kg SO₂-eq).",
            },
            "category": {
                "type": "string",
                "enum": ["gwp100", "ap", "ep", "htp", "water", "pm25"],
                "description": (
                    "Impact category key: gwp100 (GWP100, kg CO₂-eq), "
                    "ap (Acidification, kg SO₂-eq), ep (Eutrophication, kg PO₄-eq), "
                    "htp (Human Toxicity, CTUh), water (m³), pm25 (kg PM2.5-eq)."
                ),
            },
        },
    },
)


@register(lca_impact_uncertainty_bounds_spec)
async def run_lca_impact_uncertainty_bounds(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args) if args else {}
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    impact_value = a.get("impact_value")
    if impact_value is None:
        return err_payload("'impact_value' is required", "BAD_ARGS")
    try:
        impact_value = float(impact_value)
    except (TypeError, ValueError):
        return err_payload("'impact_value' must be a number", "BAD_ARGS")

    category = a.get("category", "").strip()
    if not category:
        return err_payload("'category' is required", "BAD_ARGS")

    try:
        result = impact_uncertainty_bounds(impact_value, category)
    except Exception as e:
        return err_payload(str(e), "CALC_ERROR")

    result["category"] = category
    result["ci_level"] = 0.90
    result["method"] = "ISO 14044 §4.5 lognormal; GSD² from Ecoinvent pedigree matrix"
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool 2: lca_monte_carlo_uncertainty
# ---------------------------------------------------------------------------

lca_monte_carlo_uncertainty_spec = ToolSpec(
    name="lca_monte_carlo_uncertainty",
    description=(
        "Propagate LCA parameter uncertainty through a simple multiplicative model "
        "using Monte Carlo simulation (ISO 14044 §4.3.3). Each parameter is treated "
        "as lognormal(mean, GSD²). The model computes sum(factor_i × mass_i) across "
        "all parameters, representing total impact from a multi-material BOM. "
        "Returns {mean, median, std, ci_low, ci_high, n_samples, ci_level}. "
        "Default N=10,000 samples, 90% CI. Reproducible via seed=42."
    ),
    input_schema={
        "type": "object",
        "required": ["parameters"],
        "properties": {
            "parameters": {
                "type": "array",
                "description": (
                    "List of uncertain parameters, each with: "
                    "name (str), mean (float), gsd2 (float ≥ 1.0, default 1.05 for GWP)."
                ),
                "items": {
                    "type": "object",
                    "required": ["name", "mean"],
                    "properties": {
                        "name": {"type": "string"},
                        "mean": {"type": "number"},
                        "gsd2": {"type": "number", "description": "GSD² ≥ 1.0. Default 1.05."},
                    },
                },
            },
            "n_samples": {
                "type": "integer",
                "description": "Number of Monte Carlo samples (default 10000, max 100000).",
            },
            "ci_level": {
                "type": "number",
                "description": "Confidence interval level, e.g. 0.90 for 90% CI (default 0.90).",
            },
            "seed": {
                "type": "integer",
                "description": "RNG seed for reproducibility (default 42).",
            },
        },
    },
)


@register(lca_monte_carlo_uncertainty_spec)
async def run_lca_monte_carlo_uncertainty(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args) if args else {}
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    parameters = a.get("parameters")
    if not isinstance(parameters, list) or len(parameters) == 0:
        return err_payload("'parameters' must be a non-empty array", "BAD_ARGS")

    n_samples = min(int(a.get("n_samples") or 10_000), 100_000)
    ci_level = float(a.get("ci_level") or 0.90)
    seed = int(a.get("seed") or 42)

    # Build distributions dict
    distributions: dict[str, dict] = {}
    for p in parameters:
        name = p.get("name", "")
        if not name:
            return err_payload("each parameter must have a 'name'", "BAD_ARGS")
        mean = float(p.get("mean") or 0.0)
        gsd2 = float(p.get("gsd2") or 1.05)
        distributions[name] = {"mean": mean, "gsd2": gsd2}

    # Simple additive model: total = sum of all params (each param = factor*mass already)
    def _additive_model(**kwargs):
        return sum(kwargs.values())

    try:
        result = monte_carlo_uncertainty(
            _additive_model,
            distributions,
            n_samples=n_samples,
            seed=seed,
            ci_level=ci_level,
        )
    except Exception as e:
        return err_payload(str(e), "CALC_ERROR")

    result["method"] = "ISO 14044 §4.3.3 Monte Carlo; lognormal distributions"
    result["parameters_used"] = list(distributions.keys())
    return ok_payload(result)
