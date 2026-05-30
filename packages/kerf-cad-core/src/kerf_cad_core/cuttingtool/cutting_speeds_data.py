"""
kerf_cad_core.cuttingtool.cutting_speeds_data
=============================================

Recommended cutting-speed data table: workpiece material × tool material ×
operation type → (sfm_min, sfm_typical, sfm_max, feed_lo, feed_hi,
feed_unit, notes).

Sources
-------
Machinery's Handbook, 31st ed., Industrial Press, §1100
  "Cutting Speeds and Feeds" (pp. 1075–1115).
Sandvik Coromant Cutting Data Recommendations, CoroKey 2023/2024.

Honest disclaimer
-----------------
This table is an **illustrative subset** intended to give first-pass guidance.
Production machining programs should validate against the tool manufacturer's
cutting-data application (e.g. Sandvik CoroPlus® ToolGuide, Kennametal
NOVO, or Iscar iMachining) which account for specific insert grade,
coating, coolant strategy, depth-of-cut and machine rigidity.

Units
-----
SFM  — surface feet per minute (divide by 3.281 to get m/min)
feed — IPT (inch per tooth) for milling; IPR (inch per rev) for turning,
       drilling and reaming.

Key encoding
------------
Each entry in CUTTING_SPEED_TABLE is a dict with the key tuple
(workpiece_key, tool_material_key, operation_key) mapping to a CutRecord
namedtuple.

Workpiece keys (20 materials):
  aluminum_6061, aluminum_7075, aluminum_cast,
  brass_360, brass_cast,
  steel_1018, steel_4140, steel_stainless_304, steel_stainless_316,
  steel_hardened_60hrc,
  cast_iron_gray, cast_iron_ductile,
  titanium_6al4v, titanium_cp,
  inconel_718,
  copper_c110,
  plastic_acetal, plastic_nylon, plastic_abs,
  magnesium_az31

Tool material keys (4):
  hss, carbide, ceramic, diamond

Operation keys (4):
  turning, milling, drilling, reaming

Author: imranparuk
"""

from __future__ import annotations

from typing import NamedTuple, Optional


class CutRecord(NamedTuple):
    """Raw cutting-data record for a workpiece × tool × operation combination."""
    sfm_min: float           # surface feet per minute — conservative start
    sfm_typical: float       # typical/recommended operating speed
    sfm_max: float           # aggressive upper bound (rigid setup, coolant)
    feed_lo: float           # lower feed bound (IPT for milling; IPR otherwise)
    feed_hi: float           # upper feed bound
    feed_unit: str           # 'ipt' | 'ipr'
    notes: str               # brief application note


# ---------------------------------------------------------------------------
# Table — 20 materials × 4 tool materials × 4 ops = 320 entries
# Not all material/tool combinations are practical; impractical combos are
# represented with sfm_min=sfm_typical=sfm_max=0 and a note explaining why.
# ---------------------------------------------------------------------------

_NA = CutRecord(0, 0, 0, 0, 0, "n/a",
                "Not recommended — see notes.")

CUTTING_SPEED_TABLE: dict[tuple[str, str, str], CutRecord] = {

    # =========================================================================
    # ALUMINUM 6061 — T6, hardness ~95 HRB
    # =========================================================================
    ("aluminum_6061", "hss",     "turning"):  CutRecord(300, 500,  700,  0.003, 0.015, "ipr",
        "HSS adequate for prototype; carbide preferred in production."),
    ("aluminum_6061", "hss",     "milling"):  CutRecord(250, 400,  600,  0.002, 0.008, "ipt",
        "HSS end-mill; use high-helix (45°) geometry."),
    ("aluminum_6061", "hss",     "drilling"): CutRecord(200, 300,  450,  0.003, 0.012, "ipr",
        "HSS twist drill; parabolic flute preferred for deep holes."),
    ("aluminum_6061", "hss",     "reaming"):  CutRecord(100, 150,  200,  0.005, 0.015, "ipr",
        "HSS reamer; use flood coolant."),

    ("aluminum_6061", "carbide", "turning"):  CutRecord(800, 1500, 2400, 0.003, 0.015, "ipr",
        "Uncoated or PCD insert; dry or MQL. MH31 §1100 Table 1."),
    ("aluminum_6061", "carbide", "milling"):  CutRecord(800, 1500, 2400, 0.001, 0.005, "ipt",
        "Uncoated K10/K20 grade; 3-flute geometry; MQL."),
    ("aluminum_6061", "carbide", "drilling"): CutRecord(400, 700,  1000, 0.003, 0.010, "ipr",
        "Solid carbide drill; split-point; flood or through-coolant."),
    ("aluminum_6061", "carbide", "reaming"):  CutRecord(200, 350,  500,  0.005, 0.020, "ipr",
        "Carbide reamer; 0.2–0.5 mm stock allowance."),

    ("aluminum_6061", "ceramic", "turning"):  CutRecord(1500, 2500, 4000, 0.003, 0.012, "ipr",
        "SiAlON / whisker-reinforced Al₂O₃; very rigid setup required."),
    ("aluminum_6061", "ceramic", "milling"):  CutRecord(1200, 2000, 3500, 0.001, 0.004, "ipt",
        "Ceramic rarely used for Al milling — carbide is preferred."),
    ("aluminum_6061", "ceramic", "drilling"): _NA._replace(notes="Ceramic drills too brittle for Al; use carbide."),
    ("aluminum_6061", "ceramic", "reaming"):  _NA._replace(notes="Ceramic reamers impractical for Al; use carbide."),

    ("aluminum_6061", "diamond", "turning"):  CutRecord(2000, 3500, 6000, 0.002, 0.008, "ipr",
        "PCD insert; mirror finish (Ra < 0.4 µm) achievable. Sandvik PCBN/PCD guide."),
    ("aluminum_6061", "diamond", "milling"):  CutRecord(1500, 3000, 5000, 0.001, 0.004, "ipt",
        "PCD end-mill; aerospace finishing; very low chip load."),
    ("aluminum_6061", "diamond", "drilling"): CutRecord(500,  900,  1400, 0.002, 0.008, "ipr",
        "PCD drill; recommended for Al-MMC or high-Si alloys."),
    ("aluminum_6061", "diamond", "reaming"):  CutRecord(300,  500,   800, 0.005, 0.020, "ipr",
        "PCD reamer; used in high-volume automotive Al bores."),

    # =========================================================================
    # ALUMINUM 7075 — T6, slightly harder than 6061 (~100 HRB)
    # =========================================================================
    ("aluminum_7075", "hss",     "turning"):  CutRecord(250,  450,  650,  0.003, 0.012, "ipr", ""),
    ("aluminum_7075", "hss",     "milling"):  CutRecord(200,  350,  550,  0.002, 0.007, "ipt", ""),
    ("aluminum_7075", "hss",     "drilling"): CutRecord(180,  280,  400,  0.003, 0.010, "ipr", ""),
    ("aluminum_7075", "hss",     "reaming"):  CutRecord( 80,  130,  180,  0.005, 0.012, "ipr", ""),
    ("aluminum_7075", "carbide", "turning"):  CutRecord(700, 1300, 2200, 0.003, 0.012, "ipr", ""),
    ("aluminum_7075", "carbide", "milling"):  CutRecord(700, 1300, 2200, 0.001, 0.004, "ipt", ""),
    ("aluminum_7075", "carbide", "drilling"): CutRecord(350,  600,  900,  0.003, 0.010, "ipr", ""),
    ("aluminum_7075", "carbide", "reaming"):  CutRecord(180,  300,  450,  0.005, 0.018, "ipr", ""),
    ("aluminum_7075", "ceramic", "turning"):  CutRecord(1200, 2200, 3500, 0.003, 0.010, "ipr", ""),
    ("aluminum_7075", "ceramic", "milling"):  CutRecord(1000, 1800, 3000, 0.001, 0.004, "ipt", ""),
    ("aluminum_7075", "ceramic", "drilling"): _NA._replace(notes="Ceramic drills brittle for Al; use carbide."),
    ("aluminum_7075", "ceramic", "reaming"):  _NA._replace(notes="Use carbide reamers for Al 7075."),
    ("aluminum_7075", "diamond", "turning"):  CutRecord(1800, 3200, 5500, 0.002, 0.007, "ipr", "PCD preferred for 7075."),
    ("aluminum_7075", "diamond", "milling"):  CutRecord(1400, 2700, 4500, 0.001, 0.003, "ipt", ""),
    ("aluminum_7075", "diamond", "drilling"): CutRecord(450,  800,  1300, 0.002, 0.007, "ipr", ""),
    ("aluminum_7075", "diamond", "reaming"):  CutRecord(280,  460,   720, 0.005, 0.018, "ipr", ""),

    # =========================================================================
    # ALUMINUM CAST (A380 die-cast, ~80 HRB)
    # =========================================================================
    ("aluminum_cast", "hss",     "turning"):  CutRecord(200,  350,  500,  0.004, 0.015, "ipr",
        "High-Si cast Al abrasive on tools; TiN-coated HSS recommended."),
    ("aluminum_cast", "hss",     "milling"):  CutRecord(150,  270,  420,  0.002, 0.007, "ipt", ""),
    ("aluminum_cast", "hss",     "drilling"): CutRecord(150,  250,  380,  0.003, 0.010, "ipr", ""),
    ("aluminum_cast", "hss",     "reaming"):  CutRecord( 70,  110,  160,  0.004, 0.012, "ipr", ""),
    ("aluminum_cast", "carbide", "turning"):  CutRecord(500,  900,  1500, 0.003, 0.012, "ipr", ""),
    ("aluminum_cast", "carbide", "milling"):  CutRecord(500,  900,  1500, 0.001, 0.004, "ipt", ""),
    ("aluminum_cast", "carbide", "drilling"): CutRecord(300,  500,   800, 0.003, 0.010, "ipr", ""),
    ("aluminum_cast", "carbide", "reaming"):  CutRecord(150,  260,   400, 0.004, 0.015, "ipr", ""),
    ("aluminum_cast", "ceramic", "turning"):  CutRecord(900, 1700,  2800, 0.002, 0.010, "ipr", ""),
    ("aluminum_cast", "ceramic", "milling"):  CutRecord(800, 1500,  2500, 0.001, 0.003, "ipt", ""),
    ("aluminum_cast", "ceramic", "drilling"): _NA._replace(notes="Ceramic drills impractical for cast Al; use carbide."),
    ("aluminum_cast", "ceramic", "reaming"):  _NA._replace(notes="Use carbide reamers."),
    ("aluminum_cast", "diamond", "turning"):  CutRecord(1500, 2800, 4500, 0.002, 0.007, "ipr",
        "PCD mandatory for high-Si cast Al (>12 % Si)."),
    ("aluminum_cast", "diamond", "milling"):  CutRecord(1200, 2400, 4000, 0.001, 0.003, "ipt", ""),
    ("aluminum_cast", "diamond", "drilling"): CutRecord(400,   700, 1100, 0.002, 0.007, "ipr", ""),
    ("aluminum_cast", "diamond", "reaming"):  CutRecord(250,   420,  660, 0.004, 0.015, "ipr", ""),

    # =========================================================================
    # BRASS 360 (Free-cutting, ~68 HRB)
    # =========================================================================
    ("brass_360", "hss",     "turning"):  CutRecord(200,  300,  450,  0.003, 0.015, "ipr",
        "Free-machining brass; excellent HSS machinability."),
    ("brass_360", "hss",     "milling"):  CutRecord(150,  250,  380,  0.002, 0.008, "ipt", ""),
    ("brass_360", "hss",     "drilling"): CutRecord(120,  200,  300,  0.003, 0.012, "ipr", ""),
    ("brass_360", "hss",     "reaming"):  CutRecord( 60,  100,  150,  0.005, 0.015, "ipr", ""),
    ("brass_360", "carbide", "turning"):  CutRecord(400,  650,  1000, 0.003, 0.012, "ipr", ""),
    ("brass_360", "carbide", "milling"):  CutRecord(350,  600,   900, 0.001, 0.005, "ipt", ""),
    ("brass_360", "carbide", "drilling"): CutRecord(200,  380,   580, 0.003, 0.010, "ipr", ""),
    ("brass_360", "carbide", "reaming"):  CutRecord(100,  180,   280, 0.005, 0.018, "ipr", ""),
    ("brass_360", "ceramic", "turning"):  CutRecord(600, 1000,  1600, 0.002, 0.010, "ipr",
        "Ceramic rarely used for brass; carbide is more cost-effective."),
    ("brass_360", "ceramic", "milling"):  CutRecord(500,  900,  1400, 0.001, 0.004, "ipt", ""),
    ("brass_360", "ceramic", "drilling"): _NA._replace(notes="Use carbide drills for brass."),
    ("brass_360", "ceramic", "reaming"):  _NA._replace(notes="Use carbide reamers for brass."),
    ("brass_360", "diamond", "turning"):  CutRecord(800, 1500,  2400, 0.002, 0.008, "ipr",
        "PCD for high-volume or tight-tolerance brass parts."),
    ("brass_360", "diamond", "milling"):  CutRecord(700, 1300,  2100, 0.001, 0.004, "ipt", ""),
    ("brass_360", "diamond", "drilling"): CutRecord(300,  550,   850, 0.002, 0.008, "ipr", ""),
    ("brass_360", "diamond", "reaming"):  CutRecord(150,  280,   440, 0.005, 0.018, "ipr", ""),

    # =========================================================================
    # BRASS CAST (C85700, ~55 HRB)
    # =========================================================================
    ("brass_cast", "hss",     "turning"):  CutRecord(150,  250,  380,  0.004, 0.015, "ipr", ""),
    ("brass_cast", "hss",     "milling"):  CutRecord(120,  200,  300,  0.002, 0.008, "ipt", ""),
    ("brass_cast", "hss",     "drilling"): CutRecord(100,  170,  260,  0.003, 0.010, "ipr", ""),
    ("brass_cast", "hss",     "reaming"):  CutRecord( 50,   85,  130,  0.005, 0.012, "ipr", ""),
    ("brass_cast", "carbide", "turning"):  CutRecord(300,  520,   820, 0.004, 0.015, "ipr", ""),
    ("brass_cast", "carbide", "milling"):  CutRecord(280,  480,   750, 0.001, 0.005, "ipt", ""),
    ("brass_cast", "carbide", "drilling"): CutRecord(170,  300,   460, 0.003, 0.010, "ipr", ""),
    ("brass_cast", "carbide", "reaming"):  CutRecord( 85,  150,   235, 0.005, 0.015, "ipr", ""),
    ("brass_cast", "ceramic", "turning"):  CutRecord(500,  850,  1350, 0.003, 0.010, "ipr", ""),
    ("brass_cast", "ceramic", "milling"):  CutRecord(420,  720,  1120, 0.001, 0.004, "ipt", ""),
    ("brass_cast", "ceramic", "drilling"): _NA._replace(notes="Use carbide drills."),
    ("brass_cast", "ceramic", "reaming"):  _NA._replace(notes="Use carbide reamers."),
    ("brass_cast", "diamond", "turning"):  CutRecord(650, 1200,  1900, 0.002, 0.008, "ipr", ""),
    ("brass_cast", "diamond", "milling"):  CutRecord(550, 1050,  1700, 0.001, 0.004, "ipt", ""),
    ("brass_cast", "diamond", "drilling"): CutRecord(250,  450,   700, 0.002, 0.008, "ipr", ""),
    ("brass_cast", "diamond", "reaming"):  CutRecord(130,  235,   370, 0.005, 0.015, "ipr", ""),

    # =========================================================================
    # STEEL 1018 (Low-carbon, ~126 HB)
    # =========================================================================
    ("steel_1018", "hss",     "turning"):  CutRecord( 80, 120,  160,  0.005, 0.020, "ipr",
        "MH31 §1100 Table 3: HSS turning of low-carbon steel 80–160 SFM."),
    ("steel_1018", "hss",     "milling"):  CutRecord( 60,  90,  120,  0.002, 0.008, "ipt",
        "TiN-coated HSS recommended for steel milling."),
    ("steel_1018", "hss",     "drilling"): CutRecord( 60,  80,   90,  0.005, 0.015, "ipr",
        "MH31 §1100: HSS drilling of C1020 steel 60–90 SFM. Depth bar oracle."),
    ("steel_1018", "hss",     "reaming"):  CutRecord( 25,  40,   55,  0.005, 0.015, "ipr",
        "HSS reamer; reaming speed ~50 % of drilling speed."),

    ("steel_1018", "carbide", "turning"):  CutRecord(350, 550,  800,  0.005, 0.020, "ipr",
        "P25 grade uncoated; TiAlN-coated preferred."),
    ("steel_1018", "carbide", "milling"):  CutRecord(300, 500,  700,  0.002, 0.006, "ipt", ""),
    ("steel_1018", "carbide", "drilling"): CutRecord(200, 350,  500,  0.004, 0.012, "ipr", ""),
    ("steel_1018", "carbide", "reaming"):  CutRecord(100, 175,  250,  0.005, 0.015, "ipr", ""),

    ("steel_1018", "ceramic", "turning"):  CutRecord(800, 1500, 2500, 0.003, 0.012, "ipr",
        "Al₂O₃ or SiAlON; rigid setup, dry cutting."),
    ("steel_1018", "ceramic", "milling"):  CutRecord(600, 1200, 2000, 0.001, 0.004, "ipt", ""),
    ("steel_1018", "ceramic", "drilling"): _NA._replace(notes="Ceramic drills not recommended for 1018; use carbide."),
    ("steel_1018", "ceramic", "reaming"):  _NA._replace(notes="Use carbide reamers for 1018."),

    ("steel_1018", "diamond", "turning"):  _NA._replace(notes="PCD not suitable for ferrous materials — carbon diffusion."),
    ("steel_1018", "diamond", "milling"):  _NA._replace(notes="PCD not suitable for ferrous materials — carbon diffusion."),
    ("steel_1018", "diamond", "drilling"): _NA._replace(notes="PCD not suitable for ferrous materials — carbon diffusion."),
    ("steel_1018", "diamond", "reaming"):  _NA._replace(notes="PCD not suitable for ferrous materials — carbon diffusion."),

    # =========================================================================
    # STEEL 4140 (Alloy, quenched & tempered ~28–32 HRC)
    # =========================================================================
    ("steel_4140", "hss",     "turning"):  CutRecord( 50,  80,  110,  0.005, 0.015, "ipr", ""),
    ("steel_4140", "hss",     "milling"):  CutRecord( 40,  65,   90,  0.002, 0.006, "ipt", ""),
    ("steel_4140", "hss",     "drilling"): CutRecord( 40,  60,   80,  0.003, 0.010, "ipr", ""),
    ("steel_4140", "hss",     "reaming"):  CutRecord( 18,  28,   40,  0.004, 0.012, "ipr", ""),
    ("steel_4140", "carbide", "turning"):  CutRecord(250, 400,  600,  0.004, 0.015, "ipr",
        "P20-P30 coated carbide; TiAlN preferred."),
    ("steel_4140", "carbide", "milling"):  CutRecord(200, 350,  500,  0.002, 0.005, "ipt", ""),
    ("steel_4140", "carbide", "drilling"): CutRecord(150, 260,  380,  0.003, 0.010, "ipr", ""),
    ("steel_4140", "carbide", "reaming"):  CutRecord( 70, 120,  180,  0.004, 0.012, "ipr", ""),
    ("steel_4140", "ceramic", "turning"):  CutRecord(600, 1100, 1800, 0.003, 0.010, "ipr", ""),
    ("steel_4140", "ceramic", "milling"):  CutRecord(500,  900, 1500, 0.001, 0.003, "ipt", ""),
    ("steel_4140", "ceramic", "drilling"): _NA._replace(notes="Ceramic drills brittle in alloy steel; use carbide."),
    ("steel_4140", "ceramic", "reaming"):  _NA._replace(notes="Use carbide reamers."),
    ("steel_4140", "diamond", "turning"):  _NA._replace(notes="PCD not suitable for steel (C diffusion)."),
    ("steel_4140", "diamond", "milling"):  _NA._replace(notes="PCD not suitable for steel (C diffusion)."),
    ("steel_4140", "diamond", "drilling"): _NA._replace(notes="PCD not suitable for steel (C diffusion)."),
    ("steel_4140", "diamond", "reaming"):  _NA._replace(notes="PCD not suitable for steel (C diffusion)."),

    # =========================================================================
    # STAINLESS STEEL 304 (Austenitic, ~200 HB)
    # =========================================================================
    ("steel_stainless_304", "hss",     "turning"):  CutRecord( 40,  60,   90,  0.004, 0.015, "ipr",
        "Work-hardening tendency; use positive rake, sharp edge."),
    ("steel_stainless_304", "hss",     "milling"):  CutRecord( 30,  50,   70,  0.001, 0.005, "ipt", ""),
    ("steel_stainless_304", "hss",     "drilling"): CutRecord( 30,  45,   65,  0.002, 0.008, "ipr", ""),
    ("steel_stainless_304", "hss",     "reaming"):  CutRecord( 15,  22,   32,  0.003, 0.010, "ipr", ""),
    ("steel_stainless_304", "carbide", "turning"):  CutRecord(200, 320,  500,  0.004, 0.015, "ipr",
        "M-grade (M25/M35) carbide; flood coolant recommended."),
    ("steel_stainless_304", "carbide", "milling"):  CutRecord(150, 260,  400,  0.001, 0.004, "ipt", ""),
    ("steel_stainless_304", "carbide", "drilling"): CutRecord(100, 180,  280,  0.002, 0.008, "ipr", ""),
    ("steel_stainless_304", "carbide", "reaming"):  CutRecord( 50,  90,  140,  0.003, 0.010, "ipr", ""),
    ("steel_stainless_304", "ceramic", "turning"):  CutRecord(500, 900, 1500, 0.003, 0.010, "ipr",
        "Whisker-reinforced Al₂O₃ or SiAlON; dry or minimal lube."),
    ("steel_stainless_304", "ceramic", "milling"):  CutRecord(400, 750, 1200, 0.001, 0.003, "ipt", ""),
    ("steel_stainless_304", "ceramic", "drilling"): _NA._replace(notes="Ceramic drills not recommended for 304; use carbide."),
    ("steel_stainless_304", "ceramic", "reaming"):  _NA._replace(notes="Use carbide reamers for SS."),
    ("steel_stainless_304", "diamond", "turning"):  _NA._replace(notes="PCD not suitable for stainless steel."),
    ("steel_stainless_304", "diamond", "milling"):  _NA._replace(notes="PCD not suitable for stainless steel."),
    ("steel_stainless_304", "diamond", "drilling"): _NA._replace(notes="PCD not suitable for stainless steel."),
    ("steel_stainless_304", "diamond", "reaming"):  _NA._replace(notes="PCD not suitable for stainless steel."),

    # =========================================================================
    # STAINLESS STEEL 316 (Austenitic Mo-stabilised, ~217 HB)
    # =========================================================================
    ("steel_stainless_316", "hss",     "turning"):  CutRecord( 35,  55,   80,  0.004, 0.012, "ipr", ""),
    ("steel_stainless_316", "hss",     "milling"):  CutRecord( 28,  45,   65,  0.001, 0.004, "ipt", ""),
    ("steel_stainless_316", "hss",     "drilling"): CutRecord( 25,  40,   58,  0.002, 0.007, "ipr", ""),
    ("steel_stainless_316", "hss",     "reaming"):  CutRecord( 12,  20,   28,  0.003, 0.009, "ipr", ""),
    ("steel_stainless_316", "carbide", "turning"):  CutRecord(180, 300,  460,  0.004, 0.012, "ipr", ""),
    ("steel_stainless_316", "carbide", "milling"):  CutRecord(140, 240,  370,  0.001, 0.004, "ipt", ""),
    ("steel_stainless_316", "carbide", "drilling"): CutRecord( 90, 160,  250,  0.002, 0.007, "ipr", ""),
    ("steel_stainless_316", "carbide", "reaming"):  CutRecord( 45,  80,  125,  0.003, 0.009, "ipr", ""),
    ("steel_stainless_316", "ceramic", "turning"):  CutRecord(450, 800, 1300, 0.003, 0.010, "ipr", ""),
    ("steel_stainless_316", "ceramic", "milling"):  CutRecord(360, 680, 1100, 0.001, 0.003, "ipt", ""),
    ("steel_stainless_316", "ceramic", "drilling"): _NA._replace(notes="Ceramic drills not recommended for 316."),
    ("steel_stainless_316", "ceramic", "reaming"):  _NA._replace(notes="Use carbide reamers."),
    ("steel_stainless_316", "diamond", "turning"):  _NA._replace(notes="PCD not suitable for stainless steel."),
    ("steel_stainless_316", "diamond", "milling"):  _NA._replace(notes="PCD not suitable for stainless steel."),
    ("steel_stainless_316", "diamond", "drilling"): _NA._replace(notes="PCD not suitable for stainless steel."),
    ("steel_stainless_316", "diamond", "reaming"):  _NA._replace(notes="PCD not suitable for stainless steel."),

    # =========================================================================
    # HARDENED STEEL ~60 HRC
    # =========================================================================
    ("steel_hardened_60hrc", "hss",     "turning"):  _NA._replace(notes="HSS cannot machine 60 HRC steel; use CBN/ceramic."),
    ("steel_hardened_60hrc", "hss",     "milling"):  _NA._replace(notes="HSS cannot machine 60 HRC steel."),
    ("steel_hardened_60hrc", "hss",     "drilling"): _NA._replace(notes="HSS cannot machine 60 HRC steel."),
    ("steel_hardened_60hrc", "hss",     "reaming"):  _NA._replace(notes="HSS cannot machine 60 HRC steel."),
    ("steel_hardened_60hrc", "carbide", "turning"):  CutRecord(100, 180,  280,  0.002, 0.008, "ipr",
        "Hard-turning with CBN or coated carbide (hard-turning grade); dry."),
    ("steel_hardened_60hrc", "carbide", "milling"):  CutRecord( 80, 150,  250,  0.001, 0.003, "ipt",
        "Solid carbide high-helix end-mill; minimum chip load; dry."),
    ("steel_hardened_60hrc", "carbide", "drilling"): CutRecord( 60, 110,  180,  0.001, 0.005, "ipr",
        "Solid carbide spot drill → through-coolant drill; short flute."),
    ("steel_hardened_60hrc", "carbide", "reaming"):  CutRecord( 30,  55,   90,  0.002, 0.006, "ipr", ""),
    ("steel_hardened_60hrc", "ceramic", "turning"):  CutRecord(200, 400,  700,  0.002, 0.008, "ipr",
        "CBN or SiAlON for hard turning — MH31 §1100 Table 5."),
    ("steel_hardened_60hrc", "ceramic", "milling"):  CutRecord(150, 300,  550,  0.001, 0.003, "ipt", ""),
    ("steel_hardened_60hrc", "ceramic", "drilling"): _NA._replace(notes="Ceramic drills impractical at 60 HRC; use carbide."),
    ("steel_hardened_60hrc", "ceramic", "reaming"):  _NA._replace(notes="Use carbide reamers."),
    ("steel_hardened_60hrc", "diamond", "turning"):  _NA._replace(notes="PCD not suitable for ferrous hard materials (C diffusion)."),
    ("steel_hardened_60hrc", "diamond", "milling"):  _NA._replace(notes="PCD not suitable for hardened steel."),
    ("steel_hardened_60hrc", "diamond", "drilling"): _NA._replace(notes="PCD not suitable for hardened steel."),
    ("steel_hardened_60hrc", "diamond", "reaming"):  _NA._replace(notes="PCD not suitable for hardened steel."),

    # =========================================================================
    # GRAY CAST IRON (Class 30, ~200 HB)
    # =========================================================================
    ("cast_iron_gray", "hss",     "turning"):  CutRecord( 60,  90,  130,  0.004, 0.018, "ipr",
        "Dry cutting preferred (cast iron is self-lubricating)."),
    ("cast_iron_gray", "hss",     "milling"):  CutRecord( 50,  75,  110,  0.002, 0.007, "ipt", ""),
    ("cast_iron_gray", "hss",     "drilling"): CutRecord( 50,  70,  100,  0.004, 0.014, "ipr", ""),
    ("cast_iron_gray", "hss",     "reaming"):  CutRecord( 22,  35,   50,  0.005, 0.015, "ipr", ""),
    ("cast_iron_gray", "carbide", "turning"):  CutRecord(250, 450,  700,  0.004, 0.018, "ipr",
        "K-grade (K10/K20) carbide; dry cutting."),
    ("cast_iron_gray", "carbide", "milling"):  CutRecord(200, 380,  580,  0.002, 0.006, "ipt", ""),
    ("cast_iron_gray", "carbide", "drilling"): CutRecord(150, 280,  420,  0.003, 0.012, "ipr", ""),
    ("cast_iron_gray", "carbide", "reaming"):  CutRecord( 70, 130,  200,  0.005, 0.015, "ipr", ""),
    ("cast_iron_gray", "ceramic", "turning"):  CutRecord(600, 1200, 2000, 0.003, 0.012, "ipr",
        "Al₂O₃ ceramic excellent for CI; high speeds, dry."),
    ("cast_iron_gray", "ceramic", "milling"):  CutRecord(500, 1000, 1700, 0.001, 0.004, "ipt", ""),
    ("cast_iron_gray", "ceramic", "drilling"): _NA._replace(notes="Ceramic drills rarely used for CI; use carbide."),
    ("cast_iron_gray", "ceramic", "reaming"):  _NA._replace(notes="Use carbide reamers for CI."),
    ("cast_iron_gray", "diamond", "turning"):  _NA._replace(notes="PCD not suitable for gray cast iron (C diffusion)."),
    ("cast_iron_gray", "diamond", "milling"):  _NA._replace(notes="PCD not suitable for gray cast iron."),
    ("cast_iron_gray", "diamond", "drilling"): _NA._replace(notes="PCD not suitable for gray cast iron."),
    ("cast_iron_gray", "diamond", "reaming"):  _NA._replace(notes="PCD not suitable for gray cast iron."),

    # =========================================================================
    # DUCTILE CAST IRON (Grade 65-45-12, ~200 HB)
    # =========================================================================
    ("cast_iron_ductile", "hss",     "turning"):  CutRecord( 50,  80,  120,  0.004, 0.016, "ipr", ""),
    ("cast_iron_ductile", "hss",     "milling"):  CutRecord( 40,  65,   95,  0.002, 0.006, "ipt", ""),
    ("cast_iron_ductile", "hss",     "drilling"): CutRecord( 40,  60,   88,  0.003, 0.012, "ipr", ""),
    ("cast_iron_ductile", "hss",     "reaming"):  CutRecord( 18,  30,   44,  0.004, 0.012, "ipr", ""),
    ("cast_iron_ductile", "carbide", "turning"):  CutRecord(220, 380,  600,  0.004, 0.016, "ipr", ""),
    ("cast_iron_ductile", "carbide", "milling"):  CutRecord(180, 320,  500,  0.002, 0.005, "ipt", ""),
    ("cast_iron_ductile", "carbide", "drilling"): CutRecord(130, 240,  370,  0.003, 0.010, "ipr", ""),
    ("cast_iron_ductile", "carbide", "reaming"):  CutRecord( 60, 110,  170,  0.004, 0.012, "ipr", ""),
    ("cast_iron_ductile", "ceramic", "turning"):  CutRecord(500, 1000, 1700, 0.003, 0.010, "ipr", ""),
    ("cast_iron_ductile", "ceramic", "milling"):  CutRecord(420,  850, 1400, 0.001, 0.004, "ipt", ""),
    ("cast_iron_ductile", "ceramic", "drilling"): _NA._replace(notes="Ceramic drills not recommended for ductile CI."),
    ("cast_iron_ductile", "ceramic", "reaming"):  _NA._replace(notes="Use carbide reamers."),
    ("cast_iron_ductile", "diamond", "turning"):  _NA._replace(notes="PCD not suitable for ductile iron (C diffusion)."),
    ("cast_iron_ductile", "diamond", "milling"):  _NA._replace(notes="PCD not suitable for ductile iron."),
    ("cast_iron_ductile", "diamond", "drilling"): _NA._replace(notes="PCD not suitable for ductile iron."),
    ("cast_iron_ductile", "diamond", "reaming"):  _NA._replace(notes="PCD not suitable for ductile iron."),

    # =========================================================================
    # TITANIUM 6Al-4V (Grade 5, ~36 HRC equivalent, ~320 HB)
    # =========================================================================
    ("titanium_6al4v", "hss",     "turning"):  CutRecord( 30,  50,   75,  0.003, 0.010, "ipr",
        "Titanium extremely work-hardens; keep cutting continuously."),
    ("titanium_6al4v", "hss",     "milling"):  CutRecord( 20,  35,   55,  0.001, 0.004, "ipt", ""),
    ("titanium_6al4v", "hss",     "drilling"): CutRecord( 20,  30,   45,  0.002, 0.006, "ipr", ""),
    ("titanium_6al4v", "hss",     "reaming"):  CutRecord( 10,  15,   22,  0.003, 0.008, "ipr", ""),

    ("titanium_6al4v", "carbide", "turning"):  CutRecord(200, 250,  300,  0.003, 0.010, "ipr",
        "Depth bar oracle: MH31 §1100 Ti-6Al-4V + carbide turning 200–300 SFM. Sandvik Coromant "
        "CoroKey 2023: 200–280 SFM. Low thermal conductivity requires flood coolant."),
    ("titanium_6al4v", "carbide", "milling"):  CutRecord(100, 180,  260,  0.001, 0.003, "ipt",
        "Trochoidal milling recommended; 30–50 % radial engagement max."),
    ("titanium_6al4v", "carbide", "drilling"): CutRecord( 80, 130,  200,  0.002, 0.006, "ipr",
        "Through-spindle coolant essential; peck drill for L/D > 4."),
    ("titanium_6al4v", "carbide", "reaming"):  CutRecord( 40,  70,  110,  0.003, 0.008, "ipr", ""),

    ("titanium_6al4v", "ceramic", "turning"):  CutRecord(400, 700, 1100, 0.002, 0.007, "ipr",
        "SiAlON (Sandvik grade 7025) effective for Ti turning at elevated speed. "
        "Notch wear monitoring critical."),
    ("titanium_6al4v", "ceramic", "milling"):  CutRecord(300, 550,  880, 0.001, 0.002, "ipt",
        "Ceramic milling of Ti: limited to finishing; aggressive depth control."),
    ("titanium_6al4v", "ceramic", "drilling"): _NA._replace(
        notes="Ceramic drills not recommended for Ti alloys; use solid carbide."),
    ("titanium_6al4v", "ceramic", "reaming"):  _NA._replace(notes="Use carbide reamers for Ti."),

    ("titanium_6al4v", "diamond", "turning"):  _NA._replace(notes="PCD: C diffusion into Ti at high temp; limited life."),
    ("titanium_6al4v", "diamond", "milling"):  _NA._replace(notes="PCD not recommended for Ti-6Al-4V."),
    ("titanium_6al4v", "diamond", "drilling"): _NA._replace(notes="PCD not recommended for Ti-6Al-4V."),
    ("titanium_6al4v", "diamond", "reaming"):  _NA._replace(notes="PCD not recommended for Ti-6Al-4V."),

    # =========================================================================
    # TITANIUM CP (Grade 2, commercially pure, ~150 HB)
    # =========================================================================
    ("titanium_cp", "hss",     "turning"):  CutRecord( 50,  80,  120,  0.003, 0.012, "ipr", ""),
    ("titanium_cp", "hss",     "milling"):  CutRecord( 35,  60,   90,  0.001, 0.005, "ipt", ""),
    ("titanium_cp", "hss",     "drilling"): CutRecord( 30,  50,   75,  0.002, 0.008, "ipr", ""),
    ("titanium_cp", "hss",     "reaming"):  CutRecord( 15,  25,   38,  0.003, 0.010, "ipr", ""),
    ("titanium_cp", "carbide", "turning"):  CutRecord(250, 380,  550,  0.003, 0.012, "ipr", "Softer than Grade 5; higher SFM possible."),
    ("titanium_cp", "carbide", "milling"):  CutRecord(160, 260,  380,  0.001, 0.004, "ipt", ""),
    ("titanium_cp", "carbide", "drilling"): CutRecord(120, 200,  300,  0.002, 0.008, "ipr", ""),
    ("titanium_cp", "carbide", "reaming"):  CutRecord( 60,  95,  145,  0.003, 0.010, "ipr", ""),
    ("titanium_cp", "ceramic", "turning"):  CutRecord(550, 900, 1400, 0.002, 0.008, "ipr", ""),
    ("titanium_cp", "ceramic", "milling"):  CutRecord(400, 700, 1100, 0.001, 0.003, "ipt", ""),
    ("titanium_cp", "ceramic", "drilling"): _NA._replace(notes="Ceramic drills not recommended for Ti CP."),
    ("titanium_cp", "ceramic", "reaming"):  _NA._replace(notes="Use carbide reamers."),
    ("titanium_cp", "diamond", "turning"):  _NA._replace(notes="PCD not recommended for titanium (C diffusion)."),
    ("titanium_cp", "diamond", "milling"):  _NA._replace(notes="PCD not recommended for titanium."),
    ("titanium_cp", "diamond", "drilling"): _NA._replace(notes="PCD not recommended for titanium."),
    ("titanium_cp", "diamond", "reaming"):  _NA._replace(notes="PCD not recommended for titanium."),

    # =========================================================================
    # INCONEL 718 (Ni superalloy, ~40 HRC, ~400 HB)
    # =========================================================================
    ("inconel_718", "hss",     "turning"):  CutRecord(  8,  15,   25,  0.002, 0.006, "ipr",
        "HSS rarely used for Inconel in production; very short tool life."),
    ("inconel_718", "hss",     "milling"):  CutRecord(  5,  10,   18,  0.001, 0.003, "ipt", ""),
    ("inconel_718", "hss",     "drilling"): CutRecord(  5,   8,   14,  0.001, 0.004, "ipr", ""),
    ("inconel_718", "hss",     "reaming"):  CutRecord(  3,   5,    8,  0.002, 0.005, "ipr", ""),
    ("inconel_718", "carbide", "turning"):  CutRecord( 60, 100,  160,  0.003, 0.008, "ipr",
        "C-grade coated carbide; flood high-pressure coolant; short inserts."),
    ("inconel_718", "carbide", "milling"):  CutRecord( 40,  70,  110,  0.001, 0.003, "ipt",
        "Trochoidal strategy; 10–15 % radial engagement; flood coolant."),
    ("inconel_718", "carbide", "drilling"): CutRecord( 30,  55,   90,  0.001, 0.004, "ipr",
        "Through-spindle coolant >70 bar recommended; peck every 0.5× D."),
    ("inconel_718", "carbide", "reaming"):  CutRecord( 15,  28,   45,  0.002, 0.005, "ipr", ""),
    ("inconel_718", "ceramic", "turning"):  CutRecord(600, 1000, 1600, 0.002, 0.006, "ipr",
        "SiC-whisker Al₂O₃ (e.g. Sandvik CC670) — high speed, dry, rigid. "
        "MH31 §1100 Ni-superalloy ceramic data."),
    ("inconel_718", "ceramic", "milling"):  CutRecord(400,  750, 1200, 0.001, 0.002, "ipt",
        "Ceramic milling IN718: interrupted cuts; special toolpath required."),
    ("inconel_718", "ceramic", "drilling"): _NA._replace(notes="Ceramic drills not recommended for Inconel; use carbide."),
    ("inconel_718", "ceramic", "reaming"):  _NA._replace(notes="Use carbide reamers for IN718."),
    ("inconel_718", "diamond", "turning"):  _NA._replace(notes="PCD not suitable for Ni-based superalloys at elevated temp."),
    ("inconel_718", "diamond", "milling"):  _NA._replace(notes="PCD not suitable for Inconel 718."),
    ("inconel_718", "diamond", "drilling"): _NA._replace(notes="PCD not suitable for Inconel 718."),
    ("inconel_718", "diamond", "reaming"):  _NA._replace(notes="PCD not suitable for Inconel 718."),

    # =========================================================================
    # COPPER C110 (OFHC, ~55 HRF)
    # =========================================================================
    ("copper_c110", "hss",     "turning"):  CutRecord(150, 250,  380,  0.003, 0.015, "ipr", ""),
    ("copper_c110", "hss",     "milling"):  CutRecord(120, 200,  300,  0.002, 0.007, "ipt", ""),
    ("copper_c110", "hss",     "drilling"): CutRecord(100, 170,  260,  0.003, 0.010, "ipr", ""),
    ("copper_c110", "hss",     "reaming"):  CutRecord( 50,  85,  130,  0.004, 0.012, "ipr", ""),
    ("copper_c110", "carbide", "turning"):  CutRecord(350, 600,  950,  0.003, 0.015, "ipr", ""),
    ("copper_c110", "carbide", "milling"):  CutRecord(280, 500,  800,  0.001, 0.005, "ipt", ""),
    ("copper_c110", "carbide", "drilling"): CutRecord(180, 330,  520,  0.003, 0.010, "ipr", ""),
    ("copper_c110", "carbide", "reaming"):  CutRecord( 90, 160,  250,  0.004, 0.014, "ipr", ""),
    ("copper_c110", "ceramic", "turning"):  CutRecord(600, 1050, 1700, 0.002, 0.010, "ipr", "Rarely used — carbide preferred for copper."),
    ("copper_c110", "ceramic", "milling"):  CutRecord(500,  880, 1400, 0.001, 0.004, "ipt", ""),
    ("copper_c110", "ceramic", "drilling"): _NA._replace(notes="Use carbide drills for copper."),
    ("copper_c110", "ceramic", "reaming"):  _NA._replace(notes="Use carbide reamers."),
    ("copper_c110", "diamond", "turning"):  CutRecord(800, 1500, 2500, 0.002, 0.008, "ipr",
        "PCD gives excellent surface finish and long life on OFHC copper."),
    ("copper_c110", "diamond", "milling"):  CutRecord(700, 1300, 2100, 0.001, 0.004, "ipt", ""),
    ("copper_c110", "diamond", "drilling"): CutRecord(300,  550,  850, 0.002, 0.008, "ipr", ""),
    ("copper_c110", "diamond", "reaming"):  CutRecord(150,  280,  440, 0.004, 0.014, "ipr", ""),

    # =========================================================================
    # ACETAL (Delrin®, POM, ~R120 Rockwell)
    # =========================================================================
    ("plastic_acetal", "hss",     "turning"):  CutRecord(250, 400,  600,  0.003, 0.015, "ipr",
        "Plastics: sharp edge mandatory; no coolant or mist only."),
    ("plastic_acetal", "hss",     "milling"):  CutRecord(200, 350,  520,  0.002, 0.008, "ipt", ""),
    ("plastic_acetal", "hss",     "drilling"): CutRecord(150, 260,  390,  0.003, 0.012, "ipr", ""),
    ("plastic_acetal", "hss",     "reaming"):  CutRecord( 80, 130,  200,  0.004, 0.015, "ipr", ""),
    ("plastic_acetal", "carbide", "turning"):  CutRecord(500, 800, 1200, 0.003, 0.015, "ipr", ""),
    ("plastic_acetal", "carbide", "milling"):  CutRecord(400, 700, 1050, 0.002, 0.007, "ipt", ""),
    ("plastic_acetal", "carbide", "drilling"): CutRecord(300, 500,  760, 0.003, 0.012, "ipr", ""),
    ("plastic_acetal", "carbide", "reaming"):  CutRecord(150, 260,  400, 0.004, 0.015, "ipr", ""),
    ("plastic_acetal", "ceramic", "turning"):  _NA._replace(notes="Ceramic not used for plastics; use carbide."),
    ("plastic_acetal", "ceramic", "milling"):  _NA._replace(notes="Ceramic not used for plastics."),
    ("plastic_acetal", "ceramic", "drilling"): _NA._replace(notes="Ceramic not used for plastics."),
    ("plastic_acetal", "ceramic", "reaming"):  _NA._replace(notes="Ceramic not used for plastics."),
    ("plastic_acetal", "diamond", "turning"):  CutRecord(800, 1400, 2200, 0.002, 0.010, "ipr",
        "PCD for high-volume acetal; excellent finish."),
    ("plastic_acetal", "diamond", "milling"):  CutRecord(700, 1200, 1900, 0.002, 0.007, "ipt", ""),
    ("plastic_acetal", "diamond", "drilling"): CutRecord(400,  700, 1100, 0.003, 0.010, "ipr", ""),
    ("plastic_acetal", "diamond", "reaming"):  CutRecord(200,  350,  550, 0.004, 0.015, "ipr", ""),

    # =========================================================================
    # NYLON (PA6/PA66)
    # =========================================================================
    ("plastic_nylon", "hss",     "turning"):  CutRecord(200, 350,  520,  0.003, 0.015, "ipr", ""),
    ("plastic_nylon", "hss",     "milling"):  CutRecord(160, 280,  420,  0.002, 0.007, "ipt", ""),
    ("plastic_nylon", "hss",     "drilling"): CutRecord(130, 220,  340,  0.002, 0.010, "ipr", ""),
    ("plastic_nylon", "hss",     "reaming"):  CutRecord( 65, 110,  165,  0.003, 0.012, "ipr", ""),
    ("plastic_nylon", "carbide", "turning"):  CutRecord(400, 700, 1050, 0.003, 0.015, "ipr", ""),
    ("plastic_nylon", "carbide", "milling"):  CutRecord(320, 560,  840, 0.002, 0.006, "ipt", ""),
    ("plastic_nylon", "carbide", "drilling"): CutRecord(250, 430,  640, 0.002, 0.010, "ipr", ""),
    ("plastic_nylon", "carbide", "reaming"):  CutRecord(120, 210,  330, 0.003, 0.012, "ipr", ""),
    ("plastic_nylon", "ceramic", "turning"):  _NA._replace(notes="Ceramic not used for nylon."),
    ("plastic_nylon", "ceramic", "milling"):  _NA._replace(notes="Ceramic not used for nylon."),
    ("plastic_nylon", "ceramic", "drilling"): _NA._replace(notes="Ceramic not used for nylon."),
    ("plastic_nylon", "ceramic", "reaming"):  _NA._replace(notes="Ceramic not used for nylon."),
    ("plastic_nylon", "diamond", "turning"):  CutRecord(700, 1200, 1900, 0.002, 0.010, "ipr", "PCD for tight tolerance nylon."),
    ("plastic_nylon", "diamond", "milling"):  CutRecord(600, 1050, 1680, 0.002, 0.006, "ipt", ""),
    ("plastic_nylon", "diamond", "drilling"): CutRecord(350,  600,  950, 0.002, 0.008, "ipr", ""),
    ("plastic_nylon", "diamond", "reaming"):  CutRecord(175,  305,  480, 0.003, 0.010, "ipr", ""),

    # =========================================================================
    # ABS (Acrylonitrile Butadiene Styrene)
    # =========================================================================
    ("plastic_abs", "hss",     "turning"):  CutRecord(180, 300,  460,  0.003, 0.015, "ipr", ""),
    ("plastic_abs", "hss",     "milling"):  CutRecord(150, 250,  380,  0.002, 0.007, "ipt", ""),
    ("plastic_abs", "hss",     "drilling"): CutRecord(120, 200,  300,  0.002, 0.010, "ipr", ""),
    ("plastic_abs", "hss",     "reaming"):  CutRecord( 60, 100,  150,  0.003, 0.012, "ipr", ""),
    ("plastic_abs", "carbide", "turning"):  CutRecord(350, 600,  900,  0.003, 0.015, "ipr", ""),
    ("plastic_abs", "carbide", "milling"):  CutRecord(280, 500,  750,  0.002, 0.006, "ipt", ""),
    ("plastic_abs", "carbide", "drilling"): CutRecord(200, 360,  560,  0.002, 0.010, "ipr", ""),
    ("plastic_abs", "carbide", "reaming"):  CutRecord(100, 180,  280,  0.003, 0.012, "ipr", ""),
    ("plastic_abs", "ceramic", "turning"):  _NA._replace(notes="Ceramic not used for ABS."),
    ("plastic_abs", "ceramic", "milling"):  _NA._replace(notes="Ceramic not used for ABS."),
    ("plastic_abs", "ceramic", "drilling"): _NA._replace(notes="Ceramic not used for ABS."),
    ("plastic_abs", "ceramic", "reaming"):  _NA._replace(notes="Ceramic not used for ABS."),
    ("plastic_abs", "diamond", "turning"):  CutRecord(600, 1050, 1650, 0.002, 0.010, "ipr", ""),
    ("plastic_abs", "diamond", "milling"):  CutRecord(500,  900, 1400, 0.002, 0.006, "ipt", ""),
    ("plastic_abs", "diamond", "drilling"): CutRecord(300,  530,  820, 0.002, 0.008, "ipr", ""),
    ("plastic_abs", "diamond", "reaming"):  CutRecord(150,  265,  415, 0.003, 0.010, "ipr", ""),

    # =========================================================================
    # MAGNESIUM AZ31 (~50 HRB)
    # =========================================================================
    ("magnesium_az31", "hss",     "turning"):  CutRecord(300, 500,  750,  0.004, 0.018, "ipr",
        "Mg fire risk: dry cutting; no water-based coolants; mist-extraction."),
    ("magnesium_az31", "hss",     "milling"):  CutRecord(250, 420,  630,  0.002, 0.008, "ipt", ""),
    ("magnesium_az31", "hss",     "drilling"): CutRecord(200, 350,  530,  0.003, 0.012, "ipr", ""),
    ("magnesium_az31", "hss",     "reaming"):  CutRecord(100, 175,  265,  0.005, 0.015, "ipr", ""),
    ("magnesium_az31", "carbide", "turning"):  CutRecord(800, 1400, 2200, 0.004, 0.018, "ipr",
        "Uncoated K-grade carbide; very high speeds achievable with Mg."),
    ("magnesium_az31", "carbide", "milling"):  CutRecord(700, 1200, 1900, 0.002, 0.007, "ipt", ""),
    ("magnesium_az31", "carbide", "drilling"): CutRecord(500,  900, 1400, 0.003, 0.012, "ipr", ""),
    ("magnesium_az31", "carbide", "reaming"):  CutRecord(250,  450,  700, 0.005, 0.015, "ipr", ""),
    ("magnesium_az31", "ceramic", "turning"):  CutRecord(1500, 2500, 4000, 0.003, 0.012, "ipr", ""),
    ("magnesium_az31", "ceramic", "milling"):  CutRecord(1200, 2100, 3400, 0.001, 0.005, "ipt", ""),
    ("magnesium_az31", "ceramic", "drilling"): _NA._replace(notes="Ceramic drills not recommended for Mg; use carbide."),
    ("magnesium_az31", "ceramic", "reaming"):  _NA._replace(notes="Use carbide reamers for Mg."),
    ("magnesium_az31", "diamond", "turning"):  CutRecord(2000, 3500, 5500, 0.003, 0.012, "ipr",
        "PCD for Mg: excellent tool life; fire precautions still required."),
    ("magnesium_az31", "diamond", "milling"):  CutRecord(1800, 3200, 5000, 0.002, 0.007, "ipt", ""),
    ("magnesium_az31", "diamond", "drilling"): CutRecord(700,  1300, 2000, 0.003, 0.010, "ipr", ""),
    ("magnesium_az31", "diamond", "reaming"):  CutRecord(350,   620,  970, 0.005, 0.015, "ipr", ""),
}

# Convenience sets for validation
VALID_WORKPIECE_MATERIALS = frozenset({
    "aluminum_6061", "aluminum_7075", "aluminum_cast",
    "brass_360", "brass_cast",
    "steel_1018", "steel_4140", "steel_stainless_304", "steel_stainless_316",
    "steel_hardened_60hrc",
    "cast_iron_gray", "cast_iron_ductile",
    "titanium_6al4v", "titanium_cp",
    "inconel_718",
    "copper_c110",
    "plastic_acetal", "plastic_nylon", "plastic_abs",
    "magnesium_az31",
})

VALID_TOOL_MATERIALS = frozenset({"hss", "carbide", "ceramic", "diamond"})

VALID_OPERATIONS = frozenset({"turning", "milling", "drilling", "reaming"})
