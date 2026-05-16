"""kerf_cad_core.dfm — Design-for-Manufacture geometric checks."""
from kerf_cad_core.dfm.checks import (
    wall_thickness_min,
    sharp_internal_corners,
    no_draft_faces,
    undercut_regions,
    machinability_score,
    dfm_audit,
)

__all__ = [
    "wall_thickness_min",
    "sharp_internal_corners",
    "no_draft_faces",
    "undercut_regions",
    "machinability_score",
    "dfm_audit",
]
