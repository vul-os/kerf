"""
WireViz YAML → SVG compilation route.

POST /run-wireviz
Body:  { "source": "<WireViz YAML string>" }
Returns: { "svg": "<SVG string or null>", "warnings": ["..."] }

The route never crashes even when WireViz is not installed — it returns a
descriptive warning payload instead so the frontend can surface a helpful
message.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.post("/run-wireviz")
async def run_wireviz_route(req: dict) -> dict:
    """Compile WireViz YAML to SVG."""
    source = req.get("source", "")
    if not isinstance(source, str):
        return {"svg": None, "warnings": ["'source' must be a YAML string"]}

    from kerf_wiring.wireviz_runner import run_wireviz
    result = run_wireviz(source)
    return {"svg": result.svg, "warnings": result.warnings}
