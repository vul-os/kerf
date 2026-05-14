#!/usr/bin/env python3
"""
generate_freecad_fixtures.py — Generate .FCStd test fixtures for the FreeCAD import suite.

Usage (requires FreeCAD's Python environment with `import FreeCAD`):
    freecadcmd scripts/generate_freecad_fixtures.py

Or from within a FreeCAD Python console:
    exec(open("scripts/generate_freecad_fixtures.py").read())

Output: packages/kerf-imports/tests/freecad/fixtures/*.FCStd

If freecadcmd is unavailable, run:
    python scripts/generate_freecad_fixtures.py --minimal

The --minimal flag uses pure-Python zipfile to generate minimal valid .FCStd
archives without actual BRep geometry.  These are used for unit tests that
don't require BRep round-trips.

The pre-built fixtures committed to the repo were generated with --minimal
(because freecadcmd is not available in the CI image).  When you have a full
FreeCAD installation you can regenerate richer fixtures with:
    freecadcmd scripts/generate_freecad_fixtures.py
and commit the resulting files.
"""
from __future__ import annotations

import argparse
import io
import math
import os
import sys
import zipfile
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent.parent / "packages/kerf-imports/tests/freecad/fixtures"


# ---------------------------------------------------------------------------
# Minimal-fixture builders (no FreeCAD install required)
# ---------------------------------------------------------------------------

def _make_fcstd(doc_xml: str, extra_files: dict[str, bytes] | None = None) -> bytes:
    """Build a minimal .FCStd zip from Document.xml content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Document.xml", doc_xml)
        if extra_files:
            for name, data in extra_files.items():
                zf.writestr(name, data)
    return buf.getvalue()


def _minimal_doc_xml(
    schema_version: int = 4,
    program_version: str = "0.21R3",
    objects: list[tuple[str, str, str]] | None = None,  # (name, type, label)
    object_data: str = "",
) -> str:
    """
    Build a minimal Document.xml string.

    Parameters
    ----------
    objects : list of (name, type, label) tuples for the <Objects> block.
    object_data : raw XML to inject inside <ObjectData>.
    """
    if objects is None:
        objects = []

    obj_list = "\n".join(
        f'    <Object type="{t}" name="{n}" label="{lbl}"/>'
        for n, t, lbl in objects
    )
    count = len(objects)

    obj_data_count = object_data.count("<Object name=")

    return f"""<?xml version="1.0" encoding="utf-8"?>
<Document SchemaVersion="{schema_version}" ProgramVersion="{program_version}">
  <Objects Count="{count}">
{obj_list}
  </Objects>
  <ObjectData Count="{obj_data_count}">
{object_data}
  </ObjectData>
</Document>"""


def build_single_pad() -> bytes:
    """single_pad.FCStd — one Body, one Sketch (rectangle), one Pad."""
    sketch_xml = """
    <Object name="Sketch">
      <Properties Count="2">
        <Property name="Geometry" type="Part::PropertyGeometryList">
          <GeometryList count="4">
            <Geometry type="Part::GeomLineSegment">
              <Start x="0" y="0" z="0"/>
              <End x="10" y="0" z="0"/>
            </Geometry>
            <Geometry type="Part::GeomLineSegment">
              <Start x="10" y="0" z="0"/>
              <End x="10" y="10" z="0"/>
            </Geometry>
            <Geometry type="Part::GeomLineSegment">
              <Start x="10" y="10" z="0"/>
              <End x="0" y="10" z="0"/>
            </Geometry>
            <Geometry type="Part::GeomLineSegment">
              <Start x="0" y="10" z="0"/>
              <End x="0" y="0" z="0"/>
            </Geometry>
          </GeometryList>
        </Property>
        <Property name="Constraints" type="Sketcher::PropertyConstraintList">
          <ConstraintList count="4">
            <Constrain Name="Horizontal0" Type="2" First="0" FirstPos="0" Second="-1"/>
            <Constrain Name="Vertical0" Type="3" First="1" FirstPos="0" Second="-1"/>
            <Constrain Name="Horizontal1" Type="2" First="2" FirstPos="0" Second="-1"/>
            <Constrain Name="Vertical1" Type="3" First="3" FirstPos="0" Second="-1"/>
          </ConstraintList>
        </Property>
      </Properties>
    </Object>
    <Object name="Pad">
      <Properties Count="2">
        <Property name="Profile" type="App::PropertyLink">
          <Link value="Sketch"/>
        </Property>
        <Property name="Length" type="App::PropertyLength">
          <Quantity v="10" unit="mm"/>
        </Property>
      </Properties>
    </Object>
    <Object name="Body">
      <Properties Count="2">
        <Property name="Tip" type="App::PropertyLink">
          <Link value="Pad"/>
        </Property>
        <Property name="Model" type="App::PropertyLinkList">
          <LinkList count="2">
            <Link value="Sketch"/>
            <Link value="Pad"/>
          </LinkList>
        </Property>
      </Properties>
    </Object>"""

    objects = [
        ("Body",   "PartDesign::Body",        "Body"),
        ("Sketch", "Sketcher::SketchObject",   "Sketch"),
        ("Pad",    "PartDesign::Pad",          "Pad"),
    ]
    xml = _minimal_doc_xml(objects=objects, object_data=sketch_xml)
    return _make_fcstd(xml)


def build_pad_and_pocket() -> bytes:
    """pad_and_pocket.FCStd — Pad then Pocket on top face."""
    object_data = """
    <Object name="Sketch">
      <Properties Count="2">
        <Property name="Geometry" type="Part::PropertyGeometryList">
          <GeometryList count="2">
            <Geometry type="Part::GeomLineSegment">
              <Start x="0" y="0" z="0"/>
              <End x="20" y="0" z="0"/>
            </Geometry>
            <Geometry type="Part::GeomLineSegment">
              <Start x="0" y="0" z="0"/>
              <End x="0" y="20" z="0"/>
            </Geometry>
          </GeometryList>
        </Property>
        <Property name="Constraints" type="Sketcher::PropertyConstraintList">
          <ConstraintList count="0"/>
        </Property>
      </Properties>
    </Object>
    <Object name="SketchPocket">
      <Properties Count="2">
        <Property name="Geometry" type="Part::PropertyGeometryList">
          <GeometryList count="1">
            <Geometry type="Part::GeomCircle">
              <Center x="5" y="5" z="0"/>
              <Radius v="3" unit="mm"/>
            </Geometry>
          </GeometryList>
        </Property>
        <Property name="Constraints" type="Sketcher::PropertyConstraintList">
          <ConstraintList count="0"/>
        </Property>
      </Properties>
    </Object>
    <Object name="Pad">
      <Properties Count="2">
        <Property name="Profile" type="App::PropertyLink">
          <Link value="Sketch"/>
        </Property>
        <Property name="Length" type="App::PropertyLength">
          <Quantity v="15" unit="mm"/>
        </Property>
      </Properties>
    </Object>
    <Object name="Pocket">
      <Properties Count="2">
        <Property name="Profile" type="App::PropertyLink">
          <Link value="SketchPocket"/>
        </Property>
        <Property name="Length" type="App::PropertyLength">
          <Quantity v="5" unit="mm"/>
        </Property>
      </Properties>
    </Object>
    <Object name="Body">
      <Properties Count="2">
        <Property name="Tip" type="App::PropertyLink">
          <Link value="Pocket"/>
        </Property>
        <Property name="Model" type="App::PropertyLinkList">
          <LinkList count="4">
            <Link value="Sketch"/>
            <Link value="SketchPocket"/>
            <Link value="Pad"/>
            <Link value="Pocket"/>
          </LinkList>
        </Property>
      </Properties>
    </Object>"""

    objects = [
        ("Body",        "PartDesign::Body",        "Body"),
        ("Sketch",      "Sketcher::SketchObject",   "Sketch"),
        ("SketchPocket","Sketcher::SketchObject",   "SketchPocket"),
        ("Pad",         "PartDesign::Pad",          "Pad"),
        ("Pocket",      "PartDesign::Pocket",       "Pocket"),
    ]
    xml = _minimal_doc_xml(objects=objects, object_data=object_data)
    return _make_fcstd(xml)


def build_two_bodies() -> bytes:
    """two_bodies.FCStd — two separate Bodies in one doc."""
    object_data = """
    <Object name="Body">
      <Properties Count="1">
        <Property name="Placement" type="App::PropertyPlacement">
          <Placement Px="0" Py="0" Pz="0" Q0="1" Q1="0" Q2="0" Q3="0"/>
        </Property>
      </Properties>
    </Object>
    <Object name="Body001">
      <Properties Count="1">
        <Property name="Placement" type="App::PropertyPlacement">
          <Placement Px="50" Py="0" Pz="0" Q0="1" Q1="0" Q2="0" Q3="0"/>
        </Property>
      </Properties>
    </Object>"""

    objects = [
        ("Body",    "PartDesign::Body", "Body"),
        ("Body001", "PartDesign::Body", "Body001"),
    ]
    xml = _minimal_doc_xml(objects=objects, object_data=object_data)
    return _make_fcstd(xml)


def build_sketch_constraints() -> bytes:
    """sketch_constraints.FCStd — sketch using Coincident, Distance, Angle, Tangent."""
    object_data = """
    <Object name="Sketch">
      <Properties Count="2">
        <Property name="Geometry" type="Part::PropertyGeometryList">
          <GeometryList count="3">
            <Geometry type="Part::GeomLineSegment">
              <Start x="0" y="0" z="0"/>
              <End x="20" y="0" z="0"/>
            </Geometry>
            <Geometry type="Part::GeomLineSegment">
              <Start x="20" y="0" z="0"/>
              <End x="20" y="15" z="0"/>
            </Geometry>
            <Geometry type="Part::GeomArcOfCircle">
              <Center x="10" y="7.5" z="0"/>
              <Radius v="5" unit="mm"/>
              <StartAngle v="0" unit="rad"/>
              <EndAngle v="3.14159" unit="rad"/>
            </Geometry>
          </GeometryList>
        </Property>
        <Property name="Constraints" type="Sketcher::PropertyConstraintList">
          <ConstraintList count="5">
            <Constrain Name="Coincident0" Type="1" First="0" FirstPos="2" Second="1" SecondPos="1"/>
            <Constrain Name="Distance0" Type="6" First="0" FirstPos="1" Second="0" SecondPos="2" Value="20"/>
            <Constrain Name="Angle0" Type="9" First="0" FirstPos="0" Second="1" SecondPos="0" Value="1.5707963"/>
            <Constrain Name="Tangent0" Type="5" First="1" FirstPos="2" Second="2" SecondPos="1"/>
            <Constrain Name="Radius0" Type="11" First="2" FirstPos="0" Value="5"/>
          </ConstraintList>
        </Property>
      </Properties>
    </Object>
    <Object name="Body">
      <Properties Count="0"/>
    </Object>"""

    objects = [
        ("Body",   "PartDesign::Body",       "Body"),
        ("Sketch", "Sketcher::SketchObject",  "Sketch"),
    ]
    xml = _minimal_doc_xml(objects=objects, object_data=object_data)
    return _make_fcstd(xml)


def build_unsupported_constraints() -> bytes:
    """unsupported_constraints.FCStd — sketch with SnellsLaw + Weight constraints (drop-with-warning)."""
    object_data = """
    <Object name="Sketch">
      <Properties Count="2">
        <Property name="Geometry" type="Part::PropertyGeometryList">
          <GeometryList count="2">
            <Geometry type="Part::GeomLineSegment">
              <Start x="0" y="0" z="0"/>
              <End x="10" y="0" z="0"/>
            </Geometry>
            <Geometry type="Part::GeomBSplineCurve"/>
          </GeometryList>
        </Property>
        <Property name="Constraints" type="Sketcher::PropertyConstraintList">
          <ConstraintList count="3">
            <Constrain Name="SnellsLaw0" Type="16" First="0" FirstPos="2" Second="1" SecondPos="1"/>
            <Constrain Name="Weight0" Type="19" First="1" FirstPos="0" Value="1.0"/>
            <Constrain Name="InternalAlignment0" Type="15" First="1" FirstPos="0"/>
          </ConstraintList>
        </Property>
      </Properties>
    </Object>
    <Object name="Body">
      <Properties Count="0"/>
    </Object>"""

    objects = [
        ("Body",   "PartDesign::Body",       "Body"),
        ("Sketch", "Sketcher::SketchObject",  "Sketch"),
    ]
    xml = _minimal_doc_xml(objects=objects, object_data=object_data)
    return _make_fcstd(xml)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

FIXTURES = {
    "single_pad.FCStd":             build_single_pad,
    "pad_and_pocket.FCStd":         build_pad_and_pocket,
    "two_bodies.FCStd":             build_two_bodies,
    "sketch_constraints.FCStd":     build_sketch_constraints,
    "unsupported_constraints.FCStd": build_unsupported_constraints,
}


def main():
    parser = argparse.ArgumentParser(description="Generate FreeCAD test fixtures")
    parser.add_argument(
        "--minimal", action="store_true",
        help="Use pure-Python builder (no freecadcmd required). Always true when freecadcmd absent.",
    )
    parser.add_argument(
        "--output-dir", default=str(FIXTURE_DIR),
        help="Output directory for .FCStd files.",
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # If freecadcmd is available and --minimal is not set, we'd call FreeCAD
    # here.  For now (and for CI), always use the minimal builder.
    # TODO: add the freecadcmd path when a FreeCAD install is available.

    generated = []
    for filename, builder in FIXTURES.items():
        path = out_dir / filename
        data = builder()
        path.write_bytes(data)
        generated.append(path)
        print(f"  wrote {path} ({len(data)} bytes)")

    print(f"\nGenerated {len(generated)} fixtures in {out_dir}")


if __name__ == "__main__":
    main()
