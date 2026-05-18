"""kerf_api.routes_aero_orbit — Orbital trajectory propagation endpoint.

POST /aero/orbit/propagate
    Body: OrbitalElements + propagation parameters.
    Response: trajectory point array in km (IJK/ECI frame).

This route is stateless — no DB access required.  It delegates entirely to
kerf_aero.orbital.kepler.propagate_kepler.
"""
from __future__ import annotations

import math
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from kerf_aero.orbital.kepler import OrbitalElements, propagate_kepler

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class PropagateRequest(BaseModel):
    """Request body for POST /aero/orbit/propagate.

    All angular inputs are in radians; distances in km; time in seconds.
    """

    # Classical orbital elements
    a: float = Field(..., description="Semi-major axis (km)", gt=0)
    e: float = Field(
        ..., description="Eccentricity (dimensionless, 0 ≤ e < 1)", ge=0, lt=1
    )
    i: float = Field(..., description="Inclination (rad)")
    raan: float = Field(
        ..., alias="Omega",
        description="Right ascension of ascending node Ω (rad)"
    )
    argp: float = Field(
        ..., alias="omega",
        description="Argument of perigee ω (rad)"
    )
    nu0: float = Field(..., description="Initial true anomaly ν₀ (rad)")

    # Propagation settings
    duration_s: float = Field(
        ..., description="Propagation duration (seconds)", gt=0
    )
    n_steps: int = Field(
        200,
        description="Number of trajectory sample points (≥ 2)",
        ge=2,
        le=10_000,
    )

    model_config = {"populate_by_name": True}

    @field_validator("i")
    @classmethod
    def _validate_inclination(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("inclination must be finite")
        return v

    @field_validator("raan", "argp", "nu0", mode="before")
    @classmethod
    def _validate_angle(cls, v: float) -> float:
        if not math.isfinite(float(v)):
            raise ValueError("angle must be finite")
        return v


class TrajectoryPoint(BaseModel):
    x: float  # km
    y: float  # km
    z: float  # km


class PropagateResponse(BaseModel):
    ok: bool = True
    n_steps: int
    duration_s: float
    # orbital elements echo
    a_km: float
    e: float
    trajectory: List[TrajectoryPoint]


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post(
    "/aero/orbit/propagate",
    response_model=PropagateResponse,
    summary="Propagate a Keplerian orbit",
    tags=["aero", "orbit"],
)
async def propagate_orbit(body: PropagateRequest) -> PropagateResponse:
    """Propagate a Keplerian orbit and return the trajectory in the IJK frame.

    Accepts classical orbital elements (a, e, i, Ω, ω, ν₀) plus a
    propagation duration and step count.  Returns n_steps position vectors
    (x, y, z) in kilometres in the Earth-centred inertial (ECI / IJK) frame.

    The computation is pure two-body Keplerian (no perturbations).
    """
    elements = OrbitalElements(
        a=body.a,
        e=body.e,
        i=body.i,
        raan=body.raan,
        argp=body.argp,
        nu0=body.nu0,
    )

    try:
        points = propagate_kepler(elements, body.duration_s, body.n_steps)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    trajectory = [TrajectoryPoint(x=x, y=y, z=z) for x, y, z in points]

    return PropagateResponse(
        ok=True,
        n_steps=len(trajectory),
        duration_s=body.duration_s,
        a_km=body.a,
        e=body.e,
        trajectory=trajectory,
    )
