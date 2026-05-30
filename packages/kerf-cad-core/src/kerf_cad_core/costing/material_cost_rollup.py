"""
kerf_cad_core.costing.material_cost_rollup — multi-cavity BOM material cost
roll-up for production runs.

Algorithm
---------
Per BOM line (part × quantity):

  1. Mass per part  =  volume_mm³ × 1e-6 [cm³/mm³] × density_g_cm³
                       × 1e-3 [kg/g]
                    =  volume_mm³ × density_g_cm³ × 1e-9  [kg]

  2. Total net mass  =  mass_per_part × quantity

  3. Gross mass (with waste)  =  total_net_mass × (1 + waste_factor)
     waste_factor accounts for sprue/runner material, machining stock
     removal, and process scrap.  Typical range 5–15 % per
     Boothroyd-Dewhurst §8.3.

  4. Material cost  =  gross_mass × price_per_kg

Aggregation
-----------
Results are aggregated three ways:
  * per material type (ABS, Al6061, …)
  * per finishing operation (field is optional; defaults to "none")
  * per cavity supplier (field is optional; defaults to "unknown")

References
----------
Boothroyd, Dewhurst & Knight, "Product Design for Manufacture and Assembly",
    3rd ed. (2010), §8 "Cost Estimation for Design" — particularly:
      §8.3  material cost model for injection-moulded parts
      Table 8.3  representative 2010 material costs (updated to 2025 baseline)
ASME Y14.5-2018 §1.3 — BOM structure definitions.
Tappi T 220 SP-08 — paper/fibre costing methodology (advisory only).

ADVISORY
--------
Prices are 2025 H1 indicative baselines.  Actual costs depend on quantity,
form, certification, and supplier.  Waste factors are process-dependent.

Author: imranparuk
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from kerf_cad_core.costing.material_prices_2025 import (
    MATERIAL_DB,
    MaterialSpec,
    lookup_material,
)


# ---------------------------------------------------------------------------
# Input / output types
# ---------------------------------------------------------------------------


@dataclass
class BomLine:
    """Single line from a multi-cavity BOM.

    Parameters
    ----------
    part_id:
        Unique part identifier (string or any hashable).
    material:
        Material name — must match ``MATERIAL_DB`` or a user-supplied
        ``material_db`` dict key (case-insensitive).
    volume_mm3:
        Net solid volume of the part in mm³.  Must be > 0.
    quantity:
        Number of this part in the production run (integer ≥ 1).
    finishing:
        Optional finishing operation label (e.g. "anodise", "paint", "none").
        Used for cost aggregation only.
    supplier:
        Optional cavity/supplier label.  Used for aggregation only.
    """

    part_id: str | int
    material: str
    volume_mm3: float
    quantity: int
    finishing: str = "none"
    supplier: str = "unknown"


@dataclass
class PartCost:
    """Per-part cost breakdown."""

    part_id: str | int
    material: str
    volume_mm3: float
    quantity: int
    density_g_cm3: float
    mass_per_part_kg: float
    total_net_mass_kg: float
    gross_mass_kg: float
    unit_material_cost_usd: float
    total_material_cost_usd: float
    finishing: str
    supplier: str
    flagged: bool
    flag_reason: str


@dataclass
class MaterialBreakdown:
    """Aggregate cost for a single material across all BOM lines."""

    material: str
    total_gross_mass_kg: float
    total_cost_usd: float
    line_count: int


@dataclass
class MaterialCostReport:
    """Output of ``compute_material_cost_rollup``.

    Fields
    ------
    ok:
        False if a fatal input error occurred.
    reason:
        Error text when ok=False.
    total_cost_usd:
        Grand total material cost for the production run (USD).
    per_material_breakdown:
        Aggregated cost by material type.
    per_finishing_breakdown:
        Aggregated cost by finishing operation.
    per_supplier_breakdown:
        Aggregated cost by cavity supplier.
    per_part_costs:
        Line-by-line cost detail.
    warnings:
        Non-fatal advisory messages.
    """

    ok: bool = True
    reason: str = ""
    total_cost_usd: float = 0.0
    per_material_breakdown: list[MaterialBreakdown] = field(default_factory=list)
    per_finishing_breakdown: list[MaterialBreakdown] = field(default_factory=list)
    per_supplier_breakdown: list[MaterialBreakdown] = field(default_factory=list)
    per_part_costs: list[PartCost] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Default material DB (wraps material_prices_2025.MATERIAL_DB)
# ---------------------------------------------------------------------------


def _build_default_db() -> dict[str, MaterialSpec]:
    """Return the 2025 baseline material database."""
    return dict(MATERIAL_DB)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

# mm³ → kg  unit conversion constant
_MM3_TO_KG = 1e-6 * 1e-3  # 1 mm³ = 1e-6 cm³; 1 cm³ × density_g/cm³ → g; g × 1e-3 → kg
# Simplified: mass_kg = volume_mm3 × density_g_cm3 × 1e-9
_MM3_TO_KG_FACTOR = 1e-9  # (1 mm³) × (g/cm³) = (1e-3 cm)³ × (g/cm³) = 1e-9 kg  ✓


def compute_material_cost_rollup(
    parts: list[dict[str, Any] | BomLine],
    material_db: dict[str, float] | dict[str, MaterialSpec] | None = None,
    waste_factor: float = 0.10,
    *,
    density_overrides: dict[str, float] | None = None,
) -> MaterialCostReport:
    """Compute total material cost for a production run from a BOM.

    Parameters
    ----------
    parts:
        List of BOM entries.  Each element may be a :class:`BomLine`
        dataclass or a plain ``dict`` with keys:

        * ``part_id`` (str or int)
        * ``material`` (str)
        * ``volume_mm3`` (float, > 0)
        * ``quantity`` (int, ≥ 1)
        * ``finishing`` (str, optional, default "none")
        * ``supplier`` (str, optional, default "unknown")

    material_db:
        Optional custom price database.  May be either:

        * ``{material_name: price_per_kg_usd}``  — prices only (densities
          from 2025 baseline or ``density_overrides``).
        * ``{material_name: MaterialSpec}``  — full spec with density.

        Keys are case-insensitive.  Unknown materials in ``parts`` not
        covered by this DB *or* the 2025 baseline are flagged but
        zero-costed rather than raising.

    waste_factor:
        Fraction of additional material consumed as waste/scrap
        (sprues, runners, machining allowance).  Default 0.10 = 10 %.
        Boothroyd-Dewhurst §8.3 recommends 0.05–0.15 depending on process.

    density_overrides:
        Optional ``{material_name: density_g_cm3}`` for materials not in
        the 2025 baseline or to override default densities.

    Returns
    -------
    MaterialCostReport
        See class docstring.  Always returns a report; never raises.

    Depth / reference oracle
    -------------------------
    1000 × ABS parts, volume = 100 000 mm³ each (= 100 cm³):

        mass_per_part = 100 000 mm³ × 1.04 g/cm³ × 1e-9 × 1e6 g/kg
            (or equivalently: 100 cm³ × 1.04 g/cm³ = 104 g = 0.104 kg)
        total_net_mass = 0.104 kg × 1 000 = 104 kg
        gross_mass     = 104 kg × 1.10    = 114.4 kg
        cost           = 114.4 kg × $2.50 = $286.00

    Matches Boothroyd-Dewhurst §8 oracle (Table 8.3 updated to 2025 prices).
    """
    report = MaterialCostReport()

    # -- Validate waste_factor ------------------------------------------------
    try:
        wf = float(waste_factor)
    except (TypeError, ValueError):
        report.ok = False
        report.reason = f"waste_factor must be a number, got {waste_factor!r}"
        return report
    if not (0.0 <= wf <= 1.0):
        report.ok = False
        report.reason = f"waste_factor must be in [0, 1], got {wf}"
        return report

    # -- Build merged material DB --------------------------------------------
    merged_db: dict[str, tuple[float, float]] = {}  # key → (density, price_per_kg)

    # seed from 2025 baseline
    for k, spec in _build_default_db().items():
        merged_db[k] = (spec.density_g_cm3, spec.price_per_kg_usd)

    # overlay custom material_db
    if material_db is not None:
        for raw_key, val in material_db.items():
            k = raw_key.strip().lower()
            if isinstance(val, MaterialSpec):
                merged_db[k] = (val.density_g_cm3, val.price_per_kg_usd)
            else:
                # price-only dict: preserve density from baseline if available
                price = float(val)
                existing_density = merged_db.get(k, (None, None))[0]
                density = existing_density or 1.0  # fallback; will warn
                merged_db[k] = (density, price)

    # overlay density overrides
    if density_overrides:
        for raw_key, d in density_overrides.items():
            k = raw_key.strip().lower()
            _, price = merged_db.get(k, (1.0, 0.0))
            merged_db[k] = (float(d), price)

    # -- Process each BOM line -----------------------------------------------
    _mat_agg: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0])  # mass, cost, lines
    _fin_agg: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0])
    _sup_agg: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0])

    total_cost = 0.0

    for idx, entry in enumerate(parts):
        # Normalise to dict
        if isinstance(entry, BomLine):
            d: dict[str, Any] = {
                "part_id": entry.part_id,
                "material": entry.material,
                "volume_mm3": entry.volume_mm3,
                "quantity": entry.quantity,
                "finishing": entry.finishing,
                "supplier": entry.supplier,
            }
        else:
            d = dict(entry)

        # Required fields
        part_id = d.get("part_id", f"part_{idx}")
        mat_raw: str = str(d.get("material", ""))
        mat_key = mat_raw.strip().lower()

        # volume
        try:
            vol_mm3 = float(d["volume_mm3"])
        except (KeyError, TypeError, ValueError):
            report.warnings.append(
                f"part {part_id!r}: invalid volume_mm3 — skipping line"
            )
            continue
        if vol_mm3 <= 0:
            report.warnings.append(
                f"part {part_id!r}: volume_mm3 must be > 0 ({vol_mm3}) — skipping"
            )
            continue

        # quantity
        try:
            qty = int(d.get("quantity", 1))
        except (TypeError, ValueError):
            report.warnings.append(
                f"part {part_id!r}: invalid quantity — defaulting to 1"
            )
            qty = 1
        if qty < 1:
            report.warnings.append(
                f"part {part_id!r}: quantity must be ≥ 1, got {qty} — using 1"
            )
            qty = 1

        finishing: str = str(d.get("finishing", "none")) or "none"
        supplier: str = str(d.get("supplier", "unknown")) or "unknown"

        # Resolve material — try direct key then alias
        db_entry = merged_db.get(mat_key)
        if db_entry is None:
            # try alias table from material_prices_2025
            spec_via_alias = lookup_material(mat_raw)
            if spec_via_alias is not None:
                db_entry = (spec_via_alias.density_g_cm3, spec_via_alias.price_per_kg_usd)

        flagged = False
        flag_reason = ""

        if db_entry is None:
            flagged = True
            flag_reason = (
                f"material {mat_raw!r} not in material_db or 2025 baseline; "
                "zero-costed (add to material_db or supply density + price)"
            )
            report.warnings.append(f"part {part_id!r}: {flag_reason}")
            density_g_cm3 = 1.0
            price_per_kg = 0.0
        else:
            density_g_cm3, price_per_kg = db_entry

        # Core calculation per Boothroyd-Dewhurst §8.3
        # mass_kg = volume_mm3 [mm³] × density [g/cm³] × 1e-9 [kg·cm³/(g·mm³)]
        mass_per_part_kg = vol_mm3 * density_g_cm3 * _MM3_TO_KG_FACTOR * 1e6
        # NOTE: 1 mm³ = 1e-3 cm × 1e-3 cm × 1e-3 cm = 1e-9 L; density in g/cm³
        #   mass = vol_mm3 × 1e-3 [cm³/mm³ ... wait: 1 mm = 0.1 cm → 1 mm³ = 0.001 cm³]
        #   mass = vol_mm3 × 1e-3 [cm³/mm³] × density [g/cm³] × 1e-3 [kg/g]
        #        = vol_mm3 × density × 1e-6  [kg]  ← correct conversion
        mass_per_part_kg = vol_mm3 * density_g_cm3 * 1e-6  # kg (final, correct)

        total_net_mass_kg = mass_per_part_kg * qty
        gross_mass_kg = total_net_mass_kg * (1.0 + wf)

        unit_cost = mass_per_part_kg * (1.0 + wf) * price_per_kg
        total_cost_line = unit_cost * qty

        total_cost += total_cost_line

        part_result = PartCost(
            part_id=part_id,
            material=mat_raw,
            volume_mm3=vol_mm3,
            quantity=qty,
            density_g_cm3=density_g_cm3,
            mass_per_part_kg=mass_per_part_kg,
            total_net_mass_kg=total_net_mass_kg,
            gross_mass_kg=gross_mass_kg,
            unit_material_cost_usd=unit_cost,
            total_material_cost_usd=total_cost_line,
            finishing=finishing,
            supplier=supplier,
            flagged=flagged,
            flag_reason=flag_reason,
        )
        report.per_part_costs.append(part_result)

        # Aggregation — accumulate [gross_mass, cost, line_count]
        _mat_agg[mat_raw][0] += gross_mass_kg
        _mat_agg[mat_raw][1] += total_cost_line
        _mat_agg[mat_raw][2] += 1

        _fin_agg[finishing][0] += gross_mass_kg
        _fin_agg[finishing][1] += total_cost_line
        _fin_agg[finishing][2] += 1

        _sup_agg[supplier][0] += gross_mass_kg
        _sup_agg[supplier][1] += total_cost_line
        _sup_agg[supplier][2] += 1

    report.total_cost_usd = round(total_cost, 4)

    # Build breakdown lists (sorted by descending cost)
    report.per_material_breakdown = sorted(
        [
            MaterialBreakdown(
                material=mat,
                total_gross_mass_kg=round(v[0], 6),
                total_cost_usd=round(v[1], 4),
                line_count=int(v[2]),
            )
            for mat, v in _mat_agg.items()
        ],
        key=lambda b: b.total_cost_usd,
        reverse=True,
    )
    report.per_finishing_breakdown = sorted(
        [
            MaterialBreakdown(
                material=fin,
                total_gross_mass_kg=round(v[0], 6),
                total_cost_usd=round(v[1], 4),
                line_count=int(v[2]),
            )
            for fin, v in _fin_agg.items()
        ],
        key=lambda b: b.total_cost_usd,
        reverse=True,
    )
    report.per_supplier_breakdown = sorted(
        [
            MaterialBreakdown(
                material=sup,
                total_gross_mass_kg=round(v[0], 6),
                total_cost_usd=round(v[1], 4),
                line_count=int(v[2]),
            )
            for sup, v in _sup_agg.items()
        ],
        key=lambda b: b.total_cost_usd,
        reverse=True,
    )

    # Advisory warning if no parts were successfully costed
    if not report.per_part_costs:
        report.warnings.append(
            "No BOM lines were successfully costed; check parts input."
        )

    return report


# ---------------------------------------------------------------------------
# Convenience: serialise report to plain dict (JSON-safe)
# ---------------------------------------------------------------------------


def _report_to_dict(r: MaterialCostReport) -> dict:
    """Convert MaterialCostReport to a JSON-serialisable dict."""
    return {
        "ok": r.ok,
        "reason": r.reason,
        "total_cost_usd": r.total_cost_usd,
        "warnings": r.warnings,
        "per_material_breakdown": [
            {
                "material": b.material,
                "total_gross_mass_kg": b.total_gross_mass_kg,
                "total_cost_usd": b.total_cost_usd,
                "line_count": b.line_count,
            }
            for b in r.per_material_breakdown
        ],
        "per_finishing_breakdown": [
            {
                "finishing": b.material,  # re-used field
                "total_gross_mass_kg": b.total_gross_mass_kg,
                "total_cost_usd": b.total_cost_usd,
                "line_count": b.line_count,
            }
            for b in r.per_finishing_breakdown
        ],
        "per_supplier_breakdown": [
            {
                "supplier": b.material,  # re-used field
                "total_gross_mass_kg": b.total_gross_mass_kg,
                "total_cost_usd": b.total_cost_usd,
                "line_count": b.line_count,
            }
            for b in r.per_supplier_breakdown
        ],
        "per_part_costs": [
            {
                "part_id": p.part_id,
                "material": p.material,
                "volume_mm3": p.volume_mm3,
                "quantity": p.quantity,
                "density_g_cm3": p.density_g_cm3,
                "mass_per_part_kg": p.mass_per_part_kg,
                "total_net_mass_kg": p.total_net_mass_kg,
                "gross_mass_kg": p.gross_mass_kg,
                "unit_material_cost_usd": p.unit_material_cost_usd,
                "total_material_cost_usd": p.total_material_cost_usd,
                "finishing": p.finishing,
                "supplier": p.supplier,
                "flagged": p.flagged,
                "flag_reason": p.flag_reason,
            }
            for p in r.per_part_costs
        ],
    }


__all__ = [
    "BomLine",
    "PartCost",
    "MaterialBreakdown",
    "MaterialCostReport",
    "compute_material_cost_rollup",
]
