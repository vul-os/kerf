"""
PCB trace current-capacity and copper-thermal design.

This module is distinct from:
  • kerf_electronics.protection  — fuse selection, Onderdonk fusing (thermal runaway)
  • kerf_electronics.pdn         — power-delivery network impedance / IR-drop
  • kerf_electronics.stackup     — controlled-impedance / transmission-line design
  • kerf_electronics.thermal     — component junction-to-board thermal paths

Covered topics
--------------
ampacity.py
    IPC-2152 steady-state trace current vs cross-section and allowable temp rise
    (internal / external, copper-weight, base-material k and board-thickness
    correction, copper-plane proximity factor).  Required trace width for a given
    current / ΔT.  Trace DC resistance, I²R power, voltage drop (with temperature
    coefficient of resistance).  Via current capacity and required number of vias.
    Thermal-via array thermal resistance.  Copper-plane sheet resistance, current
    density, and Onderdonk-based fusing margin (cross-check only).  Polygon-pour
    heatsink area for a target Rθ.  Busbar copper sizing.

All functions are pure Python (math module only) and follow the kerf never-raise
contract: validation errors are returned as dicts with {ok: False, reason: str};
over-temperature / undersized-trace / via-overcurrent conditions are flagged via
warnings.warn; exceptions are never raised to callers.
"""
