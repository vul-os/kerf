"""
kerf_civil.landxml — LandXML 1.2 import / export.

Supports:
  <Alignments> / <Alignment>
      CoordGeom: <Line> and <Curve> elements
      Profile:   <ProfAlign> with <PVI> and <CircCurve>/<ParaCurve>
  <Surfaces> / <Surface>
      TIN via <Pnts> + <Faces>
  <Parcels> / <Parcel>
      Boundary lines

Public API
----------
export_landxml(alignments, surfaces, parcels) -> str
    Serialise geometry to a LandXML 1.2 XML string.

import_landxml(xml_str) -> dict
    Parse a LandXML string; returns:
        {
          "alignments": [...],
          "surfaces": [...],
          "parcels": [...]
        }

All coordinates are (x, y) or (x, y, z) tuples in project CRS (metres).

Standard reference: LandXML Schema version 1.2
  http://www.landxml.org/schema/LandXML-1.2/LandXML-1.2.xsd
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

# LandXML 1.2 namespace
_NS = "http://www.landxml.org/schema/LandXML-1.2"
_NS_PREFIX = "LandXML"

# Register empty prefix so serialiser emits xmlns="..." on root element
# instead of xmlns:ns0="..." on every element.
ET.register_namespace("", _NS)


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def _tag(name: str) -> str:
    """Fully-qualified XML tag with LandXML 1.2 namespace."""
    return f"{{{_NS}}}{name}"


def _fmt(v: float, decimals: int = 6) -> str:
    return f"{v:.{decimals}f}"


def _pt_str(x: float, y: float, z: float | None = None) -> str:
    """LandXML point string: 'y x' or 'y x z' (northing easting order)."""
    if z is not None:
        return f"{_fmt(y)} {_fmt(x)} {_fmt(z)}"
    return f"{_fmt(y)} {_fmt(x)}"


def _parse_pt(s: str) -> tuple:
    """Parse 'northing easting [elev]' → (x, y) or (x, y, z)."""
    parts = s.strip().split()
    northing = float(parts[0])
    easting = float(parts[1])
    if len(parts) >= 3:
        return (easting, northing, float(parts[2]))
    return (easting, northing)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_landxml(
    alignments: list[dict] | None = None,
    surfaces: list[dict] | None = None,
    parcels: list[dict] | None = None,
) -> str:
    """
    Export geometry to a LandXML 1.2 XML string.

    Parameters
    ----------
    alignments : list of alignment dicts
        Each dict:
            name      : str
            desc      : str (optional)
            elements  : list of element dicts:
                type  : 'Line' | 'Curve'
                -- Line:
                    start : (x, y)
                    end   : (x, y)
                -- Curve:
                    start  : (x, y)
                    end    : (x, y)
                    center : (x, y)
                    radius : float
                    dir    : 'CCW' | 'CW'
            profile  : optional dict
                elements : list of profile elements
                    type     : 'PVI' | 'ParaCurve'
                    station  : float
                    elevation: float
                    length   : float (ParaCurve only)

    surfaces : list of surface dicts
        Each dict:
            name   : str
            points : list of (x, y, z) tuples
            faces  : list of (i0, i1, i2) 1-based index tuples

    parcels : list of parcel dicts
        Each dict:
            name   : str
            lines  : list of {'start': (x,y), 'end': (x,y)} dicts

    Returns
    -------
    str — LandXML 1.2 XML string
    """
    alignments = alignments or []
    surfaces = surfaces or []
    parcels = parcels or []

    root = ET.Element(_tag("LandXML"))
    root.set("version", "1.2")
    # Note: ET.register_namespace("", _NS) (at module level) ensures
    # the serialiser emits xmlns="..." rather than xmlns:ns0="...".
    # Do NOT also call root.set("xmlns", ...) — that would duplicate it.

    # --- Units (SI) ---
    units_el = ET.SubElement(root, _tag("Units"))
    si = ET.SubElement(units_el, _tag("Metric"))
    si.set("areaUnit", "squareMeter")
    si.set("linearUnit", "meter")
    si.set("volumeUnit", "cubicMeter")

    # --- Alignments ---
    if alignments:
        aligns_el = ET.SubElement(root, _tag("Alignments"))
        for aln in alignments:
            aln_el = ET.SubElement(aligns_el, _tag("Alignment"))
            aln_el.set("name", aln.get("name", "Alignment"))
            if aln.get("desc"):
                aln_el.set("desc", aln["desc"])

            cg_el = ET.SubElement(aln_el, _tag("CoordGeom"))
            for elem in aln.get("elements", []):
                etype = elem.get("type", "Line")
                if etype == "Line":
                    line_el = ET.SubElement(cg_el, _tag("Line"))
                    s_el = ET.SubElement(line_el, _tag("Start"))
                    s_el.text = _pt_str(*elem["start"])
                    e_el = ET.SubElement(line_el, _tag("End"))
                    e_el.text = _pt_str(*elem["end"])
                elif etype == "Curve":
                    curve_el = ET.SubElement(cg_el, _tag("Curve"))
                    curve_el.set("rot", elem.get("dir", "CCW"))
                    curve_el.set("radius", _fmt(elem["radius"], 4))
                    s_el = ET.SubElement(curve_el, _tag("Start"))
                    s_el.text = _pt_str(*elem["start"])
                    ctr_el = ET.SubElement(curve_el, _tag("Center"))
                    ctr_el.text = _pt_str(*elem["center"])
                    e_el = ET.SubElement(curve_el, _tag("End"))
                    e_el.text = _pt_str(*elem["end"])

            # Profile
            profile = aln.get("profile")
            if profile:
                prof_el = ET.SubElement(aln_el, _tag("Profile"))
                pa_el = ET.SubElement(prof_el, _tag("ProfAlign"))
                pa_el.set("name", aln.get("name", "Alignment") + "_profile")
                for pe in profile.get("elements", []):
                    ptype = pe.get("type", "PVI")
                    if ptype == "PVI":
                        pvi_el = ET.SubElement(pa_el, _tag("PVI"))
                        pvi_el.text = f"{_fmt(pe['station'])} {_fmt(pe['elevation'])}"
                    elif ptype == "ParaCurve":
                        pc_el = ET.SubElement(pa_el, _tag("ParaCurve"))
                        pc_el.set("length", _fmt(pe["length"], 4))
                        pc_el.text = f"{_fmt(pe['station'])} {_fmt(pe['elevation'])}"

    # --- Surfaces (TIN) ---
    if surfaces:
        surfs_el = ET.SubElement(root, _tag("Surfaces"))
        for surf in surfaces:
            surf_el = ET.SubElement(surfs_el, _tag("Surface"))
            surf_el.set("name", surf.get("name", "Surface"))
            defn_el = ET.SubElement(surf_el, _tag("Definition"))
            defn_el.set("surfType", "TIN")

            # Points
            pnts_el = ET.SubElement(defn_el, _tag("Pnts"))
            for idx, pt in enumerate(surf.get("points", []), start=1):
                p_el = ET.SubElement(pnts_el, _tag("P"))
                p_el.set("id", str(idx))
                x, y, z = pt[0], pt[1], pt[2] if len(pt) > 2 else 0.0
                p_el.text = _pt_str(x, y, z)

            # Faces
            faces_el = ET.SubElement(defn_el, _tag("Faces"))
            for f in surf.get("faces", []):
                f_el = ET.SubElement(faces_el, _tag("F"))
                f_el.text = " ".join(str(i) for i in f)

    # --- Parcels ---
    if parcels:
        parcels_el = ET.SubElement(root, _tag("Parcels"))
        for parcel in parcels:
            parcel_el = ET.SubElement(parcels_el, _tag("Parcel"))
            parcel_el.set("name", parcel.get("name", "Parcel"))
            cg_el = ET.SubElement(parcel_el, _tag("CoordGeom"))
            for line in parcel.get("lines", []):
                line_el = ET.SubElement(cg_el, _tag("Line"))
                s_el = ET.SubElement(line_el, _tag("Start"))
                s_el.text = _pt_str(*line["start"])
                e_el = ET.SubElement(line_el, _tag("End"))
                e_el.text = _pt_str(*line["end"])

    # Serialise with declaration
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=False)


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def import_landxml(xml_str: str) -> dict:
    """
    Parse a LandXML 1.2 (or 1.0/2.0) string.

    Returns
    -------
    dict with keys:
        alignments : list of alignment dicts (same shape as export input)
        surfaces   : list of surface dicts
        parcels    : list of parcel dicts
    """
    root = ET.fromstring(xml_str)

    # Detect namespace from actual document (handles 1.0/1.2/2.0)
    tag = root.tag
    if tag.startswith("{"):
        ns = tag[1: tag.index("}")]
    else:
        ns = _NS

    def t(name: str) -> str:
        return f"{{{ns}}}{name}" if ns else name

    alignments_out = []
    surfaces_out = []
    parcels_out = []

    # --- Alignments ---
    for aligns_el in root.iter(t("Alignments")):
        for aln_el in aligns_el.findall(t("Alignment")):
            aln_name = aln_el.get("name", "")
            elements = []
            cg_el = aln_el.find(t("CoordGeom"))
            if cg_el is not None:
                for child in cg_el:
                    local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if local == "Line":
                        start_el = child.find(t("Start"))
                        end_el = child.find(t("End"))
                        if start_el is not None and end_el is not None:
                            elements.append({
                                "type": "Line",
                                "start": _parse_pt(start_el.text or ""),
                                "end": _parse_pt(end_el.text or ""),
                            })
                    elif local == "Curve":
                        start_el = child.find(t("Start"))
                        ctr_el = child.find(t("Center"))
                        end_el = child.find(t("End"))
                        radius = child.get("radius")
                        rot = child.get("rot", "CCW")
                        elem = {
                            "type": "Curve",
                            "dir": rot,
                        }
                        if radius:
                            elem["radius"] = float(radius)
                        if start_el is not None:
                            elem["start"] = _parse_pt(start_el.text or "")
                        if ctr_el is not None:
                            elem["center"] = _parse_pt(ctr_el.text or "")
                        if end_el is not None:
                            elem["end"] = _parse_pt(end_el.text or "")
                        elements.append(elem)

            # Profile
            profile = None
            prof_el = aln_el.find(t("Profile"))
            if prof_el is not None:
                pa_el = prof_el.find(t("ProfAlign"))
                if pa_el is not None:
                    prof_elements = []
                    for child in pa_el:
                        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                        text = (child.text or "").strip()
                        if local == "PVI":
                            parts = text.split()
                            if len(parts) >= 2:
                                prof_elements.append({
                                    "type": "PVI",
                                    "station": float(parts[0]),
                                    "elevation": float(parts[1]),
                                })
                        elif local == "ParaCurve":
                            length = float(child.get("length", "0"))
                            parts = text.split()
                            prof_elements.append({
                                "type": "ParaCurve",
                                "station": float(parts[0]) if len(parts) > 0 else 0.0,
                                "elevation": float(parts[1]) if len(parts) > 1 else 0.0,
                                "length": length,
                            })
                    profile = {"elements": prof_elements}

            alignments_out.append({
                "name": aln_name,
                "elements": elements,
                "profile": profile,
            })

    # --- Surfaces ---
    for surfs_el in root.iter(t("Surfaces")):
        for surf_el in surfs_el.findall(t("Surface")):
            surf_name = surf_el.get("name", "")
            points = []
            faces = []
            defn_el = surf_el.find(t("Definition"))
            if defn_el is None:
                defn_el = surf_el  # some LandXML omit Definition wrapper
            pnts_el = defn_el.find(t("Pnts"))
            if pnts_el is not None:
                # Build id → index mapping
                id_to_idx: dict[str, int] = {}
                for p_el in pnts_el.findall(t("P")):
                    pid = p_el.get("id", str(len(points) + 1))
                    pt = _parse_pt(p_el.text or "")
                    id_to_idx[pid] = len(points) + 1  # 1-based
                    points.append(pt)
            faces_el = defn_el.find(t("Faces"))
            if faces_el is not None:
                for f_el in faces_el.findall(t("F")):
                    idxs = [int(i) for i in (f_el.text or "").split()]
                    if len(idxs) >= 3:
                        faces.append(tuple(idxs[:3]))
            surfaces_out.append({
                "name": surf_name,
                "points": points,
                "faces": faces,
            })

    # --- Parcels ---
    for parcels_el in root.iter(t("Parcels")):
        for parcel_el in parcels_el.findall(t("Parcel")):
            parcel_name = parcel_el.get("name", "")
            lines = []
            cg_el = parcel_el.find(t("CoordGeom"))
            if cg_el is not None:
                for line_el in cg_el.findall(t("Line")):
                    start_el = line_el.find(t("Start"))
                    end_el = line_el.find(t("End"))
                    if start_el is not None and end_el is not None:
                        lines.append({
                            "start": _parse_pt(start_el.text or ""),
                            "end": _parse_pt(end_el.text or ""),
                        })
            parcels_out.append({"name": parcel_name, "lines": lines})

    return {
        "alignments": alignments_out,
        "surfaces": surfaces_out,
        "parcels": parcels_out,
    }
