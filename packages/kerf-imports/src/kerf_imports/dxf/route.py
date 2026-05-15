"""
route.py — FastAPI route for DXF import (pyworker endpoint).

POST /import-dxf
    Accepts a .dxf binary upload.
    Returns structured import result::

        {
          "created_files": [
            {
              "kind": "sketch" | "drawing",
              "name": "import.sketch",
              "payload": { ... }    # inline Kerf file JSON
            },
            ...
          ],
          "stats": {
            "entities": N,
            "annotations": N,
            "blocks": N,
            "warnings": N,
            "loops": N
          },
          "warnings": ["...", ...],
          "import_folder": "/dxf_import"
        }

Does NOT persist anything to the database — that is the LLM tool's job.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File

from kerf_imports.dxf.reader import read_dxf_bytes
from kerf_imports.dxf.mapper import dxf_to_both, find_closed_loops

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/import-dxf")
async def import_dxf(
    file: UploadFile = File(...),
    import_folder: Optional[str] = Query(default="/dxf_import"),
    expand_inserts: Optional[str] = Query(default="1"),
):
    """
    Parse a DXF file and return sketch + drawing payloads.

    Does not write to the database; the LLM tool handles persistence.
    """
    fname = (file.filename or "").lower()
    if fname and not fname.endswith(".dxf"):
        raise HTTPException(
            status_code=400,
            detail="Only .dxf files are accepted by this endpoint.",
        )

    content: bytes = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    _expand = expand_inserts not in ("0", "false", "no")

    try:
        doc = read_dxf_bytes(content)
    except Exception as exc:
        logger.exception("DXF parse error")
        raise HTTPException(status_code=422, detail=f"DXF parse error: {exc}")

    try:
        sketch_payload, drawing_payload = dxf_to_both(doc, expand_inserts=_expand)
    except Exception as exc:
        logger.exception("DXF mapping error")
        raise HTTPException(status_code=500, detail=f"DXF mapping error: {exc}")

    # Detect closed loops in the sketch
    try:
        loops = find_closed_loops(sketch_payload)
        sketch_payload["loops"] = [[eid for eid in loop] for loop in loops]
    except Exception as exc:
        logger.warning("Loop detection failed: %s", exc)
        loops = []

    # Build file list — only emit files with content
    created_files = []
    sketch_entities = sketch_payload.get("entities", [])
    drawing_annotations = drawing_payload.get("sheets", [{}])[0].get("annotations", [])

    if sketch_entities:
        created_files.append({
            "kind": "sketch",
            "name": "import.sketch",
            "payload": sketch_payload,
        })

    if drawing_annotations:
        created_files.append({
            "kind": "drawing",
            "name": "import.drawing",
            "payload": drawing_payload,
        })

    all_warnings = list(doc.warnings)
    all_warnings.extend(sketch_payload.get("warnings", []))
    # de-dup while preserving order
    seen: set[str] = set()
    deduped_warnings = []
    for w in all_warnings:
        if w not in seen:
            seen.add(w)
            deduped_warnings.append(w)

    stats = {
        "entities":    len(sketch_entities),
        "annotations": len(drawing_annotations),
        "blocks":      len(doc.blocks),
        "warnings":    len(deduped_warnings),
        "loops":       len(loops),
    }

    return {
        "created_files": created_files,
        "stats": stats,
        "warnings": deduped_warnings,
        "import_folder": import_folder or "/dxf_import",
    }
