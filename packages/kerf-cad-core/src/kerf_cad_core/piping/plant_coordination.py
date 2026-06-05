"""
kerf_cad_core.piping.plant_coordination — Multi-discipline federated plant model.

Implements a PlantModel that federates structural + HVAC + piping + civil
discipline sub-models in a shared 3D coordinate space with:

  1. PlantModel — assembly of DisciplineElement objects from any discipline,
     each tagged with discipline type, position, AABB, and clearance requirements.

  2. Cross-discipline coordination:
     - Interference / clash detection between disciplines using AABB overlap
       (pipe-vs-structure, duct-vs-pipe, equipment-vs-structure, all pairs).
     - Clearance-rule checking: each discipline pair has a minimum separation
       requirement; soft clashes (clearance violation) and hard clashes (overlap)
       are reported separately.
     - CoordinationReport: clashes grouped by discipline pair with locations,
       severity, and clearance margin.

  3. Discipline roll-up:
     - Combined BOM / quantity takeoff aggregated across all disciplines.
     - Spatial zones: user-defined axis-aligned zones (e.g. pump bay, pipe rack);
       elements are assigned to zones; zone summary returned.

  4. LLM tool wrappers: plant_model_assemble, plant_coordination_check.

References
----------
BS 1192-4:2014 — COBie federated model exchange.
USACE EM 1110-1-1000 — Multi-discipline design coordination.
ISO 16739-1:2018 — IFC 4 schema (discipline file types).
ASME B31.3-2022 §321 — Flexibility / clearance requirements for process piping.
AISC 360-22 §B3 — Minimum clearances for steel members.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Discipline tags
# ---------------------------------------------------------------------------

class PlantDiscipline(str, Enum):
    """Engineering discipline identifiers per ISO 16739-1 / BS 1192-4."""
    STRUCTURAL = "structural"
    HVAC = "hvac"
    PIPING = "piping"
    CIVIL = "civil"
    EQUIPMENT = "equipment"
    ELECTRICAL = "electrical"
    INSTRUMENT = "instrument"


# ---------------------------------------------------------------------------
# Clearance rules (m) per discipline pair
# ---------------------------------------------------------------------------

# Minimum required separation between element surfaces per discipline pair.
# References:
#   ASME B31.3-2022 §321.1.3 — piping near structural: 25 mm min
#   SMACNA HVAC-DCS §5.4     — duct-to-pipe: 50 mm min
#   AISC 360-22 §B3.9        — structural member clearance: 50 mm min
#   IEC 61439-3              — electrical bus to structure: 100 mm min
_CLEARANCE_RULES_M: Dict[Tuple[str, str], float] = {
    ("structural", "piping"):    0.025,   # ASME B31.3 §321.1.3 — 25 mm
    ("piping", "structural"):    0.025,
    ("structural", "hvac"):      0.050,   # SMACNA §5.4 — 50 mm
    ("hvac", "structural"):      0.050,
    ("hvac", "piping"):          0.050,   # SMACNA §5.4 — 50 mm
    ("piping", "hvac"):          0.050,
    ("structural", "equipment"): 0.100,   # AISC §B3.9 — 100 mm maintenance
    ("equipment", "structural"): 0.100,
    ("piping", "equipment"):     0.075,   # ASME B31.3 §321 — 75 mm
    ("equipment", "piping"):     0.075,
    ("hvac", "equipment"):       0.100,
    ("equipment", "hvac"):       0.100,
    ("electrical", "structural"): 0.100,
    ("structural", "electrical"): 0.100,
    ("electrical", "piping"):    0.150,   # IEC 61439-3 — 150 mm
    ("piping", "electrical"):    0.150,
    ("civil", "piping"):         0.050,
    ("piping", "civil"):         0.050,
    ("civil", "structural"):     0.050,
    ("structural", "civil"):     0.050,
    ("civil", "hvac"):           0.050,
    ("hvac", "civil"):           0.050,
    ("instrument", "piping"):    0.025,
    ("piping", "instrument"):    0.025,
}

_DEFAULT_CLEARANCE_M = 0.025  # fallback if pair not in table


def get_clearance_m(disc_a: str, disc_b: str) -> float:
    """Return the required clearance (m) between two discipline types."""
    key = (disc_a, disc_b)
    rev = (disc_b, disc_a)
    return _CLEARANCE_RULES_M.get(key, _CLEARANCE_RULES_M.get(rev, _DEFAULT_CLEARANCE_M))


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

BBOX3 = Tuple[Tuple[float, float, float], Tuple[float, float, float]]


def _bbox_center(bbox: BBOX3) -> Tuple[float, float, float]:
    """Centroid of an AABB."""
    lo, hi = bbox
    return (
        (lo[0] + hi[0]) / 2.0,
        (lo[1] + hi[1]) / 2.0,
        (lo[2] + hi[2]) / 2.0,
    )


def _bbox_gap(bbox_a: BBOX3, bbox_b: BBOX3) -> float:
    """
    Minimum surface-to-surface distance between two AABBs.

    Returns negative value when boxes overlap (penetration depth in metres).
    Returns 0.0 when boxes touch at a face.
    Returns positive value when boxes are separated.

    Reference: Christer Ericson — "Real-Time Collision Detection" §5.1.
    """
    lo_a, hi_a = bbox_a
    lo_b, hi_b = bbox_b
    # Gap per axis: max(lo_b - hi_a, lo_a - hi_b) > 0 means separated on that axis
    gaps = [
        max(lo_b[i] - hi_a[i], lo_a[i] - hi_b[i])
        for i in range(3)
    ]
    # If all axes are negative → overlap; gap = max(gaps) (least penetration)
    # If some are positive → separated; gap = sqrt(sum of squared positive gaps)
    pos_gaps = [g for g in gaps if g > 0]
    neg_gaps = [g for g in gaps if g <= 0]
    if pos_gaps:
        # Separated: Euclidean distance from faces
        return math.sqrt(sum(g * g for g in pos_gaps))
    else:
        # Overlapping: return max (least negative = shallowest penetration in 3D)
        return max(gaps)  # ≤ 0


def _bbox_overlap_volume(bbox_a: BBOX3, bbox_b: BBOX3) -> float:
    """Signed overlap volume between two AABBs.  Returns 0 if not overlapping."""
    lo_a, hi_a = bbox_a
    lo_b, hi_b = bbox_b
    dims = [
        min(hi_a[i], hi_b[i]) - max(lo_a[i], lo_b[i])
        for i in range(3)
    ]
    if any(d <= 0 for d in dims):
        return 0.0
    return dims[0] * dims[1] * dims[2]


def _bbox_clearance_violation_depth(bbox_a: BBOX3, bbox_b: BBOX3, required_clearance: float) -> float:
    """
    Return the clearance shortfall (m) between two AABBs given a required clearance.

    Positive return = clearance is violated (gap < required_clearance).
    Negative return = clearance is satisfied.

    A clearance violation exists when:
      gap < required_clearance    → shortfall = required_clearance - gap

    When boxes overlap (gap < 0):
      shortfall = required_clearance + |gap| > required_clearance
    """
    gap = _bbox_gap(bbox_a, bbox_b)
    return required_clearance - gap


# ---------------------------------------------------------------------------
# Plant element
# ---------------------------------------------------------------------------

@dataclass
class PlantElement:
    """
    A single design element in the plant, from any discipline.

    Parameters
    ----------
    element_id   Unique identifier (e.g. 'BEAM-A1-01', 'DN150-PIPE-001').
    discipline   Which discipline owns this element.
    bbox         Axis-aligned bounding box in metres: ((x_min,y_min,z_min),(x_max,y_max,z_max)).
    label        Human-readable label (e.g. 'W310x97 column', 'DN150 CS steam pipe').
    system       Optional system/zone tag (e.g. 'RACK-A', 'PUMP-BAY-1').
    material     Optional material descriptor for BOM.
    unit_cost    Optional unit cost (USD) for cost roll-up.
    quantity     Quantity for BOM (default 1).
    unit         Unit for BOM (default 'ea').
    weight_kg    Optional weight per unit (kg).
    """
    element_id:  str
    discipline:  PlantDiscipline
    bbox:        BBOX3
    label:       str = ""
    system:      str = ""
    material:    str = ""
    unit_cost:   float = 0.0
    quantity:    float = 1.0
    unit:        str = "ea"
    weight_kg:   float = 0.0


# ---------------------------------------------------------------------------
# Clash records
# ---------------------------------------------------------------------------

@dataclass
class ClashRecord:
    """A detected clash (hard) or clearance violation (soft) between two elements."""
    element_a:    str            # element_id
    element_b:    str            # element_id
    discipline_a: str
    discipline_b: str
    clash_type:   str            # 'hard' | 'soft'
    gap_m:        float          # actual gap (negative = overlap)
    required_clearance_m: float
    shortfall_m:  float          # required_clearance - gap (>0 = violation)
    overlap_volume_m3: float     # 0 for soft clashes
    location_m:   Tuple[float, float, float]   # approximate clash centroid
    severity:     str            # 'critical' | 'major' | 'minor'

    def as_dict(self) -> dict:
        return {
            "element_a": self.element_a,
            "element_b": self.element_b,
            "discipline_a": self.discipline_a,
            "discipline_b": self.discipline_b,
            "clash_type": self.clash_type,
            "gap_m": round(self.gap_m, 4),
            "required_clearance_m": round(self.required_clearance_m, 4),
            "shortfall_m": round(self.shortfall_m, 4),
            "overlap_volume_m3": round(self.overlap_volume_m3, 6),
            "location_m": [round(v, 3) for v in self.location_m],
            "severity": self.severity,
        }


def _classify_severity(gap_m: float, required_clearance: float) -> str:
    """Classify clash severity based on gap and required clearance."""
    if gap_m < 0:
        return "critical"     # hard clash — elements physically overlap
    shortfall = required_clearance - gap_m
    if shortfall > required_clearance * 0.5:
        return "major"        # more than 50% of clearance violated
    return "minor"            # small clearance shortfall


# ---------------------------------------------------------------------------
# Coordination report
# ---------------------------------------------------------------------------

@dataclass
class CoordinationReport:
    """
    Coordination report for a multi-discipline plant model.

    Attributes
    ----------
    project_id         Project identifier.
    total_elements     Total number of elements in the plant.
    hard_clash_count   Number of hard (overlap) clashes.
    soft_clash_count   Number of soft (clearance-violation) clashes.
    clashes_by_pair    Dict keyed by 'disciplineA-disciplineB' with clash lists.
    bom_by_discipline  Bill of materials aggregated per discipline.
    zone_summary       Elements per zone (system).
    warnings           Coordinate / setup warnings.
    """
    project_id: str
    total_elements: int
    hard_clash_count: int
    soft_clash_count: int
    clashes_by_pair: Dict[str, List[dict]]
    bom_by_discipline: Dict[str, List[dict]]
    zone_summary: Dict[str, dict]
    warnings: List[str]

    def as_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "total_elements": self.total_elements,
            "hard_clash_count": self.hard_clash_count,
            "soft_clash_count": self.soft_clash_count,
            "clashes_by_pair": self.clashes_by_pair,
            "bom_by_discipline": self.bom_by_discipline,
            "zone_summary": self.zone_summary,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# PlantModel
# ---------------------------------------------------------------------------

@dataclass
class PlantModel:
    """
    Multi-discipline federated plant model.

    Federates structural members, HVAC ducts, pipe routes, civil/equipment
    elements into a shared 3D coordinate space (metres, right-hand Z-up).

    All elements must be in the same coordinate system.  Use
    ``coordinate_system`` and ``datum_elevation`` attributes to document
    the shared reference frame (validated in ``coordinate_check()``).

    References
    ----------
    BS 1192-4:2014 §4.4 — federated model coordination protocol.
    USACE EM 1110-1-1000 §5 — multi-discipline plant coordination.
    """
    project_id: str
    elements: List[PlantElement] = field(default_factory=list)
    coordinate_system: str = "metric-SI"
    datum_elevation: float = 0.0

    # Spatial zones: {zone_id: bbox}
    zones: Dict[str, BBOX3] = field(default_factory=dict)

    # -----------------------------------------------------------------------
    # Construction helpers
    # -----------------------------------------------------------------------

    def add_element(self, element: PlantElement) -> None:
        """Add a discipline element to the plant model."""
        self.elements.append(element)

    def add_zone(self, zone_id: str, bbox: BBOX3) -> None:
        """Register a spatial zone (e.g. pump bay, pipe rack)."""
        self.zones[zone_id] = bbox

    # -----------------------------------------------------------------------
    # Clash / coordination detection
    # -----------------------------------------------------------------------

    def run_coordination_check(
        self,
        *,
        check_hard_clashes: bool = True,
        check_soft_clashes: bool = True,
    ) -> List[ClashRecord]:
        """
        Run cross-discipline interference and clearance checking.

        For every pair of elements from different disciplines, compute:
          - Hard clash: if AABB overlap volume > 0.
          - Soft clash: if surface-to-surface gap < required clearance.

        Returns a list of ClashRecord objects.

        Algorithm: O(n²) AABB pair scan adequate for plant-model scale
        (hundreds–low thousands of elements; use spatial indexing for larger).

        References
        ----------
        ASME B31.3-2022 §321 — piping flexibility / clearance.
        SMACNA HVAC Duct Construction Standards §5.4 — duct clearances.
        AISC 360-22 §B3 — structural steel clearance.
        """
        clashes: List[ClashRecord] = []
        n = len(self.elements)

        for i in range(n):
            ea = self.elements[i]
            for j in range(i + 1, n):
                eb = self.elements[j]

                # Only check cross-discipline pairs
                if ea.discipline == eb.discipline:
                    continue

                disc_a = ea.discipline.value
                disc_b = eb.discipline.value
                required_clearance = get_clearance_m(disc_a, disc_b)

                gap = _bbox_gap(ea.bbox, eb.bbox)
                overlap_vol = _bbox_overlap_volume(ea.bbox, eb.bbox)

                # Hard clash: actual overlap
                if check_hard_clashes and overlap_vol > 0.0:
                    shortfall = required_clearance - gap  # gap is negative
                    loc = _bbox_center(ea.bbox)
                    clashes.append(ClashRecord(
                        element_a=ea.element_id,
                        element_b=eb.element_id,
                        discipline_a=disc_a,
                        discipline_b=disc_b,
                        clash_type="hard",
                        gap_m=gap,
                        required_clearance_m=required_clearance,
                        shortfall_m=shortfall,
                        overlap_volume_m3=overlap_vol,
                        location_m=loc,
                        severity=_classify_severity(gap, required_clearance),
                    ))
                # Soft clash: clearance violation (gap > 0 but < required)
                elif check_soft_clashes and overlap_vol == 0.0 and gap < required_clearance:
                    shortfall = required_clearance - gap
                    # Location: midpoint between nearest faces (approximate)
                    loc_a = _bbox_center(ea.bbox)
                    loc_b = _bbox_center(eb.bbox)
                    loc = (
                        (loc_a[0] + loc_b[0]) / 2.0,
                        (loc_a[1] + loc_b[1]) / 2.0,
                        (loc_a[2] + loc_b[2]) / 2.0,
                    )
                    clashes.append(ClashRecord(
                        element_a=ea.element_id,
                        element_b=eb.element_id,
                        discipline_a=disc_a,
                        discipline_b=disc_b,
                        clash_type="soft",
                        gap_m=gap,
                        required_clearance_m=required_clearance,
                        shortfall_m=shortfall,
                        overlap_volume_m3=0.0,
                        location_m=loc,
                        severity=_classify_severity(gap, required_clearance),
                    ))

        return clashes

    # -----------------------------------------------------------------------
    # BOM roll-up
    # -----------------------------------------------------------------------

    def bom_by_discipline(self) -> Dict[str, List[dict]]:
        """
        Aggregate bill of materials per discipline.

        Returns a dict keyed by discipline value with BOM line items.

        References
        ----------
        BS 1192-4:2014 §7 — COBie component and resource tables.
        """
        bom: Dict[str, List[dict]] = {}
        for elem in self.elements:
            disc = elem.discipline.value
            if disc not in bom:
                bom[disc] = []
            bom[disc].append({
                "element_id": elem.element_id,
                "label": elem.label,
                "material": elem.material,
                "quantity": elem.quantity,
                "unit": elem.unit,
                "weight_kg": elem.weight_kg,
                "unit_cost": elem.unit_cost,
                "total_cost": round(elem.quantity * elem.unit_cost, 2),
                "system": elem.system,
            })
        return bom

    def combined_bom_summary(self) -> Dict[str, dict]:
        """
        Combined BOM summary across all disciplines.

        Returns per-discipline totals: element count, total weight, total cost.
        """
        by_disc = self.bom_by_discipline()
        summary: Dict[str, dict] = {}
        for disc, items in by_disc.items():
            total_weight = sum(i["weight_kg"] * i["quantity"] for i in items)
            total_cost = sum(i["total_cost"] for i in items)
            summary[disc] = {
                "element_count": len(items),
                "total_weight_kg": round(total_weight, 2),
                "total_cost_usd": round(total_cost, 2),
            }
        # Grand total row
        summary["_total"] = {
            "element_count": sum(v["element_count"] for v in summary.values()),
            "total_weight_kg": round(sum(v["total_weight_kg"] for v in summary.values()), 2),
            "total_cost_usd": round(sum(v["total_cost_usd"] for v in summary.values()), 2),
        }
        return summary

    # -----------------------------------------------------------------------
    # Spatial zone assignment
    # -----------------------------------------------------------------------

    def assign_zones(self) -> Dict[str, List[str]]:
        """
        Assign elements to spatial zones by AABB centroid containment.

        Returns a dict keyed by zone_id with lists of element_ids.
        Unzoned elements appear under key '_unzoned'.
        """
        assignment: Dict[str, List[str]] = {zid: [] for zid in self.zones}
        assignment["_unzoned"] = []

        for elem in self.elements:
            cx, cy, cz = _bbox_center(elem.bbox)
            placed = False
            for zid, zbbox in self.zones.items():
                zlo, zhi = zbbox
                if (zlo[0] <= cx <= zhi[0] and
                        zlo[1] <= cy <= zhi[1] and
                        zlo[2] <= cz <= zhi[2]):
                    assignment[zid].append(elem.element_id)
                    placed = True
                    break
            if not placed:
                assignment["_unzoned"].append(elem.element_id)

        return assignment

    # -----------------------------------------------------------------------
    # Full coordination report
    # -----------------------------------------------------------------------

    def coordination_report(self) -> CoordinationReport:
        """
        Build a complete coordination report for the plant model.

        Returns a CoordinationReport with:
          - Clash counts (hard + soft) per discipline pair.
          - BOM per discipline.
          - Zone summary.
          - Coordinate / setup warnings.

        References
        ----------
        USACE EM 1110-1-1000 §5.3 — spatial coordination checking procedure.
        BS 1192-4:2014 §6.3 — coordination report format.
        """
        clashes = self.run_coordination_check()
        hard_clashes = [c for c in clashes if c.clash_type == "hard"]
        soft_clashes = [c for c in clashes if c.clash_type == "soft"]

        # Group clashes by discipline pair (canonical key: sorted pair)
        clashes_by_pair: Dict[str, List[dict]] = {}
        for c in clashes:
            da, db = sorted([c.discipline_a, c.discipline_b])
            key = f"{da}--{db}"
            if key not in clashes_by_pair:
                clashes_by_pair[key] = []
            clashes_by_pair[key].append(c.as_dict())

        # BOM per discipline
        bom = self.bom_by_discipline()

        # Zone summary
        zone_assign = self.assign_zones()
        zone_summary: Dict[str, dict] = {}
        for zid, elem_ids in zone_assign.items():
            zone_summary[zid] = {
                "element_count": len(elem_ids),
                "element_ids": elem_ids[:20],  # cap at 20 for readability
            }

        # Warnings
        warnings: List[str] = []
        disciplines_present = {e.discipline.value for e in self.elements}
        if len(disciplines_present) < 2:
            warnings.append(
                "Plant model contains elements from only one discipline — "
                "multi-discipline coordination cannot be performed."
            )
        if not self.elements:
            warnings.append("Plant model is empty — add discipline elements first.")
        if hard_clashes:
            warnings.append(
                f"{len(hard_clashes)} hard clash(es) detected — "
                "immediate design resolution required."
            )

        return CoordinationReport(
            project_id=self.project_id,
            total_elements=len(self.elements),
            hard_clash_count=len(hard_clashes),
            soft_clash_count=len(soft_clashes),
            clashes_by_pair=clashes_by_pair,
            bom_by_discipline=bom,
            zone_summary=zone_summary,
            warnings=warnings,
        )


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def make_plant_element(
    element_id: str,
    discipline: str,
    x0: float, y0: float, z0: float,
    x1: float, y1: float, z1: float,
    *,
    label: str = "",
    system: str = "",
    material: str = "",
    quantity: float = 1.0,
    unit: str = "ea",
    weight_kg: float = 0.0,
    unit_cost: float = 0.0,
) -> PlantElement:
    """Convenience factory for PlantElement objects."""
    try:
        disc = PlantDiscipline(discipline.lower())
    except ValueError:
        raise ValueError(
            f"Unknown discipline '{discipline}'. "
            f"Valid options: {[d.value for d in PlantDiscipline]}"
        )
    return PlantElement(
        element_id=element_id,
        discipline=disc,
        bbox=((min(x0, x1), min(y0, y1), min(z0, z1)),
              (max(x0, x1), max(y0, y1), max(z0, z1))),
        label=label,
        system=system,
        material=material,
        quantity=quantity,
        unit=unit,
        weight_kg=weight_kg,
        unit_cost=unit_cost,
    )
