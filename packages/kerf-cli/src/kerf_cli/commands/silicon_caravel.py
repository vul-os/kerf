"""silicon_caravel.py — ``kerf silicon caravel {validate,package}`` sub-commands.

Usage
-----
    kerf silicon caravel validate  <design-dir>  [--info INFO_JSON]
    kerf silicon caravel package   <design-dir>  [--info INFO_JSON]
                                                  [--clock-period NS]
                                                  [--output OUTPUT_DIR]

``--info`` accepts a JSON file or inline JSON string with the project metadata
structure expected by :func:`kerf_silicon.caravel.package_for_caravel`.

Minimal info JSON example::

    {
        "project": {
            "title": "My counter",
            "author": "Alice",
            "description": "8-bit counter",
            "top_module": "user_counter",
            "language": "Verilog"
        }
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_project_info(info_arg: str) -> dict:
    """Load project info from a JSON file path or inline JSON string."""
    path = Path(info_arg)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        return json.loads(info_arg)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"--info must be a path to a JSON file or valid inline JSON. "
            f"Got: {info_arg!r}\nJSON error: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# validate sub-command
# ---------------------------------------------------------------------------


def cmd_caravel_validate(args: argparse.Namespace) -> int:
    from kerf_silicon.caravel.validate import validate, ValidationError  # noqa: PLC0415

    try:
        project_info = _load_project_info(args.info) if args.info else {}
        validate(args.design_dir, project_info)
        print(f"OK: {args.design_dir} passes all Caravel validation checks.")
        return 0
    except ValidationError as exc:
        print(f"Validation failed:\n{exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


# ---------------------------------------------------------------------------
# package sub-command
# ---------------------------------------------------------------------------


def cmd_caravel_package(args: argparse.Namespace) -> int:
    from kerf_silicon.caravel import package_for_caravel, ValidationError  # noqa: PLC0415

    try:
        project_info = _load_project_info(args.info) if args.info else {}
        out_dir = package_for_caravel(
            args.design_dir,
            project_info,
            clock_period_ns=args.clock_period,
        )
        print(f"Packaged → {out_dir}")
        return 0
    except ValidationError as exc:
        print(f"Packaging failed (validation):\n{exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


# ---------------------------------------------------------------------------
# Argument parser helpers — called from main.py
# ---------------------------------------------------------------------------


def add_caravel_parser(
    sub: "argparse._SubParsersAction",  # type: ignore[type-arg]
) -> None:
    """Register the ``silicon caravel`` sub-parser onto *sub*."""
    caravel_p = sub.add_parser(
        "caravel",
        help="Efabless Caravel harness wrapping (validate / package)",
        description=(
            "Wrap a Kerf silicon project into the Efabless Caravel\n"
            "user_project_wrapper.v shape for MPW submission.\n\n"
            "Sub-commands:\n"
            "  validate  — run pre-packaging checks (port signature, CDC)\n"
            "  package   — validate + emit the full submission bundle\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    caravel_sub = caravel_p.add_subparsers(
        dest="caravel_command", metavar="<command>"
    )
    caravel_sub.required = True

    # ---- validate ----
    val_p = caravel_sub.add_parser(
        "validate",
        help="Run Caravel validation checks on a design directory",
    )
    val_p.add_argument("design_dir", metavar="design-dir")
    val_p.add_argument(
        "--info",
        default="",
        metavar="JSON",
        help="Project metadata as a JSON file path or inline JSON string.",
    )
    val_p.set_defaults(func=cmd_caravel_validate)

    # ---- package ----
    pkg_p = caravel_sub.add_parser(
        "package",
        help="Package a design for Caravel MPW submission",
    )
    pkg_p.add_argument("design_dir", metavar="design-dir")
    pkg_p.add_argument(
        "--info",
        default="",
        metavar="JSON",
        help="Project metadata as a JSON file path or inline JSON string.",
    )
    pkg_p.add_argument(
        "--clock-period",
        type=float,
        default=10.0,
        metavar="NS",
        help="Target clock period in nanoseconds (default: 10 = 100 MHz).",
    )
    pkg_p.set_defaults(func=cmd_caravel_package)
