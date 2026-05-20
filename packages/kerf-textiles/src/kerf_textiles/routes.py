"""
kerf_textiles.routes
====================
FastAPI router for textile generation endpoints.
"""

from __future__ import annotations

from typing import Any, Literal, Optional
from fastapi import APIRouter
from pydantic import BaseModel, Field

from kerf_textiles.weave import plain_weave, twill_weave, satin_weave, jacquard_from_draft
from kerf_textiles.knit import jersey_knit, rib_knit, interlock_knit, custom_knit
from kerf_textiles.draft import canonical_plain_draft, canonical_twill_draft, canonical_satin_draft
from kerf_textiles.export import weave_to_svg, knit_to_svg, draft_to_wif, weave_to_json, knit_to_json

router = APIRouter(prefix="/textiles", tags=["textiles"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class WeaveRequest(BaseModel):
    structure: Literal["plain", "twill", "satin", "jacquard"] = "plain"
    over: int = Field(2, ge=1, description="Twill: warp-over count")
    under: int = Field(1, ge=1, description="Twill: warp-under count")
    direction: Literal["RH", "LH"] = "RH"
    shafts: int = Field(5, ge=4, description="Satin: number of shafts")
    move: int = Field(2, ge=2, description="Satin: move number")
    threading: Optional[list[int]] = None
    treadling: Optional[list[int]] = None
    tie_up: Optional[list[list[bool]]] = None
    format: Literal["json", "svg", "wif"] = "json"


class KnitRequest(BaseModel):
    structure: Literal["jersey", "rib", "interlock", "custom"] = "jersey"
    needles: int = Field(10, ge=2)
    courses: int = Field(10, ge=2)
    gauge: float = Field(5.0, gt=0)
    courses_per_cm: float = Field(7.0, gt=0)
    knit_count: int = Field(1, ge=1, description="Rib: knit columns")
    purl_count: int = Field(1, ge=1, description="Rib: purl columns")
    notation: Optional[list[list[str]]] = None
    format: Literal["json", "svg"] = "json"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/weave")
def generate_weave(req: WeaveRequest) -> Any:
    if req.structure == "plain":
        result = plain_weave()
    elif req.structure == "twill":
        result = twill_weave(over=req.over, under=req.under, direction=req.direction)
    elif req.structure == "satin":
        result = satin_weave(shafts=req.shafts, move=req.move)
    elif req.structure == "jacquard":
        if req.threading is None or req.treadling is None or req.tie_up is None:
            return {"error": "jacquard requires threading, treadling, tie_up"}
        result = jacquard_from_draft(req.threading, req.treadling, req.tie_up)
    else:
        return {"error": f"unknown structure: {req.structure}"}

    if req.format == "svg":
        return {"svg": weave_to_svg(result)}
    return {"data": weave_to_json(result)}


@router.post("/knit")
def generate_knit(req: KnitRequest) -> Any:
    if req.structure == "jersey":
        result = jersey_knit(
            needles=req.needles, courses=req.courses,
            gauge=req.gauge, courses_per_cm=req.courses_per_cm,
        )
    elif req.structure == "rib":
        result = rib_knit(
            knit_count=req.knit_count, purl_count=req.purl_count,
            needles=req.needles, courses=req.courses,
            gauge=req.gauge, courses_per_cm=req.courses_per_cm,
        )
    elif req.structure == "interlock":
        result = interlock_knit(
            needles=req.needles, courses=req.courses,
            gauge=req.gauge, courses_per_cm=req.courses_per_cm,
        )
    elif req.structure == "custom":
        if req.notation is None:
            return {"error": "custom requires notation"}
        result = custom_knit(req.notation, gauge=req.gauge, courses_per_cm=req.courses_per_cm)
    else:
        return {"error": f"unknown structure: {req.structure}"}

    if req.format == "svg":
        return {"svg": knit_to_svg(result)}
    return {"data": knit_to_json(result)}


@router.get("/draft/{structure}")
def get_draft(
    structure: Literal["plain", "twill", "satin"],
    over: int = 2,
    under: int = 1,
    shafts: int = 5,
    move: int = 2,
    fmt: Literal["json", "wif"] = "json",
) -> Any:
    if structure == "plain":
        draft = canonical_plain_draft()
    elif structure == "twill":
        draft = canonical_twill_draft(over=over, under=under)
    elif structure == "satin":
        draft = canonical_satin_draft(shafts=shafts, move=move)
    else:
        return {"error": f"unknown structure: {structure}"}

    if fmt == "wif":
        return {"wif": draft_to_wif(draft)}
    from kerf_textiles.draft import draft_to_dict
    return {"draft": draft_to_dict(draft)}
