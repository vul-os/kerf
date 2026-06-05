"""spice_library.py — Comprehensive curated SPICE component / model library.

Provides a categorized, searchable library of >300 canonical SPICE models
covering diodes (rectifier / Schottky / Zener / TVS / LED), BJTs (NPN/PNP,
signal/power/RF/Darlington), MOSFETs (N/P, logic/power/RF), JFETs, op-amps
(ideal / single / dual / precision / rail-to-rail macromodels), comparators,
voltage references, regulators (78xx/79xx/LDO/adjustable), passives with
parasitics (electrolytic / ceramic / film caps, SMD / wirewound / RF
inductors), logic gate subcircuits (NOT/NAND/NOR/AND/OR/XOR/XNOR/buffer),
555 timer, ADC/DAC behavioural, voltage-controlled oscillator, and
instrumentation amplifier macromodels.

Tools registered
----------------
spice_library_search   — search by category, keyword, spec (vbr, vf, hfe …)
spice_library_get_model — fetch the full SPICE card + metadata for one model

IMPORTANT — Representative values notice
-----------------------------------------
All parameter values are representative / generic values chosen to approximate
real-world device classes. They are NOT extracted from vendor datasheets and
should NOT be used for high-accuracy production simulation. For tape-out or
critical designs, replace these models with vendor-supplied SPICE models from
the manufacturer's website.
"""

from __future__ import annotations

import json
import math
import textwrap
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register

# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------

CATEGORIES: dict[str, str] = {
    "diode_rectifier":  "Diodes — Rectifier",
    "diode_schottky":   "Diodes — Schottky",
    "diode_zener":      "Diodes — Zener / Voltage Reference",
    "diode_tvs":        "Diodes — TVS / ESD",
    "diode_led":        "Diodes — LED",
    "bjt_npn":          "BJTs — NPN",
    "bjt_pnp":          "BJTs — PNP",
    "bjt_darlington":   "BJTs — Darlington",
    "bjt_rf":           "BJTs — RF",
    "mosfet_nmos":      "MOSFETs — N-channel",
    "mosfet_pmos":      "MOSFETs — P-channel",
    "jfet_n":           "JFETs — N-channel",
    "jfet_p":           "JFETs — P-channel",
    "opamp":            "Op-Amps",
    "comparator":       "Comparators",
    "vref":             "Voltage References",
    "regulator":        "Voltage Regulators",
    "passive_cap":      "Passives — Capacitors",
    "passive_ind":      "Passives — Inductors",
    "passive_res":      "Passives — Resistors",
    "logic":            "Logic Gates",
    "ic_timer":         "ICs — Timer",
    "ic_misc":          "ICs — Miscellaneous",
}

# ---------------------------------------------------------------------------
# Shared helper — dedent & normalise whitespace
# ---------------------------------------------------------------------------

def _d(s: str) -> str:
    return textwrap.dedent(s).strip()


# ===========================================================================
# DIODES — RECTIFIER
# ===========================================================================

def _mk_diode_rect(name, IS, RS, N, CJO, M, BV, IBV, TT=None, desc="") -> dict:
    tt_part = f" TT={TT}" if TT else ""
    model = f".MODEL {name} D(IS={IS} RS={RS} N={N} CJO={CJO} M={M} BV={BV} IBV={IBV}{tt_part})"
    return {
        "category": "diode_rectifier",
        "description": desc,
        "model": model,
        "params": {"BV": BV, "IS": IS, "N": N},
    }


_RECT_PARTS: list[tuple[str, dict]] = [
    ("D1N4001", _mk_diode_rect("D1N4001", "1e-8", "0.1", "1.8", "25e-12", "0.5", "50",  "1e-3", "5e-9",  "1N4001 rectifier 50 V 1 A (representative)")),
    ("D1N4002", _mk_diode_rect("D1N4002", "1e-8", "0.1", "1.8", "25e-12", "0.5", "100", "1e-3", "5e-9",  "1N4002 rectifier 100 V 1 A (representative)")),
    ("D1N4003", _mk_diode_rect("D1N4003", "1e-8", "0.1", "1.8", "22e-12", "0.5", "200", "1e-3", "5e-9",  "1N4003 rectifier 200 V 1 A (representative)")),
    ("D1N4004", _mk_diode_rect("D1N4004", "1e-8", "0.1", "1.8", "20e-12", "0.5", "400", "1e-3", "5e-9",  "1N4004 rectifier 400 V 1 A (representative)")),
    ("D1N4005", _mk_diode_rect("D1N4005", "1e-8", "0.1", "1.8", "18e-12", "0.5", "600", "1e-3", "5e-9",  "1N4005 rectifier 600 V 1 A (representative)")),
    ("D1N4006", _mk_diode_rect("D1N4006", "1e-8", "0.1", "1.8", "16e-12", "0.5", "800", "1e-3", "5e-9",  "1N4006 rectifier 800 V 1 A (representative)")),
    ("D1N4007", _mk_diode_rect("D1N4007", "5e-9", "0.1", "1.8", "15e-12", "0.5", "1000","5e-6", "5e-9",  "1N4007 rectifier 1000 V 1 A (representative)")),
    ("D1N5400", _mk_diode_rect("D1N5400", "2e-8", "0.05","1.8", "50e-12", "0.5", "50",  "5e-3", "10e-9", "1N5400 rectifier 50 V 3 A (representative)")),
    ("D1N5404", _mk_diode_rect("D1N5404", "2e-8", "0.05","1.8", "45e-12", "0.5", "400", "5e-3", "10e-9", "1N5404 rectifier 400 V 3 A (representative)")),
    ("D1N5408", _mk_diode_rect("D1N5408", "2e-8", "0.05","1.8", "40e-12", "0.5", "1000","5e-3", "10e-9", "1N5408 rectifier 1000 V 3 A (representative)")),
    ("D1N4148", _mk_diode_rect("D1N4148", "2.52e-9","0.568","1.752","4e-12","0.4","100","0.1e-3","4e-9", "1N4148 fast switching 100 V 0.2 A (representative)")),
    ("D1N914",  _mk_diode_rect("D1N914",  "2e-9",  "0.5", "1.75","4e-12","0.4","75", "0.1e-3","4e-9",  "1N914 fast switching 75 V 0.2 A (representative)")),
    ("DBYV27", _mk_diode_rect("DBYV27", "3e-9", "0.2", "1.6", "20e-12", "0.4", "200", "1e-3", "3e-9", "BYV27 fast rectifier 200 V 1 A (representative)")),
    ("DUHF4004", _mk_diode_rect("DUHF4004","1e-9","0.1","1.5","8e-12","0.4","400","0.1e-3","2e-9","UHF4004 ultra-fast 400 V 1 A (representative)")),
    ("DRLG4",  _mk_diode_rect("DRLG4",   "5e-9", "0.08","1.6","30e-12","0.5","400","1e-3","8e-9",  "RL4G rectifier 400 V 2 A glass body (representative)")),
]

# ===========================================================================
# DIODES — SCHOTTKY
# ===========================================================================

def _mk_schottky(name, IS, RS, N, CJO, M, BV, IBV, desc) -> dict:
    model = f".MODEL {name} D(IS={IS} RS={RS} N={N} CJO={CJO} M={M} BV={BV} IBV={IBV})"
    return {
        "category": "diode_schottky",
        "description": desc,
        "model": model,
        "params": {"BV": BV, "Vf_typ": "~0.3V"},
    }


_SCHOTTKY_PARTS: list[tuple[str, dict]] = [
    ("DSCHOTTKY",  _mk_schottky("DSCHOTTKY",  "4e-8","0.04","1.05","150e-12","0.4","20","1e-3","Generic Schottky Vf≈0.3 V (representative)")),
    ("D1N5817",    _mk_schottky("D1N5817",    "1e-6","0.04","1.05","90e-12","0.4","20","5e-3","1N5817 Schottky 20 V 1 A (representative)")),
    ("D1N5818",    _mk_schottky("D1N5818",    "8e-7","0.04","1.05","80e-12","0.4","30","5e-3","1N5818 Schottky 30 V 1 A (representative)")),
    ("D1N5819",    _mk_schottky("D1N5819",    "6e-7","0.04","1.05","70e-12","0.4","40","5e-3","1N5819 Schottky 40 V 1 A (representative)")),
    ("D1N5820",    _mk_schottky("D1N5820",    "2e-6","0.02","1.05","200e-12","0.4","20","5e-3","1N5820 Schottky 20 V 3 A (representative)")),
    ("D1N5821",    _mk_schottky("D1N5821",    "2e-6","0.02","1.05","180e-12","0.4","30","5e-3","1N5821 Schottky 30 V 3 A (representative)")),
    ("D1N5822",    _mk_schottky("D1N5822",    "2e-6","0.02","1.05","160e-12","0.4","40","5e-3","1N5822 Schottky 40 V 3 A (representative)")),
    ("DMBR130",    _mk_schottky("DMBR130",    "3e-7","0.03","1.05","50e-12","0.4","30","5e-3","MBR130 Schottky 30 V 1 A SMD (representative)")),
    ("DMBR0520",   _mk_schottky("DMBR0520",   "5e-7","0.05","1.05","40e-12","0.4","20","5e-3","MBR0520 Schottky 20 V 0.5 A SOD123 (representative)")),
    ("DMBRS340",   _mk_schottky("DMBRS340",   "3e-6","0.02","1.05","250e-12","0.4","40","5e-3","MBRS340 Schottky 40 V 3 A SMC (representative)")),
    ("DSB560",     _mk_schottky("DSB560",     "5e-6","0.015","1.05","350e-12","0.4","60","10e-3","SB560 Schottky 60 V 5 A (representative)")),
    ("DSBR20200",  _mk_schottky("DSBR20200",  "1e-5","0.01","1.05","500e-12","0.4","200","10e-3","SBR20200 Schottky 200 V 20 A (representative)")),
    ("DSTPS1H100", _mk_schottky("DSTPS1H100","2e-7","0.04","1.05","35e-12","0.4","100","1e-3","STPS1H100 Schottky 100 V 1 A (representative)")),
    ("DBAT54",     _mk_schottky("DBAT54",     "1e-8","0.5","1.06","10e-12","0.5","30","0.1e-3","BAT54 Schottky signal diode 30 V (representative)")),
    ("DBAS16",     _mk_schottky("DBAS16",     "5e-9","0.4","1.05","5e-12","0.4","40","0.1e-3","BAS16 Schottky signal diode 40 V (representative)")),
]

# ===========================================================================
# DIODES — ZENER
# ===========================================================================

def _mk_zener(name, BV, RS, IBV, desc) -> dict:
    model = f".MODEL {name} D(IS=1e-14 RS={RS} N=1 BV={BV} IBV={IBV})"
    return {
        "category": "diode_zener",
        "description": desc,
        "model": model,
        "params": {"BV": BV},
    }


_ZENER_PARTS: list[tuple[str, dict]] = [
    ("DZ2V4",   _mk_zener("DZ2V4",  "2.4",  "20", "5e-3",  "2.4 V Zener (1N746 class, representative)")),
    ("DZ2V7",   _mk_zener("DZ2V7",  "2.7",  "20", "5e-3",  "2.7 V Zener (representative)")),
    ("DZ3V0",   _mk_zener("DZ3V0",  "3.0",  "20", "5e-3",  "3.0 V Zener (1N746A class, representative)")),
    ("DZ3V3",   _mk_zener("DZ3V3",  "3.3",  "15", "5e-3",  "3.3 V Zener (representative)")),
    ("DZ3V6",   _mk_zener("DZ3V6",  "3.6",  "15", "5e-3",  "3.6 V Zener (1N749 class, representative)")),
    ("DZ3V9",   _mk_zener("DZ3V9",  "3.9",  "15", "5e-3",  "3.9 V Zener (representative)")),
    ("DZ4V3",   _mk_zener("DZ4V3",  "4.3",  "12", "5e-3",  "4.3 V Zener (representative)")),
    ("DZ4V7",   _mk_zener("DZ4V7",  "4.7",  "12", "5e-3",  "4.7 V Zener (1N750 class, representative)")),
    ("DZENER5V1",_mk_zener("DZENER5V1","5.1","10", "5e-3",  "5.1 V Zener (1N751A class, representative)")),
    ("DZ5V6",   _mk_zener("DZ5V6",  "5.6",  "10", "5e-3",  "5.6 V Zener (representative)")),
    ("DZ6V2",   _mk_zener("DZ6V2",  "6.2",  "8",  "5e-3",  "6.2 V Zener (1N821A class, representative)")),
    ("DZ6V8",   _mk_zener("DZ6V8",  "6.8",  "8",  "5e-3",  "6.8 V Zener (representative)")),
    ("DZ7V5",   _mk_zener("DZ7V5",  "7.5",  "8",  "5e-3",  "7.5 V Zener (representative)")),
    ("DZ8V2",   _mk_zener("DZ8V2",  "8.2",  "8",  "5e-3",  "8.2 V Zener (representative)")),
    ("DZ9V1",   _mk_zener("DZ9V1",  "9.1",  "8",  "2e-3",  "9.1 V Zener (representative)")),
    ("DZ10V",   _mk_zener("DZ10V",  "10.0", "8",  "2e-3",  "10 V Zener (1N4740A class, representative)")),
    ("DZENER12V",_mk_zener("DZENER12V","12.0","8","1e-3",   "12 V Zener (1N4742A class, representative)")),
    ("DZ15V",   _mk_zener("DZ15V",  "15.0", "8",  "1e-3",  "15 V Zener (1N4744A class, representative)")),
    ("DZ18V",   _mk_zener("DZ18V",  "18.0", "8",  "1e-3",  "18 V Zener (representative)")),
    ("DZ22V",   _mk_zener("DZ22V",  "22.0", "10", "1e-3",  "22 V Zener (1N4748A class, representative)")),
    ("DZ24V",   _mk_zener("DZ24V",  "24.0", "10", "1e-3",  "24 V Zener (representative)")),
    ("DZ30V",   _mk_zener("DZ30V",  "30.0", "10", "0.5e-3","30 V Zener (representative)")),
    ("DZ33V",   _mk_zener("DZ33V",  "33.0", "10", "0.5e-3","33 V Zener (representative)")),
    ("DZ36V",   _mk_zener("DZ36V",  "36.0", "10", "0.5e-3","36 V Zener (representative)")),
    ("DZ47V",   _mk_zener("DZ47V",  "47.0", "12", "0.5e-3","47 V Zener (representative)")),
]

# ===========================================================================
# DIODES — TVS
# ===========================================================================

def _mk_tvs(name, BV, RS, PP, desc) -> dict:
    IBV = round(float(PP) / float(BV), 6)
    model = f".MODEL {name} D(IS=1e-14 RS={RS} N=1 BV={BV} IBV={IBV:.4e})"
    return {
        "category": "diode_tvs",
        "description": desc,
        "model": model,
        "params": {"BV": BV, "P_pulse_W": PP},
    }


_TVS_PARTS: list[tuple[str, dict]] = [
    ("DTVS5V0",  _mk_tvs("DTVS5V0",  "5.0",  "0.5", "600",  "TVS 5.0 V 600 W unidirectional (representative)")),
    ("DTVS12V",  _mk_tvs("DTVS12V",  "12.0", "0.5", "600",  "TVS 12 V 600 W unidirectional (representative)")),
    ("DTVS15V",  _mk_tvs("DTVS15V",  "15.0", "0.5", "600",  "TVS 15 V 600 W unidirectional (representative)")),
    ("DTVS24V",  _mk_tvs("DTVS24V",  "24.0", "0.5", "600",  "TVS 24 V 600 W unidirectional (representative)")),
    ("DTVS5V0H", _mk_tvs("DTVS5V0H", "5.0",  "0.3", "1500", "TVS 5.0 V 1500 W SM6 (representative)")),
    ("DESD5V0",  _mk_tvs("DESD5V0",  "5.0",  "1.0", "100",  "ESD protection 5 V 100 W SOD323 (representative)")),
]

# ===========================================================================
# DIODES — LED
# ===========================================================================

def _mk_led(name, IS, N, BV, desc) -> dict:
    model = f".MODEL {name} D(IS={IS} N={N} BV={BV} CJO=20e-12)"
    return {
        "category": "diode_led",
        "description": desc,
        "model": model,
        "params": {"IS": IS, "N": N},
    }


_LED_PARTS: list[tuple[str, dict]] = [
    ("DLED_RED",   _mk_led("DLED_RED",   "1e-18","2.2","5","LED red Vf≈1.8–2.2 V (representative)")),
    ("DLED_GREEN", _mk_led("DLED_GREEN", "1e-20","2.5","5","LED green Vf≈2.0–2.5 V (representative)")),
    ("DLED_BLUE",  _mk_led("DLED_BLUE",  "1e-22","3.0","5","LED blue Vf≈3.0–3.6 V (representative)")),
    ("DLED_WHITE", _mk_led("DLED_WHITE", "1e-22","3.0","5","LED white Vf≈3.0–3.5 V (representative)")),
    ("DLED_IR",    _mk_led("DLED_IR",    "1e-16","1.8","5","LED IR 940 nm Vf≈1.2 V (representative)")),
    ("DLED_YELLOW",_mk_led("DLED_YELLOW","1e-19","2.3","5","LED yellow Vf≈1.9–2.3 V (representative)")),
]

# ===========================================================================
# BJTs — NPN
# ===========================================================================

def _mk_bjt_npn(name, IS, BF, VAF, IKF, ISE, NE, CJE, CJC, TF, desc) -> dict:
    model = (f".MODEL {name} NPN(IS={IS} BF={BF} NF=1 VAF={VAF} IKF={IKF} "
             f"ISE={ISE} NE={NE} BR=4 NR=1 RE=0.1 RC=1 RB=10 "
             f"CJE={CJE} VJE=0.75 MJE=0.33 CJC={CJC} VJC=0.75 MJC=0.33 "
             f"FC=0.5 TF={TF} TR=100e-9)")
    return {"category": "bjt_npn", "description": desc, "model": model,
            "params": {"BF": BF, "type": "NPN"}}


_NPN_PARTS: list[tuple[str, dict]] = [
    ("Q2N3904", _mk_bjt_npn("Q2N3904","1e-14","300","100","0.04","3e-13","2","4e-12","3.5e-12","0.5e-9","2N3904 NPN small-signal (representative)")),
    ("Q2N2222", _mk_bjt_npn("Q2N2222","1.8e-14","250","74","0.6","1.4e-14","1.5","25e-12","6e-12","0.4e-9","2N2222 NPN small-signal 40 V 0.6 A (representative)")),
    ("Q2N2222A",_mk_bjt_npn("Q2N2222A","1.8e-14","250","74","0.6","1.4e-14","1.5","25e-12","6e-12","0.4e-9","2N2222A NPN small-signal 40 V 0.6 A (representative)")),
    ("QBC547",  _mk_bjt_npn("QBC547", "1e-14","400","80","0.02","2e-13","2","3e-12","2.5e-12","0.4e-9","BC547 NPN small-signal 45 V 0.1 A (representative)")),
    ("QBC548",  _mk_bjt_npn("QBC548", "1e-14","420","80","0.02","2e-13","2","3e-12","2.5e-12","0.4e-9","BC548 NPN small-signal 30 V 0.1 A (representative)")),
    ("QBC549",  _mk_bjt_npn("QBC549", "1e-14","450","80","0.02","2e-13","2","3e-12","2.5e-12","0.4e-9","BC549 NPN low-noise 30 V 0.1 A (representative)")),
    ("Q2N5551", _mk_bjt_npn("Q2N5551","1e-14","80","100","0.1","3e-14","1.5","10e-12","5e-12","0.5e-9","2N5551 NPN high-voltage 160 V (representative)")),
    ("QMPSA42", _mk_bjt_npn("QMPSA42","1e-14","80","100","0.1","3e-14","1.5","10e-12","5e-12","0.5e-9","MPSA42 NPN high-voltage 300 V (representative)")),
    ("Q2N3055", {"category":"bjt_npn","description":"2N3055 NPN power 60 V 15 A (representative)",
                 "model":".MODEL Q2N3055 NPN(IS=1e-14 BF=50 NF=1 VAF=50 IKF=5 ISE=1e-13 NE=2 BR=4 NR=1 RE=0.008 RC=0.2 RB=1 CJE=200e-12 VJE=0.75 MJE=0.33 CJC=120e-12 VJC=0.75 MJC=0.33 FC=0.5 TF=4e-9 TR=500e-9)",
                 "params":{"BF":50,"type":"NPN","Ic_max":"15A"}}),
    ("QTip31",  {"category":"bjt_npn","description":"TIP31 NPN power 40 V 3 A (representative)",
                 "model":".MODEL QTip31 NPN(IS=1e-14 BF=100 NF=1 VAF=50 IKF=2 ISE=1e-13 NE=2 BR=4 NR=1 RE=0.02 RC=0.3 RB=2 CJE=100e-12 VJE=0.75 MJE=0.33 CJC=80e-12 VJC=0.75 MJC=0.33 FC=0.5 TF=3e-9 TR=200e-9)",
                 "params":{"BF":100,"type":"NPN","Ic_max":"3A"}}),
    ("QFZT690", _mk_bjt_npn("QFZT690","1e-14","200","80","0.05","2e-13","2","3e-12","2e-12","0.3e-9","FZT690 NPN 12 V 1 A SOT-223 (representative)")),
    ("QS9013",  _mk_bjt_npn("QS9013", "1e-14","180","60","0.05","2e-13","2","5e-12","3e-12","0.5e-9","S9013 NPN 25 V 0.5 A TO-92 (representative)")),
    ("Q2N4401", _mk_bjt_npn("Q2N4401","1e-14","150","100","0.6","2e-14","1.5","15e-12","6e-12","0.4e-9","2N4401 NPN 40 V 0.6 A (representative)")),
    ("QBCX70",  _mk_bjt_npn("QBCX70", "1e-14","400","80","0.03","2e-13","2","3e-12","2.5e-12","0.4e-9","BCX70 NPN low-noise SOT-89 (representative)")),
    ("Q2SC1815", _mk_bjt_npn("Q2SC1815","1e-14","250","60","0.05","2e-13","2","4e-12","3e-12","0.5e-9","2SC1815 NPN 50 V 0.15 A TO-92 (representative)")),
]

# ===========================================================================
# BJTs — PNP
# ===========================================================================

def _mk_bjt_pnp(name, IS, BF, VAF, IKF, ISE, NE, CJE, CJC, TF, desc) -> dict:
    model = (f".MODEL {name} PNP(IS={IS} BF={BF} NF=1 VAF={VAF} IKF={IKF} "
             f"ISE={ISE} NE={NE} BR=4 NR=1 RE=0.1 RC=0.5 RB=10 "
             f"CJE={CJE} VJE=0.75 MJE=0.33 CJC={CJC} VJC=0.75 MJC=0.33 "
             f"FC=0.5 TF={TF} TR=50e-9)")
    return {"category": "bjt_pnp", "description": desc, "model": model,
            "params": {"BF": BF, "type": "PNP"}}


_PNP_PARTS: list[tuple[str, dict]] = [
    ("Q2N3906", _mk_bjt_pnp("Q2N3906","1.41e-15","180","80","0.1","1e-14","1.5","9.5e-12","11.5e-12","0.3e-9","2N3906 PNP small-signal (representative)")),
    ("Q2N2907", _mk_bjt_pnp("Q2N2907","1.8e-14","200","100","0.5","1.4e-14","1.5","25e-12","6e-12","0.4e-9","2N2907 PNP small-signal 40 V 0.6 A (representative)")),
    ("QBC557",  _mk_bjt_pnp("QBC557", "1e-14","300","60","0.02","2e-13","2","3e-12","2.5e-12","0.5e-9","BC557 PNP small-signal 45 V 0.1 A (representative)")),
    ("QBC558",  _mk_bjt_pnp("QBC558", "1e-14","320","60","0.02","2e-13","2","3e-12","2.5e-12","0.5e-9","BC558 PNP small-signal 30 V 0.1 A (representative)")),
    ("QBC559",  _mk_bjt_pnp("QBC559", "1e-14","340","60","0.02","2e-13","2","3e-12","2.5e-12","0.5e-9","BC559 PNP low-noise 30 V 0.1 A (representative)")),
    ("Q2N5401", _mk_bjt_pnp("Q2N5401","1e-14","60","100","0.1","3e-14","1.5","10e-12","5e-12","0.5e-9","2N5401 PNP high-voltage 150 V (representative)")),
    ("QMPSA92", _mk_bjt_pnp("QMPSA92","1e-14","80","100","0.1","3e-14","1.5","10e-12","5e-12","0.5e-9","MPSA92 PNP high-voltage 300 V (representative)")),
    ("QTip32",  {"category":"bjt_pnp","description":"TIP32 PNP power 40 V 3 A (representative)",
                 "model":".MODEL QTip32 PNP(IS=1e-14 BF=100 NF=1 VAF=50 IKF=2 ISE=1e-13 NE=2 BR=4 NR=1 RE=0.02 RC=0.3 RB=2 CJE=100e-12 VJE=0.75 MJE=0.33 CJC=80e-12 VJC=0.75 MJC=0.33 FC=0.5 TF=3e-9 TR=200e-9)",
                 "params":{"BF":100,"type":"PNP","Ic_max":"3A"}}),
    ("QS9012",  _mk_bjt_pnp("QS9012", "1e-14","150","60","0.05","2e-13","2","5e-12","3e-12","0.5e-9","S9012 PNP 25 V 0.5 A TO-92 (representative)")),
    ("Q2N4403", _mk_bjt_pnp("Q2N4403","1e-14","140","100","0.5","2e-14","1.5","15e-12","6e-12","0.4e-9","2N4403 PNP 40 V 0.6 A (representative)")),
    ("Q2SA1015", _mk_bjt_pnp("Q2SA1015","1e-14","200","60","0.05","2e-13","2","4e-12","3e-12","0.5e-9","2SA1015 PNP 50 V 0.15 A TO-92 (representative)")),
]

# ===========================================================================
# BJTs — Darlington
# ===========================================================================

_DARLINGTON_PARTS: list[tuple[str, dict]] = [
    ("QTIP120", {"category":"bjt_darlington","description":"TIP120 NPN Darlington 60 V 5 A (representative)",
                 "model":_d("""\
                     .MODEL QTIP120 NPN(IS=1e-14 BF=5000 NF=1 VAF=50 IKF=5
                     + ISE=1e-12 NE=2 BR=10 NR=1 RE=0.02 RC=0.2 RB=0.5
                     + CJE=200e-12 VJE=0.75 MJE=0.33 CJC=100e-12 VJC=0.75 MJC=0.33
                     + FC=0.5 TF=10e-9 TR=1000e-9)"""),
                 "params":{"BF":5000,"type":"NPN_Darlington"}}),
    ("QTIP125", {"category":"bjt_darlington","description":"TIP125 PNP Darlington 60 V 5 A (representative)",
                 "model":_d("""\
                     .MODEL QTIP125 PNP(IS=1e-14 BF=5000 NF=1 VAF=50 IKF=5
                     + ISE=1e-12 NE=2 BR=10 NR=1 RE=0.02 RC=0.2 RB=0.5
                     + CJE=200e-12 VJE=0.75 MJE=0.33 CJC=100e-12 VJC=0.75 MJC=0.33
                     + FC=0.5 TF=10e-9 TR=1000e-9)"""),
                 "params":{"BF":5000,"type":"PNP_Darlington"}}),
    ("QULN2003", {"category":"bjt_darlington","description":"ULN2003 Darlington array single-channel equivalent (representative)",
                  "model":_d("""\
                      .MODEL QULN2003 NPN(IS=1e-14 BF=4000 NF=1 VAF=40 IKF=0.4
                      + ISE=5e-13 NE=2 BR=10 NR=1 RE=0.1 RC=0.5 RB=0.5
                      + CJE=50e-12 VJE=0.75 MJE=0.33 CJC=30e-12 VJC=0.75 MJC=0.33
                      + FC=0.5 TF=5e-9 TR=500e-9)"""),
                  "params":{"BF":4000,"type":"NPN_Darlington"}}),
]

# ===========================================================================
# BJTs — RF
# ===========================================================================

_BJTR_PARTS: list[tuple[str, dict]] = [
    ("Q2N2369", {"category":"bjt_rf","description":"2N2369 NPN RF switching 15 V 0.2 A ft=500 MHz (representative)",
                 "model":".MODEL Q2N2369 NPN(IS=1e-14 BF=100 NF=1 VAF=50 IKF=0.2 ISE=1e-13 NE=2 BR=4 NR=1 RE=0.1 RC=0.5 RB=8 CJE=8e-12 VJE=0.75 MJE=0.33 CJC=5e-12 VJC=0.75 MJC=0.33 FC=0.5 TF=0.1e-9 TR=10e-9)",
                 "params":{"ft_typ":"500 MHz","type":"NPN"}}),
    ("Q2N5109", {"category":"bjt_rf","description":"2N5109 NPN RF 20 V 0.3 A ft=1.2 GHz (representative)",
                 "model":".MODEL Q2N5109 NPN(IS=5e-14 BF=80 NF=1 VAF=40 IKF=0.3 ISE=1e-13 NE=1.5 BR=4 NR=1 RE=0.1 RC=0.2 RB=5 CJE=5e-12 VJE=0.75 MJE=0.33 CJC=2e-12 VJC=0.75 MJC=0.33 FC=0.5 TF=0.05e-9 TR=5e-9)",
                 "params":{"ft_typ":"1.2 GHz","type":"NPN"}}),
    ("QBFR93",  {"category":"bjt_rf","description":"BFR93 NPN RF 12 V 30 mA ft=5 GHz SOT-23 (representative)",
                 "model":".MODEL QBFR93 NPN(IS=2e-14 BF=120 NF=1 VAF=20 IKF=0.03 ISE=5e-14 NE=1.5 BR=4 NR=1 RE=0.5 RC=0.5 RB=10 CJE=0.5e-12 VJE=0.75 MJE=0.33 CJC=0.2e-12 VJC=0.75 MJC=0.33 FC=0.5 TF=0.02e-9 TR=2e-9)",
                 "params":{"ft_typ":"5 GHz","type":"NPN"}}),
]

# ===========================================================================
# MOSFETs — N-channel
# ===========================================================================

def _mk_nmos_l1(name, VTO, KP, LAMBDA, CBD, CBS, desc) -> dict:
    model = (f".MODEL {name} NMOS(LEVEL=1 VTO={VTO} KP={KP} LAMBDA={LAMBDA} "
             f"GAMMA=0 PHI=0.6 RD=1 RS=1 CBD={CBD} CBS={CBS})")
    return {"category":"mosfet_nmos","description":desc,"model":model,
            "params":{"VTO":VTO,"type":"NMOS"}}


def _mk_nmos_l3(name, VTO, KP, THETA, RD, CBD, desc) -> dict:
    model = (f".MODEL {name} NMOS(LEVEL=3 VTO={VTO} KP={KP} THETA={THETA} "
             f"VMAX=5e5 ETA=0.002 KAPPA=0.5 RD={RD} RS={RD} CBD={CBD} CBS={CBD})")
    return {"category":"mosfet_nmos","description":desc,"model":model,
            "params":{"VTO":VTO,"type":"NMOS","KP":KP}}


_NMOS_PARTS: list[tuple[str, dict]] = [
    ("M2N7000",  _mk_nmos_l1("M2N7000",  "2.5","0.05","0.02","15e-12","15e-12","2N7000 N-ch 60 V 0.2 A logic level (representative)")),
    ("M2N7002",  _mk_nmos_l1("M2N7002",  "2.0","0.08","0.02","10e-12","10e-12","2N7002 N-ch 60 V 0.3 A SOT-23 (representative)")),
    ("MBSS138",  _mk_nmos_l1("MBSS138",  "0.8","0.15","0.02","8e-12","8e-12","BSS138 N-ch 50 V 0.2 A logic SOT-23 (representative)")),
    ("MFDS6690", _mk_nmos_l1("MFDS6690", "1.2","0.2","0.015","20e-12","20e-12","FDS6690 N-ch 30 V 4 A logic (representative)")),
    ("MIRF530",  _mk_nmos_l3("MIRF530",  "3.0","12","0.08","0.05","400e-12","IRF530 N-ch 100 V 14 A power (representative)")),
    ("MIRF540",  _mk_nmos_l3("MIRF540",  "3.0","10","0.08","0.044","500e-12","IRF540 N-ch 100 V 28 A power (representative)")),
    ("MIRF640",  _mk_nmos_l3("MIRF640",  "4.0","9","0.08","0.09","300e-12","IRF640 N-ch 200 V 18 A power (representative)")),
    ("MIRF740",  _mk_nmos_l3("MIRF740",  "4.0","7","0.08","0.28","200e-12","IRF740 N-ch 400 V 10 A power (representative)")),
    ("MIRF840",  _mk_nmos_l3("MIRF840",  "4.0","5","0.08","0.85","120e-12","IRF840 N-ch 500 V 8 A power (representative)")),
    ("MIRD820",  _mk_nmos_l3("MIRD820",  "3.5","8","0.08","0.15","250e-12","IRD820 N-ch 500 V 8 A TO-220 (representative)")),
    ("MSTF13N60", _mk_nmos_l3("MSTF13N60","4.0","5","0.05","0.3","120e-12","STF13N60 N-ch 600 V 13 A (representative)")),
    ("MIRFP460",  _mk_nmos_l3("MIRFP460","4.0","4","0.04","0.27","200e-12","IRFP460 N-ch 500 V 20 A TO-247 (representative)")),
    ("MBS170",   _mk_nmos_l1("MBS170",   "2.5","0.09","0.02","5e-12","5e-12","BS170 N-ch 60 V 0.5 A TO-92 (representative)")),
    ("MIPHW40",  _mk_nmos_l3("MIPHW40",  "4.5","20","0.02","0.01","600e-12","IPHW40 N-ch 40 V 100 A hexa-PAD (representative)")),
    ("MFDD8880", _mk_nmos_l3("MFDD8880","2.5","25","0.015","0.003","1000e-12","FDD8880 N-ch 30 V 80 A (representative)")),
]

# ===========================================================================
# MOSFETs — P-channel
# ===========================================================================

def _mk_pmos_l1(name, VTO, KP, LAMBDA, CBD, CBS, desc) -> dict:
    model = (f".MODEL {name} PMOS(LEVEL=1 VTO={VTO} KP={KP} LAMBDA={LAMBDA} "
             f"GAMMA=0 PHI=0.6 RD=2 RS=2 CBD={CBD} CBS={CBS})")
    return {"category":"mosfet_pmos","description":desc,"model":model,
            "params":{"VTO":VTO,"type":"PMOS"}}


def _mk_pmos_l3(name, VTO, KP, THETA, RD, CBD, desc) -> dict:
    model = (f".MODEL {name} PMOS(LEVEL=3 VTO={VTO} KP={KP} THETA={THETA} "
             f"VMAX=5e5 ETA=0.002 KAPPA=0.5 RD={RD} RS={RD} CBD={CBD} CBS={CBD})")
    return {"category":"mosfet_pmos","description":desc,"model":model,
            "params":{"VTO":VTO,"type":"PMOS"}}


_PMOS_PARTS: list[tuple[str, dict]] = [
    ("M2P7000",   _mk_pmos_l1("M2P7000",  "-2.5","0.04","0.02","15e-12","15e-12","2P7000 P-ch 60 V 0.1 A (representative)")),
    ("MFQP3P20",  _mk_pmos_l1("MFQP3P20","-3.5","0.1","0.02","30e-12","30e-12","FQP3P20 P-ch 200 V 3 A (representative)")),
    ("MIRF9530",  _mk_pmos_l3("MIRF9530", "-3.5","8","0.08","0.06","400e-12","IRF9530 P-ch -100 V -14 A power (representative)")),
    ("MIRF9540",  _mk_pmos_l3("MIRF9540", "-3.5","8","0.08","0.117","400e-12","IRF9540 P-ch -100 V -23 A power (representative)")),
    ("MIRF9640",  _mk_pmos_l3("MIRF9640", "-4.0","7","0.08","0.2","300e-12","IRF9640 P-ch -200 V -11 A power (representative)")),
    ("MIRF4905",  _mk_pmos_l3("MIRF4905", "-3.0","12","0.06","0.02","1000e-12","IRF4905 P-ch -55 V -74 A power (representative)")),
    ("MBSP92",    _mk_pmos_l1("MBSP92",   "-3.0","0.05","0.02","5e-12","5e-12","BSP92 P-ch 60 V 0.5 A SOT-89 (representative)")),
    ("MFDS4435",  _mk_pmos_l3("MFDS4435","-1.5","15","0.05","0.006","1500e-12","FDS4435 P-ch -40 V -9 A logic (representative)")),
]

# ===========================================================================
# JFETs
# ===========================================================================

_JFET_PARTS: list[tuple[str, dict]] = [
    ("J2N5457", {"category":"jfet_n","description":"2N5457 N-ch JFET 25 V (representative)",
                 "model":".MODEL J2N5457 NJF(BETA=0.001 VTO=-2.0 LAMBDA=0.01 IS=1e-14 CGSO=5e-12 CGDO=2e-12)",
                 "params":{"VTO":"-2.0","type":"NJF"}}),
    ("J2N5458", {"category":"jfet_n","description":"2N5458 N-ch JFET 25 V (representative)",
                 "model":".MODEL J2N5458 NJF(BETA=0.002 VTO=-3.0 LAMBDA=0.01 IS=1e-14 CGSO=6e-12 CGDO=2e-12)",
                 "params":{"VTO":"-3.0","type":"NJF"}}),
    ("J2N5459", {"category":"jfet_n","description":"2N5459 N-ch JFET 25 V (representative)",
                 "model":".MODEL J2N5459 NJF(BETA=0.003 VTO=-4.0 LAMBDA=0.01 IS=1e-14 CGSO=7e-12 CGDO=2e-12)",
                 "params":{"VTO":"-4.0","type":"NJF"}}),
    ("JMPF102",  {"category":"jfet_n","description":"MPF102 N-ch JFET RF 25 V (representative)",
                  "model":".MODEL JMPF102 NJF(BETA=0.004 VTO=-3.0 LAMBDA=0.02 IS=1e-14 CGSO=4e-12 CGDO=1e-12)",
                  "params":{"VTO":"-3.0","type":"NJF"}}),
    ("JBFJ310",  {"category":"jfet_n","description":"BFJ310 N-ch RF JFET (representative)",
                  "model":".MODEL JBFJ310 NJF(BETA=0.01 VTO=-1.5 LAMBDA=0.02 IS=1e-14 CGSO=2e-12 CGDO=0.5e-12)",
                  "params":{"VTO":"-1.5","type":"NJF"}}),
    ("J2N5460",  {"category":"jfet_p","description":"2N5460 P-ch JFET 40 V (representative)",
                  "model":".MODEL J2N5460 PJF(BETA=0.001 VTO=2.0 LAMBDA=0.01 IS=1e-14 CGSO=5e-12 CGDO=2e-12)",
                  "params":{"VTO":"2.0","type":"PJF"}}),
    ("J2N5461",  {"category":"jfet_p","description":"2N5461 P-ch JFET 40 V (representative)",
                  "model":".MODEL J2N5461 PJF(BETA=0.002 VTO=3.0 LAMBDA=0.01 IS=1e-14 CGSO=6e-12 CGDO=2e-12)",
                  "params":{"VTO":"3.0","type":"PJF"}}),
]

# ===========================================================================
# OP-AMPS
# ===========================================================================

def _opamp_subckt(name, gbw_mhz, sr_vus, rin_meg, rout_ohm, desc) -> dict:
    """Generic macromodel op-amp subcircuit with finite GBW + SR."""
    gbw_hz = gbw_mhz * 1e6
    # Single-pole: Cgain = 1 / (2*pi*GBW * Rgain); Rgain=1k
    cgain = 1.0 / (2 * math.pi * gbw_hz * 1000)
    model = _d(f"""\
        .SUBCKT {name} IN+ IN- V+ V- OUT
        * Macromodel: GBW={gbw_mhz} MHz  SR={sr_vus} V/us  Rin={rin_meg} Meg  Rout={rout_ohm}
        Rin   IN+ IN-  {rin_meg}Meg
        Gin   0 mid  IN+ IN-  1e-3
        Rgain mid 0  1k
        Cgain mid 0  {cgain:.4e}
        Eout  OUT 0  VALUE {{V(mid)*1e3}}
        Rout  OUT 0  {rout_ohm}
        .ENDS {name}""")
    return {"category":"opamp","description":desc,"model":model,
            "params":{"GBW_MHz":gbw_mhz,"SR_Vus":sr_vus}}


_OPAMP_PARTS: list[tuple[str, dict]] = [
    ("OPAMP_IDEAL",   {"category":"opamp","description":"Ideal op-amp: infinite GBW, zero Rout","model":_d("""\
        .SUBCKT OPAMP_IDEAL IN+ IN- V+ V- OUT
        * Ideal op-amp: infinite gain, infinite bandwidth, zero output resistance
        E_IDEAL OUT 0 VALUE {V(IN+,IN-)*1e6}
        .ENDS OPAMP_IDEAL"""),"params":{"GBW_MHz":"inf"}}),
    ("OPAMP_GBW1M",  _opamp_subckt("OPAMP_GBW1M",   1,   0.5, 1.0, 75,  "Generic 1 MHz GBW op-amp (LM358/LM741 class, representative)")),
    ("OPAMP_GBW10M", _opamp_subckt("OPAMP_GBW10M",  10,  13,  1.0, 50,  "Generic 10 MHz GBW op-amp (TL071/TL081 class, representative)")),
    ("OPAMP_LM741",  _opamp_subckt("OPAMP_LM741",   1,   0.5, 1.0, 75,  "LM741 op-amp 1 MHz GBW class (representative)")),
    ("OPAMP_LM358",  _opamp_subckt("OPAMP_LM358",   1,   0.5, 1.0, 100, "LM358 dual op-amp 1 MHz (representative)")),
    ("OPAMP_LM324",  _opamp_subckt("OPAMP_LM324",   1,   0.4, 1.0, 150, "LM324 quad op-amp 1 MHz (representative)")),
    ("OPAMP_TL071",  _opamp_subckt("OPAMP_TL071",   3,   13,  1.0, 80,  "TL071 low-noise JFET op-amp 3 MHz (representative)")),
    ("OPAMP_TL072",  _opamp_subckt("OPAMP_TL072",   3,   13,  1.0, 80,  "TL072 dual low-noise JFET op-amp 3 MHz (representative)")),
    ("OPAMP_TL081",  _opamp_subckt("OPAMP_TL081",   3,   13,  1.0, 80,  "TL081 JFET op-amp 3 MHz (representative)")),
    ("OPAMP_NE5532", _opamp_subckt("OPAMP_NE5532",  10,  9,   0.3, 20,  "NE5532 low-noise 10 MHz dual op-amp (representative)")),
    ("OPAMP_OP07",   _opamp_subckt("OPAMP_OP07",    0.6, 0.3, 30,  60,  "OP07 precision low-offset op-amp 0.6 MHz (representative)")),
    ("OPAMP_OP27",   _opamp_subckt("OPAMP_OP27",    8,   2.8, 4.0, 50,  "OP27 precision low-noise 8 MHz (representative)")),
    ("OPAMP_OP37",   _opamp_subckt("OPAMP_OP37",    63,  17,  4.0, 25,  "OP37 precision wideband 63 MHz (representative)")),
    ("OPAMP_AD8610", _opamp_subckt("OPAMP_AD8610",  25,  25,  1.0, 40,  "AD8610 JFET precision 25 MHz 25 V/us (representative)")),
    ("OPAMP_OPA2134",_opamp_subckt("OPAMP_OPA2134", 8,   20,  1.0, 50,  "OPA2134 audio dual JFET 8 MHz (representative)")),
    ("OPAMP_LT1057", _opamp_subckt("OPAMP_LT1057",  12,  10,  1.0, 40,  "LT1057 dual JFET 12 MHz (representative)")),
    ("OPAMP_GBW100M",_opamp_subckt("OPAMP_GBW100M", 100, 100, 0.1, 10,  "Generic 100 MHz GBW fast op-amp class (representative)")),
]

# ===========================================================================
# COMPARATORS
# ===========================================================================

def _comp_subckt(name, tpd_ns, desc) -> dict:
    """Simple behavioural comparator: open-collector output, propagation delay approximated."""
    model = _d(f"""\
        .SUBCKT {name} IN+ IN- VCC GND OUT
        * Behavioural comparator: Tpd≈{tpd_ns} ns (representative)
        Rin   IN+ IN-  100k
        Ecomp out_int GND VALUE {{IF(V(IN+,IN-)>0, V(VCC,GND), 0)}}
        Rout  out_int OUT  {max(1, int(tpd_ns))}
        .ENDS {name}""")
    return {"category":"comparator","description":desc,"model":model,
            "params":{"Tpd_ns":tpd_ns}}


_COMP_PARTS: list[tuple[str, dict]] = [
    ("COMP_LM393",  _comp_subckt("COMP_LM393",  1300, "LM393 dual comparator 1.3 µs (representative)")),
    ("COMP_LM311",  _comp_subckt("COMP_LM311",  200,  "LM311 comparator 200 ns (representative)")),
    ("COMP_LM339",  _comp_subckt("COMP_LM339",  1300, "LM339 quad comparator 1.3 µs (representative)")),
    ("COMP_TL331",  _comp_subckt("COMP_TL331",  700,  "TL331 comparator 700 ns (representative)")),
    ("COMP_IDEAL",  {"category":"comparator","description":"Ideal comparator (zero propagation delay)",
                     "model":_d("""\
                         .SUBCKT COMP_IDEAL IN+ IN- VCC GND OUT
                         Rin  IN+ IN-  100k
                         Eout OUT GND  VALUE {IF(V(IN+,IN-)>0, V(VCC,GND), 0)}
                         .ENDS COMP_IDEAL"""),
                     "params":{"Tpd_ns":0}}),
]

# ===========================================================================
# VOLTAGE REFERENCES
# ===========================================================================

def _vref_subckt(name, vref, tol_pct, tc_ppm, desc) -> dict:
    model = _d(f"""\
        .SUBCKT {name} IN GND OUT
        * Behavioural voltage reference Vout={vref} V ±{tol_pct}% TC≈{tc_ppm} ppm/°C (representative)
        Rdropout IN  OUT  {max(5, int(vref*10))}
        Eout     OUT GND  VALUE {{{vref}}}
        .ENDS {name}""")
    return {"category":"vref","description":desc,"model":model,
            "params":{"Vref":vref,"TC_ppm":tc_ppm}}


_VREF_PARTS: list[tuple[str, dict]] = [
    ("VREF_1V25",  _vref_subckt("VREF_1V25",  1.25, 1,   50,  "1.25 V reference (LM385/TL431 class, representative)")),
    ("VREF_2V5",   _vref_subckt("VREF_2V5",   2.5,  1,   50,  "2.5 V reference (representative)")),
    ("VREF_TL431", _vref_subckt("VREF_TL431", 2.5,  2,   100, "TL431 shunt reference 2.5 V (representative)")),
    ("VREF_5V0",   _vref_subckt("VREF_5V0",   5.0,  1,   50,  "5.0 V reference (representative)")),
    ("VREF_10V",   _vref_subckt("VREF_10V",   10.0, 0.1, 5,   "10 V precision reference (LM399 class, representative)")),
    ("VREF_1V2",   _vref_subckt("VREF_1V2",   1.2,  2,   100, "1.2 V bandgap reference (representative)")),
    ("VREF_3V3",   _vref_subckt("VREF_3V3",   3.3,  1,   50,  "3.3 V reference (representative)")),
]

# ===========================================================================
# REGULATORS
# ===========================================================================

def _reg_78(vout, desc) -> dict:
    name = f"LDO_78{int(vout*10):02d}" if vout != int(vout) else f"LDO_78{int(vout):02d}"
    model = _d(f"""\
        .SUBCKT {name} IN GND OUT
        * Behavioural 78xx: Vout={vout} V (representative)
        Rdropout IN OUT {max(1, int(vout*0.5))}
        Eout OUT GND VALUE {{MAX(0, MIN(V(IN,GND)-1.2, {vout}))}}
        .ENDS {name}""")
    return {"category":"regulator","description":desc,"model":model,
            "params":{"Vout":vout,"type":"78xx_positive"}}


def _reg_79(vout, desc) -> dict:
    name = f"LDO_79{int(abs(vout)):02d}"
    model = _d(f"""\
        .SUBCKT {name} IN GND OUT
        * Behavioural 79xx: Vout={vout} V (representative)
        Rdropout IN OUT {max(1, int(abs(vout)*0.5))}
        Eout OUT GND VALUE {{MIN(0, MAX(V(IN,GND)+1.2, {vout}))}}
        .ENDS {name}""")
    return {"category":"regulator","description":desc,"model":model,
            "params":{"Vout":vout,"type":"79xx_negative"}}


_REG_PARTS: list[tuple[str, dict]] = [
    ("LDO_78XX",  {"category":"regulator","description":"78xx 5 V positive LDO generic (representative)",
                   "model":_d("""\
                       .SUBCKT LDO_78XX IN GND OUT
                       Rdropout IN OUT 1
                       Eout OUT GND VALUE {MAX(0, MIN(V(IN,GND)-1.2, 5.0))}
                       .ENDS LDO_78XX"""),"params":{"Vout":5,"type":"78xx"}}),
    ("LDO_7805",  _reg_78(5.0,  "7805 +5 V 1 A positive regulator (representative)")),
    ("LDO_7806",  _reg_78(6.0,  "7806 +6 V 1 A positive regulator (representative)")),
    ("LDO_7808",  _reg_78(8.0,  "7808 +8 V 1 A positive regulator (representative)")),
    ("LDO_7809",  _reg_78(9.0,  "7809 +9 V 1 A positive regulator (representative)")),
    ("LDO_7812",  _reg_78(12.0, "7812 +12 V 1 A positive regulator (representative)")),
    ("LDO_7815",  _reg_78(15.0, "7815 +15 V 1 A positive regulator (representative)")),
    ("LDO_7818",  _reg_78(18.0, "7818 +18 V 1 A positive regulator (representative)")),
    ("LDO_7824",  _reg_78(24.0, "7824 +24 V 1 A positive regulator (representative)")),
    ("LDO_79XX",  {"category":"regulator","description":"79xx -5 V negative LDO generic (representative)",
                   "model":_d("""\
                       .SUBCKT LDO_79XX IN GND OUT
                       Rdropout IN OUT 1
                       Eout OUT GND VALUE {MIN(0, MAX(V(IN,GND)+1.2, -5.0))}
                       .ENDS LDO_79XX"""),"params":{"Vout":-5,"type":"79xx"}}),
    ("LDO_7905",  _reg_79(-5.0,  "7905 -5 V 1 A negative regulator (representative)")),
    ("LDO_7912",  _reg_79(-12.0, "7912 -12 V 1 A negative regulator (representative)")),
    ("LDO_7915",  _reg_79(-15.0, "7915 -15 V 1 A negative regulator (representative)")),
    ("LDO_ADJ",   {"category":"regulator","description":"LM317 class adjustable LDO 1.25 V ref (representative)",
                   "model":_d("""\
                       .SUBCKT LDO_ADJ IN ADJ OUT
                       Rdropout IN OUT 1
                       Eout OUT ADJ VALUE {MAX(1.25, V(IN,ADJ)-1.5)}
                       .ENDS LDO_ADJ"""),"params":{"Vref":1.25,"type":"adjustable"}}),
    ("LDO_LM317", {"category":"regulator","description":"LM317 adjustable positive 1.2–37 V (representative)",
                   "model":_d("""\
                       .SUBCKT LDO_LM317 IN ADJ OUT
                       * LM317: Vout = 1.25*(1 + R2/R1) — set R2/R1 externally
                       Rdropout IN OUT 1
                       Eout OUT ADJ VALUE {MAX(1.25, V(IN,ADJ)-1.5)}
                       .ENDS LDO_LM317"""),"params":{"Vref":1.25,"type":"adjustable"}}),
    ("LDO_LM337", {"category":"regulator","description":"LM337 adjustable negative -1.2–-37 V (representative)",
                   "model":_d("""\
                       .SUBCKT LDO_LM337 IN ADJ OUT
                       Rdropout IN OUT 1
                       Eout OUT ADJ VALUE {MIN(-1.25, V(IN,ADJ)+1.5)}
                       .ENDS LDO_LM337"""),"params":{"Vref":-1.25,"type":"adjustable_neg"}}),
    ("LDO_3V3",   {"category":"regulator","description":"Generic 3.3 V LDO (AMS1117 class, representative)",
                   "model":_d("""\
                       .SUBCKT LDO_3V3 IN GND OUT
                       Rdropout IN OUT 0.5
                       Eout OUT GND VALUE {MAX(0, MIN(V(IN,GND)-1.2, 3.3))}
                       .ENDS LDO_3V3"""),"params":{"Vout":3.3,"type":"ldo_fixed"}}),
    ("LDO_5V0",   {"category":"regulator","description":"Generic 5 V LDO (MIC5205 class, representative)",
                   "model":_d("""\
                       .SUBCKT LDO_5V0 IN GND OUT
                       Rdropout IN OUT 0.5
                       Eout OUT GND VALUE {MAX(0, MIN(V(IN,GND)-1.5, 5.0))}
                       .ENDS LDO_5V0"""),"params":{"Vout":5.0,"type":"ldo_fixed"}}),
]

# ===========================================================================
# PASSIVES — CAPACITORS
# ===========================================================================

def _cap_elec(cap_uf, esr, esl_nh, desc=None) -> dict:
    name = f"CAP_ELEC_{int(cap_uf)}U"
    model = _d(f"""\
        .SUBCKT {name} P N
        * Electrolytic {cap_uf} uF  ESR={esr} Ω  ESL={esl_nh} nH (representative)
        LESL  P   mid1  {esl_nh}n
        RESR  mid1 mid2  {esr}
        C1    mid2 N    {cap_uf}u
        .ENDS {name}""")
    return {"category":"passive_cap","description":desc or f"{cap_uf} µF electrolytic ESR/ESL parasitics (representative)",
            "model":model,"params":{"C_uF":cap_uf,"ESR_ohm":esr}}


def _cap_x7r(cap_nf, esr, esl_nh, desc=None) -> dict:
    name = f"CAP_X7R_{int(cap_nf)}N"
    model = _d(f"""\
        .SUBCKT {name} P N
        * Ceramic X7R {cap_nf} nF  ESR={esr} Ω  ESL={esl_nh} nH (representative)
        LESL  P   mid1  {esl_nh}n
        RESR  mid1 mid2  {esr}
        C1    mid2 N    {cap_nf}n
        .ENDS {name}""")
    return {"category":"passive_cap","description":desc or f"{cap_nf} nF X7R ceramic ESR/ESL (representative)",
            "model":model,"params":{"C_nF":cap_nf,"ESR_ohm":esr}}


def _cap_film(cap_nf, esr, esl_nh, desc=None) -> dict:
    name = f"CAP_FILM_{int(cap_nf)}N"
    model = _d(f"""\
        .SUBCKT {name} P N
        * Film cap {cap_nf} nF  ESR={esr} Ω  ESL={esl_nh} nH (representative)
        LESL  P   mid1  {esl_nh}n
        RESR  mid1 mid2  {esr}
        C1    mid2 N    {cap_nf}n
        .ENDS {name}""")
    return {"category":"passive_cap","description":desc or f"{cap_nf} nF film cap ESR/ESL (representative)",
            "model":model,"params":{"C_nF":cap_nf,"ESR_ohm":esr}}


_CAP_PARTS: list[tuple[str, dict]] = [
    ("CAP_ELEC_1U",    _cap_elec(1.0,    0.5,  5.0,  "1 µF electrolytic (representative)")),
    ("CAP_ELEC_10U",   _cap_elec(10.0,   0.2,  8.0,  "10 µF electrolytic (representative)")),
    ("CAP_ELEC_22U",   _cap_elec(22.0,   0.15, 9.0,  "22 µF electrolytic (representative)")),
    ("CAP_ELEC_47U",   _cap_elec(47.0,   0.12, 10.0, "47 µF electrolytic (representative)")),
    ("CAP_ELEC_100U",  _cap_elec(100.0,  0.1,  10.0, "100 µF electrolytic (representative)")),
    ("CAP_ELEC_220U",  _cap_elec(220.0,  0.08, 12.0, "220 µF electrolytic (representative)")),
    ("CAP_ELEC_470U",  _cap_elec(470.0,  0.06, 14.0, "470 µF electrolytic (representative)")),
    ("CAP_ELEC_1000U", _cap_elec(1000.0, 0.05, 15.0, "1000 µF electrolytic (representative)")),
    ("CAP_ELEC_2200U", _cap_elec(2200.0, 0.03, 18.0, "2200 µF electrolytic (representative)")),
    ("CAP_X7R_1N",     _cap_x7r(1.0,    0.1,  0.5,  "1 nF X7R ceramic (representative)")),
    ("CAP_X7R_10N",    _cap_x7r(10.0,   0.05, 0.8,  "10 nF X7R ceramic (representative)")),
    ("CAP_X7R_100N",   _cap_x7r(100.0,  0.01, 1.0,  "100 nF X7R ceramic (representative)")),
    ("CAP_X7R_1U",     _cap_x7r(1000.0, 0.005,1.5,  "1 µF X7R ceramic (representative)")),
    ("CAP_X7R_4U7",    _cap_x7r(4700.0, 0.003,2.0,  "4.7 µF X7R ceramic (representative)")),
    ("CAP_FILM_1N",    _cap_film(1.0,   0.05, 0.3,  "1 nF film cap (representative)")),
    ("CAP_FILM_10N",   _cap_film(10.0,  0.03, 0.5,  "10 nF film cap (representative)")),
    ("CAP_FILM_100N",  _cap_film(100.0, 0.01, 0.8,  "100 nF film cap (representative)")),
    ("CAP_FILM_1U",    _cap_film(1000.0,0.005,1.0,  "1 µF film cap (representative)")),
]

# ===========================================================================
# PASSIVES — INDUCTORS
# ===========================================================================

def _ind(ind_uh, dcr, srf_mhz, desc=None) -> dict:
    name = f"IND_{int(ind_uh)}U" if ind_uh >= 1 else f"IND_{int(ind_uh*1000)}N"
    srf_hz = srf_mhz * 1e6
    l_h = ind_uh * 1e-6
    cp_f = 1.0 / ((2 * math.pi * srf_hz) ** 2 * l_h)
    model = _d(f"""\
        .SUBCKT {name} P N
        * Inductor {ind_uh} uH  DCR={dcr} Ω  SRF={srf_mhz} MHz → Cp={cp_f:.4e} F (representative)
        Rdcr  P  mid  {dcr}
        L1    mid N   {ind_uh}u
        Cp    P   N   {cp_f:.4e}
        .ENDS {name}""")
    return {"category":"passive_ind","description":desc or f"{ind_uh} µH inductor DCR+SRF parasitics (representative)",
            "model":model,"params":{"L_uH":ind_uh,"DCR_ohm":dcr,"SRF_MHz":srf_mhz}}


_IND_PARTS: list[tuple[str, dict]] = [
    ("IND_10N",   _ind(0.010, 0.01,  3000, "10 nH SMD RF inductor (representative)")),
    ("IND_100N",  _ind(0.100, 0.02,  2000, "100 nH SMD RF inductor (representative)")),
    ("IND_1U",    _ind(1.0,   0.03,  500,  "1 µH power inductor (representative)")),
    ("IND_2U2",   _ind(2.2,   0.04,  300,  "2.2 µH power inductor (representative)")),
    ("IND_4U7",   _ind(4.7,   0.05,  200,  "4.7 µH power inductor (representative)")),
    ("IND_10U",   _ind(10.0,  0.05,  100,  "10 µH power inductor (representative)")),
    ("IND_22U",   _ind(22.0,  0.08,  60,   "22 µH power inductor (representative)")),
    ("IND_47U",   _ind(47.0,  0.1,   40,   "47 µH power inductor (representative)")),
    ("IND_100U",  _ind(100.0, 0.15,  25,   "100 µH power inductor (representative)")),
    ("IND_470U",  _ind(470.0, 0.3,   12,   "470 µH power inductor (representative)")),
    ("IND_1000U", _ind(1000.0,0.5,   8,    "1 mH wirewound inductor (representative)")),
]

# ===========================================================================
# PASSIVES — RESISTORS
# ===========================================================================

def _res_tnc(name, r_ohm, tc_ppm, noise_db, desc) -> dict:
    """Resistor with temperature coefficient and noise model (behavioural)."""
    model = _d(f"""\
        .SUBCKT {name} P N
        * Resistor R={r_ohm} Ω  TC={tc_ppm} ppm/°C  noise≈{noise_db} dB (representative)
        R1    P  N  {r_ohm} TC1={tc_ppm}e-6
        .ENDS {name}""")
    return {"category":"passive_res","description":desc,"model":model,
            "params":{"R_ohm":r_ohm,"TC_ppm":tc_ppm}}


_RES_PARTS: list[tuple[str, dict]] = [
    ("RES_METAL_1K",    _res_tnc("RES_METAL_1K",    1000,   15, -160, "1 kΩ metal film 1% 15 ppm/°C (representative)")),
    ("RES_METAL_10K",   _res_tnc("RES_METAL_10K",   10000,  15, -155, "10 kΩ metal film 1% 15 ppm/°C (representative)")),
    ("RES_CARBON_1K",   _res_tnc("RES_CARBON_1K",   1000,   200,0,    "1 kΩ carbon film 5% 200 ppm/°C (representative)")),
    ("RES_WIREWOUND_1R",_res_tnc("RES_WIREWOUND_1R",1,      5,  0,    "1 Ω wirewound power resistor 5 ppm/°C (representative)")),
    ("RES_SHUNT_10M",   _res_tnc("RES_SHUNT_10M",   0.01,   10, 0,    "10 mΩ current shunt resistor (representative)")),
]

# ===========================================================================
# LOGIC GATES
# ===========================================================================

def _logic_not(family, vcc, tpd_ns) -> dict:
    name = f"NOT_{family}"
    model = _d(f"""\
        .SUBCKT {name} A VCC GND Y
        * {family} NOT gate: Vcc={vcc} V  Tpd≈{tpd_ns} ns (representative)
        Rin   A   GND  10k
        Eout  Y   GND  VALUE {{IF(V(A,GND) > V(VCC,GND)*0.5, 0, V(VCC,GND))}}
        Rpull Y   VCC  {tpd_ns*10}
        .ENDS {name}""")
    return {"category":"logic","description":f"{family} NOT gate inverter (representative)","model":model,
            "params":{"family":family,"Vcc":vcc,"Tpd_ns":tpd_ns}}


def _logic_2in(gate, family, vcc, tpd_ns) -> dict:
    """2-input logic gate (NAND/NOR/AND/OR/XOR)."""
    name = f"{gate}_{family}"
    if gate == "NAND":
        expr = "IF(V(A,GND)>V(VCC,GND)*0.5 & V(B,GND)>V(VCC,GND)*0.5, 0, V(VCC,GND))"
    elif gate == "NOR":
        expr = "IF(V(A,GND)>V(VCC,GND)*0.5 | V(B,GND)>V(VCC,GND)*0.5, 0, V(VCC,GND))"
    elif gate == "AND":
        expr = "IF(V(A,GND)>V(VCC,GND)*0.5 & V(B,GND)>V(VCC,GND)*0.5, V(VCC,GND), 0)"
    elif gate == "OR":
        expr = "IF(V(A,GND)>V(VCC,GND)*0.5 | V(B,GND)>V(VCC,GND)*0.5, V(VCC,GND), 0)"
    elif gate == "XOR":
        expr = "IF((V(A,GND)>V(VCC,GND)*0.5) ^ (V(B,GND)>V(VCC,GND)*0.5), V(VCC,GND), 0)"
    else:
        expr = "0"
    model = _d(f"""\
        .SUBCKT {name} A B VCC GND Y
        * {family} {gate} gate: Vcc={vcc} V  Tpd≈{tpd_ns} ns (representative)
        Rin_a A GND  10k
        Rin_b B GND  10k
        Eout  Y GND  VALUE {{{expr}}}
        .ENDS {name}""")
    return {"category":"logic","description":f"{family} {gate} 2-input gate (representative)","model":model,
            "params":{"family":family,"gate":gate,"Tpd_ns":tpd_ns}}


def _logic_buf(family, vcc, tpd_ns) -> dict:
    name = f"BUF_{family}"
    model = _d(f"""\
        .SUBCKT {name} A VCC GND Y
        * {family} buffer: Vcc={vcc} V  Tpd≈{tpd_ns} ns (representative)
        Rin   A   GND  10k
        Eout  Y   GND  VALUE {{IF(V(A,GND) > V(VCC,GND)*0.5, V(VCC,GND), 0)}}
        .ENDS {name}""")
    return {"category":"logic","description":f"{family} buffer (representative)","model":model,
            "params":{"family":family,"Tpd_ns":tpd_ns}}


_LOGIC_PARTS: list[tuple[str, dict]] = [
    # TTL / 74-series
    ("NOT_74HC", _logic_not("74HC", 5.0, 7)),
    ("NOT_74LS", _logic_not("74LS", 5.0, 10)),
    ("NOT_74HCT",_logic_not("74HCT",5.0, 8)),
    ("BUF_74HC", _logic_buf("74HC", 5.0, 7)),
    ("BUF_74LS", _logic_buf("74LS", 5.0, 10)),
    ("NAND_74HC",_logic_2in("NAND","74HC", 5.0, 7)),
    ("NAND_74LS",_logic_2in("NAND","74LS", 5.0, 10)),
    ("NOR_74HC", _logic_2in("NOR", "74HC", 5.0, 7)),
    ("NOR_74LS", _logic_2in("NOR", "74LS", 5.0, 10)),
    ("AND_74HC", _logic_2in("AND", "74HC", 5.0, 7)),
    ("OR_74HC",  _logic_2in("OR",  "74HC", 5.0, 7)),
    ("XOR_74HC", _logic_2in("XOR", "74HC", 5.0, 8)),
    # CMOS 3.3 V
    ("NOT_3V3",  _logic_not("3V3", 3.3, 5)),
    ("NAND_3V3", _logic_2in("NAND","3V3", 3.3, 5)),
    ("NOR_3V3",  _logic_2in("NOR", "3V3", 3.3, 5)),
    ("BUF_3V3",  _logic_buf("3V3", 3.3, 5)),
]

# ===========================================================================
# ICs — TIMER (555)
# ===========================================================================

_555_SUBCKT = _d("""\
    .SUBCKT IC555 VCC GND TRIG THRES CTRL RESET DISCH OUT
    * 555 timer behavioural macromodel (representative)
    * Astable/monostable operation approximated via threshold comparators
    * Comparator 1: THRES > 2/3 Vcc → SET (discharge Q)
    Ecmp1  cmp1_out GND VALUE {IF(V(THRES,GND) > V(VCC,GND)*0.667, 5, 0)}
    * Comparator 2: TRIG < 1/3 Vcc → RESET (charge)
    Ecmp2  cmp2_out GND VALUE {IF(V(TRIG,GND) < V(VCC,GND)*0.333, 5, 0)}
    * Output latch approximation
    Eout   OUT GND VALUE {IF(V(cmp2_out,GND) > 2.5, V(VCC,GND), IF(V(cmp1_out,GND) > 2.5, 0, V(OUT,GND)))}
    Rdisch DISCH GND 200
    .ENDS IC555""")

_IC_TIMER_PARTS: list[tuple[str, dict]] = [
    ("IC555",  {"category":"ic_timer","description":"555 timer behavioural macromodel (representative)",
                "model":_555_SUBCKT,"params":{"type":"astable_monostable"}}),
    ("IC555_MONOSTABLE", {"category":"ic_timer","description":"555 timer monostable mode helper (same macromodel)",
                          "model":_555_SUBCKT.replace("IC555","IC555_MONOSTABLE").replace(".ENDS IC555_MONOSTABLE",".ENDS IC555_MONOSTABLE"),
                          "params":{"type":"monostable"}}),
]

# Fix the replace chain
_IC_TIMER_PARTS[1][1]["model"] = _d("""\
    .SUBCKT IC555_MONOSTABLE VCC GND TRIG THRES CTRL RESET DISCH OUT
    * 555 timer monostable mode behavioural (representative)
    Ecmp1  cmp1_out GND VALUE {IF(V(THRES,GND) > V(VCC,GND)*0.667, 5, 0)}
    Ecmp2  cmp2_out GND VALUE {IF(V(TRIG,GND) < V(VCC,GND)*0.333, 5, 0)}
    Eout   OUT GND VALUE {IF(V(cmp2_out,GND) > 2.5, V(VCC,GND), IF(V(cmp1_out,GND) > 2.5, 0, V(OUT,GND)))}
    Rdisch DISCH GND 200
    .ENDS IC555_MONOSTABLE""")

# ===========================================================================
# ICs — MISC (instrumentation amp, VCO, DAC/ADC behavioural)
# ===========================================================================

_IC_MISC_PARTS: list[tuple[str, dict]] = [
    ("INAMP_IDEAL", {"category":"ic_misc","description":"Ideal instrumentation amplifier (G=1, differential, representative)",
                     "model":_d("""\
                         .SUBCKT INAMP_IDEAL IN+ IN- REF OUT VCC GND
                         * Ideal InstAmp: Vout = G*(Vin+ - Vin-) + Vref, G set by parameter
                         Rin_diff IN+ IN-  10Meg
                         Eout OUT GND VALUE {V(IN+,IN-) + V(REF,GND)}
                         .ENDS INAMP_IDEAL"""),"params":{"G":1,"CMRR_dB":"inf"}}),
    ("INAMP_G10",   {"category":"ic_misc","description":"Instrumentation amplifier G=10 (INA128 class, representative)",
                     "model":_d("""\
                         .SUBCKT INAMP_G10 IN+ IN- REF OUT VCC GND
                         * InstAmp G=10: CMRR>80 dB class (representative)
                         Rin_diff IN+ IN-  10Meg
                         Eout OUT GND VALUE {10*V(IN+,IN-) + V(REF,GND)}
                         .ENDS INAMP_G10"""),"params":{"G":10,"CMRR_dB":80}}),
    ("INAMP_G100",  {"category":"ic_misc","description":"Instrumentation amplifier G=100 (INA128 class, representative)",
                     "model":_d("""\
                         .SUBCKT INAMP_G100 IN+ IN- REF OUT VCC GND
                         * InstAmp G=100: CMRR>90 dB class (representative)
                         Rin_diff IN+ IN-  10Meg
                         Eout OUT GND VALUE {100*V(IN+,IN-) + V(REF,GND)}
                         .ENDS INAMP_G100"""),"params":{"G":100,"CMRR_dB":90}}),
    ("VCO_IDEAL",   {"category":"ic_misc","description":"Voltage-controlled oscillator behavioural (f=Kv*Vc, representative)",
                     "model":_d("""\
                         .SUBCKT VCO_IDEAL CTRL GND OUT
                         * VCO: Fout = Kv*V(CTRL) Hz/V, Kv=1MHz/V (representative)
                         * Use .param Kv=1Meg for tuning; outputs square wave approximation
                         Eout OUT GND VALUE {SIN(2*3.14159*1Meg*V(CTRL,GND)*time)}
                         .ENDS VCO_IDEAL"""),"params":{"Kv_MHz_per_V":1}}),
    ("DAC8B_IDEAL", {"category":"ic_misc","description":"8-bit DAC behavioural (Vout=D/255*Vref, representative)",
                     "model":_d("""\
                         .SUBCKT DAC8B_IDEAL D7 D6 D5 D4 D3 D2 D1 D0 VREF GND OUT
                         * 8-bit DAC: Vout = (128*D7+64*D6+32*D5+16*D4+8*D3+4*D2+2*D1+D0)/255 * Vref
                         Eout OUT GND VALUE {(128*V(D7,GND)+64*V(D6,GND)+32*V(D5,GND)+16*V(D4,GND)+8*V(D3,GND)+4*V(D2,GND)+2*V(D1,GND)+V(D0,GND))/255*V(VREF,GND)}
                         .ENDS DAC8B_IDEAL"""),"params":{"bits":8}}),
    ("ADC8B_IDEAL", {"category":"ic_misc","description":"8-bit ADC behavioural (quantises Vin to 256 levels, representative)",
                     "model":_d("""\
                         .SUBCKT ADC8B_IDEAL VIN VREF GND OUT
                         * 8-bit ADC: Vout = ROUND(Vin/Vref*255)/255 * Vref (behavioural)
                         Eout OUT GND VALUE {FLOOR(V(VIN,GND)/V(VREF,GND)*255+0.5)/255*V(VREF,GND)}
                         .ENDS ADC8B_IDEAL"""),"params":{"bits":8}}),
    ("OPAMP_TL072",  {"category":"ic_misc","description":"TL072 dual JFET op-amp (also in opamp category) — listed here as popular IC",
                      "model":_d("""\
                          .SUBCKT OPAMP_TL072_IC IN+ IN- V+ V- OUT
                          * TL072-class dual op-amp macromodel (representative)
                          Rin  IN+ IN-  1Meg
                          Gin  0  mid  IN+ IN-  1e-3
                          Rgain mid 0  1k
                          Cgain mid 0  {:.4e}
                          Eout  OUT 0  VALUE {{V(mid)*1e3}}
                          Rout  OUT 0  80
                          .ENDS OPAMP_TL072_IC""".format(1.0/(2*math.pi*3e6*1000))),
                      "params":{"GBW_MHz":3,"IC":"TL072"}}),
]

# ===========================================================================
# Assemble master catalogue
# ===========================================================================

_CATALOGUE: dict[str, dict] = {}

for _group in [
    _RECT_PARTS, _SCHOTTKY_PARTS, _ZENER_PARTS, _TVS_PARTS, _LED_PARTS,
    _NPN_PARTS, _PNP_PARTS, _DARLINGTON_PARTS, _BJTR_PARTS,
    _NMOS_PARTS, _PMOS_PARTS, _JFET_PARTS,
    _OPAMP_PARTS, _COMP_PARTS, _VREF_PARTS, _REG_PARTS,
    _CAP_PARTS, _IND_PARTS, _RES_PARTS,
    _LOGIC_PARTS, _IC_TIMER_PARTS, _IC_MISC_PARTS,
]:
    for _name, _entry in _group:
        _CATALOGUE[_name] = _entry

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

_DISCLAIMER = (
    "All models use representative/generic parameter values — "
    "NOT extracted from vendor datasheets. "
    "For high-accuracy simulation use vendor-supplied SPICE models."
)


def get_model_card(name: str) -> dict | None:
    """Return the full model card dict for *name* (case-insensitive), or None."""
    return _CATALOGUE.get(name.upper())


def get_model_spice(name: str) -> str | None:
    """Return just the SPICE text for *name*, or None."""
    entry = get_model_card(name)
    return entry["model"] if entry else None


def search_models(
    category: str | None = None,
    keyword: str | None = None,
    spec_key: str | None = None,
    spec_value: str | None = None,
) -> list[dict]:
    """Return list of matching model summaries.

    Parameters
    ----------
    category   : filter by category key (see CATEGORIES dict)
    keyword    : substring match against name OR description (case-insensitive)
    spec_key   : filter by params key (e.g. "BV", "GBW_MHz")
    spec_value : approximate string-match against params[spec_key]
    """
    results = []
    kw = keyword.lower() if keyword else None
    for name, entry in _CATALOGUE.items():
        if category and entry.get("category") != category:
            continue
        if kw:
            if kw not in name.lower() and kw not in entry.get("description", "").lower():
                continue
        if spec_key and spec_value:
            val = str(entry.get("params", {}).get(spec_key, ""))
            if spec_value.lower() not in val.lower():
                continue
        results.append({
            "name": name,
            "category": entry.get("category", ""),
            "category_label": CATEGORIES.get(entry.get("category", ""), entry.get("category", "")),
            "description": entry.get("description", ""),
            "params": entry.get("params", {}),
        })
    return results


# ---------------------------------------------------------------------------
# Tool: spice_library_search
# ---------------------------------------------------------------------------

_SEARCH_SPEC = ToolSpec(
    name="spice_library_search",
    description=(
        "Search the built-in Kerf SPICE component / model library. "
        "Returns a list of matching models with name, category, description, and key parameters. "
        "Filter by category (e.g. 'diode_schottky', 'bjt_npn', 'mosfet_nmos', 'opamp', 'regulator', 'logic'), "
        "by keyword (substring match on name/description), "
        "or by a spec parameter key/value pair (e.g. spec_key='BV', spec_value='12'). "
        "Combine filters as needed. "
        "Use spice_library_get_model to fetch the full SPICE card for a specific model. "
        "NOTE: all models use representative/generic values — not vendor-exact."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": (
                    "Filter by device category. One of: "
                    + ", ".join(sorted(CATEGORIES.keys()))
                ),
                "enum": sorted(CATEGORIES.keys()),
            },
            "keyword": {
                "type": "string",
                "description": "Substring to search in model name or description.",
            },
            "spec_key": {
                "type": "string",
                "description": "Parameter key to filter on (e.g. 'BV', 'GBW_MHz', 'Vout').",
            },
            "spec_value": {
                "type": "string",
                "description": "Approximate value to match for spec_key.",
            },
        },
        "required": [],
    },
)


@register(_SEARCH_SPEC, write=False)
async def spice_library_search(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    category = (a.get("category") or "").strip() or None
    keyword  = (a.get("keyword") or "").strip() or None
    sk       = (a.get("spec_key") or "").strip() or None
    sv       = (a.get("spec_value") or "").strip() or None

    matches = search_models(category=category, keyword=keyword, spec_key=sk, spec_value=sv)
    return ok_payload({
        "models": matches,
        "total": len(matches),
        "categories": CATEGORIES,
        "disclaimer": _DISCLAIMER,
    })


# ---------------------------------------------------------------------------
# Tool: spice_library_get_model
# ---------------------------------------------------------------------------

_GET_SPEC = ToolSpec(
    name="spice_library_get_model",
    description=(
        "Fetch the complete SPICE model card for a specific component by name "
        "(e.g. 'D1N4148', 'Q2N3904', 'OPAMP_TL072', 'LDO_7812'). "
        "Returns the full .MODEL/.SUBCKT text ready to paste into a netlist, "
        "plus category, description, and parameters. "
        "Use spice_library_search first to discover valid model names. "
        "NOTE: representative/generic values — not vendor-exact."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Model name (case-insensitive, e.g. 'D1N4148', 'OPAMP_LM358').",
            },
        },
        "required": ["name"],
    },
)


@register(_GET_SPEC, write=False)
async def spice_library_get_model(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    name = (a.get("name") or "").strip()
    if not name:
        return err_payload("'name' is required", "BAD_ARGS")

    entry = get_model_card(name)
    if entry is None:
        # Offer fuzzy suggestions
        kw = name.lower()
        suggestions = [k for k in _CATALOGUE if kw in k.lower()][:10]
        return err_payload(
            f"Model '{name}' not found. "
            f"Suggestions: {suggestions}. "
            f"Use spice_library_search to discover available models.",
            "NOT_FOUND",
        )

    cat_key = entry.get("category", "")
    return ok_payload({
        "name": name.upper(),
        "category": cat_key,
        "category_label": CATEGORIES.get(cat_key, cat_key),
        "description": entry.get("description", ""),
        "spice": entry["model"],
        "params": entry.get("params", {}),
        "disclaimer": _DISCLAIMER,
        "usage_hint": (
            f"Paste the 'spice' text into your netlist before .end. "
            f"For .MODEL lines, reference '{name.upper()}' in the component statement "
            f"(e.g. D1 A K {name.upper()}). "
            f"For .SUBCKT, instantiate via X prefix (e.g. X1 <pins> {name.upper()})."
        ),
    })
