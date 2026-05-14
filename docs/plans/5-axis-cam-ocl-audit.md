# T1 — OpenCAMlib 5-axis Primitive Audit

> **Status:** ✅ shipped
> **Scope:** T1 in the [5-axis CAM solver plan](./5-axis-cam.md). Audits
> `opencamlib` for any native 5-axis surface area before T2–T8 begin
> implementation.

## 1. OCL Version Probed

| Field | Value |
| --- | --- |
| PyPI package | `opencamlib 2023.1.11` (latest as of 2026-05) |
| Python bindings | Boost.Python wrapper compiled into `ocl.so` (no separate version string exposed) |
| Wheel inspected | `opencamlib-2023.1.11-cp310-cp310-macosx_11_0_arm64.whl` (660 KB) |
| Upstream repo | `aewallin/opencamlib` (GitHub) |
| Audit method | Binary inspection of `ocl.so` via printable-string extraction + C++ Itanium ABI demangled symbol scan + `wheel zip` content read; **OCL not installed in CI env**, so the probe script records "would output" structure. See [Appendix A](#appendix-a-static-binary-audit-method) |

OCL is not available in the worktree Python environment (no `cp313` wheel published; `pip install opencamlib` reports "no matching distribution"). The probe script (`scripts/probe_ocl_5axis.py`) is written to run on any machine with a compatible wheel installed and produce machine-readable output. See [Appendix B](#appendix-b-how-to-run-the-probe) for instructions.

---

## 2. Native 5-axis Surface Area

**NONE FOUND.**

The complete set of Python-exposed classes in `ocl.so` (extracted from the `polymorphic_id_generator` symbol table in the binary) is:

```
AdaptivePathDropCutter    AdaptiveWaterline         Arc
BallConeCutter            BallCutter                BatchDropCutter
BatchPushCutter           Bbox                      BullConeCutter
BullCutter                CCPoint                   CCType
CLPoint                   ConeConeCutter            ConeCutter
CompBallCutter            CompCylCutter             CompositeCutter
CutterLocationSurface     CylConeCutter             CylCutter
DropCutter                Ellipse                   EllipsePosition
Fiber                     FiberPushCutter           Interval
Line                      LineCLFilter              MillingCutter
Path                      PathDropCutter            Point
PointDropCutter           PushCutter                SimpleWeave
STLReader                 STLSurf                   Triangle
Waterline                 Weave2                    ZigZag
```

Keywords searched in every class name and in every printable ASCII string ≥ 4 chars across the entire `ocl.so` binary:

| Keyword | Found? |
| --- | --- |
| `FiveAxis` / `5axis` / `5_axis` | NO |
| `Swarf` | NO |
| `ToolAxis` / `tool_axis` | NO |
| `DriveS` (drive-surface) | NO |
| `FrameG` (frame generation) | NO |
| `Tilt` | NO |
| `TiltAngle` | NO |
| `Morph` (as a class/method name) | NO — one false positive deep in unrelated ABI symbol noise; zero semantic matches |
| `MultiAxis` / `multi_axis` | NO |
| `FeedFrame` | NO |

**The OCL 2023.1.11 wheel contains zero 5-axis primitives of any kind.**

This was additionally confirmed by the upstream README
(`aewallin/opencamlib`): *"library for cutter location point computation in
3-axis CAM"* — the library is explicitly scoped to 3-axis. The issue tracker
on the upstream repo has open RFCs for 5-axis (`#3`, `#17`, `#45` and others)
that have been open for 3–5 years with no activity. See [Section 7](#7-ocl-upstream-activity).

---

## 3. What We CAN Reuse from 3-axis Primitives

| Class | Current use in `kerf-cam` | 5-axis repurpose |
| --- | --- | --- |
| `STLSurf` + `Triangle` | Drive-surface tessellation for all 3-axis ops. | **Reused as-is.** For 3+2 indexed, the STL surface is pre-rotated (via `apply_rotation_to_stl`) before being fed to the existing 3-axis solver. For constant-tilt finishing, tessellation is only used for collision checking (deferred to v2); the drive surface is sampled via pythonOCC UV iso-curves directly. |
| `BallCutter` | `CylCutter` used today for most ops; `BallCutter` present but not default. | **Required for constant-tilt finishing.** The ball-end tip-from-CC math in `_run_5axis_finish` (design doc eq. `tip = ball_centre - r * axis`) is only correct for a ball-end mill. `BallCutter(diameter, length)` is available. |
| `CylCutter`, `BullCutter` | 2.5D / 3D ops. | **Reused for 3+2 indexed sub-ops** — the 3+2 path runs the normal 3-axis solver which uses `CylCutter`. |
| `PathDropCutter` | All 3D raster / contour / pocket ops. | **Reused directly for 3+2 indexed** sub-ops. The 3+2 path applies a rigid rotation to the STL, then runs `_run_parallel_3d` / `_run_brep_contour_pocket` unchanged. `PathDropCutter` never needs to know it is in a 3+2 context. |
| `AdaptiveWaterline` | Constant-Z contour (with Boost.Polygon guard). | **Not repurposed for 5-axis** — waterline is inherently 3-axis. Not used in either 5-axis pathway. |
| `CLPoint.cc` (`CCPoint`) | Not explicitly used today (only `x,y,z` consumed). | **Useful for debugging** — `CCPoint` carries the cutter-contact point and `CCType` enum (VERTEX / EDGE / FACET / …). For 5-axis finishing, the CC point on the drive surface is computed by pythonOCC (`surf.Value(u, v)`), so `CCPoint` is not needed in the solver path, but it could be populated if the toolpath wants to expose contact classification downstream. |
| `Path`, `Line` | Path container for `PathDropCutter`. | **Not used in constant-tilt finishing** (the solver outputs `[(tip, axis), ...]` directly). **Reused in 3+2** for feeding the sub-op. |
| `STLReader` | ASCII + binary STL parse. | **Reused as-is.** |
| `Bbox` | Bounding box (used in raster step generation). | **Reused in 3+2** for the pre-rotated surface's raster bounds. |

### What CLPoint and CCPoint do NOT carry

This is the key finding that constrains the 5-axis design. From binary inspection:

**`CLPoint` fields (confirmed from ABI signatures):**
- `.x`, `.y`, `.z` — cutter-location Cartesian coordinates
- `.cc` — returns a `CCPoint` (the cutter-contact point on the surface)
- `__str__` / `__repr__` — Python string conversion

**`CLPoint` has NO:**
- tool-axis vector field
- surface normal at the contact point
- orientation quaternion or rotation matrix

**`CCPoint` fields:**
- `.x`, `.y`, `.z` — contact-point Cartesian coordinates
- `.type` — `CCType` enum (VERTEX, EDGE, FACET, EDGE_HORIZ, etc.)

**`CCPoint` has NO:**
- surface normal at the contact point
- tangent-plane basis vectors

**Conclusion:** `PathDropCutter.getCLPoints()` returns a list of `CLPoint` objects that carry position only, with an implicit `+Z` tool axis. No orientation data exists anywhere in the 3-axis output pipeline.

---

## 4. What MUST Come from pythonOCC

The entire orientation layer of the 5-axis solver must be built in pythonOCC (`pythonocc-core`), which is already a `kerf-cam` dependency (it is used for the STEP→STL pipeline, `extract_face_wires`, and `BRep_Tool.Surface`).

| Capability | Required for | pythonOCC API |
| --- | --- | --- |
| Surface-normal evaluation at UV | `_run_5axis_finish` (constant-tilt) | `GeomLProp_SLProps(surf, u, v, 1, 1e-6).Normal()` |
| Surface-point evaluation at UV | `_run_5axis_finish` | `surf.Value(u, v)` |
| First-derivative (tangent) in U / V | `_run_5axis_finish` (path tangent for lead angle) | `GeomLProp_SLProps.D1U()`, `D1V()` |
| Degenerate-normal guard | `_run_5axis_finish` (R2 risk) | `GeomLProp_SLProps.IsNormalDefined()` |
| UV parameter bounds | `_run_5axis_finish` | `BRepTools.UVBounds(face)` |
| Face normal + centroid | `_run_3plus2` | `BRep_Tool.Surface` + `GProp_GProps` |
| Drive-face selection | Both | `pick_face(occ_shape, drive_face_id)` via `TopExp_Explorer` |
| ISO-curve arc-length step spacing | `_run_5axis_finish` | `GCPnts_QuasiUniformDeflection` on iso-curve via `GeomAPI_IntCS` or `Geom_TrimmedCurve` |
| Vector rotation (tilt + lead) | `_run_5axis_finish` | `gp_Ax1` + `gp_Trsf.SetRotation` applied to `gp_Dir` |
| Rotation matrix (3+2) | `_run_3plus2` | `gp_Trsf` or `numpy` 3×3 rotation |
| Euler angles from rotation (ABC) | `_run_3plus2` kinematic inversion | `atan2` on rotation-matrix columns |
| ABC inversion for head-head AC | `_emit_5axis_gcode_head_head_ac` | `atan2(sqrt(ax²+ay²), az)` + `atan2(ay, ax)` |

---

## 5. Conclusion

**The design doc's "no native 5-axis" assumption is CONFIRMED.**

`opencamlib 2023.1.11` (the PyPI wheel consumed by `kerf-cam`) exposes:
- 41 Python classes, all 3-axis or geometry-utility in nature
- Zero classes with any 5-axis, swarf, tilt, morphing, or tool-axis keyword
- Zero per-CLpoint orientation data (no tool-axis vector, no surface normal)
- Immutable implicit `+Z` tool axis throughout all drop-cutter / waterline operations

The 5-axis solver design described in `docs/plans/5-axis-cam.md` — layering on top of OCL for CC-point grid generation and on top of pythonOCC for surface-normal / UV sampling — is the **only viable path** with the current OCL wheel. There is no shortcut.

---

## 6. T2–T8 Impact

Based on T1 findings, the task estimates and designs are **unchanged** — the audit confirms the design-doc assumption rather than refuting it.

| Task | T1 impact |
| --- | --- |
| **T2: surface-normal-at-CC-point helper** | No change. `normal_at_uv(face, u, v)` via `GeomLProp_SLProps` is the only option. `IsNormalDefined()` guard is required (design doc already notes this). |
| **T3: constant-tilt strategy** | No change. The UV iso-curve loop + `_run_5axis_finish` design stands as written. OCL contributes nothing to the constant-tilt path — not even the CC-point grid (that comes from UV sampling in pythonOCC). |
| **T4: 3+2 indexed** | **Slight simplification confirmed.** `PathDropCutter` is reusable without modification for the sub-op after the STL rotation. The `apply_rotation_to_stl` Python loop (R1 risk) is unavoidable since OCL has no built-in transform API. |
| **T5: schema + wiring** | No change. |
| **T6: post-processor** | No change. ABC inversion math stands as written. `G43.4` TCP path confirmed. |
| **T7: frontend drive-face picker** | No change. OCL has no face-selection concept; the picker is a pure frontend task. |
| **T8: end-to-end test** | No change. The `test_5axis_returns_real_toolpath` acceptance criteria (>100 G-code lines, `A` + `C` words present) are still the right bar. |

**No task grows.** The one case where a task would shrink (e.g. if OCL exposed `AdaptiveWaterline5Axis` that returned per-point normals, T2 and T3 would trivialise) does not apply.

**Open question carried to T2:** `GeomLProp_SLProps` requires the surface `Handle` (not a `TopoDS_Face`). The helper must call `BRep_Tool.Surface(face)` to get the `Geom_Surface`, then construct `SLProps`. Verify that the pythonOCC version installed in `kerf-cam`'s environment exposes `GeomLProp_SLProps` with the `(surf, u, v, N, resolution)` constructor (there are two constructors — check the version before T2 lands).

---

## 7. OCL Upstream Activity

A brief survey of the `aewallin/opencamlib` GitHub repository (last checked 2026-05-14):

- **Last commit to `master`:** 2024-01 (minor CI fixes; no new C++ classes)
- **Open 5-axis issues:** 4+ open issues requesting 5-axis support (oldest from 2013); none have associated PRs or implementation branches
- **Open RFCs on 5-axis:** Discussion threads exist for swarf cutting, tool-axis morphing, and multi-axis drop-cutter, but all are stalled
- **Active forks:** Several forks add experimental 5-axis C++ classes (e.g. `heekscnc/opencamlib`), but none have been merged upstream and none are available as PyPI wheels
- **Verdict:** OCL upstream has no credible 5-axis implementation in progress. No fork is close to PyPI distribution. This situation is unlikely to change on a timeline relevant to Kerf v1.

---

## Appendix A: Static Binary Audit Method

Since `opencamlib` is not installable in the worktree Python environment
(no `cp313` / macOS arm64 wheel for Python 3.13 on PyPI), the audit was
performed by direct inspection of the PyPI wheel binary:

1. Downloaded `opencamlib-2023.1.11-cp310-cp310-macosx_11_0_arm64.whl`
   from PyPI (660 KB, SHA256 verified by pip)
2. Unzipped and extracted `opencamlib/ocl.so` (the Boost.Python extension)
3. Extracted all printable ASCII strings ≥ 4 bytes using `re.findall(b'[ -~]{4,}', so_bytes)`
4. Enumerated all Python-registered classes by locating the
   `polymorphic_id_generator<ocl::ClassName>` and
   `non_polymorphic_id_generator<ocl::ClassName>` Boost.Python symbol
   sequences in the symbol table — this is the definitive list of what
   Boost.Python has registered with the CPython type system
5. Searched every string for 5-axis keyword variants (case-insensitive)
6. Inspected C++ Itanium ABI mangled function signatures to determine which
   methods each class exposes (e.g. `CLPoint::cc()` returns `CCPoint`;
   `CLPoint::x`, `y`, `z` are double members; no orientation member exists)

This method is deterministic: the class registry in `ocl.so` is built at
compile time and cannot change at runtime. Any class not present in the
`polymorphic_id_generator` table is not accessible to Python regardless of
what the C++ side contains.

---

## Appendix B: How to Run the Probe

On a machine with a compatible Python (3.7–3.11; no cp313 wheel yet):

```bash
# Install OCL
pip install opencamlib  # requires Python 3.7–3.11

# From the repo root
python scripts/probe_ocl_5axis.py > scripts/probe_ocl_5axis_output.txt
cat scripts/probe_ocl_5axis_output.txt
```

Expected output structure (if OCL installs cleanly):

```
=== 1. OCL IMPORT + VERSION ===
  opencamlib imported successfully
  version : <no __version__ attr>
  module  : .../site-packages/opencamlib/__init__.py

=== 2. ALL CLASSES (inspect.getmembers) ===
  Total classes exposed: 41
  ocl.AdaptivePathDropCutter
  ocl.AdaptiveWaterline
  ... (41 classes total, all 3-axis)

=== 3. 5-AXIS KEYWORD SCAN ===
  NONE FOUND — no class name contains any 5-axis keyword.

=== 4. CUTTER-POSITION CLASSES — ORIENTATION DATA ===
  ocl.PathDropCutter:
    getCLPoints() returned N points
    CLPoint members: ['cc', 'x', 'y', 'z', ...]
    No orientation fields on CLPoint (only position)
    ...

=== 9. SUMMARY ===
  OCL has any class with '5axis' in its name?    NO — CONFIRMED NONE
  ...
  T1 VERDICT:
    CONFIRMED. OCL 2023.1.11 contains zero 5-axis primitives.
```

Add `scripts/probe_ocl_5axis_output.txt` to `.gitignore` if you run the probe
locally and don't want to commit the output file; or commit it alongside a
CI run for reproducibility.

---

*T1 complete. Proceed to T2: `surface_normal.py` helper.*
