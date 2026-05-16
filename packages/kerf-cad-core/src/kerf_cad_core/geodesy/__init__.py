"""
kerf_cad_core.geodesy — Geodetic computation & map projection.

Pure-Python module (math only). Distinct from:
  - surveying/  : planar COGO / traverse (plane coordinates)
  - civil/alignment : road horizontal & vertical curves

Submodules
----------
  geo   — ellipsoid params, coordinate transforms, projections, geodesy
  tools — LLM tool wrappers registered with the Kerf tool registry

Public API (re-exported for convenience):

    from kerf_cad_core.geodesy import (
        # Ellipsoids
        WGS84, GRS80, CLARKE1866,
        # Radii of curvature & arc
        radius_curvature, meridian_arc,
        # Coordinate transforms
        geodetic_to_ecef, ecef_to_geodetic,
        ecef_to_enu, enu_to_ecef,
        # UTM
        utm_fwd, utm_inv, utm_zone_from_lon, utm_lon0,
        # Transverse Mercator (raw)
        transverse_mercator_fwd, transverse_mercator_inv,
        # Lambert Conformal Conic
        lcc_fwd, lcc_inv,
        # Web Mercator
        web_mercator_fwd, web_mercator_inv,
        # Geodesics
        vincenty_inverse, vincenty_direct,
        haversine, rhumb_line,
        # Grid ↔ Ground
        grid_to_ground,
        # Informational
        GEOID_NOTE,
    )

References
----------
Bowring (1976) — geodetic ↔ ECEF
Karney / Krüger (2011/1912) — Transverse Mercator series
Vincenty (1975) — geodesic distance / direct solution
EPSG Guidance Note 7-2 (2023) — map projections
NIMA TR8350.2 (1997) — WGS-84

Author: imranparuk
"""
from __future__ import annotations

from kerf_cad_core.geodesy.geo import (
    WGS84,
    GRS80,
    CLARKE1866,
    radius_curvature,
    meridian_arc,
    geodetic_to_ecef,
    ecef_to_geodetic,
    ecef_to_enu,
    enu_to_ecef,
    utm_fwd,
    utm_inv,
    utm_zone_from_lon,
    utm_lon0,
    transverse_mercator_fwd,
    transverse_mercator_inv,
    lcc_fwd,
    lcc_inv,
    web_mercator_fwd,
    web_mercator_inv,
    vincenty_inverse,
    vincenty_direct,
    haversine,
    rhumb_line,
    grid_to_ground,
    GEOID_NOTE,
)

__all__ = [
    "WGS84",
    "GRS80",
    "CLARKE1866",
    "radius_curvature",
    "meridian_arc",
    "geodetic_to_ecef",
    "ecef_to_geodetic",
    "ecef_to_enu",
    "enu_to_ecef",
    "utm_fwd",
    "utm_inv",
    "utm_zone_from_lon",
    "utm_lon0",
    "transverse_mercator_fwd",
    "transverse_mercator_inv",
    "lcc_fwd",
    "lcc_inv",
    "web_mercator_fwd",
    "web_mercator_inv",
    "vincenty_inverse",
    "vincenty_direct",
    "haversine",
    "rhumb_line",
    "grid_to_ground",
    "GEOID_NOTE",
]
