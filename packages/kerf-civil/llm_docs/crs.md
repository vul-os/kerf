# kerf-civil · crs.py

Coordinate Reference System (CRS) transforms using EPSG codes.

## Primary backend

**pyproj** (PROJ 9+, optional). Install with `pip install 'kerf-civil[crs]'` for
full EPSG library support.

**Fallback** (pyproj not installed): pure-Python WGS-84 ↔ UTM series expansion,
accurate to ~1 m; covers EPSG:4326 ↔ EPSG:326xx (UTM North) / EPSG:327xx (UTM South).

## Entrypoints

### `transform(x, y, from_crs, to_crs, *, z=None)`

Transform coordinates. Accepts scalars or lists.

```python
from kerf_civil.crs import transform

# WGS-84 geographic → UTM Zone 34N (Cape Town area)
easting, northing = transform(18.4241, -33.9249, 4326, 32734)

# Multiple points
east_list, north_list = transform(
    [18.4241, 18.5000],
    [-33.9249, -33.8000],
    4326, 32734,
)

# With elevation
e, n, z_out = transform(18.4241, -33.9249, 4326, 32734, z=100.0)
```

### `round_trip_error(x, y, from_crs, to_crs, *, z=None) -> float`

Transform forward then back; return max absolute residual.
Values < 1e-3 confirm sub-millimetre round-trip consistency.

```python
from kerf_civil.crs import round_trip_error

err = round_trip_error(18.4241, -33.9249, 4326, 32734)
assert err < 1e-3  # sub-millimetre
```

### `wgs84_to_utm(lon_deg, lat_deg, zone=None) -> (easting, northing, zone, north)`

Pure-Python fallback (no pyproj needed).

```python
from kerf_civil.crs import wgs84_to_utm

e, n, zone, north = wgs84_to_utm(18.4241, -33.9249)
# → easting≈261788 m, northing≈6243282 m, zone=34, north=False
```

### `utm_to_wgs84(easting, northing, zone, north=True) -> (lon_deg, lat_deg)`

```python
from kerf_civil.crs import utm_to_wgs84

lon, lat = utm_to_wgs84(261788.0, 6243282.0, zone=34, north=False)
```

### `utm_zone_from_lon(lon_deg) -> int`

```python
from kerf_civil.crs import utm_zone_from_lon
zone = utm_zone_from_lon(18.4241)  # → 34
```

### `epsg_for_utm(zone, north=True) -> int`

```python
from kerf_civil.crs import epsg_for_utm
epsg = epsg_for_utm(34, north=False)  # → 32734
```

## LLM tool: `civil_crs_transform`

| Parameter  | Type             | Description |
|------------|------------------|-------------|
| `x`        | number or array  | X / longitude |
| `y`        | number or array  | Y / latitude |
| `from_crs` | int or string    | Source CRS (EPSG code) |
| `to_crs`   | int or string    | Target CRS (EPSG code) |
| `z`        | number or null   | Optional elevation (m) |

Returns `{x, y, round_trip_error_m}`.

## Standards

- EPSG Geodetic Parameter Dataset
- PROJ coordinate transformation library
- WGS-84 (EPSG:4326) — GPS / web mapping standard
- UTM zones 1–60 N/S (EPSG:326xx / 327xx)
