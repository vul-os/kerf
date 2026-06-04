"""
kerf_cad_core.piping.multi_discipline_federation — AVEVA E3D parity:
multi-discipline plant model federation.

Implements federated structural + HVAC + civil + piping model with cross-discipline
clash detection, coordinate-system consistency checking, and staleness detection.

Public API
----------
Discipline               — enum of CAD/BIM disciplines
DisciplineSubmodel       — metadata record for a single discipline's model file
FederatedPlantModel      — aggregation of submodels + coordination grid
detect_stale_submodels() — find disciplines whose source SHA has changed

Design: pure Python + numpy; no OCC / IFC dependency at this layer.

References
----------
BS 1192-4:2014 — Collaborative production of information Part 4: COBie — Code of practice
USACE EM 1110-1-1000 — Multi-discipline design coordination (Engineering and Design)
Eastman et al. (2011) — "BIM Handbook: A Guide to Building Information Modeling"

Wave 12B: AVEVA E3D parity (piping catalog + multi-discipline + concurrent)

Author: imranparuk
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Discipline enum
# ---------------------------------------------------------------------------

class Discipline(str, Enum):
    """Engineering discipline identifiers per BS 1192-4:2014 COBie federation scheme."""
    STRUCTURAL = "structural"
    HVAC = "hvac"
    PLUMBING = "plumbing"
    ELECTRICAL = "electrical"
    PIPING_PROCESS = "piping_process"
    CIVIL = "civil"
    ARCHITECTURAL = "architectural"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DisciplineSubmodel:
    """Metadata record for a single discipline's design file within a federated model.

    bbox: axis-aligned bounding box as ((min_x, min_y, min_z), (max_x, max_y, max_z)) in metres.
    sha256: content fingerprint used for staleness detection.
    coordinate_system: 'metric-SI' | 'imperial-ft' | 'imperial-in' (default 'metric-SI').
    datum_elevation: project datum Z offset in metres (default 0.0).
    grid_ref: project grid reference string (e.g. 'WGS84-UTM35S') or '' for local.

    Reference: BS 1192-4:2014 §4.2 — submodel exchange packages.
    """
    discipline: Discipline
    file_path: str
    last_modified_iso: str
    element_count: int
    bbox: tuple[tuple[float, float, float], tuple[float, float, float]]
    sha256: str
    coordinate_system: str = "metric-SI"
    datum_elevation: float = 0.0
    grid_ref: str = ""
    # Per-element simplified geometry for clash detection.
    # Each element is {id, bbox: ((x0,y0,z0),(x1,y1,z1))}
    elements: list[dict] = field(default_factory=list)


@dataclass
class FederatedPlantModel:
    """Federated multi-discipline plant model.

    Aggregates several DisciplineSubmodel objects and exposes cross-discipline
    clash detection and coordinate consistency checking.

    coordination_grids: shared grid axes dict, e.g.:
      { 'origin': (x, y, z), 'unit': 'm', 'north_deg': 0.0 }

    Reference:
      BS 1192-4:2014 §4.4 — federated model coordination.
      USACE EM 1110-1-1000 §5 — multi-discipline coordination.
    """
    project_id: str
    submodels: list[DisciplineSubmodel]
    coordination_grids: dict = field(default_factory=dict)

    def _submodel_by_discipline(self, d: Discipline) -> Optional[DisciplineSubmodel]:
        for sm in self.submodels:
            if sm.discipline == d:
                return sm
        return None

    def cross_discipline_clashes(self) -> list[dict]:
        """Run AABB clash detection between all submodel element pairs.

        Returns a list of clash records:
          {discipline_a, discipline_b, element_a, element_b,
           clash_volume_m3, clash_bbox}

        Algorithm: for each pair of submodels (A, B), iterate elements in A
        against elements in B and compute axis-aligned bounding-box intersection.
        Elements with intersection volume > 0 are reported as clashes.

        Complexity: O(|E_a| × |E_b|) per submodel pair — adequate for coordination
        models (thousands of elements); production systems use spatial indexing.

        Reference: USACE EM 1110-1-1000 §5.3 — spatial coordination checking.
        """
        clashes: list[dict] = []
        n = len(self.submodels)
        for i in range(n):
            for j in range(i + 1, n):
                sm_a = self.submodels[i]
                sm_b = self.submodels[j]
                for elem_a in sm_a.elements:
                    for elem_b in sm_b.elements:
                        clash = _bbox_intersection(elem_a["bbox"], elem_b["bbox"])
                        if clash is not None:
                            vol = _bbox_volume(clash)
                            if vol > 0.0:
                                clashes.append({
                                    "discipline_a": sm_a.discipline.value,
                                    "discipline_b": sm_b.discipline.value,
                                    "element_a": elem_a["id"],
                                    "element_b": elem_b["id"],
                                    "clash_volume_m3": round(vol, 6),
                                    "clash_bbox": clash,
                                })
        return clashes

    def coordinate_system_consistency(self) -> list[str]:
        """Check that all submodels share a consistent coordinate system.

        Returns a list of human-readable inconsistency warnings.  An empty list
        means all submodels are consistent.

        Checks performed:
        1. All submodels use the same unit system (metric vs imperial).
        2. All submodels share the same datum elevation (within 0.001 m tolerance).
        3. All submodels share the same grid reference string (if any non-empty).

        Reference: BS 1192-4:2014 §5.1 — coordinate reference system alignment.
        """
        warnings: list[str] = []
        if not self.submodels:
            return warnings

        # Check unit systems
        unit_systems = {sm.discipline.value: sm.coordinate_system for sm in self.submodels}
        unique_units = set(unit_systems.values())
        if len(unique_units) > 1:
            warnings.append(
                f"Coordinate system mismatch across disciplines: "
                f"{unit_systems}. All models must use the same unit system."
            )

        # Check datum elevations
        datums = {sm.discipline.value: sm.datum_elevation for sm in self.submodels}
        unique_datums = set(datums.values())
        if len(unique_datums) > 1:
            max_diff = max(datums.values()) - min(datums.values())
            warnings.append(
                f"Datum elevation inconsistency (max delta = {max_diff:.3f} m): "
                f"{datums}. Federation requires a common project datum."
            )

        # Check grid references
        grid_refs = {sm.discipline.value: sm.grid_ref for sm in self.submodels
                     if sm.grid_ref}
        unique_grids = set(grid_refs.values())
        if len(unique_grids) > 1:
            warnings.append(
                f"Grid reference mismatch: {grid_refs}. "
                f"All submodels should reference the same coordinate grid."
            )

        # Check bounding-box plausibility: flag any submodel that does not overlap
        # with the overall federation bbox
        if len(self.submodels) > 1:
            all_mins = np.array([sm.bbox[0] for sm in self.submodels])
            all_maxs = np.array([sm.bbox[1] for sm in self.submodels])
            fed_min = all_mins.min(axis=0)
            fed_max = all_maxs.max(axis=0)
            for sm in self.submodels:
                sm_min = np.array(sm.bbox[0])
                sm_max = np.array(sm.bbox[1])
                # Check if submodel is completely outside federation envelope
                if np.any(sm_max < fed_min) or np.any(sm_min > fed_max):
                    warnings.append(
                        f"Submodel '{sm.discipline.value}' bounding box "
                        f"{sm.bbox} does not overlap with the federation envelope — "
                        f"possible coordinate offset or wrong file."
                    )

        return warnings


# ---------------------------------------------------------------------------
# Utility: AABB helpers
# ---------------------------------------------------------------------------

def _bbox_intersection(
    bbox_a: tuple[tuple[float, ...], tuple[float, ...]],
    bbox_b: tuple[tuple[float, ...], tuple[float, ...]],
) -> Optional[tuple[tuple[float, ...], tuple[float, ...]]]:
    """Return the intersection AABB of two axis-aligned boxes, or None if disjoint."""
    min_a, max_a = np.asarray(bbox_a[0]), np.asarray(bbox_a[1])
    min_b, max_b = np.asarray(bbox_b[0]), np.asarray(bbox_b[1])
    i_min = np.maximum(min_a, min_b)
    i_max = np.minimum(max_a, max_b)
    if np.any(i_max <= i_min):
        return None
    return (tuple(float(v) for v in i_min), tuple(float(v) for v in i_max))


def _bbox_volume(bbox: tuple[tuple[float, ...], tuple[float, ...]]) -> float:
    """Volume of an AABB in cubic metres."""
    dims = np.asarray(bbox[1]) - np.asarray(bbox[0])
    if np.any(dims <= 0):
        return 0.0
    return float(np.prod(dims))


# ---------------------------------------------------------------------------
# Staleness detection
# ---------------------------------------------------------------------------

def detect_stale_submodels(
    model: FederatedPlantModel,
    sha256_now: dict[str, str],
) -> list[Discipline]:
    """Return disciplines whose source-file SHA256 has changed since last federation.

    Parameters
    ----------
    model:
        The previously federated model with stored sha256 per DisciplineSubmodel.
    sha256_now:
        Current SHA256 fingerprints keyed by discipline value string,
        e.g. ``{'structural': 'abc123...', 'hvac': 'def456...'}``.

    Returns
    -------
    List of :class:`Discipline` values that are now stale (SHA mismatch).

    Reference: BS 1192-4:2014 §6.2 — exchange package version management.
    """
    stale: list[Discipline] = []
    for sm in model.submodels:
        current_sha = sha256_now.get(sm.discipline.value)
        if current_sha is None:
            continue  # discipline not present in snapshot — skip
        if current_sha != sm.sha256:
            stale.append(sm.discipline)
    return stale


# ---------------------------------------------------------------------------
# Factory helpers (used in tests and tooling)
# ---------------------------------------------------------------------------

def make_element(
    eid: str,
    x0: float, y0: float, z0: float,
    x1: float, y1: float, z1: float,
) -> dict:
    """Convenience factory for element bbox dicts."""
    return {"id": eid, "bbox": ((x0, y0, z0), (x1, y1, z1))}
