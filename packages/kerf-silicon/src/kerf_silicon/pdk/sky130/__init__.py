"""kerf_silicon.pdk.sky130 — SkyWater SKY130 PDK (Apache 2.0 licensed).

Exposes the layer table, standard-cell library, and design-rule set
for the SkyWater 130 nm open-source process.

References:
  https://skywater-pdk.readthedocs.io
  https://github.com/google/skywater-pdk
"""

from kerf_silicon.pdk.sky130.layers import LAYERS, get_layer
from kerf_silicon.pdk.sky130.std_cells import STD_CELLS, get_cell
from kerf_silicon.pdk.sky130.design_rules import DESIGN_RULES, get_rule
from kerf_silicon.pdk.sky130.installer import is_pdk_available, pdk_path, install_hint

__all__ = [
    "LAYERS",
    "get_layer",
    "STD_CELLS",
    "get_cell",
    "DESIGN_RULES",
    "get_rule",
    "is_pdk_available",
    "pdk_path",
    "install_hint",
]

# Convenience object that bundles the three tables for downstream consumers.
SKY130_PDK = {
    "name": "sky130A",
    "process": "SkyWater 130 nm",
    "license": "Apache-2.0",
    "layers": LAYERS,
    "std_cells": STD_CELLS,
    "design_rules": DESIGN_RULES,
}
