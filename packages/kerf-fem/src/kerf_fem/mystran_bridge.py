"""
MYSTRAN subprocess bridge for modal and aeroelastic analysis.

MYSTRAN is an open-source, NASTRAN-compatible finite-element solver that reads
Bulk Data Format (.BDF/.bdf) decks and writes F06 and PCH output files.

Public entry-point
------------------
    MystranBridge.solve(mesh, materials, boundary_conditions, *, analysis_type)
        -> Result

Where *analysis_type* is one of:
    "modal"          — SOL 103  real eigenvalue extraction
    "linear_static"  — SOL 101  linear statics

Usage example
-------------
    bridge = MystranBridge()
    result = bridge.solve(
        mesh={"nodes": [...], "elements": [...]},
        materials={"E": 200e9, "nu": 0.3, "rho": 7850.0},
        boundary_conditions=[{"type": "fixed", "node_ids": [1, 2, 3]}],
        analysis_type="modal",
    )

BDF syntax reference
--------------------
MSC.Software, "MSC Nastran Quick Reference Guide", 2023.
MYSTRAN User's Manual (MYSTRAN project, GitHub mystran/mystran).

F06 output parsing
------------------
MYSTRAN writes eigenvalues in the "R E A L   E I G E N V A L U E S" table:
    MODE  EXTRACTION ORDER  EIGENVALUE      RADIANS         CYCLES
     1         1           1.000000E+06    1.000000E+03    1.591549E+02

PCH (punch) output parsing
---------------------------
When ``STRESS(PUNCH)=ALL`` is added to the case control deck, MYSTRAN writes
a ``<basename>.pch`` (or ``.PCH``) file beside the F06.  Cards are 80-char
fixed-format NASTRAN punch output.  Stress sections are introduced by a
comment header ``$ELEMENT STRESSES`` and each element occupies one or more
80-char data records.  ``_parse_pch_stresses`` recovers the full six-component
stress tensor and the von-Mises scalar per element.
"""

from __future__ import annotations

import logging
import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Availability probe (cached)
# ---------------------------------------------------------------------------

_MYSTRAN_AVAILABLE: Optional[bool] = None


def _mystran_available() -> bool:
    global _MYSTRAN_AVAILABLE
    if _MYSTRAN_AVAILABLE is None:
        _MYSTRAN_AVAILABLE = shutil.which("mystran") is not None
    return _MYSTRAN_AVAILABLE


ENGINE_PENDING_WARNING = (
    "Engine pending — MYSTRAN not installed or not in PATH.  "
    "Install from https://github.com/MYSTRANsolver/MYSTRAN/releases."
)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class MystranResult:
    """Parsed output from a MYSTRAN run."""

    ok: bool
    analysis_type: str
    # Modal results
    frequencies: list[float] = field(default_factory=list)     # Hz
    eigenvalues: list[float] = field(default_factory=list)     # rad²/s²
    # Static results
    displacements: list[dict[str, float]] = field(default_factory=list)
    stresses: list[dict[str, float]] = field(default_factory=list)
    max_displacement: float = 0.0
    max_vonmises_stress: float = 0.0
    # Diagnostics
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status: str = "ok"  # "ok" | "pending" | "failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "analysis_type": self.analysis_type,
            "frequencies": self.frequencies,
            "eigenvalues": self.eigenvalues,
            "displacements": self.displacements,
            "stresses": self.stresses,
            "max_displacement": self.max_displacement,
            "max_vonmises_stress": self.max_vonmises_stress,
            "warnings": self.warnings,
            "errors": self.errors,
            "status": self.status,
        }


# ---------------------------------------------------------------------------
# Stress result per element
# ---------------------------------------------------------------------------


@dataclass
class StressResult:
    """
    Full stress state for a single element recovered from PCH punch output.

    Attributes
    ----------
    eid:
        Element ID (NASTRAN 1-based integer).
    sigma_xx, sigma_yy, sigma_zz:
        Normal stress components [Pa].
    tau_xy, tau_yz, tau_zx:
        Shear stress components [Pa].
    von_mises:
        Von Mises equivalent stress [Pa], computed as:
            σ_vm = √½[(σ_xx−σ_yy)²+(σ_yy−σ_zz)²+(σ_zz−σ_xx)²
                       + 6(τ_xy²+τ_yz²+τ_zx²)]
    principal_1, principal_2, principal_3:
        Eigenvalues of the symmetric 3×3 stress tensor [Pa], sorted
        descending (σ₁ ≥ σ₂ ≥ σ₃).
    """

    eid: int
    sigma_xx: float = 0.0
    sigma_yy: float = 0.0
    sigma_zz: float = 0.0
    tau_xy: float = 0.0
    tau_yz: float = 0.0
    tau_zx: float = 0.0
    von_mises: float = 0.0
    principal_1: float = 0.0
    principal_2: float = 0.0
    principal_3: float = 0.0

    def as_stress_dict(self) -> dict[str, float]:
        """Return a plain dict suitable for embedding in MystranResult.stresses."""
        return {
            "eid": float(self.eid),
            "sigma_xx": self.sigma_xx,
            "sigma_yy": self.sigma_yy,
            "sigma_zz": self.sigma_zz,
            "tau_xy": self.tau_xy,
            "tau_yz": self.tau_yz,
            "tau_zx": self.tau_zx,
            "von_mises": self.von_mises,
            "principal_1": self.principal_1,
            "principal_2": self.principal_2,
            "principal_3": self.principal_3,
        }


# ---------------------------------------------------------------------------
# BDF (Bulk Data Format) deck writer
# ---------------------------------------------------------------------------

# NASTRAN fixed-field format: 10 fields of 8 characters each (80-col card).
# Free-field (*BULK DATA) is also accepted by MYSTRAN.

def _fmt8(v: Any) -> str:
    """Format a scalar value into an 8-character NASTRAN field."""
    if isinstance(v, int):
        return f"{v:>8d}"
    if isinstance(v, float):
        # Use NASTRAN scientific notation — up to 8 chars including sign.
        s = f"{v:.4E}"
        # Shorten exponent: 1.2345E+02 → 1.2345E+2 if possible
        s = re.sub(r"E([+-])0+(\d+)$", lambda m: f"E{m.group(1)}{m.group(2)}", s)
        if len(s) > 8:
            s = f"{v:.3E}"
            s = re.sub(r"E([+-])0+(\d+)$", lambda m: f"E{m.group(1)}{m.group(2)}", s)
        return f"{s:>8s}"
    return f"{str(v):>8s}"


def _card(*fields: Any) -> str:
    """Build a free-field BDF card line (comma-separated, MYSTRAN compatible)."""
    return ",".join(str(f) for f in fields)


def _write_bdf_modal(
    nodes: list[tuple[float, float, float]],
    elements: list[tuple[int, str, list[int]]],
    materials: dict,
    boundary_conditions: list[dict],
    num_modes: int = 10,
    *,
    shell_thickness: Optional[float] = None,
) -> str:
    """
    Build a NASTRAN/MYSTRAN Bulk Data deck for SOL 103 real normal modes.

    Parameters
    ----------
    nodes:
        List of (x, y, z) node coordinates (0-indexed; internally 1-indexed).
    elements:
        List of (elem_id, elem_type, node_list) where elem_type is one of:
        "CQUAD4", "CTRIA3", "CTETRA", "CHEXA".
    materials:
        Dict with keys E [Pa], nu, rho [kg/m³].  Optional: yield_strength.
    boundary_conditions:
        List of dicts.  Supported: {"type": "fixed", "node_ids": [...]}.
    num_modes:
        Number of eigenvalues to extract.
    shell_thickness:
        Required for shell elements (CQUAD4 / CTRIA3).  If None, defaults to
        1e-3 m (1 mm) when shell elements are detected.
    """
    E = float(materials.get("E", 200e9))
    nu = float(materials.get("nu", 0.3))
    rho = float(materials.get("rho", 7850.0))

    lines: list[str] = []

    # ---- Executive Control Deck -----------------------------------------
    lines += [
        "SOL 103",
        "CEND",
    ]

    # ---- Case Control Deck ----------------------------------------------
    lines += [
        "TITLE = MYSTRAN MODAL ANALYSIS",
        "ECHO = NONE",
        f"METHOD = 1",
        "DISPLACEMENT(SORT1,REAL) = ALL",
        "BEGIN BULK",
    ]

    # ---- Bulk Data -------------------------------------------------------

    # EIGRL card: Lanczos real eigenvalue extraction, request num_modes modes.
    # EIGRL  SID  V1   V2   ND
    lines.append(f"EIGRL,1,,,{num_modes}")

    # MAT1: isotropic material
    # MAT1  MID  E    G    NU   RHO
    lines.append(f"MAT1,1,{E:.6E},,{nu:.4f},{rho:.4f}")

    # PSOLID / PSHELL property
    has_shell = any(et in ("CQUAD4", "CTRIA3")
                    for (_, et, _) in elements)
    has_solid = any(et in ("CTETRA", "CHEXA")
                    for (_, et, _) in elements)

    if has_shell:
        t = shell_thickness if shell_thickness is not None else 1e-3
        # PSHELL  PID  MID1  T  MID2  12I/T^3  MID3  TS/T  NSM
        lines.append(f"PSHELL,1,1,{t:.6E},1")

    if has_solid:
        # PSOLID  PID  MID  CORDM  IN  STRESS  ISOP  FCTN
        lines.append("PSOLID,2,1")

    # GRID cards: node coordinates
    for i, (x, y, z) in enumerate(nodes):
        nid = i + 1
        # GRID  NID  CP  X1  X2  X3  CD  PS  SEID
        lines.append(f"GRID,{nid},,{x:.10g},{y:.10g},{z:.10g}")

    # Element connectivity
    for eid, etype, enodes in elements:
        nstr = ",".join(str(n) for n in enodes)
        pid = 1 if etype in ("CQUAD4", "CTRIA3") else 2
        lines.append(f"{etype},{eid},{pid},{nstr}")

    # SPC1: single-point constraints (fixed boundary conditions)
    spc_id = 10
    spc_written = False
    for bc in boundary_conditions:
        if bc.get("type") == "fixed":
            node_ids = bc.get("node_ids", [])
            if not node_ids:
                continue
            # SPC1  SID  C  G1  G2  ...  (C=123456 = all 6 DOF)
            # MYSTRAN accepts free-field; split into groups of 7 nodes per card.
            chunk_size = 7
            for chunk_start in range(0, len(node_ids), chunk_size):
                chunk = node_ids[chunk_start:chunk_start + chunk_size]
                nstr = ",".join(str(n) for n in chunk)
                lines.append(f"SPC1,{spc_id},123456,{nstr}")
            spc_written = True

    if spc_written:
        # Reference the SPC set in the Case Control section.
        # We need to inject SPC=spc_id before BEGIN BULK.
        bulk_idx = lines.index("BEGIN BULK")
        lines.insert(bulk_idx, f"SPC = {spc_id}")

    lines.append("ENDDATA")
    return "\n".join(lines) + "\n"


def _write_bdf_static(
    nodes: list[tuple[float, float, float]],
    elements: list[tuple[int, str, list[int]]],
    materials: dict,
    boundary_conditions: list[dict],
    loads: list[dict],
    *,
    shell_thickness: Optional[float] = None,
) -> str:
    """
    Build a NASTRAN/MYSTRAN Bulk Data deck for SOL 101 linear statics.
    """
    E = float(materials.get("E", 200e9))
    nu = float(materials.get("nu", 0.3))
    rho = float(materials.get("rho", 7850.0))

    lines: list[str] = []

    lines += ["SOL 101", "CEND"]
    lines += [
        "TITLE = MYSTRAN STATIC ANALYSIS",
        "ECHO = NONE",
        "SUBCASE 1",
        "  LOAD = 1",
        "  DISPLACEMENT(SORT1,REAL) = ALL",
        "  STRESS(SORT1,REAL) = ALL",
        "BEGIN BULK",
    ]

    # MAT1
    lines.append(f"MAT1,1,{E:.6E},,{nu:.4f},{rho:.4f}")

    has_shell = any(et in ("CQUAD4", "CTRIA3") for (_, et, _) in elements)
    has_solid = any(et in ("CTETRA", "CHEXA") for (_, et, _) in elements)

    if has_shell:
        t = shell_thickness if shell_thickness is not None else 1e-3
        lines.append(f"PSHELL,1,1,{t:.6E},1")
    if has_solid:
        lines.append("PSOLID,2,1")

    for i, (x, y, z) in enumerate(nodes):
        nid = i + 1
        lines.append(f"GRID,{nid},,{x:.10g},{y:.10g},{z:.10g}")

    for eid, etype, enodes in elements:
        nstr = ",".join(str(n) for n in enodes)
        pid = 1 if etype in ("CQUAD4", "CTRIA3") else 2
        lines.append(f"{etype},{eid},{pid},{nstr}")

    spc_id = 10
    spc_written = False
    for bc in boundary_conditions:
        if bc.get("type") == "fixed":
            node_ids = bc.get("node_ids", [])
            if not node_ids:
                continue
            chunk_size = 7
            for chunk_start in range(0, len(node_ids), chunk_size):
                chunk = node_ids[chunk_start:chunk_start + chunk_size]
                nstr = ",".join(str(n) for n in chunk)
                lines.append(f"SPC1,{spc_id},123456,{nstr}")
            spc_written = True

    if spc_written:
        bulk_idx = lines.index("BEGIN BULK")
        lines.insert(bulk_idx, f"SPC = {spc_id}")

    # FORCE cards (point loads): load.{"type":"force","node_id":1,"fx":0,"fy":0,"fz":-1000}
    force_cards: list[str] = []
    for i, load in enumerate(loads or []):
        if load.get("type") == "force":
            nid = load.get("node_id", 1)
            fx = load.get("fx", 0.0)
            fy = load.get("fy", 0.0)
            fz = load.get("fz", 0.0)
            mag = math.sqrt(fx * fx + fy * fy + fz * fz)
            if mag > 0:
                nx, ny, nz = fx / mag, fy / mag, fz / mag
                force_cards.append(
                    f"FORCE,1,{nid},,{mag:.6E},{nx:.6f},{ny:.6f},{nz:.6f}"
                )

    lines.extend(force_cards)
    lines.append("ENDDATA")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# F06 output parser
# ---------------------------------------------------------------------------

def _parse_f06_eigenvalues(content: str) -> tuple[list[float], list[float]]:
    """
    Extract real eigenvalues and frequencies from MYSTRAN F06 output.

    MYSTRAN writes:
        R E A L   E I G E N V A L U E S
        MODE NO.  EXTRACTION ORDER  EIGENVALUE        RADIANS        CYCLES
           1           1          1.00000E+06    1.00000E+03    1.59155E+02

    Returns (eigenvalues [rad²/s²], frequencies [Hz]).
    """
    eigenvalues: list[float] = []
    frequencies: list[float] = []

    # Match the block header (spaced out letters)
    block = re.search(
        r"R\s*E\s*A\s*L\s+E\s*I\s*G\s*E\s*N\s*V\s*A\s*L\s*U\s*E\s*S(.*?)"
        r"(?=\n\s*\n|\Z)",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if not block:
        return eigenvalues, frequencies

    for line in block.group(1).splitlines():
        parts = line.split()
        # Expect: mode_no  extraction_order  eigenvalue  radians  cycles
        if len(parts) >= 5 and parts[0].isdigit():
            try:
                ev = float(parts[2])
                freq_hz = float(parts[4])
                if ev > 0 and freq_hz > 0:
                    eigenvalues.append(ev)
                    frequencies.append(freq_hz)
            except (ValueError, IndexError):
                pass

    return eigenvalues, frequencies


def _parse_f06_displacements(content: str) -> list[dict[str, float]]:
    """
    Parse displacement output block from MYSTRAN F06.

    Block header pattern:
        D I S P L A C E M E N T   V E C T O R
        POINT ID.   TYPE   T1             T2             T3             R1
    """
    disps: list[dict[str, float]] = []

    block = re.search(
        r"D\s*I\s*S\s*P\s*L\s*A\s*C\s*E\s*M\s*E\s*N\s*T\s+"
        r"V\s*E\s*C\s*T\s*O\s*R(.*?)"
        r"(?=\n\s*\n|\Z)",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if not block:
        return disps

    for line in block.group(1).splitlines():
        parts = line.split()
        # POINT_ID  G  T1  T2  T3  R1  R2  R3
        if len(parts) >= 5 and parts[0].isdigit():
            try:
                t1, t2, t3 = float(parts[2]), float(parts[3]), float(parts[4])
                disps.append({"ux": t1, "uy": t2, "uz": t3})
            except (ValueError, IndexError):
                pass

    return disps


# ---------------------------------------------------------------------------
# PCH (punch) output helpers
# ---------------------------------------------------------------------------

def _compute_von_mises(sxx: float, syy: float, szz: float,
                        txy: float, tyz: float, tzx: float) -> float:
    """
    Compute von Mises equivalent stress from the 6 independent tensor
    components.

    σ_vm = √½ [(σ_xx−σ_yy)² + (σ_yy−σ_zz)² + (σ_zz−σ_xx)²
                + 6(τ_xy² + τ_yz² + τ_zx²)]
    """
    return math.sqrt(0.5 * (
        (sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2
        + 6.0 * (txy ** 2 + tyz ** 2 + tzx ** 2)
    ))


def _compute_principal_stresses(sxx: float, syy: float, szz: float,
                                  txy: float, tyz: float, tzx: float,
                                  ) -> tuple[float, float, float]:
    """
    Return the three principal stresses (eigenvalues of the symmetric 3×3
    stress tensor) sorted in descending order (σ₁ ≥ σ₂ ≥ σ₃).

    Uses the closed-form Cardano / trigonometric approach to avoid
    importing numpy.  Follows Kopp (2008) arXiv:physics/0610206 §2.
    """
    # Characteristic equation coefficients:
    #   λ³ - I1·λ² + I2·λ - I3 = 0
    I1 = sxx + syy + szz
    I2 = (sxx * syy + syy * szz + szz * sxx
          - txy * txy - tyz * tyz - tzx * tzx)
    I3 = (sxx * (syy * szz - tyz * tyz)
          - txy * (txy * szz - tyz * tzx)
          + tzx * (txy * tyz - syy * tzx))

    p1 = I1 / 3.0
    # Shift: μ = (λ - p1), gives  μ³ + q·μ + r = 0
    q = I2 - I1 * I1 / 3.0  # = -(s₁₁²+s₂₂²+s₃₃²+2τ²)/3  (≤ 0 for real tensor)
    r = -2.0 * p1 ** 3 + I1 * I2 / 3.0 - I3

    # Discriminant for depressed cubic  μ³ + q·μ + r = 0
    disc = (r / 2.0) ** 2 + (q / 3.0) ** 3  # ≤ 0 for three real roots

    if disc > 1e-30:
        # Numerically near-degenerate (e.g. uniaxial): fall back to one real root
        A = _cbrt(-r / 2.0 + math.sqrt(disc))
        B = _cbrt(-r / 2.0 - math.sqrt(disc))
        lam = A + B + p1
        # Other two roots are complex; approximate as equal to lam
        eigs = sorted([lam, lam, lam], reverse=True)
    else:
        # Three real roots via trigonometric method
        rho = math.sqrt(-(q / 3.0) ** 3)
        if rho < 1e-30:
            eigs = [p1, p1, p1]
        else:
            cos_arg = max(-1.0, min(1.0, -r / (2.0 * rho)))
            theta = math.acos(cos_arg) / 3.0
            two_rho13 = 2.0 * rho ** (1.0 / 3.0)
            lam1 = two_rho13 * math.cos(theta) + p1
            lam2 = two_rho13 * math.cos(theta + 2.0 * math.pi / 3.0) + p1
            lam3 = two_rho13 * math.cos(theta + 4.0 * math.pi / 3.0) + p1
            eigs = sorted([lam1, lam2, lam3], reverse=True)

    return eigs[0], eigs[1], eigs[2]


def _cbrt(x: float) -> float:
    """Cube root preserving sign (math.cbrt added in Python 3.11; this works on 3.9+)."""
    if x >= 0.0:
        return x ** (1.0 / 3.0)
    return -((-x) ** (1.0 / 3.0))


def _emit_punch_request(deck_str: str) -> str:
    """
    Inject ``STRESS(PUNCH)=ALL`` into the case-control section of a BDF deck
    string if not already present.  The injection occurs immediately before
    ``BEGIN BULK`` so it lands inside the case control section and is valid for
    all subcases.

    Parameters
    ----------
    deck_str:
        Complete BDF deck as a multi-line string.

    Returns
    -------
    str
        Modified deck with the PUNCH directive added (or unchanged if already
        present).
    """
    # Check idempotency: if any variant of STRESS(PUNCH) is already there, skip.
    if re.search(r"STRESS\s*\(\s*PUNCH", deck_str, re.IGNORECASE):
        return deck_str

    # Inject before BEGIN BULK line.
    return re.sub(
        r"(?m)^(BEGIN BULK\s*)$",
        r"STRESS(PUNCH)=ALL\n\1",
        deck_str,
        count=1,
    )


def _parse_pch_stresses(pch_path: "Path") -> "dict[int, StressResult]":
    """
    Parse element stresses from a NASTRAN/MYSTRAN punch (.pch) file.

    The punch file uses 80-character fixed-format records.  Stress output
    sections are introduced by a ``$ELEMENT STRESSES`` or
    ``$ELEMENT STRAINS`` comment header.  Within a section each element
    appears as one or more records.

    MYSTRAN punch stress format (free-field variant, comma-separated):
        $ELEMENT STRESSES
        $ EID       SIGMA_XX   SIGMA_YY   SIGMA_ZZ   TAU_XY     TAU_YZ     TAU_ZX
        1,          1.000E+03, 2.000E+03, ...

    Fixed-format NASTRAN punch records (alternative):
        Record 1 (columns 1-8: EID, 9-16: type, 17-80: values...)

    Both layouts are handled: the parser first tries comma-split (free-field),
    falling back to fixed-field column slicing.

    Parameters
    ----------
    pch_path:
        Path to the .pch file.

    Returns
    -------
    dict[int, StressResult]
        Keyed by integer element ID.  Empty dict if the file contains no
        recognisable stress output.
    """
    results: dict[int, StressResult] = {}

    try:
        text = pch_path.read_text(errors="replace")
    except OSError:
        return results

    in_stress_section = False
    # A two-line buffer for fixed-format records that span continuation cards.
    _pending: list[float] = []
    _pending_eid: int = -1

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        # --- Section header detection ---
        if line.startswith("$"):
            upper = line.upper()
            if "ELEMENT STRESSES" in upper or "ELEMENT STRAINS" in upper:
                in_stress_section = True
                _pending.clear()
                _pending_eid = -1
            elif in_stress_section:
                # A $ line that looks like a *different* NASTRAN output-section
                # title (e.g. "$ELEMENT FORCES", "$DISPLACEMENTS") ends the
                # current stress section.  Plain column-header comment lines
                # (e.g. "$ EID, SXX, SYY ...") must NOT end the section — we
                # distinguish by checking for a known section keyword.
                _SECTION_KEYWORDS = (
                    "ELEMENT FORCES", "DISPLACEMENTS", "GRID POINT",
                    "APPLIED LOADS", "REACTIONS", "MPC FORCES",
                    "ELEMENT STRAINS",  # starts a strain section (still ok)
                )
                if any(kw in upper for kw in _SECTION_KEYWORDS):
                    in_stress_section = False
                    _pending.clear()
                    _pending_eid = -1
                # else: it's just an intra-section comment line — stay in section
            continue

        if not in_stress_section:
            continue

        # Strip trailing blanks; skip blank lines
        stripped = line.strip()
        if not stripped:
            continue

        # --- Try comma-separated (free-field) parse ---
        if "," in stripped:
            tokens = [t.strip() for t in stripped.split(",") if t.strip()]
            try:
                eid = int(tokens[0])
                floats = [float(t) for t in tokens[1:]]
            except (ValueError, IndexError):
                continue
            _store_element_stress(results, eid, floats)
            continue

        # --- Fixed-format (80-col) parse ---
        # NASTRAN punch records: first 8 cols = EID (or continuation marker),
        # then 8-char fields.
        try:
            col0 = stripped[:8].strip()
            # Continuation record: starts with '+' or '-' or is pure whitespace
            if col0.startswith("+") or col0.startswith("-"):
                # Continuation: append value fields to pending
                field_vals = _extract_fixed_fields(stripped, start_col=8)
                _pending.extend(field_vals)
                if _pending_eid >= 0 and len(_pending) >= 6:
                    _store_element_stress(results, _pending_eid, _pending[:6])
                    _pending.clear()
                    _pending_eid = -1
            else:
                # First record for this element
                eid = int(col0)
                field_vals = _extract_fixed_fields(stripped, start_col=8)
                if len(field_vals) >= 6:
                    _store_element_stress(results, eid, field_vals[:6])
                elif field_vals:
                    _pending_eid = eid
                    _pending = list(field_vals)
        except (ValueError, IndexError):
            continue

    return results


def _extract_fixed_fields(line: str, start_col: int = 8) -> list[float]:
    """
    Extract floating-point values from 8-character fixed-format fields
    starting at *start_col* (0-indexed).
    """
    vals: list[float] = []
    i = start_col
    while i + 8 <= len(line):
        field = line[i:i + 8].strip()
        if field:
            try:
                # NASTRAN uses 'D' as exponent separator in some versions
                vals.append(float(field.replace("D", "E").replace("d", "e")))
            except ValueError:
                pass
        i += 8
    return vals


def _store_element_stress(
    results: "dict[int, StressResult]",
    eid: int,
    floats: list[float],
) -> None:
    """
    Build a StressResult from a list of at least 1 float and insert into
    *results*.  Fills missing components with 0.0.  Computes von Mises and
    principal stresses.

    Expected order (6-component solid):
        [sigma_xx, sigma_yy, sigma_zz, tau_xy, tau_yz, tau_zx]
    Expected order (3-component 2-D shell / plane-stress):
        [sigma_xx, sigma_yy, tau_xy]  — sigma_zz = tau_yz = tau_zx = 0.

    When exactly 3 components are supplied the record is treated as a
    2-D shell centroid result (NASTRAN CQUAD4/CTRIA3 punch convention).
    """
    n = len(floats)
    sxx = floats[0] if n > 0 else 0.0
    syy = floats[1] if n > 1 else 0.0

    if n == 3:
        # 2-D shell: (sxx, syy, tau_xy) — sigma_zz and out-of-plane shears = 0
        szz = 0.0
        txy = floats[2]
        tyz = 0.0
        tzx = 0.0
    else:
        szz = floats[2] if n > 2 else 0.0
        txy = floats[3] if n > 3 else 0.0
        tyz = floats[4] if n > 4 else 0.0
        tzx = floats[5] if n > 5 else 0.0

    vm = _compute_von_mises(sxx, syy, szz, txy, tyz, tzx)
    p1, p2, p3 = _compute_principal_stresses(sxx, syy, szz, txy, tyz, tzx)

    results[eid] = StressResult(
        eid=eid,
        sigma_xx=sxx,
        sigma_yy=syy,
        sigma_zz=szz,
        tau_xy=txy,
        tau_yz=tyz,
        tau_zx=tzx,
        von_mises=vm,
        principal_1=p1,
        principal_2=p2,
        principal_3=p3,
    )


# ---------------------------------------------------------------------------
# Main bridge class
# ---------------------------------------------------------------------------


class MystranBridge:
    """
    Subprocess wrapper for MYSTRAN (open-source NASTRAN-compatible solver).

    Supported analysis types
    ------------------------
    "modal"         — SOL 103 real normal modes.  Result contains
                      ``frequencies`` [Hz] and ``eigenvalues`` [rad²/s²].
    "linear_static" — SOL 101 linear statics.  Result contains
                      ``displacements``, ``max_displacement``, and full
                      stress fields (``stresses``, ``max_vonmises_stress``)
                      recovered from PCH punch output when available;
                      gracefully falls back to empty stress list with a
                      warning when the PCH file is absent or unparseable.

    When MYSTRAN is not on PATH the bridge returns immediately with
    ``status="pending"`` and a descriptive warning so callers can degrade
    gracefully without raising.
    """

    def __init__(self, timeout: int = 600):
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def solve(
        self,
        mesh: dict,
        materials: dict,
        boundary_conditions: list[dict],
        *,
        analysis_type: str = "modal",
    ) -> MystranResult:
        """
        Run a MYSTRAN analysis.

        Parameters
        ----------
        mesh:
            Dict with:
            - ``nodes``: list of (x, y, z) tuples
            - ``elements``: list of (elem_id, elem_type, node_list) tuples
            - ``shell_thickness`` (optional): float [m], required for shell elements
        materials:
            Dict with keys ``E`` [Pa], ``nu``, ``rho`` [kg/m³].
        boundary_conditions:
            List of dicts.  Supported: ``{"type": "fixed", "node_ids": [...]}``.
        analysis_type:
            ``"modal"`` or ``"linear_static"``.

        Returns
        -------
        MystranResult
            Always returns (never raises).  Check ``.ok`` and ``.status``.
        """
        if not _mystran_available():
            return MystranResult(
                ok=False,
                analysis_type=analysis_type,
                status="pending",
                warnings=[ENGINE_PENDING_WARNING],
            )

        nodes: list[tuple[float, float, float]] = [
            tuple(n) for n in mesh.get("nodes", [])  # type: ignore[misc]
        ]
        elements: list[tuple[int, str, list[int]]] = [
            tuple(e) for e in mesh.get("elements", [])  # type: ignore[misc]
        ]
        shell_thickness: Optional[float] = mesh.get("shell_thickness")

        if analysis_type == "modal":
            return self._run_modal(
                nodes, elements, materials, boundary_conditions,
                shell_thickness=shell_thickness,
            )
        elif analysis_type == "linear_static":
            return self._run_static(
                nodes, elements, materials, boundary_conditions,
                loads=mesh.get("loads", []),
                shell_thickness=shell_thickness,
            )
        else:
            return MystranResult(
                ok=False,
                analysis_type=analysis_type,
                status="failed",
                errors=[f"Unsupported analysis_type: {analysis_type!r}"],
            )

    # ------------------------------------------------------------------
    # Internal runners
    # ------------------------------------------------------------------

    def _run_modal(
        self,
        nodes: list,
        elements: list,
        materials: dict,
        boundary_conditions: list[dict],
        *,
        shell_thickness: Optional[float] = None,
        num_modes: int = 10,
    ) -> MystranResult:
        deck = _write_bdf_modal(
            nodes, elements, materials, boundary_conditions,
            num_modes=num_modes,
            shell_thickness=shell_thickness,
        )
        try:
            f06_content = self._run_mystran(deck)
        except RuntimeError as exc:
            return MystranResult(
                ok=False,
                analysis_type="modal",
                status="failed",
                errors=[str(exc)],
            )

        evs, freqs = _parse_f06_eigenvalues(f06_content)
        return MystranResult(
            ok=True,
            analysis_type="modal",
            eigenvalues=evs,
            frequencies=freqs,
            warnings=[] if freqs else ["No eigenvalues found in F06 output"],
        )

    def _run_static(
        self,
        nodes: list,
        elements: list,
        materials: dict,
        boundary_conditions: list[dict],
        loads: list[dict],
        *,
        shell_thickness: Optional[float] = None,
    ) -> MystranResult:
        deck = _write_bdf_static(
            nodes, elements, materials, boundary_conditions, loads,
            shell_thickness=shell_thickness,
        )
        # Inject STRESS(PUNCH)=ALL so MYSTRAN writes a .pch file.
        deck = _emit_punch_request(deck)

        result_warnings: list[str] = []
        try:
            f06_content, pch_path = self._run_mystran_with_pch(deck)
        except RuntimeError as exc:
            return MystranResult(
                ok=False,
                analysis_type="linear_static",
                status="failed",
                errors=[str(exc)],
            )

        disps = _parse_f06_displacements(f06_content)
        max_disp = max(
            (math.sqrt(d["ux"] ** 2 + d["uy"] ** 2 + d["uz"] ** 2) for d in disps),
            default=0.0,
        )

        # --- PCH stress recovery ---
        stress_list: list[dict] = []
        max_vm: float = 0.0
        if pch_path is not None and pch_path.exists():
            try:
                stress_map = _parse_pch_stresses(pch_path)
                if stress_map:
                    stress_list = [sr.as_stress_dict() for sr in stress_map.values()]
                    max_vm = max(sr.von_mises for sr in stress_map.values())
                else:
                    result_warnings.append(
                        "PCH file found but contained no parseable stress records."
                    )
            except Exception as exc:  # pragma: no cover — defensive
                result_warnings.append(
                    f"PCH stress parse failed ({exc!s}); stress fields omitted."
                )
        else:
            result_warnings.append(
                "No PCH output file found; stress fields unavailable. "
                "Ensure MYSTRAN supports STRESS(PUNCH)=ALL for this model."
            )

        return MystranResult(
            ok=True,
            analysis_type="linear_static",
            displacements=disps,
            max_displacement=max_disp,
            stresses=stress_list,
            max_vonmises_stress=max_vm,
            warnings=result_warnings,
        )

    def _run_mystran(self, bdf_content: str) -> str:
        """
        Write the BDF deck to a temp dir, invoke ``mystran``, and return the
        F06 output as a string.  Raises RuntimeError on non-zero exit.

        This variant discards any PCH output.  For linear-static analyses
        that need stress recovery, use ``_run_mystran_with_pch`` instead.
        """
        f06_content, _ = self._run_mystran_with_pch(bdf_content)
        return f06_content

    def _run_mystran_with_pch(
        self, bdf_content: str
    ) -> "tuple[str, Optional[Path]]":
        """
        Write the BDF deck to a temp dir, invoke ``mystran``, and return
        ``(f06_content, pch_path)`` where *pch_path* is the Path to the punch
        file (or None when not produced).  Raises RuntimeError on non-zero
        exit or missing F06.

        The temporary directory is **not** cleaned up before the caller has
        read the PCH; this method uses a context-manager that copies the PCH
        into a sibling temp file so the caller can access it after the
        TemporaryDirectory is deleted.
        """
        import tempfile as _tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            bdf_path = tmpdir / "analysis.bdf"
            bdf_path.write_text(bdf_content)

            proc = subprocess.run(
                ["mystran", str(bdf_path)],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"MYSTRAN exited with code {proc.returncode}: "
                    f"{proc.stderr[:2000]}"
                )

            # MYSTRAN writes output as <basename>.F06 (uppercase or lowercase)
            f06_path = tmpdir / "analysis.F06"
            if not f06_path.exists():
                f06_path = tmpdir / "analysis.f06"
            if not f06_path.exists():
                raise RuntimeError(
                    "MYSTRAN did not produce an F06 output file. "
                    f"stdout: {proc.stdout[:500]}"
                )
            f06_content = f06_path.read_text(errors="replace")

            # Look for PCH output (case-insensitive: .PCH or .pch)
            pch_result: Optional[Path] = None
            for suffix in ("analysis.PCH", "analysis.pch"):
                candidate = tmpdir / suffix
                if candidate.exists():
                    # Copy to a named temp file that survives the TemporaryDirectory.
                    fd, tmp_pch = _tempfile.mkstemp(suffix=".pch")
                    import os
                    os.close(fd)
                    pch_result_path = Path(tmp_pch)
                    pch_result_path.write_bytes(candidate.read_bytes())
                    pch_result = pch_result_path
                    break

            return f06_content, pch_result
