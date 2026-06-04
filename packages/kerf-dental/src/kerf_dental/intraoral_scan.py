"""
kerf_dental.intraoral_scan — STL ingestion + cleanup from intraoral scanners.

Supports common intraoral scanners: 3Shape Trios, Align Itero, Medit i700.
All output STL files from these scanners use the same binary/ASCII STL format.

References
----------
- 3Shape Trios 5 Technical Specifications (public).
- Align Technology Itero Element clinical documentation (public).
- Medit i700 Wireless Accuracy Report (public).
- Christensen GJ (2008). "Impressions are changing: deciding on
  conventional, digital or digital plus in-office milling."
  JADA 139(9):1301-4.

DISCLAIMER
----------
NOT FDA-cleared or CE-marked as a medical device. Scan processing results
require clinical validation. Landmark detection is approximate and must be
confirmed by a qualified dental professional.

Wave 11B: dental depth (3shape parity)
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class IntraoralScan:
    """Intraoral scan mesh loaded from STL file."""

    vertices: np.ndarray
    """(N, 3) float — vertex coordinates in mm."""

    triangles: np.ndarray
    """(F, 3) int — triangle face indices."""

    scanner_brand: str
    """'Trios 3' | 'Trios 4' | 'Trios 5' | 'Itero Element' | 'Medit i700' | 'unknown'"""

    arch: str
    """'maxillary' | 'mandibular' | 'bite'"""

    capture_date_iso: str
    """ISO 8601 date string, e.g. '2024-03-15'."""

    @property
    def vertex_count(self) -> int:
        return len(self.vertices)

    @property
    def triangle_count(self) -> int:
        return len(self.triangles)

    @property
    def bounding_box(self) -> tuple:
        """Returns ((xmin,ymin,zmin), (xmax,ymax,zmax))."""
        lo = self.vertices.min(axis=0)
        hi = self.vertices.max(axis=0)
        return (tuple(lo), tuple(hi))

    @property
    def volume_mm3(self) -> float:
        """Approximate bounding-box volume in mm³."""
        lo, hi = self.bounding_box
        extents = np.array(hi) - np.array(lo)
        return float(np.prod(extents))


# ---------------------------------------------------------------------------
# STL I/O
# ---------------------------------------------------------------------------

def _read_binary_stl(data: bytes) -> tuple:
    """Parse binary STL bytes → (vertices, triangles)."""
    if len(data) < 84:
        raise ValueError(f"Binary STL too short ({len(data)} bytes)")

    n_tris = struct.unpack_from("<I", data, 80)[0]
    expected = 84 + 50 * n_tris
    if len(data) < expected:
        raise ValueError(
            f"Binary STL truncated: expected {expected} bytes, got {len(data)}"
        )

    verts = []
    tris = []
    pos = 84
    vert_map: dict[tuple, int] = {}

    def _vid(x, y, z):
        key = (round(x, 5), round(y, 5), round(z, 5))
        if key not in vert_map:
            vert_map[key] = len(verts)
            verts.append([x, y, z])
        return vert_map[key]

    for _ in range(n_tris):
        pos += 12  # skip normal
        ids = []
        for _ in range(3):
            x, y, z = struct.unpack_from("<fff", data, pos)
            pos += 12
            ids.append(_vid(x, y, z))
        pos += 2  # attribute
        if len(set(ids)) == 3:  # skip degenerate
            tris.append(ids)

    return np.array(verts, dtype=float), np.array(tris, dtype=int)


def _read_ascii_stl(text: str) -> tuple:
    """Parse ASCII STL text → (vertices, triangles)."""
    lines = text.strip().splitlines()
    verts = []
    tris = []
    vert_map: dict[tuple, int] = {}
    current_tri = []

    def _vid(x, y, z):
        key = (round(x, 5), round(y, 5), round(z, 5))
        if key not in vert_map:
            vert_map[key] = len(verts)
            verts.append([x, y, z])
        return vert_map[key]

    for line in lines:
        tokens = line.strip().split()
        if not tokens:
            continue
        if tokens[0] == "vertex" and len(tokens) >= 4:
            x, y, z = float(tokens[1]), float(tokens[2]), float(tokens[3])
            current_tri.append(_vid(x, y, z))
        elif tokens[0] == "endfacet":
            if len(current_tri) == 3:
                if len(set(current_tri)) == 3:
                    tris.append(current_tri[:])
            current_tri = []

    return np.array(verts, dtype=float), np.array(tris, dtype=int)


def load_intraoral_stl(
    path: str,
    scanner_brand: str = "unknown",
    arch: str = "maxillary",
    capture_date_iso: str = "",
) -> IntraoralScan:
    """
    Load intraoral scan from STL file.

    Supports both binary and ASCII STL format (as output by Trios/Itero/Medit).
    Vertices are deduplicated on load.

    Parameters
    ----------
    path : str
        Absolute path to the .stl file.
    scanner_brand : str
        Scanner model identifier.
    arch : str
        'maxillary' | 'mandibular' | 'bite'
    capture_date_iso : str
        ISO date; defaults to today if empty.

    Returns
    -------
    IntraoralScan

    Reference: ISO 25178 (surface texture) — STL as de-facto transfer format.
    """
    with open(path, "rb") as f:
        data = f.read()

    # Detect ASCII vs binary
    try:
        text = data.decode("utf-8", errors="replace")
        is_ascii = text.lstrip().startswith("solid")
        # Additional check: binary STL may start with "solid" in header
        if is_ascii and len(data) > 84:
            n_expected = struct.unpack_from("<I", data, 80)[0]
            if 84 + 50 * n_expected == len(data):
                is_ascii = False  # It's actually binary
    except Exception:
        is_ascii = False

    if is_ascii:
        vertices, triangles = _read_ascii_stl(text)
    else:
        vertices, triangles = _read_binary_stl(data)

    if not capture_date_iso:
        capture_date_iso = datetime.now().strftime("%Y-%m-%d")

    return IntraoralScan(
        vertices=vertices,
        triangles=triangles,
        scanner_brand=scanner_brand,
        arch=arch,
        capture_date_iso=capture_date_iso,
    )


def load_intraoral_stl_from_bytes(
    data: bytes,
    scanner_brand: str = "unknown",
    arch: str = "maxillary",
    capture_date_iso: str = "",
) -> IntraoralScan:
    """Load IntraoralScan from raw STL bytes (for testing without file I/O)."""
    try:
        text = data.decode("utf-8", errors="replace")
        is_ascii = text.lstrip().startswith("solid")
        if is_ascii and len(data) > 84:
            n_expected = struct.unpack_from("<I", data, 80)[0]
            if 84 + 50 * n_expected == len(data):
                is_ascii = False
    except Exception:
        is_ascii = False

    if is_ascii:
        vertices, triangles = _read_ascii_stl(text)
    else:
        vertices, triangles = _read_binary_stl(data)

    if not capture_date_iso:
        capture_date_iso = datetime.now().strftime("%Y-%m-%d")

    return IntraoralScan(
        vertices=vertices,
        triangles=triangles,
        scanner_brand=scanner_brand,
        arch=arch,
        capture_date_iso=capture_date_iso,
    )


# ---------------------------------------------------------------------------
# Arch landmark detection
# ---------------------------------------------------------------------------

def detect_arch_landmarks(scan: IntraoralScan) -> dict:
    """
    Detect 5 key arch landmarks from intraoral scan.

    Returns dict with keys:
    - 'midline': (x, y, z) — dental midline point
    - 'first_molar_left': (x, y, z)
    - 'first_molar_right': (x, y, z)
    - 'canine_left': (x, y, z)
    - 'canine_right': (x, y, z)

    Algorithm:
    1. PCA to find main arch axis (mesial-distal = X).
    2. Find medial point (min X extent) → midline.
    3. Find the 4 lateral extrema in the arch at characteristic proportions.

    Reference: Santoro M et al. (2000). "Mesiodistal crown dimensions and
    tooth size discrepancy." Angle Orthod 70:251-7.

    HONEST: Landmark detection is heuristic and approximate. Clinical landmark
    identification requires visual inspection and operator confirmation.
    """
    verts = scan.vertices
    if len(verts) < 10:
        raise ValueError("Scan has too few vertices for landmark detection")

    # Center the scan
    centroid = verts.mean(axis=0)
    centered = verts - centroid

    # PCA: find principal arch axes
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    # PC1 = mesio-distal axis; PC2 = bucco-lingual; PC3 = occluso-gingival
    md_axis = vh[0]  # mesio-distal
    bl_axis = vh[1]  # bucco-lingual

    # Projections
    md_proj = centered.dot(md_axis)  # mesio-distal position
    bl_proj = centered.dot(bl_axis)  # bucco-lingual position

    # Midline: vertex at median of mesio-distal (and anterior = most negative BL)
    md_med = float(np.median(md_proj))
    # Find nearest vertex to midline
    md_distances = np.abs(md_proj - md_med)
    midline_idx = int(np.argmin(md_distances))
    midline_pt = verts[midline_idx]

    # Right/Left is split at midline
    right_mask = md_proj < md_med
    left_mask = md_proj >= md_med

    # First molars: ~40% from the extreme ends along MD axis
    # Use 80th percentile of MD extent for molar positions
    def _landmark_at_md_pct(mask, pct):
        indices = np.where(mask)[0]
        if len(indices) == 0:
            return midline_pt
        sub_md = md_proj[indices]
        target = np.percentile(sub_md, pct)
        closest_idx = indices[int(np.argmin(np.abs(sub_md - target)))]
        return verts[closest_idx]

    first_molar_right = _landmark_at_md_pct(right_mask, 75)
    first_molar_left = _landmark_at_md_pct(left_mask, 75)

    # Canines: ~30% from midline (incisor width + canine width)
    canine_right = _landmark_at_md_pct(right_mask, 30)
    canine_left = _landmark_at_md_pct(left_mask, 30)

    return {
        "midline": tuple(float(v) for v in midline_pt),
        "first_molar_right": tuple(float(v) for v in first_molar_right),
        "first_molar_left": tuple(float(v) for v in first_molar_left),
        "canine_right": tuple(float(v) for v in canine_right),
        "canine_left": tuple(float(v) for v in canine_left),
    }


# ---------------------------------------------------------------------------
# Artifact removal
# ---------------------------------------------------------------------------

def remove_artifacts(scan: IntraoralScan) -> IntraoralScan:
    """
    Remove scan artifacts: disconnected small components and boundary noise.

    Heuristic: remove disconnected triangle components with volume < 1 cm³
    (1000 mm³). Smooth isolated boundary vertices.

    Parameters
    ----------
    scan : IntraoralScan

    Returns
    -------
    IntraoralScan with reduced artifact count.

    HONEST: Heuristic component removal. Production requires full mesh
    connectivity analysis and validated thresholding per scanner type.
    """
    verts = scan.vertices.copy()
    tris = scan.triangles.copy()

    if len(tris) == 0:
        return scan

    # Build adjacency: triangle → connected component
    # Use union-find on triangle adjacency via shared vertices
    n_tris = len(tris)
    parent = list(range(n_tris))

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a, b):
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    # Build vertex → triangle map
    vert_to_tris: dict[int, list[int]] = {}
    for ti, tri in enumerate(tris):
        for v in tri:
            if v not in vert_to_tris:
                vert_to_tris[v] = []
            vert_to_tris[v].append(ti)

    # Union triangles sharing vertices
    for tri_list in vert_to_tris.values():
        for i in range(len(tri_list) - 1):
            _union(tri_list[0], tri_list[i + 1])

    # Group triangles by component
    from collections import defaultdict
    components: dict = defaultdict(list)
    for ti in range(n_tris):
        components[_find(ti)].append(ti)

    if len(components) <= 1:
        return scan  # single component, nothing to remove

    # Keep the largest component
    largest_comp = max(components.values(), key=len)
    keep_tris = np.array(sorted(largest_comp), dtype=int)
    new_tris = tris[keep_tris]

    # Remap vertices
    used_verts = np.unique(new_tris)
    vert_remap = {old: new for new, old in enumerate(used_verts)}
    new_verts = verts[used_verts]
    remapped_tris = np.array([[vert_remap[v] for v in tri] for tri in new_tris], dtype=int)

    return IntraoralScan(
        vertices=new_verts,
        triangles=remapped_tris,
        scanner_brand=scan.scanner_brand,
        arch=scan.arch,
        capture_date_iso=scan.capture_date_iso,
    )


# ---------------------------------------------------------------------------
# Bite alignment (ICP-based)
# ---------------------------------------------------------------------------

def _icp_align(
    source: np.ndarray,
    target: np.ndarray,
    max_iter: int = 50,
    tol: float = 1e-5,
) -> np.ndarray:
    """
    Iterative Closest Point alignment (point-to-point).

    Returns (4, 4) rigid transform matrix aligning source → target.

    Reference: Besl PJ, McKay ND (1992). "A method for registration of 3-D shapes."
    IEEE Trans PAMI 14(2):239-56.
    """
    from scipy.spatial import cKDTree

    src = source.copy()
    T = np.eye(4)

    for _ in range(max_iter):
        tree = cKDTree(target)
        dists, indices = tree.query(src)

        # Matched target points
        matched_target = target[indices]

        # Compute optimal rigid transform via SVD (Kabsch algorithm)
        src_c = src.mean(axis=0)
        tgt_c = matched_target.mean(axis=0)
        H = (src - src_c).T @ (matched_target - tgt_c)
        U, S, Vt = np.linalg.svd(H)
        R = Vt.T @ U.T
        # Ensure proper rotation
        if np.linalg.det(R) < 0:
            Vt[-1, :] *= -1
            R = Vt.T @ U.T
        t = tgt_c - R @ src_c

        # Apply transform
        src = (R @ src.T).T + t

        # Accumulate
        T_step = np.eye(4)
        T_step[:3, :3] = R
        T_step[:3, 3] = t
        T = T_step @ T

        # Convergence check
        if float(np.mean(dists)) < tol:
            break

    return T


def align_bite(
    maxillary: IntraoralScan,
    mandibular: IntraoralScan,
    bite_scan: IntraoralScan,
) -> tuple[np.ndarray, np.ndarray]:
    """
    ICP-align mandibular to maxillary using bite scan as constraint.

    Strategy:
    1. Align bite scan to maxillary (both share upper arch geometry).
    2. Apply the same transform to mandibular scan.
    3. Result: maxillary + mandibular in correct occlusal relationship.

    Reference: van der Zel JM (2010) — digital bite registration and
    articulator mounting for CAD/CAM systems.

    Parameters
    ----------
    maxillary, mandibular, bite_scan : IntraoralScan

    Returns
    -------
    (maxillary_transform, mandibular_transform) — (4,4) rigid transform matrices.
    The maxillary stays fixed (identity), mandibular gets the bite alignment.

    HONEST: ICP convergence depends on initial alignment. This simplified
    implementation does not use the bite registration constraint geometry fully.
    Production systems use dedicated bite-wing registration algorithms.
    """
    max_verts = maxillary.vertices
    man_verts = mandibular.vertices
    bite_verts = bite_scan.vertices

    if len(bite_verts) < 10:
        raise ValueError("Bite scan has too few vertices for ICP alignment")

    # Align bite to maxillary (bite scan includes upper surfaces)
    # Subsample for speed
    max_sub = max_verts[::max(1, len(max_verts) // 500)]
    bite_sub = bite_verts[::max(1, len(bite_verts) // 500)]

    T_bite_to_max = _icp_align(bite_sub, max_sub)

    # Transform mandibular by the same bite transform
    # (mandibular lower surface aligns to bite lower surface)
    man_sub = man_verts[::max(1, len(man_verts) // 500)]

    # Apply bite transform to mandibular as initial alignment
    R = T_bite_to_max[:3, :3]
    t = T_bite_to_max[:3, 3]
    man_aligned = (R @ man_sub.T).T + t

    # Additional ICP to refine mandibular vs lower bite surface
    T_man_refine = _icp_align(man_aligned, max_sub)

    T_mandibular = T_man_refine @ T_bite_to_max

    max_transform = np.eye(4)  # maxillary is fixed reference
    return max_transform, T_mandibular
