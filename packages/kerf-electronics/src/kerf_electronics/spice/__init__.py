"""kerf_electronics.spice — SPICE foundry-parity reference path.

Modules:
  bsim4_model     — BSIM4.8 compact MOSFET model (I-V + capacitance)
  corner_analysis — PVT / Monte-Carlo corner sweep
  netlist_codegen — Schematic graph → Spectre / ngspice / HSPICE netlist
  foundry_tools   — LLM tool wrappers for the above

HONEST DISCLAIMER: these implementations use the UC Berkeley BSIM4.8 public
reference equations and Pelgrom (1989) statistical matching.  They are NOT
equivalent to a commercial foundry PDK and must not be used for tape-out
sign-off.  They are suitable for design exploration and educational use.
"""
