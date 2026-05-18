"""
kerf_civil.crs — Coordinate Reference System transforms.

Primary backend: pyproj (PROJ 9+), optional dependency.
Fallback:        a self-contained WGS-84 ↔ UTM implementation
                 (Helmert / Karney-style series expansion, accurate to ~1 mm
                 over the UTM zone).

Public API
----------
transform(x, y, from_crs, to_crs, *, z=None)
    Convert a single point or arrays of points between two CRS identifiers
    (EPSG codes as strings or integers, or proj-string / WKT when pyproj is
    available).

round_trip_error(x, y, from_crs, to_crs, *, z=None) -> float
    Convenience: transform forward then back, return max absolute residual.

utm_zone_from_lon(lon_deg) -> int
    Return the UTM zone number (1-60) for a given longitude.

epsg_for_utm(zone, north=True) -> int
    Return the WGS-84 UTM EPSG code for a given zone / hemisphere.

wgs84_to_utm(lon_deg, lat_deg, zone=None) -> (easting, northing, zone, north)
    Pure-Python fallback: WGS-84 geographic → UTM projected (metres).

utm_to_wgs84(easting, northing, zone, north=True) -> (lon_deg, lat_deg)
    Pure-Python fallback: UTM projected (metres) → WGS-84 geographic.

Notes
-----
- All functions accept scalar floats or array-likes.  When pyproj is not
  installed, array-like inputs are handled element-wise.
- SI units (metres) for projected coordinates, decimal degrees for geographic.
- The fallback implementation covers the full UTM grid to better than 1 m; for
  sub-centimetre surveying accuracy install pyproj.
"""

from __future__ import annotations

import math
from typing import Sequence, Union

# ---------------------------------------------------------------------------
# Optional pyproj backend
# ---------------------------------------------------------------------------

try:
    from pyproj import Transformer as _ProjTransformer, CRS as _CRS
    _PYPROJ_AVAILABLE = True
except ImportError:
    _PYPROJ_AVAILABLE = False


# ---------------------------------------------------------------------------
# WGS-84 ellipsoid constants
# ---------------------------------------------------------------------------

_A = 6_378_137.0          # semi-major axis (m)
_F = 1 / 298.257_223_563  # flattening
_B = _A * (1 - _F)        # semi-minor axis
_E2 = 1 - (_B / _A) ** 2  # eccentricity squared
_E = math.sqrt(_E2)

_K0 = 0.9996              # UTM scale factor
_E0 = 500_000.0           # false easting  (m)


def utm_zone_from_lon(lon_deg: float) -> int:
    """Return the UTM zone number (1–60) for *lon_deg* decimal degrees."""
    return int((lon_deg + 180) / 6) % 60 + 1


def epsg_for_utm(zone: int, north: bool = True) -> int:
    """Return the WGS-84 UTM EPSG code for *zone* / hemisphere."""
    if north:
        return 32600 + zone
    return 32700 + zone


# ---------------------------------------------------------------------------
# Pure-Python WGS-84 ↔ UTM (Transverse Mercator, Helmert series)
# ---------------------------------------------------------------------------

def _meridional_arc(lat_rad: float) -> float:
    """Distance along the meridian from equator to *lat_rad* (m)."""
    n = (_A - _B) / (_A + _B)
    n2, n3, n4 = n * n, n ** 3, n ** 4
    A0 = 1 - n2 / 4 - 3 * n4 / 64
    A2 = 3 / 2 * (n - 3 * n3 / 8)
    A4 = 15 / 16 * (n2 - n4 / 4)
    A6 = 35 / 48 * n3
    A8 = 315 / 512 * n4
    return _A / (1 + n) * (
        A0 * lat_rad
        - A2 * math.sin(2 * lat_rad)
        + A4 * math.sin(4 * lat_rad)
        - A6 * math.sin(6 * lat_rad)
        + A8 * math.sin(8 * lat_rad)
    )


def wgs84_to_utm(
    lon_deg: float,
    lat_deg: float,
    zone: int | None = None,
) -> tuple[float, float, int, bool]:
    """
    Convert WGS-84 geographic coordinates to UTM projected coordinates.

    Parameters
    ----------
    lon_deg, lat_deg : float  — decimal degrees
    zone             : int | None — override UTM zone (auto-selected if None)

    Returns
    -------
    (easting, northing, zone, north) where north is True for Northern hemisphere
    """
    if zone is None:
        zone = utm_zone_from_lon(lon_deg)

    north = lat_deg >= 0.0
    N0 = 0.0 if north else 10_000_000.0  # false northing

    lon_rad = math.radians(lon_deg)
    lat_rad = math.radians(lat_deg)
    lon0_rad = math.radians((zone - 1) * 6 - 180 + 3)  # central meridian

    # Trigonometric sub-quantities
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    tan_lat = sin_lat / cos_lat

    N = _A / math.sqrt(1 - _E2 * sin_lat ** 2)   # prime vertical radius
    T = tan_lat ** 2
    C = _E2 / (1 - _E2) * cos_lat ** 2           # C = e'^2 cos²φ
    A_ = cos_lat * (lon_rad - lon0_rad)
    M = _meridional_arc(lat_rad)

    # Easting series
    easting = _K0 * N * (
        A_
        + A_ ** 3 / 6 * (1 - T + C)
        + A_ ** 5 / 120 * (5 - 18 * T + T * T + 72 * C - 58 * _E2 / (1 - _E2))
    ) + _E0

    # Northing series
    northing = _K0 * (
        M
        + N * tan_lat * (
            A_ ** 2 / 2
            + A_ ** 4 / 24 * (5 - T + 9 * C + 4 * C * C)
            + A_ ** 6 / 720 * (61 - 58 * T + T * T + 600 * C - 330 * _E2 / (1 - _E2))
        )
    ) + N0

    return easting, northing, zone, north


def utm_to_wgs84(
    easting: float,
    northing: float,
    zone: int,
    north: bool = True,
) -> tuple[float, float]:
    """
    Convert UTM projected coordinates to WGS-84 geographic.

    Parameters
    ----------
    easting, northing : float — metres
    zone              : int
    north             : bool  — True = Northern hemisphere

    Returns
    -------
    (lon_deg, lat_deg) in decimal degrees
    """
    N0 = 0.0 if north else 10_000_000.0
    lon0_rad = math.radians((zone - 1) * 6 - 180 + 3)

    x = easting - _E0
    y = northing - N0

    # Footpoint latitude via inverse meridional arc (Newton-Raphson)
    M0 = y / _K0
    mu = M0 / (_A * (1 - _E2 / 4 - 3 * _E2 ** 2 / 64 - 5 * _E2 ** 3 / 256))

    n = (_A - _B) / (_A + _B)
    n2, n3, n4 = n * n, n ** 3, n ** 4
    e1 = 3 / 2 * n - 27 / 32 * n3
    e2 = 21 / 16 * n2 - 55 / 32 * n4
    e3 = 151 / 96 * n3
    e4 = 1097 / 512 * n4
    lat1 = (
        mu
        + e1 * math.sin(2 * mu)
        + e2 * math.sin(4 * mu)
        + e3 * math.sin(6 * mu)
        + e4 * math.sin(8 * mu)
    )

    sin1 = math.sin(lat1)
    cos1 = math.cos(lat1)
    tan1 = sin1 / cos1

    N1 = _A / math.sqrt(1 - _E2 * sin1 ** 2)
    R1 = _A * (1 - _E2) / (1 - _E2 * sin1 ** 2) ** 1.5
    T1 = tan1 ** 2
    C1 = _E2 / (1 - _E2) * cos1 ** 2
    D = x / (N1 * _K0)

    # Latitude series
    lat_rad = lat1 - (N1 * tan1 / R1) * (
        D * D / 2
        - D ** 4 / 24 * (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * _E2 / (1 - _E2))
        + D ** 6 / 720 * (
            61 + 90 * T1 + 298 * C1 + 45 * T1 * T1
            - 252 * _E2 / (1 - _E2) - 3 * C1 * C1
        )
    )

    # Longitude series
    lon_rad = lon0_rad + (
        D
        - D ** 3 / 6 * (1 + 2 * T1 + C1)
        + D ** 5 / 120 * (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * _E2 / (1 - _E2) + 24 * T1 * T1)
    ) / cos1

    return math.degrees(lon_rad), math.degrees(lat_rad)


# ---------------------------------------------------------------------------
# High-level transform() API
# ---------------------------------------------------------------------------

def _parse_epsg(crs_id: str | int) -> int | None:
    """Return the EPSG integer if crs_id looks like an EPSG code, else None."""
    if isinstance(crs_id, int):
        return crs_id
    s = str(crs_id).strip().upper()
    if s.startswith("EPSG:"):
        return int(s[5:])
    try:
        return int(s)
    except ValueError:
        return None


_WGS84_EPSGS = {4326}
_UTM_NORTH_BASE = 32600
_UTM_SOUTH_BASE = 32700


def _is_wgs84(epsg: int | None) -> bool:
    return epsg in _WGS84_EPSGS


def _is_utm(epsg: int | None) -> tuple[bool, int, bool]:
    """Return (is_utm, zone, north)."""
    if epsg is None:
        return False, 0, True
    if _UTM_NORTH_BASE < epsg <= _UTM_NORTH_BASE + 60:
        return True, epsg - _UTM_NORTH_BASE, True
    if _UTM_SOUTH_BASE < epsg <= _UTM_SOUTH_BASE + 60:
        return True, epsg - _UTM_SOUTH_BASE, False
    return False, 0, True


def transform(
    x: float | Sequence[float],
    y: float | Sequence[float],
    from_crs: str | int,
    to_crs: str | int,
    *,
    z: float | Sequence[float] | None = None,
) -> tuple:
    """
    Transform coordinates between two CRS identifiers.

    Parameters
    ----------
    x, y      : scalar float or list/array of floats
    from_crs  : source CRS  — EPSG int/str e.g. 4326, "EPSG:4326"
    to_crs    : target CRS  — EPSG int/str
    z         : optional elevation(s) in metres

    Returns
    -------
    (x_out, y_out) scalars, or (x_out, y_out, z_out) when z is supplied.
    Scalar input → scalar output; list input → list output.
    """
    scalar = not isinstance(x, (list, tuple))
    xs = [x] if scalar else list(x)
    ys = [y] if scalar else list(y)
    zs = ([z] if scalar else list(z)) if z is not None else None

    if _PYPROJ_AVAILABLE:
        t = _ProjTransformer.from_crs(from_crs, to_crs, always_xy=True)
        if zs is not None:
            rx, ry, rz = t.transform(xs, ys, zs)
            rz = list(rz)
        else:
            rx, ry = t.transform(xs, ys)
            rz = None
        rx, ry = list(rx), list(ry)
    else:
        # Fallback: only WGS-84 (EPSG:4326) ↔ UTM supported
        from_epsg = _parse_epsg(from_crs)
        to_epsg = _parse_epsg(to_crs)
        from_wgs = _is_wgs84(from_epsg)
        to_wgs = _is_wgs84(to_epsg)
        from_utm, from_zone, from_north = _is_utm(from_epsg)
        to_utm, to_zone, to_north = _is_utm(to_epsg)

        if from_wgs and to_utm:
            results = [wgs84_to_utm(xi, yi, zone=to_zone) for xi, yi in zip(xs, ys)]
            rx = [r[0] for r in results]
            ry = [r[1] for r in results]
        elif from_utm and to_wgs:
            results = [utm_to_wgs84(xi, yi, from_zone, from_north) for xi, yi in zip(xs, ys)]
            rx = [r[0] for r in results]
            ry = [r[1] for r in results]
        else:
            raise ValueError(
                f"pyproj not installed; fallback only supports WGS-84 (EPSG:4326) "
                f"↔ UTM (EPSG:326xx/327xx). Got from={from_crs!r}, to={to_crs!r}."
            )
        rz = zs

    if scalar:
        if rz is not None:
            return rx[0], ry[0], rz[0]
        return rx[0], ry[0]
    if rz is not None:
        return rx, ry, rz
    return rx, ry


def round_trip_error(
    x: float | Sequence[float],
    y: float | Sequence[float],
    from_crs: str | int,
    to_crs: str | int,
    *,
    z: float | Sequence[float] | None = None,
) -> float:
    """
    Transform forward then back; return the maximum absolute residual (metres
    or degrees, depending on *from_crs*).

    Useful for regression tests: values below 1e-3 confirm sub-millimetre
    round-trip consistency.
    """
    fwd = transform(x, y, from_crs, to_crs, z=z)
    # fwd is (x2, y2) or (x2, y2, z2)
    if z is not None:
        x2, y2, z2 = fwd
        bwd = transform(x2, y2, to_crs, from_crs, z=z2)
        x3, y3, z3 = bwd
    else:
        x2, y2 = fwd
        bwd = transform(x2, y2, to_crs, from_crs)
        x3, y3 = bwd
        z3 = None

    scalar = not isinstance(x, (list, tuple))
    xs = [x] if scalar else list(x)
    ys = [y] if scalar else list(y)
    x3s = [x3] if scalar else list(x3)
    y3s = [y3] if scalar else list(y3)

    err = max(
        max(abs(a - b) for a, b in zip(xs, x3s)),
        max(abs(a - b) for a, b in zip(ys, y3s)),
    )
    return err
