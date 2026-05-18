"""
Homologation-style inspection report generator.

Given a list of :class:`~kerf_gdnt.feature_control_frame.FeatureControlFrame`
objects (each describing one geometric tolerance callout) together with nominal
and measured values, this module produces:

  - A list of :class:`InspectionRow` records (one per FCF measurement)
  - A text/Markdown inspection sheet via :func:`render_report`
  - A plain ``list[dict]`` for JSON export via :func:`report_to_dicts`

Pass/fail logic
---------------
A measurement *passes* when::

    abs(measured - nominal) <= tolerance_value / 2   (bilateral)

or, for unilateral tolerances (the default when ``unilateral=True``)::

    0 <= measured - nominal <= tolerance_value

Deviation is always reported as ``measured - nominal``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from kerf_gdnt.feature_control_frame import FeatureControlFrame


@dataclass
class InspectionRow:
    """
    One row in the inspection report — corresponds to a single FCF callout.

    Parameters
    ----------
    feature_id:
        A label identifying the measured feature, e.g. ``"F1"``, ``"bore_A"``.
    fcf:
        The tolerance specification.
    nominal:
        Nominal dimension (in drawing units).
    measured:
        Actual measured value from CMM / gauge.
    unilateral:
        If ``True``, the zone is ``[nominal, nominal + tolerance_value]``.
        If ``False`` (default), the zone is bilateral:
        ``[nominal - t/2, nominal + t/2]``.
    """
    feature_id: str
    fcf: FeatureControlFrame
    nominal: float
    measured: float
    unilateral: bool = False

    @property
    def deviation(self) -> float:
        """Signed deviation: ``measured − nominal``."""
        return self.measured - self.nominal

    @property
    def passed(self) -> bool:
        """True when the deviation is within the tolerance zone."""
        tol = self.fcf.tolerance_value
        dev = self.deviation
        if self.unilateral:
            return 0.0 <= dev <= tol
        else:
            return abs(dev) <= tol / 2.0

    @property
    def status(self) -> str:
        """``"PASS"`` or ``"FAIL"``."""
        return "PASS" if self.passed else "FAIL"

    def to_dict(self) -> dict:
        return {
            "feature_id": self.feature_id,
            "symbol_code": self.fcf.symbol_code,
            "symbol_name": self.fcf.symbol.name,
            "fcf_rendered": self.fcf.render(),
            "nominal": self.nominal,
            "measured": self.measured,
            "deviation": round(self.deviation, 6),
            "tolerance_value": self.fcf.tolerance_value,
            "unilateral": self.unilateral,
            "status": self.status,
            "note": self.fcf.note,
        }


@dataclass
class InspectionReport:
    """
    Complete homologation inspection report.

    Parameters
    ----------
    part_number:
        Drawing part number / identifier.
    revision:
        Drawing revision level, e.g. ``"C"``.
    inspector:
        Name or ID of the inspector.
    inspection_date:
        Date of inspection.
    rows:
        Ordered list of :class:`InspectionRow` records.
    """
    part_number: str
    revision: str = "A"
    inspector: str = ""
    inspection_date: Optional[date] = None
    rows: list[InspectionRow] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.rows if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.rows if not r.passed)

    @property
    def overall_pass(self) -> bool:
        """True when every row passes."""
        return all(r.passed for r in self.rows)


def render_report(report: InspectionReport, *, units: str = "mm") -> str:
    """
    Render the inspection report as a human-readable Markdown/text sheet.

    This is the homologation documentation output suitable for inclusion
    in a first-article inspection (FAI) package or quality dossier.
    """
    idate = report.inspection_date or date.today()
    lines: list[str] = [
        "# GD&T Inspection Report",
        "",
        f"| Part number | {report.part_number} |",
        f"|-------------|------|",
        f"| Revision    | {report.revision} |",
        f"| Inspector   | {report.inspector or '—'} |",
        f"| Date        | {idate.isoformat()} |",
        f"| Units       | {units} |",
        "",
        "## Results",
        "",
        f"| Feature | FCF | Nominal ({units}) | Measured ({units}) "
        f"| Deviation ({units}) | Tolerance ({units}) | Status |",
        "|---------|-----|---------|---------|-----------|-----------|--------|",
    ]

    for row in report.rows:
        fcf_text = row.fcf.render()
        lines.append(
            f"| {row.feature_id} "
            f"| `{fcf_text}` "
            f"| {row.nominal:.4g} "
            f"| {row.measured:.4g} "
            f"| {row.deviation:+.4g} "
            f"| {row.fcf.tolerance_value:.4g} "
            f"| **{row.status}** |"
        )

    overall = "PASS" if report.overall_pass else "FAIL"
    lines += [
        "",
        "## Summary",
        "",
        f"- Total features: {report.total}",
        f"- Passed: {report.passed_count}",
        f"- Failed: {report.failed_count}",
        f"- **Overall: {overall}**",
    ]

    if report.failed_count:
        lines += ["", "### Failed features", ""]
        for row in report.rows:
            if not row.passed:
                lines.append(
                    f"- **{row.feature_id}** ({row.fcf.symbol.name}): "
                    f"deviation {row.deviation:+.4g} {units} "
                    f"(tolerance ±{row.fcf.tolerance_value / 2:.4g} {units})"
                )

    return "\n".join(lines)


def report_to_dicts(report: InspectionReport) -> list[dict]:
    """Serialise all rows to a plain list of dicts for JSON export."""
    return [r.to_dict() for r in report.rows]


def build_report(
    part_number: str,
    measurements: list[dict],
    *,
    revision: str = "A",
    inspector: str = "",
    inspection_date: Optional[date] = None,
) -> InspectionReport:
    """
    Convenience factory: build an :class:`InspectionReport` from a list of
    measurement dicts.

    Each ``dict`` in *measurements* must have keys:

    - ``feature_id``  (str)
    - ``fcf``         (:class:`~kerf_gdnt.feature_control_frame.FeatureControlFrame`)
    - ``nominal``     (float)
    - ``measured``    (float)
    - ``unilateral``  (bool, optional, default ``False``)
    """
    rows: list[InspectionRow] = []
    for m in measurements:
        rows.append(InspectionRow(
            feature_id=m["feature_id"],
            fcf=m["fcf"],
            nominal=float(m["nominal"]),
            measured=float(m["measured"]),
            unilateral=bool(m.get("unilateral", False)),
        ))
    return InspectionReport(
        part_number=part_number,
        revision=revision,
        inspector=inspector,
        inspection_date=inspection_date,
        rows=rows,
    )
