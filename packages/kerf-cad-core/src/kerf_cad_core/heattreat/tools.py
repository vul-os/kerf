"""
kerf_cad_core.heattreat.tools — LLM tool wrappers for heat-treatment process engineering.

Registers tools with the Kerf tool registry:

  ht_grossmann_DI              — Grossmann ideal critical diameter from composition
  ht_jominy_hardness           — Jominy end-quench hardness & equivalent cooling rate
  ht_actual_critical_diameter  — actual critical diameter from DI and quench severity H
  ht_as_quenched_hardness      — as-quenched hardness from %C and %martensite
  ht_hollomon_jaffe             — Hollomon-Jaffe tempering parameter & tempered hardness
  ht_carburizing_case_depth    — carburizing case depth (Harris + erfc)
  ht_nitriding_case_depth      — nitriding white-layer + diffusion zone depth
  ht_induction_case_depth      — induction hardening skin/case depth
  ht_austenitizing_temperature — recommended austenitizing temperature range
  ht_andrews_Ac1               — Andrews Ac1 lower critical temperature
  ht_andrews_Ac3               — Andrews Ac3 upper critical temperature
  ht_martensite_start_Ms       — Andrews Ms martensite-start temperature
  ht_martensite_finish_Mf      — Mf martensite-finish estimate
  ht_koistinen_marburger       — Koistinen-Marburger martensite fraction
  ht_retained_austenite        — retained austenite after quench
  ht_annealing_temperature     — full-anneal / process-anneal temperature guidance
  ht_normalizing_temperature   — normalizing temperature guidance
  ht_stress_relief_temperature — stress-relief temperature guidance by steel family
  ht_hardness_convert          — hardness conversions HRC↔HB↔HV↔HRB↔UTS

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Grossmann M.A. (1942) — Trans. AIME 150, 227-259
Andrews K.W. (1965) — JISI 203, 721-727
Koistinen D.P., Marburger R.E. (1959) — Acta Metall. 7, 59-60
Hollomon J.H., Jaffe L.D. (1945) — Trans. AIME 162, 223-249
ASM Handbook Vol. 4 — Heat Treating (1991)

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.heattreat.process import (
    grossmann_DI,
    jominy_hardness,
    actual_critical_diameter,
    as_quenched_hardness,
    hollomon_jaffe,
    carburizing_case_depth,
    nitriding_case_depth,
    induction_case_depth,
    austenitizing_temperature,
    andrews_Ac1,
    andrews_Ac3,
    martensite_start_Ms,
    martensite_finish_Mf,
    koistinen_marburger,
    retained_austenite,
    annealing_temperature,
    normalizing_temperature,
    stress_relief_temperature,
    hardness_convert,
)


# ---------------------------------------------------------------------------
# Tool: ht_grossmann_DI
# ---------------------------------------------------------------------------

_grossmann_DI_spec = ToolSpec(
    name="ht_grossmann_DI",
    description=(
        "Compute the Grossmann ideal critical diameter DI from steel composition "
        "and ASTM grain size.\n"
        "\n"
        "DI = DI0(C, grain_size) × fMn × fSi × fCr × fNi × fMo × fCu × fV\n"
        "\n"
        "DI is the bar diameter that will achieve 50% martensite at the centre "
        "when quenched in an ideal (infinite-severity) quench.  All composition "
        "inputs in weight percent.\n"
        "\n"
        "Flags low-hardenability and out-of-range grain size in warnings. "
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C":   {"type": "number", "description": "Carbon (wt%). Required. ~0.05–1.10."},
            "Mn":  {"type": "number", "description": "Manganese (wt%). Default 0."},
            "Si":  {"type": "number", "description": "Silicon (wt%). Default 0."},
            "Cr":  {"type": "number", "description": "Chromium (wt%). Default 0."},
            "Ni":  {"type": "number", "description": "Nickel (wt%). Default 0."},
            "Mo":  {"type": "number", "description": "Molybdenum (wt%). Default 0."},
            "Cu":  {"type": "number", "description": "Copper (wt%). Default 0."},
            "V":   {"type": "number", "description": "Vanadium (wt%). Default 0."},
            "grain_size_ASTM": {
                "type": "number",
                "description": "ASTM grain size number (3–12). Default 7.",
            },
        },
        "required": ["C"],
    },
)


@register(_grossmann_DI_spec, write=False)
async def run_ht_grossmann_DI(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("C") is None:
        return json.dumps({"ok": False, "reason": "C is required"})

    kwargs: dict = {}
    for key in ("Mn", "Si", "Cr", "Ni", "Mo", "Cu", "V", "grain_size_ASTM"):
        if key in a:
            kwargs[key] = a[key]

    result = grossmann_DI(a["C"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_jominy_hardness
# ---------------------------------------------------------------------------

_jominy_hardness_spec = ToolSpec(
    name="ht_jominy_hardness",
    description=(
        "Estimate as-quenched Jominy end-quench hardness (HRC) at a given "
        "distance from the quenched end, and return the equivalent cooling rate.\n"
        "\n"
        "Based on a simplified exponential-decay model calibrated to plain carbon "
        "steels.  For alloy steels, actual hardenability will be higher; use "
        "ht_grossmann_DI to assess hardenability depth.\n"
        "\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C": {
                "type": "number",
                "description": "Carbon content (wt%). Valid ~0.05–1.0.",
            },
            "jominy_dist_mm": {
                "type": "number",
                "description": "Distance from quenched end (mm). Must be > 0.",
            },
        },
        "required": ["C", "jominy_dist_mm"],
    },
)


@register(_jominy_hardness_spec, write=False)
async def run_ht_jominy_hardness(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("C", "jominy_dist_mm"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = jominy_hardness(a["C"], a["jominy_dist_mm"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_actual_critical_diameter
# ---------------------------------------------------------------------------

_actual_critical_diameter_spec = ToolSpec(
    name="ht_actual_critical_diameter",
    description=(
        "Compute the actual critical diameter D_act from the ideal critical "
        "diameter DI and Grossmann quench severity H.\n"
        "\n"
        "D_act is the largest bar diameter that will achieve 50% martensite at "
        "its centre under the specified quench.\n"
        "\n"
        "Typical H values:\n"
        "  0.2 — still air\n"
        "  0.35 — poor oil agitation\n"
        "  0.5 — moderate oil\n"
        "  1.0 — good oil (vigorous)\n"
        "  1.5 — water, no agitation\n"
        "  2.0 — water, vigorous agitation\n"
        "  5.0 — brine, vigorous agitation\n"
        "\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "DI_mm": {
                "type": "number",
                "description": "Ideal critical diameter (mm). Must be > 0.",
            },
            "H": {
                "type": "number",
                "description": (
                    "Grossmann quench severity (in⁻¹ equivalent). Must be > 0. "
                    "Typical range 0.2 (still air) – 5.0 (brine)."
                ),
            },
        },
        "required": ["DI_mm", "H"],
    },
)


@register(_actual_critical_diameter_spec, write=False)
async def run_ht_actual_critical_diameter(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("DI_mm", "H"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = actual_critical_diameter(a["DI_mm"], a["H"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_as_quenched_hardness
# ---------------------------------------------------------------------------

_as_quenched_hardness_spec = ToolSpec(
    name="ht_as_quenched_hardness",
    description=(
        "Estimate as-quenched hardness from carbon content and martensite "
        "percentage, using the Hodge-Orehoski model.\n"
        "\n"
        "HRC = f_M × HRC_100M + (1 − f_M) × HRC_0M\n"
        "\n"
        "where HRC_100M is the 100%-martensite hardness (function of C) and "
        "HRC_0M is the reference pearlite/bainite hardness.\n"
        "\n"
        "Flags insufficient martensite fraction in warnings.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C_wt_pct": {
                "type": "number",
                "description": "Carbon content (wt%). Must be > 0.",
            },
            "martensite_pct": {
                "type": "number",
                "description": "Martensite percentage (0–100). Must be >= 0.",
            },
        },
        "required": ["C_wt_pct", "martensite_pct"],
    },
)


@register(_as_quenched_hardness_spec, write=False)
async def run_ht_as_quenched_hardness(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("C_wt_pct", "martensite_pct"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = as_quenched_hardness(a["C_wt_pct"], a["martensite_pct"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_hollomon_jaffe
# ---------------------------------------------------------------------------

_hollomon_jaffe_spec = ToolSpec(
    name="ht_hollomon_jaffe",
    description=(
        "Compute the Hollomon-Jaffe tempering parameter P and estimate the "
        "resulting tempered hardness (HRC).\n"
        "\n"
        "P = T_K × (C_HJ + log₁₀(t))   [T in Kelvin, t in hours]\n"
        "\n"
        "Tempered hardness is estimated via an empirical softening model "
        "calibrated to medium-carbon alloy steels.\n"
        "\n"
        "Flags over-temper risk and temperature-range warnings.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C_wt_pct": {
                "type": "number",
                "description": (
                    "Carbon content (wt%). Used to estimate as-quenched HRC "
                    "if HRC_as_quenched not provided."
                ),
            },
            "T_C": {
                "type": "number",
                "description": "Tempering temperature (°C). Must be > 0.",
            },
            "t_hours": {
                "type": "number",
                "description": "Tempering time (hours). Must be > 0.",
            },
            "HRC_as_quenched": {
                "type": "number",
                "description": "Measured as-quenched hardness (HRC). Optional.",
            },
            "C_HJ": {
                "type": "number",
                "description": "Hollomon-Jaffe constant (default 20).",
            },
        },
        "required": ["C_wt_pct", "T_C", "t_hours"],
    },
)


@register(_hollomon_jaffe_spec, write=False)
async def run_ht_hollomon_jaffe(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("C_wt_pct", "T_C", "t_hours"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "HRC_as_quenched" in a:
        kwargs["HRC_as_quenched"] = a["HRC_as_quenched"]
    if "C_HJ" in a:
        kwargs["C_HJ"] = a["C_HJ"]

    result = hollomon_jaffe(a["C_wt_pct"], a["T_C"], a["t_hours"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_carburizing_case_depth
# ---------------------------------------------------------------------------

_carburizing_case_depth_spec = ToolSpec(
    name="ht_carburizing_case_depth",
    description=(
        "Compute carburizing case depth using the Harris formula and the "
        "complementary-error-function (erfc) diffusion solution.\n"
        "\n"
        "Harris:  x = k × √(D(T) × t)   [mm]\n"
        "D(T)  = D0 × exp(−Q / (R × T))  [cm²/s, Arrhenius]\n"
        "\n"
        "Returns both the simplified Harris depth and the erfc-based depth "
        "to the target carbon concentration.\n"
        "\n"
        "Flags decarb risk above 1050 °C and deep-case warnings.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T_C": {
                "type": "number",
                "description": "Carburizing temperature (°C). Typical 850–1050 °C.",
            },
            "t_hours": {
                "type": "number",
                "description": "Carburizing time (hours). Must be > 0.",
            },
            "initial_C": {
                "type": "number",
                "description": "Core (initial) carbon content (wt%). Default 0.20.",
            },
            "surface_C": {
                "type": "number",
                "description": "Surface carbon activity (wt%). Default 0.85.",
            },
            "target_C": {
                "type": "number",
                "description": "Target carbon at case-depth boundary (wt%). Default 0.35.",
            },
            "k": {
                "type": "number",
                "description": "Harris case factor (dimensionless). Default 1.0.",
            },
        },
        "required": ["T_C", "t_hours"],
    },
)


@register(_carburizing_case_depth_spec, write=False)
async def run_ht_carburizing_case_depth(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T_C", "t_hours"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for key in ("initial_C", "surface_C", "target_C", "k"):
        if key in a:
            kwargs[key] = a[key]

    result = carburizing_case_depth(a["T_C"], a["t_hours"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_nitriding_case_depth
# ---------------------------------------------------------------------------

_nitriding_case_depth_spec = ToolSpec(
    name="ht_nitriding_case_depth",
    description=(
        "Estimate nitriding white-layer (compound layer) and diffusion-zone "
        "depth for gas nitriding.\n"
        "\n"
        "Uses Arrhenius diffusivity for N in α-Fe.\n"
        "Typical nitriding: 480–570 °C for 10–100 hours.\n"
        "\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T_C": {
                "type": "number",
                "description": "Nitriding temperature (°C). Typical 480–570 °C.",
            },
            "t_hours": {
                "type": "number",
                "description": "Nitriding time (hours). Must be > 0.",
            },
        },
        "required": ["T_C", "t_hours"],
    },
)


@register(_nitriding_case_depth_spec, write=False)
async def run_ht_nitriding_case_depth(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T_C", "t_hours"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = nitriding_case_depth(a["T_C"], a["t_hours"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_induction_case_depth
# ---------------------------------------------------------------------------

_induction_case_depth_spec = ToolSpec(
    name="ht_induction_case_depth",
    description=(
        "Estimate induction hardening case depth from the electromagnetic skin "
        "depth formula.\n"
        "\n"
        "δ = √(ρ / (π × f × μ₀ × μᵣ))   [skin depth, m]\n"
        "case_depth ≈ 1.5 × δ             [empirical, ASM HB Vol. 4]\n"
        "\n"
        "High frequency (>500 kHz) → shallow case (gear teeth, small pins).\n"
        "Low frequency (<10 kHz)   → deep case (crankshafts, large shafts).\n"
        "\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_Hz": {
                "type": "number",
                "description": "Induction frequency (Hz). Must be > 0.",
            },
            "t_s": {
                "type": "number",
                "description": "Heating time (s). Must be > 0.",
            },
            "rho": {
                "type": "number",
                "description": (
                    "Electrical resistivity (Ω·m). Default 1.1e-6 "
                    "(steel at ~800 °C)."
                ),
            },
            "mu_r": {
                "type": "number",
                "description": (
                    "Relative magnetic permeability. Default 1.0 "
                    "(above Curie point ~768 °C)."
                ),
            },
        },
        "required": ["freq_Hz", "t_s"],
    },
)


@register(_induction_case_depth_spec, write=False)
async def run_ht_induction_case_depth(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("freq_Hz", "t_s"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for key in ("rho", "mu_r"):
        if key in a:
            kwargs[key] = a[key]

    result = induction_case_depth(a["freq_Hz"], a["t_s"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_austenitizing_temperature
# ---------------------------------------------------------------------------

_austenitizing_temperature_spec = ToolSpec(
    name="ht_austenitizing_temperature",
    description=(
        "Recommend an austenitizing temperature range for quench hardening.\n"
        "\n"
        "Hypoeutectoid steel (C < 0.77 wt%): Ac3 + 50–80 °C.\n"
        "Hypereutectoid steel (C > 0.77 wt%): Ac1 + 30–60 °C.\n"
        "\n"
        "Uses Andrews (1965) approximate Ac1/Ac3 for a baseline plain-carbon "
        "composition.  For precise Ac values use ht_andrews_Ac1/ht_andrews_Ac3.\n"
        "\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C_wt_pct": {
                "type": "number",
                "description": "Carbon content (wt%). Must be > 0.",
            },
        },
        "required": ["C_wt_pct"],
    },
)


@register(_austenitizing_temperature_spec, write=False)
async def run_ht_austenitizing_temperature(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("C_wt_pct") is None:
        return json.dumps({"ok": False, "reason": "C_wt_pct is required"})

    result = austenitizing_temperature(a["C_wt_pct"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_andrews_Ac1
# ---------------------------------------------------------------------------

_andrews_Ac1_spec = ToolSpec(
    name="ht_andrews_Ac1",
    description=(
        "Andrews (1965) empirical Ac1 lower critical temperature (°C).\n"
        "\n"
        "Ac1 = 723 − 16.9·Ni + 29.1·Si − 10.7·Mn + 16.9·Cr + 6.38·W\n"
        "\n"
        "All composition inputs in wt%; all default to 0.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C":  {"type": "number", "description": "Carbon (wt%). Default 0."},
            "Si": {"type": "number", "description": "Silicon (wt%). Default 0."},
            "Mn": {"type": "number", "description": "Manganese (wt%). Default 0."},
            "Cr": {"type": "number", "description": "Chromium (wt%). Default 0."},
            "Ni": {"type": "number", "description": "Nickel (wt%). Default 0."},
            "Mo": {"type": "number", "description": "Molybdenum (wt%). Default 0."},
            "V":  {"type": "number", "description": "Vanadium (wt%). Default 0."},
            "W":  {"type": "number", "description": "Tungsten (wt%). Default 0."},
            "Cu": {"type": "number", "description": "Copper (wt%). Default 0."},
            "Co": {"type": "number", "description": "Cobalt (wt%). Default 0."},
        },
        "required": [],
    },
)


@register(_andrews_Ac1_spec, write=False)
async def run_ht_andrews_Ac1(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    kwargs: dict = {}
    for key in ("C", "Si", "Mn", "Cr", "Ni", "Mo", "V", "W", "Cu", "Co"):
        if key in a:
            kwargs[key] = a[key]

    result = andrews_Ac1(**kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_andrews_Ac3
# ---------------------------------------------------------------------------

_andrews_Ac3_spec = ToolSpec(
    name="ht_andrews_Ac3",
    description=(
        "Andrews (1965) empirical Ac3 upper critical temperature (°C).\n"
        "\n"
        "Ac3 = 910 − 203√C − 15.2·Ni + 44.7·Si + 104·V + 31.5·Mo\n"
        "          − 30·Mn − 11·Cr − 20·Cu\n"
        "\n"
        "All composition inputs in wt%; C defaults to 0.20.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C":  {"type": "number", "description": "Carbon (wt%). Default 0.20."},
            "Si": {"type": "number", "description": "Silicon (wt%). Default 0."},
            "Mn": {"type": "number", "description": "Manganese (wt%). Default 0."},
            "Cr": {"type": "number", "description": "Chromium (wt%). Default 0."},
            "Ni": {"type": "number", "description": "Nickel (wt%). Default 0."},
            "Mo": {"type": "number", "description": "Molybdenum (wt%). Default 0."},
            "V":  {"type": "number", "description": "Vanadium (wt%). Default 0."},
            "W":  {"type": "number", "description": "Tungsten (wt%). Default 0."},
            "Cu": {"type": "number", "description": "Copper (wt%). Default 0."},
            "Co": {"type": "number", "description": "Cobalt (wt%). Default 0."},
        },
        "required": [],
    },
)


@register(_andrews_Ac3_spec, write=False)
async def run_ht_andrews_Ac3(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    kwargs: dict = {}
    for key in ("C", "Si", "Mn", "Cr", "Ni", "Mo", "V", "W", "Cu", "Co"):
        if key in a:
            kwargs[key] = a[key]

    result = andrews_Ac3(**kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_martensite_start_Ms
# ---------------------------------------------------------------------------

_martensite_start_Ms_spec = ToolSpec(
    name="ht_martensite_start_Ms",
    description=(
        "Andrews (1965) martensite-start temperature Ms (°C).\n"
        "\n"
        "Ms = 539 − 423·C − 30.4·Mn − 17.7·Ni − 12.1·Cr − 7.5·Mo\n"
        "         + 10·Co − 7.5·Si\n"
        "\n"
        "All composition inputs in wt%; C defaults to 0.20.  "
        "Flags sub-zero Ms for cryogenic treatment warning.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C":  {"type": "number", "description": "Carbon (wt%). Default 0.20."},
            "Mn": {"type": "number", "description": "Manganese (wt%). Default 0."},
            "Cr": {"type": "number", "description": "Chromium (wt%). Default 0."},
            "Ni": {"type": "number", "description": "Nickel (wt%). Default 0."},
            "Mo": {"type": "number", "description": "Molybdenum (wt%). Default 0."},
            "Si": {"type": "number", "description": "Silicon (wt%). Default 0."},
            "V":  {"type": "number", "description": "Vanadium (wt%). Default 0."},
            "W":  {"type": "number", "description": "Tungsten (wt%). Default 0."},
            "Co": {"type": "number", "description": "Cobalt (wt%). Default 0."},
        },
        "required": [],
    },
)


@register(_martensite_start_Ms_spec, write=False)
async def run_ht_martensite_start_Ms(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    kwargs: dict = {}
    for key in ("C", "Mn", "Cr", "Ni", "Mo", "Si", "V", "W", "Co"):
        if key in a:
            kwargs[key] = a[key]

    result = martensite_start_Ms(**kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_martensite_finish_Mf
# ---------------------------------------------------------------------------

_martensite_finish_Mf_spec = ToolSpec(
    name="ht_martensite_finish_Mf",
    description=(
        "Estimate martensite-finish temperature Mf.\n"
        "\n"
        "Mf ≈ Ms − 215 °C   (Payson & Savage, 1944)\n"
        "\n"
        "Flags sub-zero Mf requiring cryogenic treatment.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Ms_C": {
                "type": "number",
                "description": "Martensite-start temperature (°C).",
            },
        },
        "required": ["Ms_C"],
    },
)


@register(_martensite_finish_Mf_spec, write=False)
async def run_ht_martensite_finish_Mf(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("Ms_C") is None:
        return json.dumps({"ok": False, "reason": "Ms_C is required"})

    result = martensite_finish_Mf(a["Ms_C"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_koistinen_marburger
# ---------------------------------------------------------------------------

_koistinen_marburger_spec = ToolSpec(
    name="ht_koistinen_marburger",
    description=(
        "Koistinen-Marburger martensite volume fraction at quench temperature T.\n"
        "\n"
        "f_M = 1 − exp(−0.011 × (Ms − T))   for T < Ms\n"
        "f_M = 0                              for T ≥ Ms\n"
        "\n"
        "Used to predict how much martensite forms when quenching to a given "
        "temperature.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T_C": {
                "type": "number",
                "description": "Quench temperature (°C). Room temperature ≈ 25 °C.",
            },
            "Ms_C": {
                "type": "number",
                "description": "Martensite-start temperature (°C).",
            },
        },
        "required": ["T_C", "Ms_C"],
    },
)


@register(_koistinen_marburger_spec, write=False)
async def run_ht_koistinen_marburger(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T_C", "Ms_C"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = koistinen_marburger(a["T_C"], a["Ms_C"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_retained_austenite
# ---------------------------------------------------------------------------

_retained_austenite_spec = ToolSpec(
    name="ht_retained_austenite",
    description=(
        "Estimate retained austenite fraction after quenching to T_quench_C.\n"
        "\n"
        "RA = 1 − f_M = exp(−0.011 × (Ms − T_quench))   (Koistinen-Marburger)\n"
        "\n"
        "Flags high retained austenite (> 15%) with sub-zero treatment "
        "recommendation.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T_quench_C": {
                "type": "number",
                "description": "Final quench temperature (°C). Room temp ≈ 25 °C.",
            },
            "Ms_C": {
                "type": "number",
                "description": "Martensite-start temperature (°C).",
            },
        },
        "required": ["T_quench_C", "Ms_C"],
    },
)


@register(_retained_austenite_spec, write=False)
async def run_ht_retained_austenite(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T_quench_C", "Ms_C"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = retained_austenite(a["T_quench_C"], a["Ms_C"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_annealing_temperature
# ---------------------------------------------------------------------------

_annealing_temperature_spec = ToolSpec(
    name="ht_annealing_temperature",
    description=(
        "Recommended full-anneal and process-anneal temperature ranges for steel.\n"
        "\n"
        "Full anneal: above Ac3 (hypoeutectoid) or just above Ac1 "
        "(hypereutectoid spheroidizing).\n"
        "Process anneal: 540–700 °C (below Ac1).\n"
        "\n"
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C_wt_pct": {
                "type": "number",
                "description": "Carbon content (wt%). Must be > 0.",
            },
        },
        "required": ["C_wt_pct"],
    },
)


@register(_annealing_temperature_spec, write=False)
async def run_ht_annealing_temperature(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("C_wt_pct") is None:
        return json.dumps({"ok": False, "reason": "C_wt_pct is required"})

    result = annealing_temperature(a["C_wt_pct"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_normalizing_temperature
# ---------------------------------------------------------------------------

_normalizing_temperature_spec = ToolSpec(
    name="ht_normalizing_temperature",
    description=(
        "Recommended normalizing temperature range for steel.\n"
        "\n"
        "Normalizing: Ac3 + 50–100 °C.  Air cool after soaking.\n"
        "\n"
        "Flags hypereutectoid compositions where annealing is preferred.  "
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C_wt_pct": {
                "type": "number",
                "description": "Carbon content (wt%). Must be > 0.",
            },
        },
        "required": ["C_wt_pct"],
    },
)


@register(_normalizing_temperature_spec, write=False)
async def run_ht_normalizing_temperature(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("C_wt_pct") is None:
        return json.dumps({"ok": False, "reason": "C_wt_pct is required"})

    result = normalizing_temperature(a["C_wt_pct"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_stress_relief_temperature
# ---------------------------------------------------------------------------

_stress_relief_temperature_spec = ToolSpec(
    name="ht_stress_relief_temperature",
    description=(
        "Recommended stress-relief temperature range for common steel families.\n"
        "\n"
        "Supported steel types:\n"
        "  plain_carbon, low_alloy, tool_steel, stainless_304, stainless_316,\n"
        "  stainless_martensitic, maraging, cast_iron, spring_steel.\n"
        "\n"
        "Flags sensitization risk for austenitic stainless.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "steel_type": {
                "type": "string",
                "enum": [
                    "plain_carbon", "low_alloy", "tool_steel",
                    "stainless_304", "stainless_316", "stainless_martensitic",
                    "maraging", "cast_iron", "spring_steel",
                ],
                "description": "Steel family. Default 'plain_carbon'.",
            },
        },
        "required": [],
    },
)


@register(_stress_relief_temperature_spec, write=False)
async def run_ht_stress_relief_temperature(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    steel_type = a.get("steel_type", "plain_carbon")
    result = stress_relief_temperature(steel_type)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: ht_hardness_convert
# ---------------------------------------------------------------------------

_hardness_convert_spec = ToolSpec(
    name="ht_hardness_convert",
    description=(
        "Approximate hardness conversions between HRC, HB, HV, HRB, and "
        "approximate UTS (MPa).\n"
        "\n"
        "Uses ASTM E140 polynomial fits. ±3–5% accuracy typical.\n"
        "NOT a substitute for direct ASTM E140 table lookup.\n"
        "\n"
        "Flags out-of-range inputs and scale limitations in warnings.  "
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "value": {
                "type": "number",
                "description": "Input hardness value (positive). Must be > 0.",
            },
            "from_scale": {
                "type": "string",
                "enum": ["HRC", "HB", "HV", "HRB", "UTS"],
                "description": "Source hardness scale.",
            },
        },
        "required": ["value", "from_scale"],
    },
)


@register(_hardness_convert_spec, write=False)
async def run_ht_hardness_convert(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("value") is None:
        return json.dumps({"ok": False, "reason": "value is required"})
    if a.get("from_scale") is None:
        return json.dumps({"ok": False, "reason": "from_scale is required"})

    result = hardness_convert(a["value"], a["from_scale"])
    return ok_payload(result)
