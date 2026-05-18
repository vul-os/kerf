"""sky130/std_cells.py — SKY130 sky130_fd_sc_hd standard-cell library catalogue.

Data derived from the SkyWater PDK sky130_fd_sc_hd (high-density) cell
library characterisation data (Apache 2.0).

  https://github.com/google/skywater-pdk-libs-sky130_fd_sc_hd

Each entry:
  name          — full cell name  (sky130_fd_sc_hd__<cell>)
  function      — Boolean / sequential function description
  drive_strength — integer drive strength
  area_um2      — cell area in µm²
  leakage_pw    — typical leakage power in pW (nom corner)
  ports         — list of port names
"""

from __future__ import annotations

from typing import Dict, List, Optional

STD_CELLS: List[Dict] = [
    # ------------------------------------------------------------------
    # Inverters
    # ------------------------------------------------------------------
    {
        "name": "sky130_fd_sc_hd__inv_1",
        "function": "Y = !A",
        "drive_strength": 1,
        "area_um2": 1.742,
        "leakage_pw": 37.8,
        "ports": ["A", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__inv_2",
        "function": "Y = !A",
        "drive_strength": 2,
        "area_um2": 2.176,
        "leakage_pw": 57.3,
        "ports": ["A", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__inv_4",
        "function": "Y = !A",
        "drive_strength": 4,
        "area_um2": 3.480,
        "leakage_pw": 98.5,
        "ports": ["A", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__inv_8",
        "function": "Y = !A",
        "drive_strength": 8,
        "area_um2": 5.656,
        "leakage_pw": 172.0,
        "ports": ["A", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    # ------------------------------------------------------------------
    # NAND2
    # ------------------------------------------------------------------
    {
        "name": "sky130_fd_sc_hd__nand2_1",
        "function": "Y = !(A & B)",
        "drive_strength": 1,
        "area_um2": 2.176,
        "leakage_pw": 45.2,
        "ports": ["A", "B", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__nand2_2",
        "function": "Y = !(A & B)",
        "drive_strength": 2,
        "area_um2": 2.610,
        "leakage_pw": 68.9,
        "ports": ["A", "B", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__nand2_4",
        "function": "Y = !(A & B)",
        "drive_strength": 4,
        "area_um2": 4.352,
        "leakage_pw": 118.3,
        "ports": ["A", "B", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__nand2b_1",
        "function": "Y = !(!A & B)",
        "drive_strength": 1,
        "area_um2": 2.610,
        "leakage_pw": 50.6,
        "ports": ["A_N", "B", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__nand2b_2",
        "function": "Y = !(!A & B)",
        "drive_strength": 2,
        "area_um2": 3.480,
        "leakage_pw": 72.1,
        "ports": ["A_N", "B", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    # ------------------------------------------------------------------
    # NAND3 / NAND4
    # ------------------------------------------------------------------
    {
        "name": "sky130_fd_sc_hd__nand3_1",
        "function": "Y = !(A & B & C)",
        "drive_strength": 1,
        "area_um2": 2.610,
        "leakage_pw": 55.4,
        "ports": ["A", "B", "C", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__nand4_1",
        "function": "Y = !(A & B & C & D)",
        "drive_strength": 1,
        "area_um2": 3.480,
        "leakage_pw": 68.2,
        "ports": ["A", "B", "C", "D", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    # ------------------------------------------------------------------
    # NOR2
    # ------------------------------------------------------------------
    {
        "name": "sky130_fd_sc_hd__nor2_1",
        "function": "Y = !(A | B)",
        "drive_strength": 1,
        "area_um2": 2.176,
        "leakage_pw": 42.9,
        "ports": ["A", "B", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__nor2_2",
        "function": "Y = !(A | B)",
        "drive_strength": 2,
        "area_um2": 2.610,
        "leakage_pw": 64.7,
        "ports": ["A", "B", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__nor2b_1",
        "function": "Y = !(A | !B)",
        "drive_strength": 1,
        "area_um2": 2.610,
        "leakage_pw": 48.3,
        "ports": ["A", "B_N", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    # ------------------------------------------------------------------
    # AND2 / OR2
    # ------------------------------------------------------------------
    {
        "name": "sky130_fd_sc_hd__and2_1",
        "function": "X = A & B",
        "drive_strength": 1,
        "area_um2": 2.610,
        "leakage_pw": 52.1,
        "ports": ["A", "B", "X", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__and2_2",
        "function": "X = A & B",
        "drive_strength": 2,
        "area_um2": 3.480,
        "leakage_pw": 78.4,
        "ports": ["A", "B", "X", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__or2_1",
        "function": "X = A | B",
        "drive_strength": 1,
        "area_um2": 2.610,
        "leakage_pw": 53.8,
        "ports": ["A", "B", "X", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__or2_2",
        "function": "X = A | B",
        "drive_strength": 2,
        "area_um2": 3.480,
        "leakage_pw": 79.9,
        "ports": ["A", "B", "X", "VGND", "VNB", "VPB", "VPWR"],
    },
    # ------------------------------------------------------------------
    # XOR2 / XNOR2
    # ------------------------------------------------------------------
    {
        "name": "sky130_fd_sc_hd__xor2_1",
        "function": "X = A ^ B",
        "drive_strength": 1,
        "area_um2": 3.916,
        "leakage_pw": 82.6,
        "ports": ["A", "B", "X", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__xnor2_1",
        "function": "Y = !(A ^ B)",
        "drive_strength": 1,
        "area_um2": 3.916,
        "leakage_pw": 84.1,
        "ports": ["A", "B", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    # ------------------------------------------------------------------
    # D Flip-Flop (no reset)
    # ------------------------------------------------------------------
    {
        "name": "sky130_fd_sc_hd__dfxtp_1",
        "function": "Q = D (rising CLK)",
        "drive_strength": 1,
        "area_um2": 6.526,
        "leakage_pw": 145.0,
        "ports": ["CLK", "D", "Q", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__dfxtp_2",
        "function": "Q = D (rising CLK)",
        "drive_strength": 2,
        "area_um2": 8.702,
        "leakage_pw": 182.3,
        "ports": ["CLK", "D", "Q", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__dfxtp_4",
        "function": "Q = D (rising CLK)",
        "drive_strength": 4,
        "area_um2": 13.054,
        "leakage_pw": 261.7,
        "ports": ["CLK", "D", "Q", "VGND", "VNB", "VPB", "VPWR"],
    },
    # ------------------------------------------------------------------
    # D Flip-Flop with async reset
    # ------------------------------------------------------------------
    {
        "name": "sky130_fd_sc_hd__dfrtp_1",
        "function": "Q = D (rising CLK); async RESET_B=0 → Q=0",
        "drive_strength": 1,
        "area_um2": 8.702,
        "leakage_pw": 168.5,
        "ports": ["CLK", "D", "RESET_B", "Q", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__dfrtp_2",
        "function": "Q = D (rising CLK); async RESET_B=0 → Q=0",
        "drive_strength": 2,
        "area_um2": 10.878,
        "leakage_pw": 210.9,
        "ports": ["CLK", "D", "RESET_B", "Q", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__dfrtp_4",
        "function": "Q = D (rising CLK); async RESET_B=0 → Q=0",
        "drive_strength": 4,
        "area_um2": 15.230,
        "leakage_pw": 302.4,
        "ports": ["CLK", "D", "RESET_B", "Q", "VGND", "VNB", "VPB", "VPWR"],
    },
    # ------------------------------------------------------------------
    # MUX2
    # ------------------------------------------------------------------
    {
        "name": "sky130_fd_sc_hd__mux2_1",
        "function": "X = S ? B : A",
        "drive_strength": 1,
        "area_um2": 4.350,
        "leakage_pw": 92.3,
        "ports": ["A0", "A1", "S", "X", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__mux2_2",
        "function": "X = S ? B : A",
        "drive_strength": 2,
        "area_um2": 5.656,
        "leakage_pw": 124.7,
        "ports": ["A0", "A1", "S", "X", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__mux2i_1",
        "function": "Y = !(S ? B : A)",
        "drive_strength": 1,
        "area_um2": 3.916,
        "leakage_pw": 85.4,
        "ports": ["A0", "A1", "S", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    # ------------------------------------------------------------------
    # AND-OR-INVERT (AOI) / OAI compound gates
    # ------------------------------------------------------------------
    {
        "name": "sky130_fd_sc_hd__a21o_1",
        "function": "X = (A1 & A2) | B1",
        "drive_strength": 1,
        "area_um2": 3.480,
        "leakage_pw": 75.6,
        "ports": ["A1", "A2", "B1", "X", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__a21oi_1",
        "function": "Y = !((A1 & A2) | B1)",
        "drive_strength": 1,
        "area_um2": 3.046,
        "leakage_pw": 66.2,
        "ports": ["A1", "A2", "B1", "Y", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__a22o_1",
        "function": "X = (A1 & A2) | (B1 & B2)",
        "drive_strength": 1,
        "area_um2": 4.350,
        "leakage_pw": 90.1,
        "ports": ["A1", "A2", "B1", "B2", "X", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__o21a_1",
        "function": "X = (A1 | A2) & B1",
        "drive_strength": 1,
        "area_um2": 3.480,
        "leakage_pw": 73.9,
        "ports": ["A1", "A2", "B1", "X", "VGND", "VNB", "VPB", "VPWR"],
    },
    # ------------------------------------------------------------------
    # Buffer / Clock buffer
    # ------------------------------------------------------------------
    {
        "name": "sky130_fd_sc_hd__buf_1",
        "function": "X = A",
        "drive_strength": 1,
        "area_um2": 2.176,
        "leakage_pw": 33.1,
        "ports": ["A", "X", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__buf_2",
        "function": "X = A",
        "drive_strength": 2,
        "area_um2": 3.480,
        "leakage_pw": 52.4,
        "ports": ["A", "X", "VGND", "VNB", "VPB", "VPWR"],
    },
    {
        "name": "sky130_fd_sc_hd__clkbuf_1",
        "function": "X = A  (clock-optimised buffer)",
        "drive_strength": 1,
        "area_um2": 2.610,
        "leakage_pw": 38.7,
        "ports": ["A", "X", "VGND", "VNB", "VPB", "VPWR"],
    },
]

# ---------------------------------------------------------------------------
# Lookup helper
# ---------------------------------------------------------------------------

_CELL_BY_NAME: Dict[str, Dict] = {c["name"]: c for c in STD_CELLS}


def get_cell(name: str) -> Optional[Dict]:
    """Return a standard-cell dict by full name, or None if not found."""
    return _CELL_BY_NAME.get(name)
