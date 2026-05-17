"""
BOM cost / sourcing rollup + DFM report tools for CircuitJSON boards.

LLM tools registered
─────────────────────
  bom_cost_rollup    — Extended cost from BOM line items + board/assembly qty,
                       price-break selection, NRE amortisation, DNP exclusion.
  bom_dfm_report     — DFM rule check over a CircuitJSON board; returns findings
                       list + roll-up score.  Parameterised by IPC board class.
  bom_sourcing_risk  — Flag single-source / no-price / long-lead BOM lines.
                       Pure-Python; no live distributor calls.

Input shapes
─────────────
bom_line item (used by bom_cost_rollup and bom_sourcing_risk):
  {
    "refdes": "R1,R2",          # comma-separated designators or single refdes
    "qty": 2,                   # required
    "mpn": "RC0402FR-0710KL",   # optional
    "description": "...",       # optional
    "dnp": false,               # optional — true excludes from cost
    "unit_price": 0.10,         # flat price; ignored when price_breaks present
    "price_breaks": [           # optional volume price table
      {"min_qty": 1,   "unit_price": 0.15},
      {"min_qty": 100, "unit_price": 0.10},
      {"min_qty": 1000,"unit_price": 0.07}
    ],
    "lead_time_weeks": null,    # optional; null / 0 = unknown
    "num_sources": null,        # optional; null / 0 = unknown; 1 = single-source
    "manufacturer": "...",      # optional
    "distributor": "..."        # optional
  }

All tools return {"ok": true, ...} or {"ok": false, "error": ..., "code": ...}.

Author: imranparuk
"""

from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register

from kerf_electronics.dfm import run_dfm_checks, score_dfm


# ─── Cost rollup logic ───────────────────────────────────────────────────────

def _select_price(unit_price: float | None, price_breaks: list[dict], qty: int) -> float | None:
    """Select the best unit price from a price-break table at a given quantity.

    Price breaks must have keys ``min_qty`` and ``unit_price``.  We pick the
    break with the highest ``min_qty`` that is <= ``qty`` (i.e., the highest
    applicable tier).

    Falls back to ``unit_price`` (flat) if no breaks apply or table is empty.
    Returns None if no price information is available at all.
    """
    best_price: float | None = unit_price

    if price_breaks:
        # Sort descending by min_qty so we pick the best tier first
        applicable = [
            b for b in price_breaks
            if isinstance(b, dict) and int(b.get("min_qty", 0)) <= qty
        ]
        if applicable:
            best = max(applicable, key=lambda b: int(b.get("min_qty", 0)))
            try:
                best_price = float(best["unit_price"])
            except (KeyError, TypeError, ValueError):
                pass

    if best_price is None:
        return None
    try:
        return float(best_price)
    except (TypeError, ValueError):
        return None


def _compute_cost_rollup(
    bom_lines: list[dict],
    board_qty: int,
    assembly_qty: int,
    nre_usd: float,
    dnp_list: list[str],
) -> dict:
    """Core deterministic cost rollup.

    Args:
        bom_lines:    List of BOM line items (see module docstring).
        board_qty:    Number of bare boards purchased.
        assembly_qty: Number of boards to be assembled (≤ board_qty).
        nre_usd:      One-time NRE charges (tooling, setup, test fixtures).
        dnp_list:     Additional refdes names/patterns to treat as DNP.
                      Union-ed with per-line dnp=true flags.

    Returns:
        dict with keys: line_items, subtotal_parts_usd, nre_usd,
                        total_usd, per_board_usd, missing_price_lines,
                        dnp_lines.
    """
    dnp_set = {r.strip().upper() for r in dnp_list if r.strip()}

    line_results = []
    subtotal = 0.0
    missing_price: list[str] = []
    dnp_lines: list[str] = []

    for line in bom_lines:
        # Collect refdes labels for this line
        raw_refdes = line.get("refdes", "")
        refdes_list = [r.strip() for r in str(raw_refdes).split(",") if r.strip()]
        refdes_label = raw_refdes if raw_refdes else "(unnamed)"

        # DNP check: line-level flag OR any refdes in dnp_set
        line_dnp = bool(line.get("dnp", False))
        if not line_dnp and dnp_set:
            line_dnp = any(r.upper() in dnp_set for r in refdes_list)

        if line_dnp:
            dnp_lines.append(refdes_label)
            line_results.append({
                "refdes": refdes_label,
                "qty_per_board": line.get("qty", 0),
                "extended_qty": 0,
                "unit_price_usd": None,
                "extended_cost_usd": 0.0,
                "dnp": True,
            })
            continue

        qty_per_board = int(line.get("qty", 1) or 1)
        extended_qty = qty_per_board * assembly_qty

        unit_price = _select_price(
            line.get("unit_price"),
            line.get("price_breaks") or [],
            extended_qty,
        )

        if unit_price is None:
            missing_price.append(refdes_label)
            line_results.append({
                "refdes": refdes_label,
                "qty_per_board": qty_per_board,
                "extended_qty": extended_qty,
                "unit_price_usd": None,
                "extended_cost_usd": None,
                "dnp": False,
            })
            continue

        extended_cost = round(unit_price * extended_qty, 6)
        subtotal += extended_cost

        line_results.append({
            "refdes": refdes_label,
            "qty_per_board": qty_per_board,
            "extended_qty": extended_qty,
            "unit_price_usd": round(unit_price, 6),
            "extended_cost_usd": extended_cost,
            "dnp": False,
        })

    total = round(subtotal + nre_usd, 6)
    per_board = round(total / assembly_qty, 6) if assembly_qty > 0 else 0.0

    return {
        "line_items": line_results,
        "subtotal_parts_usd": round(subtotal, 6),
        "nre_usd": round(nre_usd, 6),
        "total_usd": total,
        "per_board_usd": per_board,
        "board_qty": board_qty,
        "assembly_qty": assembly_qty,
        "missing_price_lines": missing_price,
        "dnp_lines": dnp_lines,
    }


# ─── Tool: bom_cost_rollup ────────────────────────────────────────────────────

bom_cost_rollup_spec = ToolSpec(
    name="bom_cost_rollup",
    description=(
        "Compute extended BOM cost from a list of BOM line items. "
        "Selects the best price-break tier at the assembled quantity. "
        "Amortises NRE (non-recurring engineering) charges across the run. "
        "Excludes DNP (do-not-populate) parts from cost — mark a line with "
        "dnp=true or pass refdes names in the dnp_list argument. "
        "Returns: per-line extended cost, parts subtotal, NRE, total, "
        "per-board cost, and lists of DNP / missing-price lines. "
        "No live network calls — all computation is deterministic."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bom_lines": {
                "type": "array",
                "description": (
                    "List of BOM line items. Each item: "
                    "{refdes, qty, unit_price?, price_breaks?, dnp?, "
                    "mpn?, description?, lead_time_weeks?, num_sources?, "
                    "manufacturer?, distributor?}. "
                    "price_breaks: [{min_qty, unit_price}, ...] sorted ascending."
                ),
                "items": {"type": "object"},
            },
            "board_qty": {
                "type": "integer",
                "description": "Number of bare boards being manufactured (≥1).",
                "minimum": 1,
            },
            "assembly_qty": {
                "type": "integer",
                "description": (
                    "Number of boards to assemble with components. "
                    "Defaults to board_qty. Price-break tier is selected "
                    "at assembly_qty × qty_per_board."
                ),
                "minimum": 1,
            },
            "nre_usd": {
                "type": "number",
                "description": (
                    "One-time NRE charges in USD (stencil, fixtures, setup). "
                    "Amortised over assembly_qty. Default 0."
                ),
                "minimum": 0,
            },
            "dnp_list": {
                "type": "array",
                "description": (
                    "Additional refdes designators to treat as DNP regardless "
                    "of line-level dnp flags. e.g. ['R5', 'C12']."
                ),
                "items": {"type": "string"},
            },
        },
        "required": ["bom_lines"],
    },
)


@register(bom_cost_rollup_spec)
async def run_bom_cost_rollup(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    bom_lines = a.get("bom_lines")
    if not isinstance(bom_lines, list):
        return err_payload("bom_lines must be an array", "BAD_ARGS")

    if len(bom_lines) == 0:
        return err_payload("bom_lines is empty; provide at least one line item", "EMPTY_BOM")

    try:
        board_qty = int(a.get("board_qty", 1) or 1)
        if board_qty < 1:
            return err_payload("board_qty must be >= 1", "BAD_ARGS")
    except (TypeError, ValueError):
        return err_payload("board_qty must be an integer >= 1", "BAD_ARGS")

    try:
        assembly_qty = int(a.get("assembly_qty") or board_qty)
        if assembly_qty < 1:
            return err_payload("assembly_qty must be >= 1", "BAD_ARGS")
    except (TypeError, ValueError):
        return err_payload("assembly_qty must be an integer >= 1", "BAD_ARGS")

    try:
        nre_usd = float(a.get("nre_usd", 0) or 0)
        if nre_usd < 0:
            return err_payload("nre_usd must be >= 0", "BAD_ARGS")
    except (TypeError, ValueError):
        return err_payload("nre_usd must be a non-negative number", "BAD_ARGS")

    dnp_list = a.get("dnp_list") or []
    if not isinstance(dnp_list, list):
        return err_payload("dnp_list must be an array", "BAD_ARGS")

    result = _compute_cost_rollup(
        bom_lines=bom_lines,
        board_qty=board_qty,
        assembly_qty=assembly_qty,
        nre_usd=nre_usd,
        dnp_list=dnp_list,
    )

    n_lines = len(bom_lines)
    n_dnp = len(result["dnp_lines"])
    n_missing = len(result["missing_price_lines"])
    n_priced = n_lines - n_dnp - n_missing

    msg_parts = [
        f"BOM rollup: {n_lines} line(s), {n_priced} priced, "
        f"{n_dnp} DNP, {n_missing} missing price. "
        f"Parts subtotal ${result['subtotal_parts_usd']:.4f} USD "
        f"(x{assembly_qty} boards). "
        f"NRE ${result['nre_usd']:.2f} USD. "
        f"Total ${result['total_usd']:.4f} USD = "
        f"${result['per_board_usd']:.4f} USD/board."
    ]
    if n_missing:
        msg_parts.append(
            f" WARNING: {n_missing} line(s) missing price; total is incomplete."
        )

    return ok_payload({
        "ok": True,
        **result,
        "message": "".join(msg_parts),
    })


# ─── Tool: bom_dfm_report ─────────────────────────────────────────────────────

bom_dfm_report_spec = ToolSpec(
    name="bom_dfm_report",
    description=(
        "Run IPC-class DFM (design-for-manufacture) rule checks on a CircuitJSON "
        "board and return a findings list plus a roll-up score (0–100, 100=clean). "
        "Rules checked: annular ring (PTH + via), min trace width/space, "
        "drill-to-copper, silkscreen-over-pad, acid traps, copper slivers, "
        "courtyard overlap, smallest passive size vs assembly capability. "
        "Thresholds follow IPC-2221B / IPC-A-600K for the selected board class. "
        "Pure-Python, no external tools required. "
        "board_class: 1=consumer, 2=commercial/industrial (default), 3=high-reliability."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {
                "type": "array",
                "description": "Parsed CircuitJSON array from the board file.",
                "items": {"type": "object"},
            },
            "board_class": {
                "type": "integer",
                "description": (
                    "IPC board class: 1 (consumer), 2 (commercial, default), "
                    "3 (high-reliability / medical / aerospace)."
                ),
                "enum": [1, 2, 3],
            },
        },
        "required": ["circuit_json"],
    },
)


@register(bom_dfm_report_spec)
async def run_bom_dfm_report(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    circuit_json = a.get("circuit_json")
    if not isinstance(circuit_json, list):
        return err_payload("circuit_json must be an array", "BAD_ARGS")

    board_class = int(a.get("board_class", 2) or 2)
    if board_class not in (1, 2, 3):
        return err_payload("board_class must be 1, 2, or 3", "BAD_ARGS")

    findings = run_dfm_checks(circuit_json, board_class=board_class)
    score = score_dfm(findings)

    findings_dicts = [f.to_dict() for f in findings]

    fail_count = sum(1 for f in findings if f.severity == "fail")
    warn_count = sum(1 for f in findings if f.severity == "warn")
    info_count = sum(1 for f in findings if f.severity == "info")

    if not findings or (fail_count == 0 and warn_count == 0):
        summary = f"DFM clean (IPC class {board_class}): no issues found. Score: {score}/100."
    else:
        summary = (
            f"DFM report (IPC class {board_class}): "
            f"{fail_count} fail(s), {warn_count} warn(s), {info_count} info(s). "
            f"Score: {score}/100."
        )

    return ok_payload({
        "ok": True,
        "board_class": board_class,
        "score": score,
        "finding_count": len(findings_dicts),
        "fail_count": fail_count,
        "warn_count": warn_count,
        "info_count": info_count,
        "findings": findings_dicts,
        "message": summary,
    })


# ─── Tool: bom_sourcing_risk ──────────────────────────────────────────────────

bom_sourcing_risk_spec = ToolSpec(
    name="bom_sourcing_risk",
    description=(
        "Analyse BOM line items for sourcing risk: single-source parts, "
        "parts with no price information, and long-lead-time parts. "
        "Returns a risk list with severity (warn/fail) per line item. "
        "No live distributor calls — operates on the provided BOM data only. "
        "Input format is the same as bom_cost_rollup.bom_lines. "
        "long_lead_weeks threshold defaults to 16 weeks; "
        "single_source threshold is num_sources == 1."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bom_lines": {
                "type": "array",
                "description": "List of BOM line items (same schema as bom_cost_rollup).",
                "items": {"type": "object"},
            },
            "long_lead_weeks": {
                "type": "number",
                "description": (
                    "Lead time (weeks) above which a part is flagged as long-lead. "
                    "Default 16."
                ),
                "minimum": 1,
            },
        },
        "required": ["bom_lines"],
    },
)


@register(bom_sourcing_risk_spec)
async def run_bom_sourcing_risk(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    bom_lines = a.get("bom_lines")
    if not isinstance(bom_lines, list):
        return err_payload("bom_lines must be an array", "BAD_ARGS")

    if len(bom_lines) == 0:
        return err_payload("bom_lines is empty; provide at least one line item", "EMPTY_BOM")

    try:
        long_lead = float(a.get("long_lead_weeks", 16) or 16)
    except (TypeError, ValueError):
        return err_payload("long_lead_weeks must be a positive number", "BAD_ARGS")

    risks = []

    for line in bom_lines:
        refdes = str(line.get("refdes", "(unnamed)")).strip() or "(unnamed)"

        # Skip DNP parts
        if line.get("dnp", False):
            continue

        # No price info at all
        has_unit = line.get("unit_price") is not None
        has_breaks = bool(line.get("price_breaks"))
        if not has_unit and not has_breaks:
            risks.append({
                "refdes": refdes,
                "risk": "no_price",
                "severity": "warn",
                "message": (
                    f"{refdes}: no unit_price or price_breaks provided — "
                    "cost unknown, sourcing unconfirmed"
                ),
            })

        # Single-source
        num_sources = line.get("num_sources")
        if num_sources is not None:
            try:
                ns = int(num_sources)
                if ns == 1:
                    mpn = line.get("mpn", "")
                    risks.append({
                        "refdes": refdes,
                        "risk": "single_source",
                        "severity": "fail",
                        "message": (
                            f"{refdes} ({mpn or 'no MPN'}): single-source part — "
                            "supply disruption has no alternative"
                        ),
                        "mpn": mpn,
                    })
            except (TypeError, ValueError):
                pass

        # Long lead time
        lead = line.get("lead_time_weeks")
        if lead is not None:
            try:
                lead_f = float(lead)
                if lead_f > long_lead:
                    risks.append({
                        "refdes": refdes,
                        "risk": "long_lead",
                        "severity": "warn",
                        "message": (
                            f"{refdes}: lead time {lead_f:.0f} weeks "
                            f"exceeds threshold {long_lead:.0f} weeks"
                        ),
                        "lead_time_weeks": lead_f,
                    })
            except (TypeError, ValueError):
                pass

    fail_count = sum(1 for r in risks if r["severity"] == "fail")
    warn_count = sum(1 for r in risks if r["severity"] == "warn")

    if not risks:
        summary = f"No sourcing risks identified in {len(bom_lines)} BOM line(s)."
    else:
        summary = (
            f"Sourcing risk: {len(risks)} issue(s) across {len(bom_lines)} line(s) "
            f"({fail_count} critical, {warn_count} warnings)."
        )

    return ok_payload({
        "ok": True,
        "risk_count": len(risks),
        "fail_count": fail_count,
        "warn_count": warn_count,
        "risks": risks,
        "message": summary,
    })


# ─── TOOLS export (consumed by plugin._register_tools) ───────────────────────
# Each entry: (tool_name, spec, handler)
# The plugin loader calls ctx.tools.register(name, spec, handler) for each.
# We re-export the tuples from the @register decorator's Registry list.

from kerf_electronics._compat import Registry as _Registry

# Build TOOLS by inspecting the last three entries we just registered.
# This mirrors the pattern used in other tool modules.
TOOLS = [
    (t.spec.name, t.spec, t.run)
    for t in _Registry
    if t.spec.name in (
        "bom_cost_rollup",
        "bom_dfm_report",
        "bom_sourcing_risk",
    )
]
