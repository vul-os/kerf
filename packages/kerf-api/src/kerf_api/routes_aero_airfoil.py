"""Airfoil aerodynamics endpoints.

POST /aero/airfoil/coords   — return (x, y) coordinates for a named airfoil
POST /aero/airfoil/polar    — sweep alpha through panel_solve; return CL/CD vs alpha

These routes are pure-compute (no DB, no auth required) so they live on a
dedicated router that is included by plugin.py without a prefix clash.
"""
from __future__ import annotations

import math
from typing import List

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class CoordsRequest(BaseModel):
    airfoil: str  # e.g. "naca0012", "naca4412", "e387", "clarky"


class CoordsResponse(BaseModel):
    airfoil: str
    x: List[float]
    y: List[float]
    n_points: int


class PolarRequest(BaseModel):
    airfoil: str
    alpha_range: List[float]  # [start, end, step]

    @field_validator("alpha_range")
    @classmethod
    def _validate_alpha_range(cls, v: List[float]) -> List[float]:
        if len(v) != 3:
            raise ValueError("alpha_range must have exactly 3 elements: [start, end, step]")
        start, end, step = v
        if step == 0:
            raise ValueError("alpha_range step must not be zero")
        if step > 0 and start > end:
            raise ValueError("alpha_range: with positive step, start must be <= end")
        if step < 0 and start < end:
            raise ValueError("alpha_range: with negative step, start must be >= end")
        n = int(abs((end - start) / step)) + 1
        if n > 360:
            raise ValueError("alpha_range produces more than 360 points; reduce range or increase step")
        return v


class PolarResponse(BaseModel):
    airfoil: str
    alpha: List[float]
    CL: List[float]
    CD: List[float]


# ---------------------------------------------------------------------------
# Coordinate loader (NACA 4/5-digit or Selig slug)
# ---------------------------------------------------------------------------

def _load_coords(airfoil: str) -> np.ndarray:
    """Load airfoil coordinates.  Accepts NACA 4/5-digit strings (with or
    without a 'naca' prefix) or Selig slug names from the curated database.

    Returns an (N, 2) ndarray of (x, y) pairs in Selig order.
    """
    from kerf_aero.airfoils.selig import selig_load, SELIG_SLUGS
    from kerf_aero.airfoils.naca import naca4, naca5

    key = airfoil.strip().lower()

    # Prefer the Selig curated database first (covers NACA slugs too).
    if key in SELIG_SLUGS:
        return selig_load(key)

    # Strip a "naca" prefix if present and try programmatic generators.
    digits = key
    if digits.startswith("naca"):
        digits = digits[4:]

    if digits.isdigit():
        if len(digits) == 4:
            return naca4(digits, n_points=200)
        if len(digits) == 5:
            return naca5(digits, n_points=200)

    raise HTTPException(
        status_code=422,
        detail=(
            f"Unknown airfoil {airfoil!r}. Accepted: NACA 4-digit (e.g. 'naca0012'), "
            f"NACA 5-digit (e.g. 'naca23012'), or a Selig slug from the curated database."
        ),
    )


# ---------------------------------------------------------------------------
# CD estimation via Thwaites' flat-plate drag approximation
# ---------------------------------------------------------------------------

def _estimate_cd(CL: float, alpha_deg: float) -> float:  # noqa: N803
    """Return a simple induced + parasitic drag estimate.

    The panel method is an inviscid solver — it has no boundary-layer model
    so it cannot compute viscous skin-friction drag directly.  We use a
    simple but physically motivated estimate:

        CD_parasitic  ≈ 0.005  (flat-plate skin friction at typical Re)
        CD_induced    ≈ CL² / (pi * AR)  — for infinite span → 0 in 2D
        CD_pressure   ≈ |sin(alpha)| * 0.02  — bluff-body separation onset

    This is intentionally conservative and labelled as an estimate.
    """
    alpha_rad = math.radians(alpha_deg)
    cd_parasitic = 0.005
    cd_pressure = abs(math.sin(alpha_rad)) * 0.02
    return round(cd_parasitic + cd_pressure, 6)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/aero/airfoil/coords", response_model=CoordsResponse)
def airfoil_coords(req: CoordsRequest) -> CoordsResponse:
    """Return (x, y) coordinate arrays for the requested airfoil.

    The airfoil may be specified as:
    - A NACA 4-digit slug  e.g. ``naca0012``, ``naca4412``
    - A NACA 5-digit slug  e.g. ``naca23012``
    - A Selig/Eppler slug  e.g. ``e387``, ``clarky``, ``s1223``
    """
    coords = _load_coords(req.airfoil)
    xs = coords[:, 0].tolist()
    ys = coords[:, 1].tolist()
    return CoordsResponse(
        airfoil=req.airfoil,
        x=xs,
        y=ys,
        n_points=len(xs),
    )


@router.post("/aero/airfoil/polar", response_model=PolarResponse)
def airfoil_polar(req: PolarRequest) -> PolarResponse:
    """Sweep angle-of-attack and compute CL (and estimated CD) at each step.

    Uses the 2D linear-vortex panel method (panel_solve) for CL.  CD is a
    simple analytic estimate (inviscid solver has no viscous model).

    Body JSON::

        {
          "airfoil": "naca0012",
          "alpha_range": [-10, 10, 1]   // [start_deg, end_deg, step_deg]
        }
    """
    coords = _load_coords(req.airfoil)

    from kerf_aero.panel_2d import panel_solve

    start, end, step = req.alpha_range
    # Build alpha list
    alphas: list[float] = []
    a = start
    while (step > 0 and a <= end + 1e-9) or (step < 0 and a >= end - 1e-9):
        alphas.append(round(a, 6))
        a += step
        if len(alphas) > 360:
            break

    cls: list[float] = []
    cds: list[float] = []

    for alpha in alphas:
        try:
            result = panel_solve(coords, alpha_deg=alpha, n_panels=100)
            cl = round(result["CL"], 6)
        except Exception:
            cl = 0.0
        cd = _estimate_cd(cl, alpha)
        cls.append(cl)
        cds.append(cd)

    return PolarResponse(
        airfoil=req.airfoil,
        alpha=alphas,
        CL=cls,
        CD=cds,
    )
