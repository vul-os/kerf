# OCC Helpers (`occ_helpers.py`)

Shared pythonOCC utility layer for Kerf CAD compute plugins: STEP file
loading, incremental BRep meshing, and STL export, with a graceful
`_OCC_AVAILABLE` availability gate.

---

## When to use

Use these helpers when a plugin or script needs to:

- load a STEP file into an OCC `TopoDS_Shape` for downstream B-rep operations
- tessellate an OCC shape in-place before STL export or triangle-mesh tools
- write an STL from an OCC shape (ASCII or binary)
- convert a STEP file directly to STL in one call

Always check `_OCC_AVAILABLE` or handle the `RuntimeError` if pythonOCC
may not be installed.

---

## Public API

### `_OCC_AVAILABLE: bool`

`True` when `pythonocc-core` (via conda-forge or pip) is importable;
`False` otherwise.  Check this flag before calling any function if you
need a soft fallback path.

---

### `load_step(step_path: str) -> TopoDS_Shape`

Read a STEP file and return the OCC compound shape.

```python
from kerf_cad_core.occ_helpers import load_step
shape = load_step("/data/part.step")
```

**Raises:** `RuntimeError` if pythonOCC is not installed or the file
cannot be read by `STEPControl_Reader`.
The shape can be reused across multiple operations without re-reading.

---

### `mesh_shape(shape, linear_deflection: float = 0.1) -> None`

Tessellate an OCC shape in-place using `BRepMesh_IncrementalMesh`.

```python
from kerf_cad_core.occ_helpers import mesh_shape
mesh_shape(shape, linear_deflection=0.05)   # finer mesh
```

`linear_deflection` controls quality: smaller = finer triangulation,
slower.  Must be called before `write_stl`.
**Raises:** `RuntimeError` if meshing fails or pythonOCC is absent.

---

### `write_stl(shape, stl_path: str, ascii_mode: bool = True) -> None`

Write an already-meshed OCC shape to an STL file via `StlAPI_Writer`.

```python
from kerf_cad_core.occ_helpers import write_stl
write_stl(shape, "/tmp/output.stl", ascii_mode=False)
```

`ascii_mode=True` (default) writes ASCII STL; `False` writes binary.
**Raises:** `RuntimeError` if pythonOCC is absent or writing fails.

---

### `convert_step_to_stl(step_path, stl_path, linear_deflection=0.1) -> TopoDS_Shape`

One-shot convenience: load STEP → mesh → write ASCII STL, returning the
shape for further B-rep reuse.

```python
from kerf_cad_core.occ_helpers import convert_step_to_stl

shape = convert_step_to_stl("/data/part.step", "/tmp/part.stl", linear_deflection=0.08)
# shape is a live TopoDS_Compound; reuse for boolean ops, face queries, etc.
```

**Raises:** `RuntimeError` at any failing stage.

---

## Supported input contract

- STEP format: AP203 / AP214 files readable by OpenCASCADE `STEPControl_Reader`.
- Meshing: `linear_deflection` in millimetres (same unit as the STEP geometry).
- STL output: ASCII mode by default; toggle `ascii_mode=False` for binary (smaller files).
- `_OCC_AVAILABLE = False` on environments without `pythonocc-core`; install via:
  `conda install -c conda-forge pythonocc-core`

---

## Usage examples

**Load STEP and inspect shape type:**

```python
from kerf_cad_core.occ_helpers import _OCC_AVAILABLE, load_step
if _OCC_AVAILABLE:
    shape = load_step("/parts/bracket.step")
    print(shape.ShapeType())   # e.g. TopAbs_COMPOUND
```

**Batch STEP → STL pipeline:**

```python
from kerf_cad_core.occ_helpers import convert_step_to_stl
shape = convert_step_to_stl("bracket.step", "bracket.stl", 0.05)
# continue with B-rep queries on shape...
```

---

## References

OpenCASCADE Technology (OCCT) documentation — `STEPControl_Reader`, `BRepMesh_IncrementalMesh`, `StlAPI_Writer`.
ISO 10303-21 (STEP Physical File Format).
