"""
DSTV NC1 (.nc1) steel-fabrication NC file writer.

Standard reference
------------------
DSTV NC — Datenaustausch für numerisch gesteuerte Maschinen (NC data exchange for
numerically-controlled machines in structural steelwork), published by the
Deutscher Stahlbau-Verband (DSTV) / Steel Construction Institute.

The NC1 format is the primary machine-language interchange used between steel
detailing software (Tekla Structures, Advance Steel, SDS/2) and CNC fabrication
machinery (drilling machines, coping robots, plasma cutters).

Block structure (per DSTV NC §3)
----------------------------------
Each NC1 file describes a single steel member (part).  The file consists of
named blocks, each starting with a keyword line and terminated when the next
keyword line (or ``EN``) is encountered.

  ST  — Stückliste (member header)
        Lines: order-no, drawing-no, pos-no, quantity, profile designation,
               material, length (mm), saw-length (mm), cross-section dims
  BO  — Bohrungen (holes / drill patterns)
        Each hole: face-id  x(mm)  y(mm)  diameter(mm)  [slot-length(mm)]
  AK  — Außenkontour (outer part outline / copes / notches)
        Contour vertices in mm, face-relative coordinates
  IK  — Innenkontour (inner contour / web cut-outs)
        Same format as AK
  SI  — Stempelinfo (part mark / stamp)
        Position, text, size
  EN  — Ende (end of file marker)

Coordinate conventions (DSTV NC §4)
-------------------------------------
Members are laid along the X-axis (longitudinal).  The origin is at the
left-hand end of the member when looking at the **top face (o)**.

Face identifiers:
  o  — Oben     (top)         upper flange or web top
  u  — Unten    (bottom)      lower flange or web bottom
  v  — Vorne    (front/near)  near web face
  h  — Hinten   (back/far)    far web face
  a  — Anfang   (start end)   left end plate / start cross-section
  e  — Ende     (finish end)  right end plate / finish cross-section

All dimensions are in millimetres, floating-point with up to 3 decimal places.
The decimal separator is a period ('.').

Profile designations follow EN 10034 / DSTV conventions, e.g.:
  I  — universal column / beam (H/I section), e.g. ``I HEB 200``
  U  — channel section (UPN, UAP)
  L  — angle section
  T  — T-section
  RD — round solid bar
  RO — circular hollow section (CHS)
  QR — square/rectangular hollow section (RHS/SHS)
  FL — flat bar / plate
  M  — other / miscellaneous

Usage example
-------------
    from kerf_structural.dstv_nc1 import NC1Member, NC1Hole, NC1Contour, write_nc1

    member = NC1Member(
        order_no="ORD-001",
        drawing_no="DWG-001",
        pos_no="P100",
        quantity=4,
        profile="I HEB 200",
        material="S355JR",
        length_mm=5000.0,
        flange_width_mm=200.0,
        flange_thickness_mm=15.0,
        web_height_mm=200.0,
        web_thickness_mm=9.0,
        holes=[
            NC1Hole(face="o", x_mm=250.0, y_mm=0.0, diameter_mm=22.0),
            NC1Hole(face="o", x_mm=500.0, y_mm=0.0, diameter_mm=22.0),
        ],
    )
    nc1_text = write_nc1(member)
"""

from __future__ import annotations

import math
import textwrap
from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "NC1Hole",
    "NC1ContourPoint",
    "NC1Contour",
    "NC1Stamp",
    "NC1Member",
    "write_nc1",
    "parse_nc1_header",
    "VALID_FACES",
    "VALID_PROFILE_TYPES",
]

# ---------------------------------------------------------------------------
# Constants & type aliases
# ---------------------------------------------------------------------------

FaceId = Literal["o", "u", "v", "h", "a", "e"]
"""Face identifiers per DSTV NC §4."""

VALID_FACES: frozenset[str] = frozenset({"o", "u", "v", "h", "a", "e"})

VALID_PROFILE_TYPES: tuple[str, ...] = (
    "I", "U", "L", "T", "RD", "RO", "QR", "FL", "M",
    "IPE", "HEA", "HEB", "HEM", "UPN", "UPE", "UAP",
    "RHS", "SHS", "CHS",
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class NC1Hole:
    """
    A single drilled or punched hole in the member.

    Parameters
    ----------
    face : FaceId
        Face on which the hole is located:
        'o' top, 'u' bottom, 'v' front web, 'h' back web,
        'a' start end, 'e' finish end.
    x_mm : float
        Longitudinal coordinate from member start (mm).
    y_mm : float
        Transverse coordinate on the face from the face centreline (mm).
        For flanges: distance from web centreline.
        For webs:    distance from mid-height.
        For end-plates ('a'/'e'): measured in face-local coords.
    diameter_mm : float
        Nominal bolt-hole diameter (mm), > 0.
    slot_length_mm : float, optional
        Slot length for slotted holes (mm); 0 = round hole (default).
    """

    face: str
    x_mm: float
    y_mm: float
    diameter_mm: float
    slot_length_mm: float = 0.0

    def __post_init__(self) -> None:
        if self.face not in VALID_FACES:
            raise ValueError(
                f"Invalid face {self.face!r}; must be one of {sorted(VALID_FACES)}"
            )
        if self.diameter_mm <= 0:
            raise ValueError(f"diameter_mm must be > 0, got {self.diameter_mm}")
        if self.slot_length_mm < 0:
            raise ValueError(f"slot_length_mm must be >= 0, got {self.slot_length_mm}")


@dataclass
class NC1ContourPoint:
    """
    A single vertex of an AK/IK contour polygon (face-relative mm coords).

    Parameters
    ----------
    x_mm : float
        Longitudinal coordinate (mm from member start).
    y_mm : float
        Transverse coordinate (mm).
    arc_bulge : float
        Bulge factor for arc segments (0 = straight line, default).
        Bulge = tan(included_angle / 4); positive = counter-clockwise arc.
    """

    x_mm: float
    y_mm: float
    arc_bulge: float = 0.0


@dataclass
class NC1Contour:
    """
    An outer (AK) or inner (IK) contour block.

    Parameters
    ----------
    face : FaceId
        Face on which the contour lies.
    points : list[NC1ContourPoint]
        Ordered polygon vertices (closed; first == last is implied, do not
        repeat the first point at the end).
    """

    face: str
    points: list[NC1ContourPoint] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.face not in VALID_FACES:
            raise ValueError(
                f"Invalid face {self.face!r}; must be one of {sorted(VALID_FACES)}"
            )
        if len(self.points) < 3:
            raise ValueError("Contour requires at least 3 points")


@dataclass
class NC1Stamp:
    """
    Part mark / stamp text (SI block).

    Parameters
    ----------
    face : FaceId
        Face where the stamp is applied.
    x_mm : float
        Longitudinal position (mm from member start).
    y_mm : float
        Transverse position (mm).
    text : str
        Stamp text (part mark).
    size_mm : float
        Character height in mm (default 10.0).
    """

    face: str
    x_mm: float
    y_mm: float
    text: str
    size_mm: float = 10.0

    def __post_init__(self) -> None:
        if self.face not in VALID_FACES:
            raise ValueError(
                f"Invalid face {self.face!r}; must be one of {sorted(VALID_FACES)}"
            )


@dataclass
class NC1Member:
    """
    Complete description of a single steel member for NC1 export.

    Parameters
    ----------
    order_no : str
        Order / job number (max 20 chars).
    drawing_no : str
        Drawing number (max 20 chars).
    pos_no : str
        Part / position number (max 20 chars).
    quantity : int
        Number of identical pieces (default 1).
    profile : str
        Profile designation per EN 10034 / DSTV convention, e.g. ``I HEB 200``,
        ``I IPE 300``, ``U UPN 200``, ``L L100x100x10``, ``RO 139.7x8``.
    material : str
        Steel grade designation, e.g. ``S355JR``, ``A572-50`` (max 8 chars).
    length_mm : float
        Cut length of the member (mm), measured along the longitudinal axis.
    flange_width_mm : float
        Profile flange width (mm).  For hollow sections, the outer width.
        Set to 0 for round sections.
    flange_thickness_mm : float
        Flange thickness (mm).  For hollow sections, wall thickness.
    web_height_mm : float
        Total profile height (mm) for I/H sections.  For channels, the height.
        For hollow/round sections, the outer diameter.
    web_thickness_mm : float
        Web thickness (mm).  For hollow sections, same as wall thickness.
    holes : list[NC1Hole]
        List of holes (BO block).  May be empty.
    outer_contours : list[NC1Contour]
        Outer contour polygons (AK block, typically one per face with copes/notches).
        May be empty.
    inner_contours : list[NC1Contour]
        Inner contour polygons (IK block, e.g. web cope cut-outs).
        May be empty.
    stamps : list[NC1Stamp]
        Part mark stamps (SI block).  May be empty.
    saw_length_mm : float | None
        Saw cut length if different from ``length_mm`` (e.g. for skewed cuts).
        Defaults to ``length_mm`` when None.
    """

    order_no: str
    drawing_no: str
    pos_no: str
    quantity: int
    profile: str
    material: str
    length_mm: float
    flange_width_mm: float
    flange_thickness_mm: float
    web_height_mm: float
    web_thickness_mm: float
    holes: list[NC1Hole] = field(default_factory=list)
    outer_contours: list[NC1Contour] = field(default_factory=list)
    inner_contours: list[NC1Contour] = field(default_factory=list)
    stamps: list[NC1Stamp] = field(default_factory=list)
    saw_length_mm: float | None = None

    def __post_init__(self) -> None:
        if self.length_mm <= 0:
            raise ValueError(f"length_mm must be > 0, got {self.length_mm}")
        if self.quantity < 1:
            raise ValueError(f"quantity must be >= 1, got {self.quantity}")
        if self.flange_width_mm < 0:
            raise ValueError(f"flange_width_mm must be >= 0, got {self.flange_width_mm}")
        if self.flange_thickness_mm < 0:
            raise ValueError(f"flange_thickness_mm must be >= 0, got {self.flange_thickness_mm}")
        if self.web_height_mm <= 0:
            raise ValueError(f"web_height_mm must be > 0, got {self.web_height_mm}")
        if self.web_thickness_mm < 0:
            raise ValueError(f"web_thickness_mm must be >= 0, got {self.web_thickness_mm}")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt(value: float) -> str:
    """
    Format a float per DSTV NC §3.2: up to 3 decimal places, no trailing
    zeros after the decimal point, period as separator.
    """
    formatted = f"{value:.3f}".rstrip("0").rstrip(".")
    return formatted


def _pad(s: str, width: int) -> str:
    """Left-justify string in a field of given width."""
    return s[:width].ljust(width)


# ---------------------------------------------------------------------------
# Block writers
# ---------------------------------------------------------------------------

def _write_st_block(m: NC1Member) -> str:
    """
    Write the ST (Stückliste) header block.

    DSTV NC §3.3 — ST block layout (fixed-position lines):
      Line 1: Auftragsnummer (order number)        — max 20 chars
      Line 2: Zeichnungsnummer (drawing number)    — max 20 chars
      Line 3: Positionsnummer (position number)    — max 20 chars
      Line 4: Stückzahl (quantity)                 — integer
      Line 5: Profilbezeichnung (profile)          — max 30 chars
      Line 6: Güte (material / grade)              — max 8 chars
      Line 7: Länge (cut length mm)                — float
      Line 8: Sägelänge (saw length mm)            — float (= cut length if no skew)
      Line 9: Breite (flange width mm)             — float
      Line 10: Breite der Flansche (flange thickness mm) — float
      Line 11: Steghöhe (web height mm)            — float
      Line 12: Stegdicke (web thickness mm)        — float
    """
    saw_len = m.saw_length_mm if m.saw_length_mm is not None else m.length_mm
    lines = [
        "ST",
        _pad(m.order_no, 20),
        _pad(m.drawing_no, 20),
        _pad(m.pos_no, 20),
        str(int(m.quantity)),
        _pad(m.profile, 30),
        _pad(m.material, 8),
        _fmt(m.length_mm),
        _fmt(saw_len),
        _fmt(m.flange_width_mm),
        _fmt(m.flange_thickness_mm),
        _fmt(m.web_height_mm),
        _fmt(m.web_thickness_mm),
    ]
    return "\n".join(lines)


def _write_bo_block(holes: list[NC1Hole]) -> str:
    """
    Write the BO (Bohrungen) block.

    Per DSTV NC §3.4, each hole is represented on a single data line:
      <face>  <x_mm>  <y_mm>  <diameter_mm>  [<slot_length_mm>]

    Fields are separated by whitespace.  The face identifier is a single
    lowercase letter.  Round holes omit the slot_length field (or write 0).
    """
    if not holes:
        return ""
    rows = ["BO"]
    for h in holes:
        if h.slot_length_mm > 0:
            rows.append(
                f"{h.face}  {_fmt(h.x_mm)}  {_fmt(h.y_mm)}  "
                f"{_fmt(h.diameter_mm)}  {_fmt(h.slot_length_mm)}"
            )
        else:
            rows.append(
                f"{h.face}  {_fmt(h.x_mm)}  {_fmt(h.y_mm)}  {_fmt(h.diameter_mm)}"
            )
    return "\n".join(rows)


def _write_contour_block(contours: list[NC1Contour], keyword: str) -> str:
    """
    Write AK or IK contour block(s).

    Per DSTV NC §3.5, each contour starts with the keyword (AK or IK)
    followed by the face identifier on the same line, then one vertex per
    line: ``<x_mm>  <y_mm>  [<bulge>]``

    Multiple contours on the same face each get their own keyword line.
    """
    if not contours:
        return ""
    rows: list[str] = []
    for contour in contours:
        rows.append(f"{keyword} {contour.face}")
        for pt in contour.points:
            if pt.arc_bulge != 0.0:
                rows.append(f"{_fmt(pt.x_mm)}  {_fmt(pt.y_mm)}  {_fmt(pt.arc_bulge)}")
            else:
                rows.append(f"{_fmt(pt.x_mm)}  {_fmt(pt.y_mm)}")
    return "\n".join(rows)


def _write_si_block(stamps: list[NC1Stamp]) -> str:
    """
    Write the SI (Stempelinfo) block.

    Per DSTV NC §3.6, each stamp entry is:
      <face>  <x_mm>  <y_mm>  <size_mm>  <text>
    """
    if not stamps:
        return ""
    rows = ["SI"]
    for s in stamps:
        rows.append(
            f"{s.face}  {_fmt(s.x_mm)}  {_fmt(s.y_mm)}  {_fmt(s.size_mm)}  {s.text}"
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_nc1(member: NC1Member) -> str:
    """
    Serialise a :class:`NC1Member` to a DSTV NC1 text file.

    The output conforms to the DSTV NC standard for steel-fabrication NC data
    exchange.  Blocks are written in the canonical order: ST → BO → AK → IK
    → SI → EN.  Empty optional blocks (BO, AK, IK, SI) are omitted entirely.

    Parameters
    ----------
    member : NC1Member
        Fully populated member data object.

    Returns
    -------
    str
        Multi-line string containing the complete NC1 file content.
        Ends with a newline after the ``EN`` terminator.

    Notes
    -----
    - Line endings are ``\\n`` (LF).  Most CNC controllers accept LF; convert
      to CRLF if your machine requires it.
    - The file should be saved with a ``.nc1`` extension and ASCII / UTF-8
      encoding.  Non-ASCII characters in text fields may cause issues on
      older controllers; prefer ASCII-safe part marks.

    References
    ----------
    DSTV NC — Datenaustausch für numerisch gesteuerte Maschinen,
    Deutscher Stahlbau-Verband (DSTV), §3 File Structure.
    DIN 18800-7:2002 — Stahlbauten: Ausführung und Herstellerqualifikation.
    """
    parts: list[str] = []

    # ST block — always present
    parts.append(_write_st_block(member))

    # BO block — holes (omit if empty)
    bo = _write_bo_block(member.holes)
    if bo:
        parts.append(bo)

    # AK block — outer contours
    ak = _write_contour_block(member.outer_contours, "AK")
    if ak:
        parts.append(ak)

    # IK block — inner contours
    ik = _write_contour_block(member.inner_contours, "IK")
    if ik:
        parts.append(ik)

    # SI block — stamps / marks
    si = _write_si_block(member.stamps)
    if si:
        parts.append(si)

    # EN terminator
    parts.append("EN")

    return "\n".join(parts) + "\n"


def parse_nc1_header(nc1_text: str) -> dict:
    """
    Parse the ST block fields from a DSTV NC1 file and return them as a dict.

    This is a lightweight parser suitable for round-trip testing of the header
    fields produced by :func:`write_nc1`.  It does not parse BO/AK/IK/SI blocks.

    Parameters
    ----------
    nc1_text : str
        Full NC1 file content as returned by :func:`write_nc1`.

    Returns
    -------
    dict with keys:
        order_no, drawing_no, pos_no, quantity, profile, material,
        length_mm, saw_length_mm, flange_width_mm, flange_thickness_mm,
        web_height_mm, web_thickness_mm

    Raises
    ------
    ValueError
        If the text does not start with an ST block.
    """
    lines = nc1_text.splitlines()

    # Find ST block
    try:
        st_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "ST")
    except StopIteration:
        raise ValueError("No ST block found in NC1 text")

    # Extract the 12 data lines following "ST"
    data = lines[st_idx + 1 : st_idx + 13]
    if len(data) < 12:
        raise ValueError(
            f"ST block too short: expected 12 data lines, got {len(data)}"
        )

    return {
        "order_no":            data[0].strip(),
        "drawing_no":          data[1].strip(),
        "pos_no":              data[2].strip(),
        "quantity":            int(data[3].strip()),
        "profile":             data[4].strip(),
        "material":            data[5].strip(),
        "length_mm":           float(data[6].strip()),
        "saw_length_mm":       float(data[7].strip()),
        "flange_width_mm":     float(data[8].strip()),
        "flange_thickness_mm": float(data[9].strip()),
        "web_height_mm":       float(data[10].strip()),
        "web_thickness_mm":    float(data[11].strip()),
    }
