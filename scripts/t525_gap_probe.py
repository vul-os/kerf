#!/usr/bin/env python3
"""t525_gap_probe.py — throwaway analysis script for T-525.

Empirically checks what kicad_io.py's kicad_pcb_to_circuit_json() does with a
hand-built .kicad_pcb snippet that contains constructs the real repo fixtures
(packages/kerf-firmware/tests/fixtures/xcheck/*/board.kicad_pcb) do NOT
exercise: a copper zone/pour with thermal-relief + fill settings, a keepout
zone, a group, a locked footprint, a gr_text object, and a dimension object.

This is a synthetic fixture, hand-written to match real KiCad v6/v7
s-expression syntax (cross-checked against the installed kiutils==1.4.8
dataclasses, see docs/ecad-gap-analysis.md for citations). It is NOT a real
pcbnew export. Its only purpose is to prove, empirically rather than by
code-reading alone, whether kicad_io.py silently drops these nodes or errors
on them.

Not part of any test suite. Not imported by anything. Safe to delete.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "kerf-electronics" / "src"))

from kerf_electronics.kicad_io import kicad_pcb_to_circuit_json, _parse_sexpr  # noqa: E402

SYNTHETIC_BOARD = r"""
(kicad_pcb
  (version 20211014)
  (generator pcbnew)
  (general
    (thickness 1.6)
  )
  (net 0 "")
  (net 1 "GND")
  (net 2 "VCC")
  (footprint "Resistor_SMD:R_0805_2012Metric"
    (layer "F.Cu")
    (locked)
    (at 10 10 0)
    (attr smd exclude_from_pos_files allow_missing_courtyard)
    (fp_text reference "R1" (at 0 -1.68) (layer "F.SilkS"))
    (fp_text value "10k" (at 0 1.68) (layer "F.Fab"))
    (pad "1" smd custom (at -1.8625 0) (size 1.125 1.75)
      (layers "F.Cu" "F.Paste" "F.Mask")
      (options (clearance outline) (anchor rect))
      (primitives
        (gr_poly (pts (xy -0.5 -0.5) (xy 0.5 -0.5) (xy 0.5 0.5) (xy -0.5 0.5)) (width 0))
      )
      (net 2 "VCC")
    )
    (pad "2" smd roundrect (at 1.8625 0) (size 1.125 1.75)
      (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrect_rratio 0.25)
      (net 1 "GND")
    )
    (model "${KISYS3DMOD}/Resistor_SMD.3dshapes/R_0805_2012Metric.step"
      (offset (xyz 0 0 0))
      (scale (xyz 1 1 1))
      (rotate (xyz 0 0 0))
    )
  )
  (gr_text "Rev A"
    (at 50 50 0)
    (layer "Cmts.User")
    (effects (font (size 1.5 1.5) (thickness 0.3)))
  )
  (dimension
    (type aligned)
    (layer "Dwgs.User")
    (pts (xy 0 0) (xy 20 0))
    (height 5)
    (format (units 3) (precision 2))
  )
  (zone
    (net 1)
    (net_name "GND")
    (layer "F.Cu")
    (hatch edge 0.5)
    (priority 1)
    (connect_pads (clearance 0.2))
    (min_thickness 0.25)
    (fill yes
      (thermal_gap 0.5)
      (thermal_bridge_width 0.5)
    )
    (polygon
      (pts (xy 0 0) (xy 100 0) (xy 100 100) (xy 0 100))
    )
  )
  (zone
    (net 0)
    (net_name "")
    (layer "F.Cu")
    (hatch edge 0.5)
    (keepout
      (tracks not_allowed)
      (vias not_allowed)
      (pads not_allowed)
      (copperpour not_allowed)
      (footprints allowed)
    )
    (polygon
      (pts (xy 40 40) (xy 60 40) (xy 60 60) (xy 40 60))
    )
  )
  (group "power_section"
    (id "12345678-1234-1234-1234-123456789abc")
    (members "fp_r1" "seg1")
  )
  (segment (start 10 10) (end 20 10) (width 0.25) (layer "F.Cu") (net 2))
)
"""


def main() -> int:
    root = _parse_sexpr(SYNTHETIC_BOARD)
    top_level_tags = [n[0] for n in root[1:] if isinstance(n, list) and n]
    print("Top-level s-expression tags the lexer/parser produced (all present, generic parse):")
    for t in sorted(set(top_level_tags)):
        print(f"  - {t} (x{top_level_tags.count(t)})")

    cj = kicad_pcb_to_circuit_json(SYNTHETIC_BOARD)
    types_emitted = sorted({e.get("type") for e in cj if isinstance(e, dict)})
    print("\nCircuit JSON element types kicad_pcb_to_circuit_json() actually emitted:")
    for t in types_emitted:
        count = sum(1 for e in cj if e.get("type") == t)
        print(f"  - {t} (x{count})")

    dropped = set(top_level_tags) - {"footprint", "net", "segment"}
    print(f"\nTop-level tags present in the file but NEVER inspected by the reader: {sorted(dropped)}")
    print("(kicad_pcb_to_circuit_json only special-cases 'net', 'footprint', 'segment' — see")
    print(" packages/kerf-electronics/src/kerf_electronics/kicad_io.py:585,609,685)")

    # Also verify the (locked), (attr ...), and pad 'custom'/'primitives'/'model' are dropped
    # even *inside* the one footprint node it does walk.
    fp_node = next(n for n in root[1:] if isinstance(n, list) and n and n[0] == "footprint")
    fp_child_tags = [c[0] for c in fp_node[2:] if isinstance(c, list) and c]
    print(f"\nChild tags present inside the (footprint ...) node: {sorted(set(fp_child_tags))}")
    print("kicad_pcb_to_circuit_json only reads 'at', 'layer', 'tstamp', 'fp_text' from a footprint")
    print("(kicad_io.py:624-651) — 'locked', 'attr', 'pad', 'model' are present in the parse tree")
    print("but never read, so: pad shapes/primitives, 3D model link, locked flag, and footprint")
    print("attr keywords are silently dropped on read, even though the generic lexer captured them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
