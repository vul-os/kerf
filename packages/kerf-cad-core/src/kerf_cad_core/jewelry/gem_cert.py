"""
kerf_cad_core.jewelry.gem_cert
==============================

Gem-certificate metadata: link a gemstone instance to its laboratory
grading certificate (GIA, IGI, AGS, EGL, GCAL, HRD), validate the
certificate fields, and build supply-chain traceability manifests for
finished jewelry pieces.

Public API
----------
CertificateRef          — dataclass holding all cert fields
validate_cert(ref)      — sanity-check fields; return list[str] of issues
attach_to_gemstone(gem, cert_ref)
                        — annotate a gemstone dict from gem_studio / gemstones
traceability_chain(piece)
                        — supply-chain manifest for a multi-stone piece
report_summary(cert)    — human-readable one-string summary

Grading scales
--------------
Color (GIA / universal): D E F G H I J K L M N O P Q R S T U V W X Y Z
Clarity (GIA):
    FL IF VVS1 VVS2 VS1 VS2 SI1 SI2 I1 I2 I3
Cut quality (GIA):
    Excellent Very Good Good Fair Poor
Cut quality (AGS numeric, lower = better):
    0 (Ideal) 1 2 3 4 5 6 7 8 9 10
Polish (GIA / IGI / AGS):
    Excellent Very Good Good Fair Poor
Symmetry (GIA / IGI / AGS):
    Excellent Very Good Good Fair Poor
Fluorescence (GIA):
    None Faint Medium Strong Very Strong

Origin:
    natural    — mined, earth-origin
    lab_grown  — laboratory-grown (CVD, HPHT, flux, hydrothermal …)
    treated    — natural with significant enhancement (fracture-fill,
                 HPHT colour treatment, irradiation, coating …)

All public functions never raise; errors are returned as validation
messages or empty lists/dicts.

LLM tools
---------
    jewelry_gem_cert_validate
    jewelry_gem_cert_attach
    jewelry_gem_cert_traceability
    jewelry_gem_cert_report
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

# ---------------------------------------------------------------------------
# Grading scale catalogs
# ---------------------------------------------------------------------------

# GIA / universal colour grades (D = colourless; Z = light yellow/brown)
COLOR_GRADES_GIA: tuple[str, ...] = (
    "D", "E", "F",           # colourless
    "G", "H", "I", "J",     # near colourless
    "K", "L", "M",          # faint
    "N", "O", "P", "Q", "R",# very light
    "S", "T", "U", "V", "W", "X", "Y", "Z",  # light
)

# Fancy colour grades accepted separately
_FANCY_COLOR_PREFIXES = (
    "Fancy Light", "Fancy", "Fancy Intense", "Fancy Vivid",
    "Fancy Deep", "Fancy Dark",
)

# GIA clarity grades in descending order (finest first)
CLARITY_GRADES_GIA: tuple[str, ...] = (
    "FL", "IF",                       # flawless / internally flawless
    "VVS1", "VVS2",                   # very very slightly included
    "VS1", "VS2",                     # very slightly included
    "SI1", "SI2",                     # slightly included
    "I1", "I2", "I3",                 # included (eye-visible)
)

# GIA / IGI / GCAL / HRD cut grades (word form)
CUT_GRADES_WORD: tuple[str, ...] = (
    "Excellent", "Very Good", "Good", "Fair", "Poor",
)

# AGS numeric cut grades (0 = Ideal … 10 = Poor)
CUT_GRADES_AGS_NUMERIC: tuple[int, ...] = tuple(range(11))  # 0–10

# Polish / symmetry (same scale across GIA, IGI, AGS, GCAL, HRD)
POLISH_GRADES: tuple[str, ...] = (
    "Excellent", "Very Good", "Good", "Fair", "Poor",
)
SYMMETRY_GRADES: tuple[str, ...] = (
    "Excellent", "Very Good", "Good", "Fair", "Poor",
)

# Fluorescence (GIA)
FLUORESCENCE_GRADES: tuple[str, ...] = (
    "None", "Faint", "Medium", "Strong", "Very Strong",
)

# Origin
ORIGINS: frozenset[str] = frozenset({"natural", "lab_grown", "treated"})

# Labs
LABS: frozenset[str] = frozenset({"GIA", "IGI", "AGS", "EGL", "GCAL", "HRD"})

# Labs that issue lab-grown diamond grading reports
_LABS_ISSUE_LAB_GROWN: frozenset[str] = frozenset({"GIA", "IGI", "GCAL"})

# ---------------------------------------------------------------------------
# Cert-number format rules per lab
# ---------------------------------------------------------------------------
# Returns True if the cert_number string matches the lab's published format.

def _gia_cert_valid(n: str) -> bool:
    """GIA: exactly 10 decimal digits."""
    return bool(re.fullmatch(r"\d{10}", n))


def _igi_cert_valid(n: str) -> bool:
    """IGI: 9 or 10 decimal digits (format varies by era)."""
    return bool(re.fullmatch(r"\d{9,10}", n))


def _ags_cert_valid(n: str) -> bool:
    """AGS: optional 'AGS ' prefix followed by 6–12 digits."""
    return bool(re.fullmatch(r"(AGS\s*)?\d{6,12}", n, re.IGNORECASE))


def _egl_cert_valid(n: str) -> bool:
    """EGL: 2-letter country code + 6–10 digits (e.g. 'US123456789')."""
    return bool(re.fullmatch(r"[A-Z]{2}\d{6,10}", n, re.IGNORECASE))


def _gcal_cert_valid(n: str) -> bool:
    """GCAL: 7–12 digits."""
    return bool(re.fullmatch(r"\d{7,12}", n))


def _hrd_cert_valid(n: str) -> bool:
    """HRD: 8–11 digits."""
    return bool(re.fullmatch(r"\d{8,11}", n))


_CERT_VALIDATORS: dict[str, Any] = {
    "GIA":  _gia_cert_valid,
    "IGI":  _igi_cert_valid,
    "AGS":  _ags_cert_valid,
    "EGL":  _egl_cert_valid,
    "GCAL": _gcal_cert_valid,
    "HRD":  _hrd_cert_valid,
}

# ---------------------------------------------------------------------------
# CertificateRef dataclass
# ---------------------------------------------------------------------------

@dataclass
class CertificateRef:
    """All fields from a gemological laboratory grading certificate.

    Required
    --------
    lab             : one of GIA / IGI / AGS / EGL / GCAL / HRD
    cert_number     : lab-specific identifier string

    Optional (None = not recorded)
    --------------------------------
    date_issued     : ISO-8601 date string, e.g. '2023-04-15'
    weight_carat    : reported carat weight (float > 0)
    cut             : cut grade string (word form) or AGS numeric (int 0–10)
    color_grade     : GIA D-Z letter or fancy-color descriptor
    clarity_grade   : GIA clarity grade FL … I3
    dimensions_mm   : dict with keys length, width, depth (all in mm)
    polish          : polish grade
    symmetry        : symmetry grade
    fluorescence    : fluorescence grade
    origin          : 'natural' | 'lab_grown' | 'treated'
    comments        : free-text comments field from cert
    plot_diagram_url: URL or local path to the clarity plot diagram (PDF/PNG)
    cert_pdf_url    : URL or local path to the full certificate PDF
    """

    lab: str
    cert_number: str
    date_issued: Optional[str] = None
    weight_carat: Optional[float] = None
    cut: Optional[Any] = None            # str or int (AGS)
    color_grade: Optional[str] = None
    clarity_grade: Optional[str] = None
    dimensions_mm: Optional[dict] = None  # {length, width, depth}
    polish: Optional[str] = None
    symmetry: Optional[str] = None
    fluorescence: Optional[str] = None
    origin: Optional[str] = None
    comments: Optional[str] = None
    plot_diagram_url: Optional[str] = None
    cert_pdf_url: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "lab":              self.lab,
            "cert_number":      self.cert_number,
            "date_issued":      self.date_issued,
            "weight_carat":     self.weight_carat,
            "cut":              self.cut,
            "color_grade":      self.color_grade,
            "clarity_grade":    self.clarity_grade,
            "dimensions_mm":    self.dimensions_mm,
            "polish":           self.polish,
            "symmetry":         self.symmetry,
            "fluorescence":     self.fluorescence,
            "origin":           self.origin,
            "comments":         self.comments,
            "plot_diagram_url": self.plot_diagram_url,
            "cert_pdf_url":     self.cert_pdf_url,
        }


# ---------------------------------------------------------------------------
# validate_cert
# ---------------------------------------------------------------------------

_URL_RE = re.compile(
    r"^(https?://|file://|/)[^\s]+$",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_cert(ref: CertificateRef) -> list[str]:
    """Validate a CertificateRef; return a list of issue strings.

    An empty list means the cert passes all checks.
    Never raises.
    """
    issues: list[str] = []

    # --- lab ---
    if not ref.lab:
        issues.append("lab is required")
    elif ref.lab not in LABS:
        issues.append(
            f"Unknown lab {ref.lab!r}; valid: {sorted(LABS)}"
        )

    # --- cert_number ---
    if not ref.cert_number:
        issues.append("cert_number is required")
    elif ref.lab in LABS:
        validator = _CERT_VALIDATORS.get(ref.lab)
        if validator and not validator(str(ref.cert_number).strip()):
            issues.append(
                f"cert_number {ref.cert_number!r} does not match "
                f"{ref.lab} format"
            )

    # --- date_issued ---
    if ref.date_issued is not None:
        if not _DATE_RE.match(str(ref.date_issued)):
            issues.append(
                f"date_issued {ref.date_issued!r} must be ISO-8601 "
                "format YYYY-MM-DD"
            )

    # --- weight_carat ---
    if ref.weight_carat is not None:
        try:
            w = float(ref.weight_carat)
            if w <= 0:
                issues.append("weight_carat must be > 0")
            elif w > 3_106.75:
                issues.append(
                    f"weight_carat {w} exceeds the Cullinan (3106.75 ct); "
                    "verify this value"
                )
        except (TypeError, ValueError):
            issues.append("weight_carat must be a number")

    # --- cut grade ---
    if ref.cut is not None:
        cut_val = ref.cut
        # AGS numeric
        if ref.lab == "AGS":
            try:
                n = int(cut_val)
                if n not in CUT_GRADES_AGS_NUMERIC:
                    issues.append(
                        f"AGS cut grade {cut_val!r} must be 0–10"
                    )
            except (TypeError, ValueError):
                # fallback: allow word-form even for AGS
                if str(cut_val) not in CUT_GRADES_WORD:
                    issues.append(
                        f"AGS cut grade {cut_val!r} must be 0–10 or "
                        f"one of {CUT_GRADES_WORD}"
                    )
        else:
            if str(cut_val) not in CUT_GRADES_WORD:
                issues.append(
                    f"cut grade {cut_val!r} not in {CUT_GRADES_WORD}"
                )

    # --- color_grade ---
    if ref.color_grade is not None:
        cg = str(ref.color_grade).strip()
        is_fancy = any(cg.startswith(p) for p in _FANCY_COLOR_PREFIXES)
        if cg not in COLOR_GRADES_GIA and not is_fancy:
            issues.append(
                f"color_grade {cg!r} not in D-Z or recognized "
                "fancy-color descriptor"
            )

    # --- clarity_grade ---
    if ref.clarity_grade is not None:
        if ref.clarity_grade not in CLARITY_GRADES_GIA:
            issues.append(
                f"clarity_grade {ref.clarity_grade!r} not in "
                f"{CLARITY_GRADES_GIA}"
            )

    # --- polish ---
    if ref.polish is not None:
        if ref.polish not in POLISH_GRADES:
            issues.append(
                f"polish {ref.polish!r} not in {POLISH_GRADES}"
            )

    # --- symmetry ---
    if ref.symmetry is not None:
        if ref.symmetry not in SYMMETRY_GRADES:
            issues.append(
                f"symmetry {ref.symmetry!r} not in {SYMMETRY_GRADES}"
            )

    # --- fluorescence ---
    if ref.fluorescence is not None:
        if ref.fluorescence not in FLUORESCENCE_GRADES:
            issues.append(
                f"fluorescence {ref.fluorescence!r} not in "
                f"{FLUORESCENCE_GRADES}"
            )

    # --- origin ---
    if ref.origin is not None:
        if ref.origin not in ORIGINS:
            issues.append(
                f"origin {ref.origin!r} not in {sorted(ORIGINS)}"
            )

    # --- lab-grown ↔ origin consistency ---
    # GIA does not issue standard grading reports labelled 'natural' for
    # lab-grown diamonds; IGI/GCAL explicitly grade lab-grown.
    if ref.origin == "lab_grown" and ref.lab not in _LABS_ISSUE_LAB_GROWN:
        issues.append(
            f"Lab {ref.lab} is not known to issue lab-grown grading "
            "reports; verify origin or lab selection"
        )

    # --- dimensions_mm ---
    if ref.dimensions_mm is not None:
        if not isinstance(ref.dimensions_mm, dict):
            issues.append("dimensions_mm must be a dict")
        else:
            for dim_key in ("length", "width", "depth"):
                val = ref.dimensions_mm.get(dim_key)
                if val is not None:
                    try:
                        v = float(val)
                        if v <= 0:
                            issues.append(
                                f"dimensions_mm.{dim_key} must be > 0"
                            )
                    except (TypeError, ValueError):
                        issues.append(
                            f"dimensions_mm.{dim_key} must be a number"
                        )

    # --- URL fields ---
    for attr in ("plot_diagram_url", "cert_pdf_url"):
        url = getattr(ref, attr)
        if url is not None and not _URL_RE.match(str(url)):
            issues.append(
                f"{attr} {url!r} does not look like a valid URL or path"
            )

    return issues


# ---------------------------------------------------------------------------
# attach_to_gemstone
# ---------------------------------------------------------------------------

def attach_to_gemstone(gemstone: dict, cert_ref: CertificateRef) -> dict:
    """Annotate a gemstone dict with its certificate reference.

    Accepts a gemstone dict as returned by gem_studio / gemstones tools.
    Returns the same dict (mutated in-place) with a 'cert' key added.

    Never raises; on type error returns gemstone unchanged (cert omitted).
    """
    if not isinstance(gemstone, dict):
        return gemstone
    if not isinstance(cert_ref, CertificateRef):
        return gemstone
    gemstone["cert"] = cert_ref.to_dict()
    return gemstone


# ---------------------------------------------------------------------------
# traceability_chain
# ---------------------------------------------------------------------------

def traceability_chain(piece_jewelry: dict) -> dict:
    """Build a supply-chain manifest for a finished jewelry piece.

    Accepts a piece dict that contains either:
      - a 'stones' list, where each stone dict may have a 'cert' key
        (as attached by attach_to_gemstone), or
      - direct top-level 'cert' (single-stone piece)

    Returns a manifest dict:
    {
        "piece_id":      str or None,
        "stone_count":   int,
        "stones":        [
            {
                "stone_index":  int (0-based),
                "stone_id":     str or None,
                "cert_number":  str or None,
                "lab":          str or None,
                "weight_carat": float or None,
                "origin":       str or None,
                "color_grade":  str or None,
                "clarity_grade":str or None,
                "cert_pdf_url": str or None,
            }, ...
        ],
        "certified_count":   int,
        "uncertified_count": int,
        "lab_grown_count":   int,
        "natural_count":     int,
        "treated_count":     int,
    }

    Never raises.
    """
    manifest: dict = {
        "piece_id":         piece_jewelry.get("id") if isinstance(piece_jewelry, dict) else None,
        "stone_count":      0,
        "stones":           [],
        "certified_count":  0,
        "uncertified_count": 0,
        "lab_grown_count":  0,
        "natural_count":    0,
        "treated_count":    0,
    }

    if not isinstance(piece_jewelry, dict):
        return manifest

    # Collect stones: try 'stones' list first, then single-stone via top-level 'cert'
    stones_raw: list[dict] = []
    raw_list = piece_jewelry.get("stones")
    if isinstance(raw_list, list):
        stones_raw = [s for s in raw_list if isinstance(s, dict)]
    elif piece_jewelry.get("cert"):
        # treat the piece itself as a single-stone wrapper
        stones_raw = [piece_jewelry]

    manifest["stone_count"] = len(stones_raw)

    for idx, stone in enumerate(stones_raw):
        cert = stone.get("cert") if isinstance(stone, dict) else None
        entry: dict = {
            "stone_index":   idx,
            "stone_id":      stone.get("id") if isinstance(stone, dict) else None,
            "cert_number":   None,
            "lab":           None,
            "weight_carat":  None,
            "origin":        None,
            "color_grade":   None,
            "clarity_grade": None,
            "cert_pdf_url":  None,
        }

        if isinstance(cert, dict):
            entry["cert_number"]   = cert.get("cert_number")
            entry["lab"]           = cert.get("lab")
            entry["weight_carat"]  = cert.get("weight_carat")
            entry["origin"]        = cert.get("origin")
            entry["color_grade"]   = cert.get("color_grade")
            entry["clarity_grade"] = cert.get("clarity_grade")
            entry["cert_pdf_url"]  = cert.get("cert_pdf_url")
            manifest["certified_count"] += 1
        else:
            manifest["uncertified_count"] += 1

        origin = entry.get("origin")
        if origin == "lab_grown":
            manifest["lab_grown_count"] += 1
        elif origin == "natural":
            manifest["natural_count"] += 1
        elif origin == "treated":
            manifest["treated_count"] += 1

        manifest["stones"].append(entry)

    return manifest


# ---------------------------------------------------------------------------
# report_summary
# ---------------------------------------------------------------------------

def report_summary(cert: CertificateRef) -> str:
    """Return a human-readable one-line summary of the certificate.

    Never raises; returns a best-effort string even with incomplete data.
    """
    parts: list[str] = []

    lab = cert.lab or "Unknown Lab"
    num = cert.cert_number or "No#"
    parts.append(f"{lab} #{num}")

    if cert.weight_carat is not None:
        parts.append(f"{cert.weight_carat:.2f} ct")

    if cert.color_grade:
        parts.append(f"Color {cert.color_grade}")

    if cert.clarity_grade:
        parts.append(f"Clarity {cert.clarity_grade}")

    if cert.cut is not None:
        if cert.lab == "AGS":
            parts.append(f"Cut AGS {cert.cut}")
        else:
            parts.append(f"Cut {cert.cut}")

    if cert.polish:
        parts.append(f"Polish {cert.polish}")

    if cert.symmetry:
        parts.append(f"Symmetry {cert.symmetry}")

    if cert.fluorescence:
        parts.append(f"Fluorescence {cert.fluorescence}")

    if cert.origin:
        _origin_label = {
            "natural":   "Natural",
            "lab_grown": "Lab-Grown",
            "treated":   "Treated",
        }.get(cert.origin, cert.origin.replace("_", " ").title())
        parts.append(_origin_label)

    if cert.date_issued:
        parts.append(f"({cert.date_issued})")

    return " | ".join(parts)


# ---------------------------------------------------------------------------
# LLM tool: jewelry_gem_cert_validate
# ---------------------------------------------------------------------------

_cert_validate_spec = ToolSpec(
    name="jewelry_gem_cert_validate",
    description=(
        "Validate a gem-certificate metadata record (CertificateRef) against "
        "lab-specific cert-number formats, GIA grading scales, and "
        "origin-consistency rules.\n"
        "\n"
        "Supported labs: GIA, IGI, AGS, EGL, GCAL, HRD.\n"
        "\n"
        "Returns {valid: bool, issues: [str]} — issues is empty when valid. "
        "Never raises; all errors are returned in the issues list."
    ),
    input_schema={
        "type": "object",
        "required": ["lab", "cert_number"],
        "properties": {
            "lab": {
                "type": "string",
                "description": "Grading laboratory: GIA | IGI | AGS | EGL | GCAL | HRD.",
            },
            "cert_number": {
                "type": "string",
                "description": "Certificate number as printed on the grading report.",
            },
            "date_issued": {
                "type": "string",
                "description": "ISO-8601 date the certificate was issued (YYYY-MM-DD).",
            },
            "weight_carat": {
                "type": "number",
                "description": "Reported carat weight.",
            },
            "cut": {
                "description": (
                    "Cut grade string (Excellent / Very Good / Good / Fair / Poor) "
                    "or AGS numeric 0–10."
                ),
            },
            "color_grade": {
                "type": "string",
                "description": "GIA colour grade D–Z or fancy-colour descriptor.",
            },
            "clarity_grade": {
                "type": "string",
                "description": "GIA clarity grade: FL IF VVS1 VVS2 VS1 VS2 SI1 SI2 I1 I2 I3.",
            },
            "dimensions_mm": {
                "type": "object",
                "description": "Stone dimensions in mm: {length, width, depth}.",
            },
            "polish": {
                "type": "string",
                "description": "Polish grade: Excellent Very Good Good Fair Poor.",
            },
            "symmetry": {
                "type": "string",
                "description": "Symmetry grade: Excellent Very Good Good Fair Poor.",
            },
            "fluorescence": {
                "type": "string",
                "description": "Fluorescence: None Faint Medium Strong Very Strong.",
            },
            "origin": {
                "type": "string",
                "description": "Stone origin: natural | lab_grown | treated.",
            },
            "comments": {"type": "string"},
            "plot_diagram_url": {
                "type": "string",
                "description": "URL or path to the clarity plot diagram.",
            },
            "cert_pdf_url": {
                "type": "string",
                "description": "URL or path to the full certificate PDF.",
            },
        },
    },
)


@register(_cert_validate_spec, write=False)
async def run_jewelry_gem_cert_validate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    lab = a.get("lab", "")
    cert_number = a.get("cert_number", "")
    if not lab:
        return err_payload("lab is required", "BAD_ARGS")
    if not cert_number:
        return err_payload("cert_number is required", "BAD_ARGS")

    ref = CertificateRef(
        lab=str(lab).strip(),
        cert_number=str(cert_number).strip(),
        date_issued=a.get("date_issued"),
        weight_carat=a.get("weight_carat"),
        cut=a.get("cut"),
        color_grade=a.get("color_grade"),
        clarity_grade=a.get("clarity_grade"),
        dimensions_mm=a.get("dimensions_mm"),
        polish=a.get("polish"),
        symmetry=a.get("symmetry"),
        fluorescence=a.get("fluorescence"),
        origin=a.get("origin"),
        comments=a.get("comments"),
        plot_diagram_url=a.get("plot_diagram_url"),
        cert_pdf_url=a.get("cert_pdf_url"),
    )

    issues = validate_cert(ref)
    return ok_payload({"valid": len(issues) == 0, "issues": issues})


# ---------------------------------------------------------------------------
# LLM tool: jewelry_gem_cert_attach
# ---------------------------------------------------------------------------

_cert_attach_spec = ToolSpec(
    name="jewelry_gem_cert_attach",
    description=(
        "Attach a gem-certificate (CertificateRef) to a gemstone dict "
        "from the gem_studio or gemstones tools.  Returns the annotated "
        "gemstone dict with a 'cert' key added.\n"
        "\n"
        "Pass the gemstone dict as the 'gemstone' argument and the "
        "certificate fields directly as top-level arguments."
    ),
    input_schema={
        "type": "object",
        "required": ["gemstone", "lab", "cert_number"],
        "properties": {
            "gemstone": {
                "type": "object",
                "description": "Gemstone dict from jewelry_gem_studio_cutter or similar.",
            },
            "lab": {"type": "string"},
            "cert_number": {"type": "string"},
            "date_issued": {"type": "string"},
            "weight_carat": {"type": "number"},
            "cut": {},
            "color_grade": {"type": "string"},
            "clarity_grade": {"type": "string"},
            "dimensions_mm": {"type": "object"},
            "polish": {"type": "string"},
            "symmetry": {"type": "string"},
            "fluorescence": {"type": "string"},
            "origin": {"type": "string"},
            "comments": {"type": "string"},
            "plot_diagram_url": {"type": "string"},
            "cert_pdf_url": {"type": "string"},
        },
    },
)


@register(_cert_attach_spec, write=False)
async def run_jewelry_gem_cert_attach(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    gemstone = a.get("gemstone")
    if not isinstance(gemstone, dict):
        return err_payload("gemstone must be a dict", "BAD_ARGS")

    lab = a.get("lab", "")
    cert_number = a.get("cert_number", "")
    if not lab:
        return err_payload("lab is required", "BAD_ARGS")
    if not cert_number:
        return err_payload("cert_number is required", "BAD_ARGS")

    ref = CertificateRef(
        lab=str(lab).strip(),
        cert_number=str(cert_number).strip(),
        date_issued=a.get("date_issued"),
        weight_carat=a.get("weight_carat"),
        cut=a.get("cut"),
        color_grade=a.get("color_grade"),
        clarity_grade=a.get("clarity_grade"),
        dimensions_mm=a.get("dimensions_mm"),
        polish=a.get("polish"),
        symmetry=a.get("symmetry"),
        fluorescence=a.get("fluorescence"),
        origin=a.get("origin"),
        comments=a.get("comments"),
        plot_diagram_url=a.get("plot_diagram_url"),
        cert_pdf_url=a.get("cert_pdf_url"),
    )

    issues = validate_cert(ref)
    annotated = attach_to_gemstone(dict(gemstone), ref)
    return ok_payload({
        "gemstone":        annotated,
        "cert_valid":      len(issues) == 0,
        "cert_issues":     issues,
    })


# ---------------------------------------------------------------------------
# LLM tool: jewelry_gem_cert_traceability
# ---------------------------------------------------------------------------

_cert_traceability_spec = ToolSpec(
    name="jewelry_gem_cert_traceability",
    description=(
        "Build a supply-chain traceability manifest for a finished jewelry "
        "piece.  Walks the piece's 'stones' list (or the top-level 'cert' "
        "on a single-stone piece) and produces a manifest with per-stone "
        "cert numbers, labs, origins, and aggregate counts.\n"
        "\n"
        "Returns a manifest dict with stone-level cert information and "
        "summary counts for certified, uncertified, lab-grown, natural, "
        "and treated stones."
    ),
    input_schema={
        "type": "object",
        "required": ["piece"],
        "properties": {
            "piece": {
                "type": "object",
                "description": (
                    "Jewelry piece dict.  Must contain a 'stones' list where "
                    "each stone may have a 'cert' dict (from jewelry_gem_cert_attach), "
                    "or a top-level 'cert' key for single-stone pieces."
                ),
            },
        },
    },
)


@register(_cert_traceability_spec, write=False)
async def run_jewelry_gem_cert_traceability(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    piece = a.get("piece")
    if not isinstance(piece, dict):
        return err_payload("piece must be a dict", "BAD_ARGS")

    manifest = traceability_chain(piece)
    return ok_payload(manifest)


# ---------------------------------------------------------------------------
# LLM tool: jewelry_gem_cert_report
# ---------------------------------------------------------------------------

_cert_report_spec = ToolSpec(
    name="jewelry_gem_cert_report",
    description=(
        "Generate a human-readable single-line summary of a gemological "
        "certificate.  Suitable for display in a UI label, BOM line, or "
        "quote document.\n"
        "\n"
        "Returns {summary: str}."
    ),
    input_schema={
        "type": "object",
        "required": ["lab", "cert_number"],
        "properties": {
            "lab": {"type": "string"},
            "cert_number": {"type": "string"},
            "date_issued": {"type": "string"},
            "weight_carat": {"type": "number"},
            "cut": {},
            "color_grade": {"type": "string"},
            "clarity_grade": {"type": "string"},
            "polish": {"type": "string"},
            "symmetry": {"type": "string"},
            "fluorescence": {"type": "string"},
            "origin": {"type": "string"},
            "comments": {"type": "string"},
            "plot_diagram_url": {"type": "string"},
            "cert_pdf_url": {"type": "string"},
        },
    },
)


@register(_cert_report_spec, write=False)
async def run_jewelry_gem_cert_report(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    lab = a.get("lab", "")
    cert_number = a.get("cert_number", "")
    if not lab:
        return err_payload("lab is required", "BAD_ARGS")
    if not cert_number:
        return err_payload("cert_number is required", "BAD_ARGS")

    ref = CertificateRef(
        lab=str(lab).strip(),
        cert_number=str(cert_number).strip(),
        date_issued=a.get("date_issued"),
        weight_carat=a.get("weight_carat"),
        cut=a.get("cut"),
        color_grade=a.get("color_grade"),
        clarity_grade=a.get("clarity_grade"),
        dimensions_mm=a.get("dimensions_mm"),
        polish=a.get("polish"),
        symmetry=a.get("symmetry"),
        fluorescence=a.get("fluorescence"),
        origin=a.get("origin"),
        comments=a.get("comments"),
        plot_diagram_url=a.get("plot_diagram_url"),
        cert_pdf_url=a.get("cert_pdf_url"),
    )

    summary = report_summary(ref)
    return ok_payload({"summary": summary})
