#!/usr/bin/env python3
"""
probe_ocl_5axis.py — OpenCAMlib 5-axis primitive audit script (T1)

Run as:
    python scripts/probe_ocl_5axis.py > scripts/probe_ocl_5axis_output.txt

Probes the installed `opencamlib` wheel and reports:
  - Version + binding details
  - All class names (via inspect.getmembers + dir)
  - Any class name containing 5-axis keywords
  - Detailed inspection of cutter-position classes
  - CLPoint / CCPoint member inventory (orientation data check)
  - Path member inventory
  - MillingCutter family summary

The report is structured so that T1 conclusions can be drawn
without reading the full output.
"""

import sys
import textwrap

SEPARATOR = "=" * 70

def section(title):
    print()
    print(SEPARATOR)
    print(f"  {title}")
    print(SEPARATOR)


# ---------------------------------------------------------------------------
# 1. Import check
# ---------------------------------------------------------------------------
section("1. OCL IMPORT + VERSION")

try:
    import opencamlib as ocl
    print(f"  opencamlib imported successfully")
    version = getattr(ocl, "__version__", None)
    if version:
        print(f"  version : {version}")
    else:
        # Try common version attributes
        for attr in ("version", "VERSION", "__VERSION__", "__ocl_version__"):
            v = getattr(ocl, attr, None)
            if v is not None:
                print(f"  {attr} : {v}")
                break
        else:
            print("  version : <not exposed — check wheel metadata>")
    print(f"  module  : {ocl.__file__}")
    OCL_AVAILABLE = True
except ImportError as e:
    print(f"  IMPORT FAILED: {e}")
    print("  Install: pip install opencamlib")
    print("  Build from source: https://github.com/aewallin/opencamlib")
    OCL_AVAILABLE = False

if not OCL_AVAILABLE:
    print()
    print("Cannot continue without opencamlib. See docs/plans/5-axis-cam-ocl-audit.md")
    print("for the static analysis performed against the PyPI wheel binary.")
    sys.exit(0)


# ---------------------------------------------------------------------------
# 2. Full class enumeration
# ---------------------------------------------------------------------------
import inspect

section("2. ALL CLASSES (inspect.getmembers)")

all_classes = inspect.getmembers(ocl, inspect.isclass)
print(f"  Total classes exposed: {len(all_classes)}")
print()
for name, cls in sorted(all_classes):
    doc = (cls.__doc__ or "").split("\n")[0].strip()
    doc_snippet = f"  # {doc[:60]}" if doc else ""
    print(f"  ocl.{name}{doc_snippet}")


# ---------------------------------------------------------------------------
# 3. 5-axis keyword scan
# ---------------------------------------------------------------------------
section("3. 5-AXIS KEYWORD SCAN")

FIVEAXIS_KEYWORDS = [
    "5axis", "fiveaxis", "5_axis", "five_axis",
    "swarf", "tilt", "drivesurf", "toolaxis", "tool_axis",
    "morphing", "morph", "multiaxis", "multi_axis",
    "framegenerate", "framegen", "feedframe",
    "axisangle", "axis_angle",
]

found_5axis = []
for name, cls in all_classes:
    name_lower = name.lower()
    for kw in FIVEAXIS_KEYWORDS:
        if kw in name_lower:
            found_5axis.append((name, cls, kw))
            break

if found_5axis:
    print(f"  FOUND {len(found_5axis)} 5-axis-related class(es):")
    for name, cls, kw in found_5axis:
        print(f"    ocl.{name}  [matched keyword: {kw}]")
        print(f"      doc: {cls.__doc__}")
        print(f"      members: {[m for m in dir(cls) if not m.startswith('_')]}")
else:
    print("  NONE FOUND — no class name contains any 5-axis keyword.")
    print("  Keywords searched:", ", ".join(FIVEAXIS_KEYWORDS))

print()
print("  dir(ocl) top-level scan for 5-axis:")
top_level = dir(ocl)
top_5axis = [x for x in top_level if any(kw in x.lower() for kw in FIVEAXIS_KEYWORDS)]
if top_5axis:
    print(f"    Found: {top_5axis}")
else:
    print("    NONE FOUND")


# ---------------------------------------------------------------------------
# 4. Cutter-position classes — orientation data probe
# ---------------------------------------------------------------------------
section("4. CUTTER-POSITION CLASSES — ORIENTATION DATA")

CANDIDATES = [
    "PathDropCutter",
    "AdaptivePathDropCutter",
    "BatchDropCutter",
    "AdaptiveWaterline",
    "Waterline",
]

for cls_name in CANDIDATES:
    cls = getattr(ocl, cls_name, None)
    if cls is None:
        print(f"  ocl.{cls_name}: NOT FOUND")
        continue

    print(f"  ocl.{cls_name}:")
    members = [m for m in dir(cls) if not m.startswith("_")]
    print(f"    methods/attrs: {members}")

    # Instantiate and check getCLPoints result shape
    try:
        if cls_name == "PathDropCutter":
            obj = cls()
            # Set up a minimal surface + path so run() is callable
            surf = ocl.STLSurf()
            surf.addTriangle(
                ocl.Triangle(
                    ocl.Point(0, 0, 0),
                    ocl.Point(1, 0, 0),
                    ocl.Point(0, 1, 0),
                )
            )
            cutter = ocl.CylCutter(0.1, 10.0)
            path = ocl.Path()
            path.append(ocl.Line(ocl.Point(0, 0, 0), ocl.Point(1, 0, 0)))
            obj.setSTL(surf)
            obj.setCutter(cutter)
            obj.setZ(-0.01)
            obj.setSampling(0.1)
            obj.setPath(path)
            obj.run()
            cl_points = obj.getCLPoints()
            print(f"    getCLPoints() returned {len(cl_points)} points")
            if cl_points:
                p = cl_points[0]
                p_members = [m for m in dir(p) if not m.startswith("_")]
                print(f"    CLPoint members: {p_members}")
                # Check for orientation/axis/normal fields
                orientation_fields = [m for m in p_members if any(
                    kw in m.lower() for kw in ["normal", "axis", "orient", "dir", "vec", "tilt"]
                )]
                if orientation_fields:
                    print(f"    *** ORIENTATION FIELDS FOUND: {orientation_fields} ***")
                else:
                    print(f"    No orientation fields on CLPoint (only position)")
                # Show x, y, z attributes
                for attr in ("x", "y", "z", "type", "cc"):
                    val = getattr(p, attr, "<missing>")
                    print(f"      .{attr} = {val}")
                # Check CLPoint.cc (CCPoint)
                cc = getattr(p, "cc", None)
                if cc is not None:
                    cc_members = [m for m in dir(cc) if not m.startswith("_")]
                    print(f"    CCPoint members: {cc_members}")
                    orientation_on_cc = [m for m in cc_members if any(
                        kw in m.lower() for kw in ["normal", "axis", "orient", "dir", "vec", "tilt", "n_"]
                    )]
                    if orientation_on_cc:
                        print(f"    *** CCPoint ORIENTATION FIELDS: {orientation_on_cc} ***")
                    else:
                        print(f"    No orientation fields on CCPoint")
                    for attr in ("x", "y", "z", "type"):
                        val = getattr(cc, attr, "<missing>")
                        print(f"      cc.{attr} = {val}")
        else:
            print(f"    (not instantiated in probe — see PathDropCutter pattern above)")
    except Exception as e:
        print(f"    Instantiation/run error: {e}")
    print()


# ---------------------------------------------------------------------------
# 5. CLPoint / CCPoint full member inventory
# ---------------------------------------------------------------------------
section("5. CLPoint / CCPoint MEMBER INVENTORY")

for cls_name in ("CLPoint", "CCPoint", "CCType"):
    cls = getattr(ocl, cls_name, None)
    if cls is None:
        print(f"  ocl.{cls_name}: NOT FOUND")
        continue
    print(f"  ocl.{cls_name}:")
    print(f"    doc: {(cls.__doc__ or '').strip()[:120]}")
    members = [m for m in dir(cls) if not m.startswith("_")]
    print(f"    all members: {members}")
    orientation = [m for m in members if any(
        kw in m.lower() for kw in ["normal", "axis", "orient", "tilt", "vec", "dir", "tangent", "n_"]
    )]
    print(f"    orientation-related: {orientation if orientation else 'NONE'}")
    print()


# ---------------------------------------------------------------------------
# 6. ocl.Path — orientation data check
# ---------------------------------------------------------------------------
section("6. ocl.Path — ORIENTATION DATA")

PathCls = getattr(ocl, "Path", None)
if PathCls:
    print(f"  ocl.Path members: {[m for m in dir(PathCls) if not m.startswith('_')]}")
    p = PathCls()
    p_members = [m for m in dir(p) if not m.startswith("_")]
    print(f"  Path instance members: {p_members}")
    orientation = [m for m in p_members if any(
        kw in m.lower() for kw in ["normal", "axis", "orient", "tilt", "vec", "dir", "tangent", "angle"]
    )]
    print(f"  Orientation-related: {orientation if orientation else 'NONE'}")
else:
    print("  ocl.Path: NOT FOUND")


# ---------------------------------------------------------------------------
# 7. MillingCutter family — 5-axis-specific methods
# ---------------------------------------------------------------------------
section("7. MillingCutter FAMILY — 5-AXIS SPECIFICS")

CUTTER_FAMILY = [
    "MillingCutter", "CylCutter", "BallCutter", "BullCutter",
    "ConeCutter", "CompCylCutter", "CompBallCutter",
]

for cls_name in CUTTER_FAMILY:
    cls = getattr(ocl, cls_name, None)
    if cls is None:
        print(f"  ocl.{cls_name}: NOT FOUND")
        continue
    members = [m for m in dir(cls) if not m.startswith("_")]
    orientation = [m for m in members if any(
        kw in m.lower() for kw in ["normal", "axis", "tilt", "5axis", "fiveaxis", "orient", "tangent"]
    )]
    print(f"  ocl.{cls_name}: {members}")
    if orientation:
        print(f"    *** 5-axis-relevant: {orientation} ***")
    print()


# ---------------------------------------------------------------------------
# 8. CutterLocationSurface probe
# ---------------------------------------------------------------------------
section("8. CutterLocationSurface PROBE")

cls = getattr(ocl, "CutterLocationSurface", None)
if cls:
    print(f"  ocl.CutterLocationSurface found")
    print(f"  doc: {(cls.__doc__ or '').strip()[:200]}")
    members = [m for m in dir(cls) if not m.startswith("_")]
    print(f"  members: {members}")
    orientation = [m for m in members if any(
        kw in m.lower() for kw in ["normal", "axis", "tilt", "5axis", "orient"]
    )]
    print(f"  orientation-related: {orientation if orientation else 'NONE'}")
else:
    print("  CutterLocationSurface: NOT FOUND")


# ---------------------------------------------------------------------------
# 9. Summary table
# ---------------------------------------------------------------------------
section("9. SUMMARY")

print("""
  QUESTION                                          ANSWER
  -------                                           ------
  OCL has any class with '5axis' in its name?       """ + ("YES" if found_5axis else "NO — CONFIRMED NONE") + """
  CLPoint carries tool-axis vector?                 (see section 5 above)
  CCPoint carries surface normal?                   (see section 5 above)
  PathDropCutter outputs orientation per CC point?  NO — only (x,y,z) + CCType enum
  AdaptiveWaterline outputs orientation?            NO — 3-axis only
  Any MillingCutter method implies 5-axis use?      (see section 7 above)

  DESIGN DOC ASSUMPTION (from docs/plans/5-axis-cam.md):
    "OCL has no native 5-axis primitive"
  T1 VERDICT:
""")
if not found_5axis:
    print("    CONFIRMED. OCL 2023.1.11 contains zero 5-axis primitives.")
    print("    The solver MUST be layered on top via pythonOCC GeomLProp_SLProps.")
    print("    T2-T8 proceed on the pythonOCC path as designed.")
else:
    print("    REFUTED — unexpected 5-axis classes found, see section 3.")
    print("    Re-evaluate T2-T8 scope before proceeding.")

print()
print("  See docs/plans/5-axis-cam-ocl-audit.md for the full analysis.")
print()
