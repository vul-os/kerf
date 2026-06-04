# Intraoral Scan Processing

> Load, align, and clean intraoral STL scans; detect arch landmarks for downstream crown and guide workflows.

**Module**: `packages/kerf-dental/src/kerf_dental/intraoral_scan.py`
**Shipped**: Wave 10
**LLM tools**: `dental_register_scans`

---

## What it is

Intraoral scan processing reads binary or ASCII STL meshes produced by intraoral scanners, detects dental arch landmarks (midline, quadrant boundaries, approximate tooth centroids), aligns upper and lower scans to a common bite registration, and removes scan artefacts (floating triangles, duplicate vertices). The output is a clean `IntraoralScan` object ready for crown design or surgical guide placement.

## How to use it

### From chat

> "Load upper.stl and lower.stl and align them to my bite registration."

### From Python

```python
from kerf_dental.intraoral_scan import (
    load_intraoral_stl, detect_arch_landmarks,
    remove_artifacts, align_bite,
)

upper = load_intraoral_stl("upper.stl")
lower = load_intraoral_stl("lower.stl")

upper_clean = remove_artifacts(upper)
lower_clean = remove_artifacts(lower)

upper_landmarks = detect_arch_landmarks(upper_clean)
aligned_lower = align_bite(upper_clean, lower_clean)
print(upper_landmarks["midline_x_mm"])
```

### From an LLM tool spec

```json
{"tool": "dental_register_scans", "input": {"upper_stl_path": "upper.stl", "lower_stl_path": "lower.stl", "bite_registration_path": "bite.stl"}}
```

## How it works

STL loading handles both binary (80-byte header, triangle count) and ASCII formats. Arch landmark detection projects the mesh onto the occlusal plane and traces the arch curve using principal-axis analysis of the tooth-centroid point cloud. Bite alignment uses ICP (Iterative Closest Point) with the bite-registration mesh as the target, iterating until the mean point-to-surface distance is below 0.05 mm.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `load_intraoral_stl(path)` | `IntraoralScan` | Parse STL file into scan object |
| `load_intraoral_stl_from_bytes(data)` | `IntraoralScan` | Parse from raw bytes |
| `detect_arch_landmarks(scan)` | `dict` | Midline, quadrant boundaries, tooth centroids |
| `remove_artifacts(scan)` | `IntraoralScan` | Remove floating triangles and duplicate verts |
| `align_bite(upper, lower)` | `IntraoralScan` | ICP-align lower to upper arch |

## Example

```python
scan = load_intraoral_stl("scan.stl")
# IntraoralScan(n_vertices=45230, n_faces=90410, arch='upper')
lm = detect_arch_landmarks(scan)
# {'midline_x_mm': 0.3, 'arch_length_mm': 128.4, 'tooth_centroids': [...]}
```

## Honest caveats

ICP alignment requires a good initial pose; if the bite registration is heavily trimmed or the scans are misoriented by more than 30°, alignment may converge to a local minimum. Tooth centroid detection assumes a full arch; missing teeth require manual centroid annotation. STL files from different scanner brands may have non-manifold edges that survive artifact removal.

## References

- Besl & McKay, "A Method for Registration of 3-D Shapes," *IEEE PAMI* 14(2), 1992.
- Mozzo et al., "A new volumetric CT machine for dental imaging," *Eur. Radiol.* 8(9), 1998.
