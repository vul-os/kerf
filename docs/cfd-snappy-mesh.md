# SnappyHexMesh Hex-Dominant Meshing

> Generate body-fitted hex-dominant meshes from STL geometry using a snappyHexMesh-style refinement, snapping, and layer addition algorithm.

**Module**: `packages/kerf-cfd/src/kerf_cfd/meshing/snappy_hex.py`
**Shipped**: Wave 10
**LLM tools**: `cfd_snappy_mesh`

---

## What it is

blockMesh generates structured hexahedral meshes only for simple geometries. Real engineering parts (car bodies, complex ducts, propeller blades) require body-fitted unstructured meshes that wrap tightly around curved surfaces. SnappyHexMesh is OpenFOAM's automated hex-dominant mesher — it starts from a background Cartesian grid, refines cells near surfaces, snaps boundary vertices onto the surface, and grows prismatic boundary layers.

This module implements the same three-phase algorithm: (1) background Cartesian grid with multi-level refinement zones defined by a `HexMeshSpec`, (2) surface snapping that projects boundary vertices onto the STL geometry, and (3) mesh quality reporting. It does not require OpenFOAM to be installed — it generates the mesh in Python and can export it as an OpenFOAM polyMesh or return it as a NumPy mesh object.

## How to use it

### From chat (natural language)

> "Generate a hex mesh around the car body STL with 4 levels of surface refinement and 3 prismatic layers"

The LLM calls `cfd_snappy_mesh` with the geometry and refinement spec.

### From Python

```python
from kerf_cfd.meshing.snappy_hex import snappy_hex_mesh, HexMeshSpec

spec = HexMeshSpec(
    background_size=0.5,         # background cell size (m)
    domain_bounds=((-3,-2,-1), (6,2,2)),
    refinement_levels=4,
    surface_geometry=stl_file_path,
    n_boundary_layers=3,
    boundary_layer_expansion=1.3,
)
mesh = snappy_hex_mesh(spec)
print(f"Cells: {len(mesh.connectivity)}")
quality = estimate_mesh_quality(mesh)
print(f"Min orthogonality: {quality['min_orthogonality']:.3f}")
```

### From an LLM tool spec

```json
{"tool": "cfd_snappy_mesh", "stl_id": "car_body",
 "background_size": 0.5, "refinement_levels": 4, "n_layers": 3}
```

## How it works

Phase 1 builds a Cartesian background grid and recursively refines cells that intersect the surface geometry (based on distance to the STL triangles) until the specified refinement level is reached. Phase 2 snaps boundary cell vertices onto the nearest STL surface point using a Laplacian projection. Phase 3 grows prismatic cells from boundary faces inward using face extrusion and Laplacian smoothing.

Mesh quality is measured by non-orthogonality (angle between face normal and cell-centre connector) and maximum skewness; cells failing the quality thresholds are reported.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `snappy_hex_mesh(spec)` | `HexMesh` | Generate hex-dominant mesh |
| `estimate_mesh_quality(mesh)` | `dict` | Quality metrics |

`HexMeshSpec` fields: `background_size`, `domain_bounds`, `refinement_levels`, `surface_geometry`, `n_boundary_layers`, `boundary_layer_expansion`.
`HexMesh` fields: `vertices`, `connectivity`, `boundary_faces`, `cell_volumes`.

## Example

```python
mesh = snappy_hex_mesh(spec)
quality = estimate_mesh_quality(mesh)
print(f"Max skewness: {quality['max_skewness']:.3f}")  # should be < 4
print(f"Max non-orthogonality: {quality['max_non_ortho_deg']:.1f}°")  # should be < 70°
```

## Honest caveats

This is a Python re-implementation of the snappyHexMesh algorithm, not a wrapper around the binary. For production meshes on complex geometries, use the OpenFOAM snappyHexMesh binary via the OpenFOAM bridge. The surface snapping phase can produce poor-quality cells for surfaces with high curvature relative to the background cell size; refine the background grid near high-curvature regions. Boundary layer meshing is not yet fully implemented for concave corners.

## References

- OpenFOAM Foundation (2023). *snappyHexMesh User Guide*, v11.
- Jasak, Jemcov & Tukovic (2007). "OpenFOAM: A C++ library for complex physics simulations." *International Workshop on Coupled Methods in Numerical Dynamics*.
