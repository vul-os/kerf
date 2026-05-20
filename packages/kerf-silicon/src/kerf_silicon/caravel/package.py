"""package.py — Main entry point for Caravel submission packaging.

Entry point
-----------
    package_for_caravel(design_dir, project_info) -> pathlib.Path

On success writes a ``caravel_submission/`` directory inside *design_dir*
that mirrors the caravel_user_project template layout:

    caravel_submission/
        openlane/
            user_project_wrapper/
                config.tcl           ← OpenLane configuration
                pin_order.cfg        ← pin placement order
        verilog/
            rtl/
                user_project_wrapper.v   ← generated wrapper
                <user sources>           ← copied from design_dir
        PACKAGE_SUMMARY.txt

Reference layout: github.com/efabless/caravel_user_project
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .validate import (
    ValidationError,
    collect_rtl_sources,
    validate,
)
from .wrapper import generate_wrapper
from .pin_order import generate_pin_order
from .config_tcl import generate_config_tcl

__all__ = ["package_for_caravel", "ValidationError"]


def package_for_caravel(
    design_dir: str | Path,
    project_info: dict[str, Any],
    *,
    clock_period_ns: float = 10.0,
    extra_openlane_config: dict[str, Any] | None = None,
) -> Path:
    """Package *design_dir* for an Efabless Caravel MPW submission.

    Parameters
    ----------
    design_dir:
        Directory containing the user's RTL source files.
    project_info:
        Project metadata dict.  Must contain at least::

            {
                "project": {
                    "title":       str,
                    "author":      str,
                    "description": str,
                    "top_module":  str,   # Verilog identifier for user module
                    "language":    str,   # "Verilog" | "SystemVerilog" | …
                },
            }

    clock_period_ns:
        Target clock period passed into ``openlane_config.tcl``
        (default: 10 ns → 100 MHz).
    extra_openlane_config:
        Additional ``set ::env(KEY) value`` entries for ``config.tcl``.

    Returns
    -------
    pathlib.Path
        Path to the ``caravel_submission/`` directory written inside
        *design_dir*.

    Raises
    ------
    ValidationError
        For any constraint violation.
    FileNotFoundError
        If *design_dir* does not exist.
    """
    design_dir = Path(design_dir)

    # Validation (raises ValidationError / FileNotFoundError on problems)
    validate(design_dir, project_info)

    top_module: str = project_info["project"]["top_module"]

    # ------------------------------------------------------------------ #
    # Build output tree
    # ------------------------------------------------------------------ #
    out_dir = design_dir / "caravel_submission"
    if out_dir.exists():
        shutil.rmtree(out_dir)

    openlane_dir = out_dir / "openlane" / "user_project_wrapper"
    rtl_dir = out_dir / "verilog" / "rtl"

    openlane_dir.mkdir(parents=True)
    rtl_dir.mkdir(parents=True)

    # ------------------------------------------------------------------ #
    # OpenLane config.tcl
    # ------------------------------------------------------------------ #
    config_text = generate_config_tcl(
        top_module,
        clock_period_ns=clock_period_ns,
        extra_config=extra_openlane_config,
    )
    (openlane_dir / "config.tcl").write_text(config_text, encoding="utf-8")

    # ------------------------------------------------------------------ #
    # pin_order.cfg
    # ------------------------------------------------------------------ #
    pin_order_text = generate_pin_order()
    (openlane_dir / "pin_order.cfg").write_text(pin_order_text, encoding="utf-8")

    # ------------------------------------------------------------------ #
    # user_project_wrapper.v
    # ------------------------------------------------------------------ #
    wrapper_text = generate_wrapper(top_module)
    (rtl_dir / "user_project_wrapper.v").write_text(wrapper_text, encoding="utf-8")

    # ------------------------------------------------------------------ #
    # Copy user RTL sources into verilog/rtl/
    # ------------------------------------------------------------------ #
    rtl_sources = collect_rtl_sources(design_dir, exclude_dir=out_dir)
    for src in rtl_sources:
        try:
            rel = src.relative_to(design_dir)
        except ValueError:
            rel = Path(src.name)
        dest = rtl_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    # ------------------------------------------------------------------ #
    # PACKAGE_SUMMARY.txt
    # ------------------------------------------------------------------ #
    summary_lines = [
        f"packager     : kerf-silicon Caravel",
        f"top_module   : {top_module}",
        f"clock_period : {clock_period_ns} ns  ({1000 / clock_period_ns:.1f} MHz)",
        f"die_area     : 1000 x 1000 µm  (1 mm²)",
        f"rtl_sources  : {len(rtl_sources)} file(s)",
        "",
        "Layout:",
        f"  {out_dir / 'openlane' / 'user_project_wrapper' / 'config.tcl'}",
        f"  {out_dir / 'openlane' / 'user_project_wrapper' / 'pin_order.cfg'}",
        f"  {out_dir / 'verilog' / 'rtl' / 'user_project_wrapper.v'}",
    ]
    (out_dir / "PACKAGE_SUMMARY.txt").write_text(
        "\n".join(summary_lines) + "\n", encoding="utf-8"
    )

    return out_dir
