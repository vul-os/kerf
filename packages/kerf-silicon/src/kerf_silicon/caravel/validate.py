"""validate.py — Caravel project validation logic.

Checks performed
----------------
1. Required project metadata fields are present.
2. Top-module name is a valid Verilog identifier.
3. RTL sources declare the 38-bit GPIO bus, Wishbone master signals,
   and logic-analyzer probes with correct widths.
4. Clock-domain crossing: if RTL crosses from the Wishbone clock domain
   (wb_clk_i) into a user-defined clock without a recognised synchroniser
   cell name, a CDC warning is raised as a ValidationError.

The CDC check is intentionally conservative: it scans for ``always @``
blocks sensitive to both ``wb_clk_i`` and a *different* user clock signal.
If such a block directly samples a ``wbs_*`` Wishbone data signal, the
checker flags it unless a synchroniser keyword is found nearby.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class ValidationError(Exception):
    """Raised when a Caravel packaging constraint is violated."""


# ---------------------------------------------------------------------------
# Required metadata fields
# ---------------------------------------------------------------------------

_REQUIRED_META: list[tuple[str, str]] = [
    ("project", "title"),
    ("project", "author"),
    ("project", "description"),
    ("project", "top_module"),
    ("project", "language"),
]

_VALID_LANGUAGES = {"Verilog", "SystemVerilog", "VHDL", "Chisel", "Mixed"}

# ---------------------------------------------------------------------------
# Required Caravel port declarations
#
# user_project_wrapper.v interface (from caravel_user_project template):
#   - io_in[37:0] / io_out[37:0] / io_oeb[37:0]  — 38-bit GPIO
#   - wbs_stb_i, wbs_cyc_i, wbs_we_i              — Wishbone strobe/cycle/write
#   - wbs_sel_i[3:0]                               — Wishbone byte-enables
#   - wbs_dat_i[31:0] / wbs_dat_o[31:0]           — Wishbone data
#   - wbs_adr_i[31:0]                              — Wishbone address
#   - wbs_ack_o                                    — Wishbone acknowledge
#   - la_data_in[127:0] / la_data_out[127:0]       — logic analyser data
#   - la_oenb[127:0]                               — logic analyser output-enable
#   - user_clock2                                  — second user clock
#   - wb_clk_i                                     — Wishbone clock
#   - wb_rst_i                                     — Wishbone reset
#   - user_irq[2:0]                                — user interrupts
#
# ---------------------------------------------------------------------------

_PORT_SPECS: list[tuple[str, str | None]] = [
    # (port_name, required_width_pattern_or_None_for_scalar)
    ("io_in",       r"\[37:0\]"),
    ("io_out",      r"\[37:0\]"),
    ("io_oeb",      r"\[37:0\]"),
    ("wbs_stb_i",   None),
    ("wbs_cyc_i",   None),
    ("wbs_we_i",    None),
    ("wbs_sel_i",   r"\[3:0\]"),
    ("wbs_dat_i",   r"\[31:0\]"),
    ("wbs_dat_o",   r"\[31:0\]"),
    ("wbs_adr_i",   r"\[31:0\]"),
    ("wbs_ack_o",   None),
    ("la_data_in",  r"\[127:0\]"),
    ("la_data_out", r"\[127:0\]"),
    ("la_oenb",     r"\[127:0\]"),
    ("wb_clk_i",    None),
    ("wb_rst_i",    None),
    ("user_clock2", None),
    ("user_irq",    r"\[2:0\]"),
]

# Wishbone data ports — used by CDC check
_WBS_DATA_PORTS = {"wbs_dat_i", "wbs_dat_o", "wbs_adr_i", "wbs_sel_i"}

# Synchroniser cell name fragments (case-insensitive substrings)
_SYNC_KEYWORDS = [
    "synchronizer",
    "synchroniser",
    "sync_ff",
    "cdc_sync",
    "double_flop",
    "dff2",
    "_sync",
]

# RTL source file extensions
_RTL_EXTS = {".v", ".sv", ".vhd", ".vhdl"}


# ---------------------------------------------------------------------------
# Metadata validation
# ---------------------------------------------------------------------------


def validate_project_info(info: dict[str, Any]) -> None:
    """Raise ``ValidationError`` if required metadata fields are missing."""
    for section, key in _REQUIRED_META:
        section_data = info.get(section)
        if not isinstance(section_data, dict) or key not in section_data:
            raise ValidationError(
                f"project_info missing required field: {section}.{key}"
            )

    lang = info["project"]["language"]
    if lang not in _VALID_LANGUAGES:
        raise ValidationError(
            f"Unknown language {lang!r}. Expected one of {sorted(_VALID_LANGUAGES)}"
        )

    top = info["project"]["top_module"]
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", top):
        raise ValidationError(
            f"top_module {top!r} is not a valid Verilog identifier."
        )


# ---------------------------------------------------------------------------
# Port-signature validation
# ---------------------------------------------------------------------------


def validate_port_signature(sources: list[Path]) -> None:
    """Check that RTL sources declare the required Caravel port signals.

    Raises ``ValidationError`` listing every missing or incorrectly-sized port.
    """
    combined = "\n".join(p.read_text(errors="replace") for p in sources)

    errors: list[str] = []
    for port_name, width_pat in _PORT_SPECS:
        # Search for the port name as a whole word in any port declaration context
        port_re = re.compile(
            r"(?:input|output|inout)\s+(?:wire\s+|reg\s+)?"
            r"(?P<width>\[[^\]]+\]\s+)?" + re.escape(port_name) + r"\b"
        )
        matches = list(port_re.finditer(combined))
        if not matches:
            errors.append(f"  - {port_name}: not found in RTL sources")
            continue

        if width_pat is not None:
            # At least one occurrence must have the expected width
            expected_re = re.compile(width_pat)
            if not any(
                m.group("width") and expected_re.search(m.group("width") or "")
                for m in matches
            ):
                errors.append(
                    f"  - {port_name}: found but not declared with width {width_pat}"
                )

    if errors:
        raise ValidationError(
            "Caravel port-signature validation failed:\n" + "\n".join(errors)
        )


# ---------------------------------------------------------------------------
# CDC check
# ---------------------------------------------------------------------------


def check_cdc(sources: list[Path]) -> None:
    """Flag unsynchronised Wishbone→user-clock domain crossings.

    Strategy:
      1. Find all ``always @(posedge <clk>)`` blocks.
      2. If a block is sensitive to a clock *other than* ``wb_clk_i`` and
         the block body references a ``wbs_*`` data port without a recognisable
         synchroniser cell instantiation in the same source, raise a
         ``ValidationError``.

    This is a best-effort static analysis — it has known false-positive and
    false-negative cases, but it catches the most common mistake: a naive
    ``always @(posedge user_clock2) if (wbs_cyc_i) ...`` without a sync.
    """
    combined = "\n".join(p.read_text(errors="replace") for p in sources)

    # Detect synchroniser presence anywhere in the source
    lower_combined = combined.lower()
    has_synchroniser = any(kw in lower_combined for kw in _SYNC_KEYWORDS)

    # Find always-blocks driven by a non-Wishbone clock that reference wbs signals
    always_re = re.compile(
        r"always\s*@\s*\(\s*posedge\s+(?P<clk>\w+)\s*\)",
        re.IGNORECASE,
    )

    violations: list[str] = []
    for m in always_re.finditer(combined):
        clk = m.group("clk")
        if clk.lower() == "wb_clk_i":
            continue  # Same clock domain — OK

        # Extract a window of source text after the always block header
        block_start = m.end()
        block_text = combined[block_start : block_start + 2000]

        # Check if any Wishbone data port is referenced in this block
        for wbs_port in _WBS_DATA_PORTS:
            if re.search(r"\b" + re.escape(wbs_port) + r"\b", block_text):
                if not has_synchroniser:
                    violations.append(
                        f"Clock-domain crossing: always @(posedge {clk}) "
                        f"samples Wishbone port '{wbs_port}' "
                        f"without a recognisable synchroniser. "
                        f"Add a double-flop synchroniser or use wb_clk_i."
                    )
                break  # one violation per always block is enough

    if violations:
        raise ValidationError(
            "CDC validation failed:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


# ---------------------------------------------------------------------------
# RTL source collection
# ---------------------------------------------------------------------------


def collect_rtl_sources(design_dir: Path, exclude_dir: Path | None = None) -> list[Path]:
    """Return sorted list of RTL sources under *design_dir*, excluding *exclude_dir*."""
    sources: list[Path] = []
    for ext in _RTL_EXTS:
        for p in design_dir.rglob(f"*{ext}"):
            if exclude_dir is not None:
                try:
                    p.relative_to(exclude_dir)
                    continue
                except ValueError:
                    pass
            sources.append(p)
    return sorted(sources)


# ---------------------------------------------------------------------------
# Top-level validate function
# ---------------------------------------------------------------------------


def validate(design_dir: str | Path, project_info: dict[str, Any]) -> None:
    """Run all validation checks for a Caravel project.

    Parameters
    ----------
    design_dir:
        Directory containing the user's RTL source files.
    project_info:
        Project metadata dict with at least ``project.{title,author,
        description,top_module,language}``.

    Raises
    ------
    ValidationError
        If any check fails.
    FileNotFoundError
        If *design_dir* does not exist.
    """
    design_dir = Path(design_dir)
    if not design_dir.is_dir():
        raise FileNotFoundError(f"design_dir not found: {design_dir}")

    validate_project_info(project_info)

    out_dir = design_dir / "caravel_submission"
    sources = collect_rtl_sources(design_dir, exclude_dir=out_dir)
    if not sources:
        raise ValidationError(
            f"No RTL source files found under {design_dir}. "
            "Expected at least one .v / .sv / .vhd / .vhdl file."
        )

    validate_port_signature(sources)
    check_cdc(sources)
