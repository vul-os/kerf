"""
kerf-lca — Life Cycle Assessment (embodied carbon) for Kerf projects.

Provides:
  - materials database (ICE v3 reference values)
  - lca_report(): synchronous report from a BOM-like list of parts
  - lca_report tool for the Kerf chat assistant
"""

from kerf_lca.materials import load_database, lookup_material, list_materials
from kerf_lca.report import lca_report

__all__ = ["load_database", "lookup_material", "list_materials", "lca_report"]
__version__ = "0.1.0"
