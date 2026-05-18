"""sky130/design_rules.py — SKY130 design-rule set.

All dimensions in micrometres (µm) unless noted.

Data sourced from the SkyWater SKY130 DRC manual:
  https://skywater-pdk.readthedocs.io/en/main/rules/periphery.html
  https://skywater-pdk.readthedocs.io/en/main/rules/

Each entry:
  name          — rule identifier
  layer         — primary layer the rule applies to
  rule_type     — "min_width", "min_spacing", "min_enclosure",
                  "exact_size", "min_area", or "same_potential_spacing"
  value_um      — numeric value in µm  (None for fixed-size entries
                  that use width_um + height_um instead)
  width_um      — (optional) for rectangular fixed-size rules, width
  height_um     — (optional) for rectangular fixed-size rules, height
  description   — human-readable rule summary
"""

from __future__ import annotations

from typing import Dict, List, Optional

DESIGN_RULES: List[Dict] = [
    # ------------------------------------------------------------------
    # poly
    # ------------------------------------------------------------------
    {
        "name": "poly.width.min",
        "layer": "poly",
        "rule_type": "min_width",
        "value_um": 0.150,
        "description": "Minimum poly gate width (drawn gate length) = 0.150 µm",
    },
    {
        "name": "poly.spacing.min",
        "layer": "poly",
        "rule_type": "min_spacing",
        "value_um": 0.210,
        "description": "Minimum poly-to-poly spacing = 0.210 µm",
    },
    {
        "name": "poly.extension.over_diff",
        "layer": "poly",
        "rule_type": "min_enclosure",
        "value_um": 0.130,
        "description": "Poly must extend ≥ 0.130 µm beyond active diff edge",
    },
    # ------------------------------------------------------------------
    # diff / tap
    # ------------------------------------------------------------------
    {
        "name": "diff.width.min",
        "layer": "diff",
        "rule_type": "min_width",
        "value_um": 0.150,
        "description": "Minimum diffusion width = 0.150 µm",
    },
    {
        "name": "diff.spacing.min",
        "layer": "diff",
        "rule_type": "min_spacing",
        "value_um": 0.270,
        "description": "Minimum diff-to-diff spacing (same net excluded) = 0.270 µm",
    },
    # ------------------------------------------------------------------
    # li1 (local interconnect)
    # ------------------------------------------------------------------
    {
        "name": "li1.width.min",
        "layer": "li1",
        "rule_type": "min_width",
        "value_um": 0.170,
        "description": "Minimum li1 width = 0.170 µm",
    },
    {
        "name": "li1.spacing.min",
        "layer": "li1",
        "rule_type": "min_spacing",
        "value_um": 0.170,
        "description": "Minimum li1-to-li1 spacing = 0.170 µm",
    },
    {
        "name": "licon1.size.fixed",
        "layer": "licon1",
        "rule_type": "exact_size",
        "value_um": None,
        "width_um": 0.170,
        "height_um": 0.170,
        "description": "licon1 contact must be exactly 0.170 × 0.170 µm",
    },
    # ------------------------------------------------------------------
    # met1
    # ------------------------------------------------------------------
    {
        "name": "met1.width.min",
        "layer": "met1",
        "rule_type": "min_width",
        "value_um": 0.140,
        "description": "Minimum met1 width = 0.140 µm",
    },
    {
        "name": "met1.spacing.min",
        "layer": "met1",
        "rule_type": "min_spacing",
        "value_um": 0.140,
        "description": "Minimum met1-to-met1 spacing = 0.140 µm",
    },
    {
        "name": "met1.area.min",
        "layer": "met1",
        "rule_type": "min_area",
        "value_um": 0.083,
        "description": "Minimum met1 shape area = 0.083 µm²",
    },
    # ------------------------------------------------------------------
    # via (met1 → met2)
    # ------------------------------------------------------------------
    {
        "name": "via.size.fixed",
        "layer": "via",
        "rule_type": "exact_size",
        "value_um": None,
        "width_um": 0.150,
        "height_um": 0.150,
        "description": "Via must be exactly 0.150 × 0.150 µm",
    },
    {
        "name": "via.spacing.min",
        "layer": "via",
        "rule_type": "min_spacing",
        "value_um": 0.170,
        "description": "Minimum via-to-via spacing = 0.170 µm",
    },
    {
        "name": "via.enclosure.met1",
        "layer": "via",
        "rule_type": "min_enclosure",
        "value_um": 0.055,
        "description": "met1 must enclose via by ≥ 0.055 µm on all sides",
    },
    # ------------------------------------------------------------------
    # met2
    # ------------------------------------------------------------------
    {
        "name": "met2.width.min",
        "layer": "met2",
        "rule_type": "min_width",
        "value_um": 0.140,
        "description": "Minimum met2 width = 0.140 µm",
    },
    {
        "name": "met2.spacing.min",
        "layer": "met2",
        "rule_type": "min_spacing",
        "value_um": 0.140,
        "description": "Minimum met2-to-met2 spacing = 0.140 µm",
    },
    # ------------------------------------------------------------------
    # met3 / met4 / met5
    # ------------------------------------------------------------------
    {
        "name": "met3.width.min",
        "layer": "met3",
        "rule_type": "min_width",
        "value_um": 0.300,
        "description": "Minimum met3 width = 0.300 µm",
    },
    {
        "name": "met3.spacing.min",
        "layer": "met3",
        "rule_type": "min_spacing",
        "value_um": 0.300,
        "description": "Minimum met3-to-met3 spacing = 0.300 µm",
    },
    {
        "name": "met4.width.min",
        "layer": "met4",
        "rule_type": "min_width",
        "value_um": 0.300,
        "description": "Minimum met4 width = 0.300 µm",
    },
    {
        "name": "met5.width.min",
        "layer": "met5",
        "rule_type": "min_width",
        "value_um": 1.600,
        "description": "Minimum met5 (top metal) width = 1.600 µm",
    },
    {
        "name": "met5.spacing.min",
        "layer": "met5",
        "rule_type": "min_spacing",
        "value_um": 1.600,
        "description": "Minimum met5 spacing = 1.600 µm",
    },
    # ------------------------------------------------------------------
    # nwell
    # ------------------------------------------------------------------
    {
        "name": "nwell.width.min",
        "layer": "nwell",
        "rule_type": "min_width",
        "value_um": 0.840,
        "description": "Minimum nwell width = 0.840 µm",
    },
    {
        "name": "nwell.spacing.same_potential",
        "layer": "nwell",
        "rule_type": "same_potential_spacing",
        "value_um": 1.270,
        "description": "nwell-to-nwell spacing (same potential) = 1.270 µm",
    },
    {
        "name": "nwell.spacing.diff_potential",
        "layer": "nwell",
        "rule_type": "min_spacing",
        "value_um": 2.000,
        "description": "nwell-to-nwell spacing (different potential) = 2.000 µm",
    },
]

# ---------------------------------------------------------------------------
# Lookup helper
# ---------------------------------------------------------------------------

_RULE_BY_NAME: Dict[str, Dict] = {r["name"]: r for r in DESIGN_RULES}


def get_rule(name: str) -> Optional[Dict]:
    """Return a design-rule dict by name, or None if not found."""
    return _RULE_BY_NAME.get(name)
