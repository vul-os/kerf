"""
lca_report — compute embodied carbon for a list of BOM parts.

Input: a list of part dicts, each with at minimum:
  name        — part / file name  (str)
  material    — material name / key (str, optional — skipped when absent)
  mass_kg     — mass in kg (float, optional — omitted parts contribute 0)
  quantity    — integer count (default 1)

Output: LCAResult dataclass (JSON-serialisable via .to_dict()).

Circularity score (0–100):
  = 0.5 × weighted_avg(recycled_content_pct)
  + 0.5 × weighted_avg(eol_recyclability_pct)
  where weights = mass_kg × quantity per line.

The DoD oracle values (ICE v3, within ±5%):
  steel (general)     → 1.80 kg CO₂-eq/kg
  concrete (general)  → 0.115 kg CO₂-eq/kg
  aluminium (primary) → 9.16 kg CO₂-eq/kg
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kerf_lca.materials import lookup_material


@dataclass
class PartLCA:
    name: str
    quantity: int
    mass_kg: float
    material_id: str
    material_label: str
    embodied_carbon_kg_co2_per_kg: float
    total_carbon_kg_co2: float
    recycled_content_pct: float
    recyclability_pct: float
    warning: str = ""


@dataclass
class LCAResult:
    total_carbon_kg_co2: float
    parts: list[PartLCA] = field(default_factory=list)
    # per-material aggregates  {material_id: {...}}
    by_material: dict[str, dict[str, Any]] = field(default_factory=dict)
    # circularity score 0–100
    circularity_score: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_carbon_kg_co2": round(self.total_carbon_kg_co2, 4),
            "circularity_score": round(self.circularity_score, 1),
            "by_material": {
                mid: {
                    "label": v["label"],
                    "total_mass_kg": round(v["total_mass_kg"], 4),
                    "total_carbon_kg_co2": round(v["total_carbon_kg_co2"], 4),
                    "embodied_carbon_factor": v["embodied_carbon_factor"],
                    "recycled_content_pct": v["recycled_content_pct"],
                    "recyclability_pct": v["recyclability_pct"],
                }
                for mid, v in self.by_material.items()
            },
            "parts": [
                {
                    "name": p.name,
                    "quantity": p.quantity,
                    "mass_kg": p.mass_kg,
                    "material_id": p.material_id,
                    "material_label": p.material_label,
                    "embodied_carbon_factor": p.embodied_carbon_kg_co2_per_kg,
                    "total_carbon_kg_co2": round(p.total_carbon_kg_co2, 4),
                    "recycled_content_pct": p.recycled_content_pct,
                    "recyclability_pct": p.recyclability_pct,
                    **({"warning": p.warning} if p.warning else {}),
                }
                for p in self.parts
            ],
            "warnings": self.warnings,
        }


def lca_report(
    parts: list[dict],
    *,
    fallback_mass_kg: float = 1.0,
) -> LCAResult:
    """
    Compute an LCA report from a list of BOM part dicts.

    Args:
        parts: list of dicts with keys:
            name        (str)
            material    (str, optional) — material name/key; row skipped from
                        carbon calc if absent or unrecognised
            mass_kg     (float, optional) — per-unit mass; defaults to
                        fallback_mass_kg when absent
            quantity    (int, optional)  — defaults to 1
        fallback_mass_kg: mass assumed when a part omits mass_kg

    Returns:
        LCAResult
    """
    result_parts: list[PartLCA] = []
    by_material: dict[str, dict] = {}
    warnings: list[str] = []

    total_carbon = 0.0
    total_weighted_recycled = 0.0
    total_weighted_recyclability = 0.0
    total_mass_all = 0.0

    for raw in parts:
        name = raw.get("name") or raw.get("file_name") or "unnamed"
        qty = int(raw.get("quantity") or raw.get("count") or 1)
        if qty <= 0:
            qty = 1

        mass_each = raw.get("mass_kg") or raw.get("mass")
        if mass_each is None:
            mass_each = fallback_mass_kg
            warn = f"Part '{name}': mass_kg not provided; using fallback {fallback_mass_kg} kg"
            warnings.append(warn)
        else:
            try:
                mass_each = float(mass_each)
            except (TypeError, ValueError):
                mass_each = fallback_mass_kg
                warnings.append(f"Part '{name}': invalid mass_kg; using fallback {fallback_mass_kg} kg")

        material_name = raw.get("material") or raw.get("material_path") or ""
        mat = lookup_material(material_name) if material_name else None

        part_warning = ""
        if not material_name:
            part_warning = "no material specified"
            warnings.append(f"Part '{name}': {part_warning}; skipped from carbon total")
        elif mat is None:
            part_warning = f"material '{material_name}' not in ICE v3 database"
            warnings.append(f"Part '{name}': {part_warning}; skipped from carbon total")

        if mat is not None:
            factor = mat["embodied_carbon_kg_co2_per_kg"]
            line_carbon = factor * mass_each * qty
            recycled_pct = mat["recycled_content_pct"]
            recyclability_pct = mat["recyclability_pct"]
        else:
            factor = 0.0
            line_carbon = 0.0
            recycled_pct = 0.0
            recyclability_pct = 0.0

        total_carbon += line_carbon
        line_mass_total = mass_each * qty
        total_mass_all += line_mass_total
        total_weighted_recycled += recycled_pct * line_mass_total
        total_weighted_recyclability += recyclability_pct * line_mass_total

        part_lca = PartLCA(
            name=name,
            quantity=qty,
            mass_kg=mass_each,
            material_id=mat["id"] if mat else "",
            material_label=mat["label"] if mat else material_name,
            embodied_carbon_kg_co2_per_kg=factor,
            total_carbon_kg_co2=line_carbon,
            recycled_content_pct=recycled_pct,
            recyclability_pct=recyclability_pct,
            warning=part_warning,
        )
        result_parts.append(part_lca)

        if mat is not None:
            mid = mat["id"]
            if mid not in by_material:
                by_material[mid] = {
                    "label": mat["label"],
                    "total_mass_kg": 0.0,
                    "total_carbon_kg_co2": 0.0,
                    "embodied_carbon_factor": factor,
                    "recycled_content_pct": recycled_pct,
                    "recyclability_pct": recyclability_pct,
                }
            by_material[mid]["total_mass_kg"] += line_mass_total
            by_material[mid]["total_carbon_kg_co2"] += line_carbon

    # circularity score
    if total_mass_all > 0:
        avg_recycled = total_weighted_recycled / total_mass_all
        avg_recyclability = total_weighted_recyclability / total_mass_all
        circularity = 0.5 * avg_recycled + 0.5 * avg_recyclability
    else:
        circularity = 0.0

    return LCAResult(
        total_carbon_kg_co2=total_carbon,
        parts=result_parts,
        by_material=by_material,
        circularity_score=circularity,
        warnings=warnings,
    )
