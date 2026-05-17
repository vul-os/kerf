# kerf-partsgen — parametric parts generator

`kerf-partsgen` generates parametric STEP solid geometry for standard mechanical fasteners and hardware using OpenCASCADE (via CadQuery). It produces verified `kind='part'` files that drop directly into Kerf's Workshop and BOM tooling without a lossy mesh round-trip.

---

## Architecture

```
kerf_partsgen.spec          — FamilySpec: which standards/sizes to generate
  ↓
kerf_partsgen.enumerate     — generate all (family, size) combinations
  ↓
kerf_partsgen.generators.*  — parametric OCCT geometry per standard
  ↓
kerf_partsgen.kernel        — OCCT primitives facade (box, cylinder, hex_prism, pad, revolve, booleans)
  ↓
kerf_partsgen.verify        — gate: watertight + volume + bounding-box checks
  ↓
kerf_partsgen.author        — embed provenance + standard citation
  ↓
kerf_partsgen.seed          — write verified parts to Kerf DB
```

---

## Geometry kernel (`kerf_partsgen.kernel`)

The kernel facade wraps the same OpenCASCADE engine Kerf uses for B-rep work. In production it binds through `pythonocc-core` (`kerf_cad_core.occ_helpers`); in the contributor/CI toolchain it binds via `cadquery` (which wraps `OCP`). Either satisfies the facade.

```python
from kerf_partsgen.kernel import (
    box, cylinder, hex_prism,          # primitives
    sketch_circle, sketch_polygon,     # sketch builders
    union, cut, intersect, translate,  # booleans + transform
    chamfer_top_edge,                  # dress-up
)

# Build an M8×30 hex head bolt (simplified):
head = hex_prism(across_flats=13.0, height=5.3)
shaft = cylinder(radius=4.0, height=30.0)
bolt = union(head, translate(shaft, 0, 0, -15))
bolt.export_step("/tmp/M8x30.step")
```

`GeneratedPart` is the kernel output: `solid`, `is_valid`, `volume_mm3`, `bbox_mm`. The verification gate re-measures these straight off the kernel — generator-declared numbers are never trusted blindly.

When no kernel binding is available (`KERNEL_BACKEND == "none"`), calling any geometry primitive raises `KernelUnavailable`. The `enumerate` loop catches this and records a `FAIL` per variant so markdown and attribution tests remain hermetic without the kernel.

---

## Generators

Each generator is a Python module in `kerf_partsgen/generators/`. It must expose a `generate(params: dict) → GeneratedPart` function.

| Generator | Standard |
|---|---|
| `iso_4017_hex_head_bolt` | ISO 4017 / DIN 933 hex head bolt |
| `iso_4762_socket_head_cap_screw` | ISO 4762 socket head cap screw |
| `iso_4032_hex_nut` | ISO 4032 hex nut |
| `iso_7089_flat_washer` | ISO 7089 flat washer |
| `din_125_plain_washer` | DIN 125-A plain washer |

Generators compose kernel primitives: a hex head bolt is a `hex_prism` unioned with a `cylinder` shaft with an optional `chamfer_top_edge` for the point lead-in.

---

## Enumerate (`kerf_partsgen.enumerate`)

`enumerate` iterates all (standard, size) combinations defined by the `FamilySpec` and calls the appropriate generator for each. Results are `EnumeratedPart` objects tagged `PASS` / `FAIL` based on the verification gate.

```python
from kerf_partsgen.enumerate import enumerate_family
results = enumerate_family("iso_4017_hex_head_bolt")
passed = [r for r in results if r.status == "PASS"]
```

---

## Verification gate (`kerf_partsgen.verify`)

After geometry is built the gate checks:
1. `is_valid` — OCC `Shape.isValid()` must be True
2. Volume plausibility — must be within ±20% of the analytically-expected volume
3. Bounding-box plausibility — each dimension within tolerance of the standard tabulated value
4. Watertight probe — exports to STEP, re-imports, checks that the solid has no open shells

Any failure marks the variant `FAIL` and records a human-readable reason. This prevents silently seeding broken geometry into the library.

---

## Attribution (`kerf_partsgen.author`)

Each generated part gets an `attribution` block embedded in `metadata` citing:
- The generator module version
- The normative standard (e.g. "ISO 4017:2011, Table 1")
- The kerf-partsgen repository URL and commit SHA

Because geometry is generated (not ingested from an upstream repo), `original_author` is set to the generator author(s) and `source_project` to `kerf-partsgen`.

---

## CLI (`kerf_partsgen.cli`)

```bash
python -m kerf_partsgen enumerate --family iso_4017_hex_head_bolt
python -m kerf_partsgen seed --dry-run
python -m kerf_partsgen seed --all
```

The `seed` command writes passed variants to the Kerf DB as `kind='part'` files using the same `kerf_parts.seed` infrastructure.

---

## Wishlist (`kerf_partsgen.wishlist`)

`wishlist.py` tracks standard families not yet implemented, prioritised by BOM occurrence frequency. Adding a new family: implement a generator in `generators/`, register it in the family spec, run `enumerate`, verify all sizes pass, submit.
