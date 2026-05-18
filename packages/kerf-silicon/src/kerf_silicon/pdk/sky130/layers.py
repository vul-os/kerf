"""sky130/layers.py — SKY130 GDS layer table.

Layer data sourced from the SkyWater SKY130 PDK documentation:
  https://skywater-pdk.readthedocs.io/en/main/rules/layers.html

Each entry: {name, gds_layer, gds_datatype, color, description}
"""

from __future__ import annotations

from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Layer definitions
# ---------------------------------------------------------------------------

LAYERS: List[Dict] = [
    {
        "name": "nwell",
        "gds_layer": 64,
        "gds_datatype": 20,
        "color": "#9E9E9E",
        "description": "N-well implant region",
    },
    {
        "name": "pwell",
        "gds_layer": 122,
        "gds_datatype": 16,
        "color": "#BDBDBD",
        "description": "P-well implant region (virtual/marker)",
    },
    {
        "name": "dnwell",
        "gds_layer": 64,
        "gds_datatype": 18,
        "color": "#616161",
        "description": "Deep N-well implant",
    },
    {
        "name": "diff",
        "gds_layer": 65,
        "gds_datatype": 20,
        "color": "#F9A825",
        "description": "Active / diffusion region (source/drain)",
    },
    {
        "name": "tap",
        "gds_layer": 65,
        "gds_datatype": 44,
        "color": "#FF8F00",
        "description": "Well / substrate tap (diffusion contact)",
    },
    {
        "name": "poly",
        "gds_layer": 66,
        "gds_datatype": 20,
        "color": "#E53935",
        "description": "Gate polysilicon and poly resistors",
    },
    {
        "name": "licon1",
        "gds_layer": 66,
        "gds_datatype": 44,
        "color": "#F4511E",
        "description": "Local interconnect contact to poly/diff",
    },
    {
        "name": "npc",
        "gds_layer": 95,
        "gds_datatype": 20,
        "color": "#D84315",
        "description": "Nitride poly cut (removes nitride over poly contacts)",
    },
    {
        "name": "li1",
        "gds_layer": 67,
        "gds_datatype": 20,
        "color": "#00ACC1",
        "description": "Local interconnect metal layer 1 (TiN/Al)",
    },
    {
        "name": "mcon",
        "gds_layer": 67,
        "gds_datatype": 44,
        "color": "#0097A7",
        "description": "Contact via from li1 to met1",
    },
    {
        "name": "met1",
        "gds_layer": 68,
        "gds_datatype": 20,
        "color": "#1565C0",
        "description": "Metal layer 1 (Al alloy)",
    },
    {
        "name": "via",
        "gds_layer": 68,
        "gds_datatype": 44,
        "color": "#1976D2",
        "description": "Via from met1 to met2",
    },
    {
        "name": "met2",
        "gds_layer": 69,
        "gds_datatype": 20,
        "color": "#6A1B9A",
        "description": "Metal layer 2",
    },
    {
        "name": "via2",
        "gds_layer": 69,
        "gds_datatype": 44,
        "color": "#7B1FA2",
        "description": "Via from met2 to met3",
    },
    {
        "name": "met3",
        "gds_layer": 70,
        "gds_datatype": 20,
        "color": "#558B2F",
        "description": "Metal layer 3",
    },
    {
        "name": "via3",
        "gds_layer": 70,
        "gds_datatype": 44,
        "color": "#689F38",
        "description": "Via from met3 to met4",
    },
    {
        "name": "met4",
        "gds_layer": 71,
        "gds_datatype": 20,
        "color": "#EF6C00",
        "description": "Metal layer 4",
    },
    {
        "name": "via4",
        "gds_layer": 71,
        "gds_datatype": 44,
        "color": "#F57C00",
        "description": "Via from met4 to met5",
    },
    {
        "name": "met5",
        "gds_layer": 72,
        "gds_datatype": 20,
        "color": "#B71C1C",
        "description": "Metal layer 5 (top metal, thicker)",
    },
    {
        "name": "pad",
        "gds_layer": 76,
        "gds_datatype": 20,
        "color": "#FFD600",
        "description": "Bond-pad opening through passivation",
    },
    {
        "name": "areaid.standardc",
        "gds_layer": 81,
        "gds_datatype": 4,
        "color": "#B2DFDB",
        "description": "Standard-cell area identifier",
    },
    {
        "name": "areaid.lowTapDensity",
        "gds_layer": 81,
        "gds_datatype": 14,
        "color": "#C8E6C9",
        "description": "Low tap-density waiver area",
    },
    {
        "name": "prBoundary",
        "gds_layer": 235,
        "gds_datatype": 4,
        "color": "#E0E0E0",
        "description": "Place-and-route boundary / cell boundary",
    },
    {
        "name": "hvntm",
        "gds_layer": 125,
        "gds_datatype": 44,
        "color": "#F8BBD0",
        "description": "High-voltage N-type mask for 5 V transistors",
    },
    {
        "name": "hvi",
        "gds_layer": 75,
        "gds_datatype": 20,
        "color": "#FCE4EC",
        "description": "High-voltage implant — enables 5 V operation",
    },
    {
        "name": "nsdm",
        "gds_layer": 93,
        "gds_datatype": 44,
        "color": "#FFF176",
        "description": "N+ source/drain implant",
    },
    {
        "name": "psdm",
        "gds_layer": 94,
        "gds_datatype": 20,
        "color": "#CE93D8",
        "description": "P+ source/drain implant",
    },
    {
        "name": "rpm",
        "gds_layer": 86,
        "gds_datatype": 20,
        "color": "#A5D6A7",
        "description": "Poly resistor p-implant",
    },
    {
        "name": "urpm",
        "gds_layer": 79,
        "gds_datatype": 20,
        "color": "#80CBC4",
        "description": "Ultra-high-sheet-resistance poly resistor implant",
    },
    {
        "name": "natm",
        "gds_layer": 97,
        "gds_datatype": 44,
        "color": "#FFF9C4",
        "description": "Native (zero-Vt) N-type mask",
    },
    {
        "name": "hvtp",
        "gds_layer": 78,
        "gds_datatype": 44,
        "color": "#FFCCBC",
        "description": "High-voltage threshold P-type implant",
    },
    {
        "name": "lvtn",
        "gds_layer": 125,
        "gds_datatype": 20,
        "color": "#DCEDC8",
        "description": "Low-voltage-threshold N-type implant",
    },
    {
        "name": "oxide",
        "gds_layer": 75,
        "gds_datatype": 66,
        "color": "#F3E5F5",
        "description": "Thick field-oxide region marker",
    },
    {
        "name": "capm",
        "gds_layer": 89,
        "gds_datatype": 44,
        "color": "#E8EAF6",
        "description": "MIM capacitor metal layer",
    },
    {
        "name": "cap2m",
        "gds_layer": 97,
        "gds_datatype": 4,
        "color": "#EDE7F6",
        "description": "MIM capacitor 2 metal layer",
    },
    {
        "name": "cli1m",
        "gds_layer": 115,
        "gds_datatype": 44,
        "color": "#E0F7FA",
        "description": "Local interconnect li1 metal (dummy fill marker)",
    },
    {
        "name": "areaid.mt",
        "gds_layer": 81,
        "gds_datatype": 2,
        "color": "#F1F8E9",
        "description": "Module/top-level area identifier",
    },
]

# ---------------------------------------------------------------------------
# Lookup helper
# ---------------------------------------------------------------------------

_LAYER_BY_NAME: Dict[str, Dict] = {lyr["name"]: lyr for lyr in LAYERS}


def get_layer(name: str) -> Optional[Dict]:
    """Return a layer dict by name, or None if not found."""
    return _LAYER_BY_NAME.get(name)
