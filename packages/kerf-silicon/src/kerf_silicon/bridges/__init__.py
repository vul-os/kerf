"""
kerf_silicon.bridges — subprocess bridges for EDA synthesis and simulation tools.

Sub-modules (each owns its own availability sentinel):
  yosys_bridge   — Yosys RTL synthesis (gate-level netlist via write_json)
  ghdl_bridge    — GHDL VHDL simulation / synthesis  (T-235, sibling)
  ngspice_bridge — ngspice mixed-signal SPICE         (T-236, sibling)

Pattern: if the external binary is absent the public entry-point returns
``{"status": "pending", ...}`` rather than raising.  Mirrors the sentinel
pattern used in ``kerf_fem.calculix_utils``.
"""
from kerf_silicon.bridges.yosys_bridge import synthesize, SynthResult  # noqa: F401

__all__ = ["synthesize", "SynthResult"]
