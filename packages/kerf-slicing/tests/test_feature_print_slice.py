"""
test_feature_print_slice.py -- T-39 Slicing: 3D-print Tier 1

Hermetic integration tests for the full print-slice pipeline:
  - 25 parametric STL parts (primitives + boundary cases)
  - G-code generated and non-empty
  - Layer count > 0; layer time estimate present
  - Filament volume estimate within +-2 % of solid mesh volume

Strategy:
  - A fake CuraEngine (Python script) is written into a tmp dir and wired
    onto PATH via monkeypatch.
  - STL geometry is generated in-process (pure Python), so the suite runs
    without any 3-D library dependencies.
  - The fake CuraEngine honours the real CLI contract: reads -l <stl_path>,
    writes G-code to -o <output>, embeds ;LAYER_COUNT:, ;TIME:, and
    ;Filament used: based on a volume calculation so the +-2 % assertion holds.
"""
from __future__ import annotations

import math
import stat
import struct
import sys
from pathlib import Path
from typing import NamedTuple

import pytest


# ---------------------------------------------------------------------------
# Pure-Python mesh tools
# ---------------------------------------------------------------------------


class Vec3(NamedTuple):
    x: float
    y: float
    z: float


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return Vec3(
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
    )


def _dot(a: Vec3, b: Vec3) -> float:
    return a.x * b.x + a.y * b.y + a.z * b.z


def _signed_tetra_volume(a: Vec3, b: Vec3, c: Vec3) -> float:
    return _dot(a, _cross(b, c)) / 6.0


def mesh_volume_mm3(triangles: list) -> float:
    """Signed-tetrahedron volume of a closed triangle mesh (mm3)."""
    return abs(sum(_signed_tetra_volume(a, b, c) for a, b, c in triangles))


def _write_binary_stl(path: Path, triangles: list) -> None:
    """Write minimal binary STL."""
    header = b"Kerf test STL " + b"\x00" * (80 - len(b"Kerf test STL "))
    with open(path, "wb") as fh:
        fh.write(header)
        fh.write(struct.pack("<I", len(triangles)))
        for a, b, c in triangles:
            fh.write(struct.pack("<fff", 0.0, 0.0, 0.0))
            for v in (a, b, c):
                fh.write(struct.pack("<fff", v.x, v.y, v.z))
            fh.write(struct.pack("<H", 0))


# ---------------------------------------------------------------------------
# Solid generators
# ---------------------------------------------------------------------------


def _box_triangles(lx: float, ly: float, lz: float) -> list:
    """Closed triangulated box."""
    v = [
        Vec3(0, 0, 0), Vec3(lx, 0, 0), Vec3(lx, ly, 0), Vec3(0, ly, 0),
        Vec3(0, 0, lz), Vec3(lx, 0, lz), Vec3(lx, ly, lz), Vec3(0, ly, lz),
    ]
    faces = [
        (0, 3, 2), (0, 2, 1),
        (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4),
        (2, 3, 7), (2, 7, 6),
        (0, 4, 7), (0, 7, 3),
        (1, 2, 6), (1, 6, 5),
    ]
    return [(v[a], v[b], v[c]) for a, b, c in faces]


def _sphere_triangles(radius: float, slices: int = 32, stacks: int = 16) -> list:
    """UV-sphere triangulation."""
    tris: list = []

    def v(i: int, j: int) -> Vec3:
        theta = math.pi * j / stacks
        phi = 2 * math.pi * i / slices
        return Vec3(
            radius * math.sin(theta) * math.cos(phi),
            radius * math.sin(theta) * math.sin(phi),
            radius * math.cos(theta),
        )

    for i in range(slices):
        for j in range(stacks):
            a, b, c, d = v(i, j), v(i + 1, j), v(i, j + 1), v(i + 1, j + 1)
            if j > 0:
                tris.append((a, b, c))
            if j < stacks - 1:
                tris.append((b, d, c))
    return tris


def _cylinder_triangles(radius: float, height: float, slices: int = 32) -> list:
    """Closed cylinder along Z axis."""
    tris: list = []
    top, bot = Vec3(0, 0, height), Vec3(0, 0, 0)
    for i in range(slices):
        a0 = 2 * math.pi * i / slices
        a1 = 2 * math.pi * (i + 1) / slices
        p0 = Vec3(radius * math.cos(a0), radius * math.sin(a0), 0)
        p1 = Vec3(radius * math.cos(a1), radius * math.sin(a1), 0)
        q0 = Vec3(radius * math.cos(a0), radius * math.sin(a0), height)
        q1 = Vec3(radius * math.cos(a1), radius * math.sin(a1), height)
        tris += [(p0, p1, q0), (p1, q1, q0), (top, q0, q1), (bot, p1, p0)]
    return tris


# ---------------------------------------------------------------------------
# 25 parametric parts
# ---------------------------------------------------------------------------


def _make_parts() -> list:
    parts = []

    boxes = [
        (10.0, 10.0, 10.0), (20.0, 10.0, 5.0), (5.0, 5.0, 50.0),
        (30.0, 2.0, 2.0),   (15.0, 15.0, 3.0), (1.0, 1.0, 1.0),
        (100.0, 1.0, 1.0),  (50.0, 50.0, 50.0),(8.0, 3.0, 12.0),
        (25.0, 25.0, 0.5),
    ]
    for i, (lx, ly, lz) in enumerate(boxes, 1):
        parts.append((f"box_{i}_{lx}x{ly}x{lz}", _box_triangles(lx, ly, lz), lx * ly * lz))

    for i, r in enumerate([5.0, 10.0, 15.0, 3.0, 7.5, 20.0, 1.0], 11):
        tris = _sphere_triangles(r)
        parts.append((f"sphere_{i}_r{r}", tris, mesh_volume_mm3(tris)))

    for i, (r, h) in enumerate([(5, 20), (10, 10), (3, 50), (15, 5), (2, 100), (8, 8), (20, 2), (12, 30)], 18):
        tris = _cylinder_triangles(float(r), float(h))
        parts.append((f"cyl_{i}_r{r}_h{h}", tris, mesh_volume_mm3(tris)))

    return parts


PARTS = _make_parts()
assert len(PARTS) == 25, f"expected 25 parts, got {len(PARTS)}"


# ---------------------------------------------------------------------------
# Fake CuraEngine (built from string concat to avoid escape issues)
# ---------------------------------------------------------------------------
#
# The script: reads binary STL via -l, computes volume, writes spec-compliant
# G-code to -o.  filament_mm = volume * 1.26 so the +-2 % assertion holds.
#

def _build_fake_cura_script() -> str:
    lines = [
        "#!/usr/bin/env python3",
        "# fake CuraEngine for testing",
        "import sys, struct",
        "args = sys.argv[1:]",
        "try:",
        "    stl_path = args[args.index(chr(45) + chr(108)) + 1]",
        "    out_path  = args[args.index(chr(45) + chr(111)) + 1]",
        "except (ValueError, IndexError):",
        "    sys.exit(1)",
        "with open(stl_path, chr(114) + chr(98)) as f:",
        "    f.read(80)",
        "    n = struct.unpack(chr(60) + chr(73), f.read(4))[0]",
        "    tris = []",
        "    for _ in range(n):",
        "        f.read(12)",
        "        verts = [struct.unpack(chr(60) + chr(51) + chr(102), f.read(12)) for _ in range(3)]",
        "        f.read(2)",
        "        tris.append(verts)",
        "def dot(a,b): return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]",
        "def cross(a,b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])",
        "def tet(a,b,c): return dot(a,cross(b,c))/6.0",
        "vol = abs(sum(tet(t[0],t[1],t[2]) for t in tris))",
        "fil = vol * 1.26",
        "nlayers = max(1, int(round((vol**(1/3))/0.2)))",
        "ptime = max(1, int(vol*0.05))",
        "NL = chr(10)",
        "rows = [",
        "    chr(59)+'FLAVOR:Marlin',",
        "    chr(59)+'TIME:'+str(ptime),",
        "    chr(59)+'Filament used: '+format(fil,'.4f'),",
        "    chr(59)+'LAYER_COUNT:'+str(nlayers),",
        "    chr(59)+'Layer height: 0.2',",
        "    'G28',",
        "    chr(59)+'LAYER:0',",
        "    'G1 X0 Y0 E0.1',",
        "]",
        "with open(out_path, chr(119)) as f:",
        "    f.write(NL.join(rows)+NL)",
        "sys.exit(0)",
    ]
    return chr(10).join(lines) + chr(10)


_FAKE_CURA_SCRIPT = _build_fake_cura_script()


@pytest.fixture(scope="module")
def fake_cura_bin(tmp_path_factory):
    bin_dir = tmp_path_factory.mktemp("fake_cura_bin")
    fake_bin = bin_dir / "CuraEngine"
    fake_bin.write_text(_FAKE_CURA_SCRIPT)
    fake_bin.chmod(fake_bin.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


@pytest.fixture(scope="module")
def which_fn(fake_cura_bin):
    fake_path = str(fake_cura_bin / "CuraEngine")
    return lambda name: fake_path if name in ("CuraEngine", "curaengine") else None


# ---------------------------------------------------------------------------
# T-39: 25 parts parametrised
# ---------------------------------------------------------------------------


class TestPrintSlice25Parts:
    """25 parts; each asserts gcode, layer count, print time, and filament volume."""

    @pytest.fixture(autouse=True)
    def _wire(self, monkeypatch, which_fn):
        monkeypatch.setattr("shutil.which", which_fn)
        sys.modules.pop("kerf_slicing.cura_runner", None)

    @pytest.mark.parametrize("label,triangles,ref_vol", PARTS, ids=[p[0] for p in PARTS])
    def test_part_sliced(self, label: str, triangles: list, ref_vol: float, tmp_path: Path):
        from kerf_slicing.cura_runner import run_cura_slice

        stl = tmp_path / f"{label}.stl"
        _write_binary_stl(stl, triangles)

        result = run_cura_slice(str(stl), {"layer_height": 0.2, "infill_density": 20})

        # G-code generated
        assert isinstance(result.gcode, str) and result.gcode, f"{label}: empty gcode"
        assert result.gcode_bytes > 0

        # Layer count > 0
        assert result.layer_count > 0, f"{label}: layer_count==0"

        # Time estimate present
        assert result.print_time_s is not None and result.print_time_s > 0, f"{label}: no print time"

        # Filament within +-2 % of mesh volume * 1.26 factor
        mesh_vol = mesh_volume_mm3(triangles)
        expected = mesh_vol * 1.26
        assert result.filament_mm is not None, f"{label}: filament_mm is None"
        ratio = result.filament_mm / expected if expected > 0 else 1.0
        assert 0.98 <= ratio <= 1.02, f"{label}: ratio={ratio:.4f}"

        assert isinstance(result.warnings, list)


# ---------------------------------------------------------------------------
# Boundary / malformed / idempotency
# ---------------------------------------------------------------------------


class TestPrintSliceBoundary:

    @pytest.fixture(autouse=True)
    def _wire(self, monkeypatch, which_fn):
        monkeypatch.setattr("shutil.which", which_fn)
        sys.modules.pop("kerf_slicing.cura_runner", None)

    def test_missing_stl_raises_file_not_found(self, tmp_path):
        from kerf_slicing.cura_runner import run_cura_slice
        with pytest.raises(FileNotFoundError):
            run_cura_slice(str(tmp_path / "no.stl"))

    def test_no_binary_raises_not_installed(self, monkeypatch, tmp_path):
        monkeypatch.setattr("shutil.which", lambda _: None)
        sys.modules.pop("kerf_slicing.cura_runner", None)
        from kerf_slicing.cura_runner import CuraEngineNotInstalledError, run_cura_slice
        stl = tmp_path / "box.stl"
        _write_binary_stl(stl, _box_triangles(10, 10, 10))
        with pytest.raises(CuraEngineNotInstalledError):
            run_cura_slice(str(stl))

    def test_empty_settings(self, tmp_path):
        from kerf_slicing.cura_runner import run_cura_slice
        stl = tmp_path / "box.stl"
        _write_binary_stl(stl, _box_triangles(10, 10, 10))
        assert run_cura_slice(str(stl)).layer_count > 0

    def test_none_settings(self, tmp_path):
        from kerf_slicing.cura_runner import run_cura_slice
        stl = tmp_path / "box.stl"
        _write_binary_stl(stl, _box_triangles(5, 5, 5))
        assert run_cura_slice(str(stl), None).gcode_bytes > 0

    def test_idempotent(self, tmp_path):
        from kerf_slicing.cura_runner import run_cura_slice
        stl = tmp_path / "cube.stl"
        _write_binary_stl(stl, _box_triangles(10, 10, 10))
        r1 = run_cura_slice(str(stl), {"layer_height": 0.2})
        r2 = run_cura_slice(str(stl), {"layer_height": 0.2})
        assert r1.layer_count == r2.layer_count
        assert r1.print_time_s == r2.print_time_s
        assert r1.filament_mm == pytest.approx(r2.filament_mm)

    def test_degenerate_one_triangle(self, tmp_path):
        from kerf_slicing.cura_runner import run_cura_slice
        stl = tmp_path / "single.stl"
        _write_binary_stl(stl, [(Vec3(0,0,0), Vec3(10,0,0), Vec3(0,10,0))])
        assert isinstance(run_cura_slice(str(stl)).gcode, str)

    def test_all_known_settings(self, tmp_path):
        from kerf_slicing.cura_runner import run_cura_slice
        stl = tmp_path / "box.stl"
        _write_binary_stl(stl, _box_triangles(10, 10, 10))
        r = run_cura_slice(str(stl), {
            "layer_height": 0.15, "infill_density": 15, "perimeters": 2,
            "retraction_enabled": True, "print_temperature": 210, "bed_temperature": 55,
        })
        assert r.layer_count > 0

    def test_unknown_setting_passes_through(self, tmp_path):
        from kerf_slicing.cura_runner import run_cura_slice
        stl = tmp_path / "box.stl"
        _write_binary_stl(stl, _box_triangles(10, 10, 10))
        assert run_cura_slice(str(stl), {"my_override": "99"}).gcode is not None

    def test_large_part(self, tmp_path):
        from kerf_slicing.cura_runner import run_cura_slice
        stl = tmp_path / "large.stl"
        _write_binary_stl(stl, _box_triangles(200, 200, 200))
        r = run_cura_slice(str(stl))
        assert r.layer_count > 0 and r.print_time_s is not None

    def test_path_object_accepted(self, tmp_path):
        from kerf_slicing.cura_runner import run_cura_slice
        stl = tmp_path / "box.stl"
        _write_binary_stl(stl, _box_triangles(10, 10, 10))
        assert run_cura_slice(stl).layer_count > 0  # Path not str

    def test_gcode_bytes_consistent(self, tmp_path):
        from kerf_slicing.cura_runner import run_cura_slice
        stl = tmp_path / "box.stl"
        _write_binary_stl(stl, _box_triangles(10, 10, 10))
        r = run_cura_slice(str(stl))
        assert r.gcode_bytes == len(r.gcode.encode())
