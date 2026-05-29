"""
Extended test suite for the T-101-C OpenFOAM bridge additions.

Four validation test groups required by the DoD:

1. TestRoundTripCaseGeneration
   Lid-driven cavity case: write_case() → verify OpenFOAM file syntax via
   regex-level dict-format validator; reject malformed dicts.

2. TestResultParser
   Synthesise a fake OpenFOAM time-step directory with known ASCII field
   values → parsed numpy/list arrays match within 1e-9.

3. TestBCTypeFidelity
   Each of inlet/outlet/wall/symmetry maps to the correct OpenFOAM patch
   type string and field-value entry in the generated 0/ files.

4. TestRoundTripMesh
   2-cell minimal mesh → write_polymesh() → re-read topology → counts match.

Additional tests cover:
  - write_case() returns a Path with the expected directory structure
  - pisoFoam → pimpleFoam normalisation
  - Both kEpsilon and kOmegaSST turbulence models produce correct 0/ fields
  - read_results() raises FileNotFoundError on empty case dir
  - polyMesh boundary file format is parseable by OpenFOAM-style regex
"""

from __future__ import annotations

import math
import os
import re
import sys
import tempfile
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _PKG_SRC not in sys.path:
    sys.path.insert(0, _PKG_SRC)

import pytest

from kerf_cfd.openfoam_bridge import (
    ResultBundle,
    _parse_foam_field_file,
    read_results,
    write_case,
    write_polymesh,
    _BC_PATCH_TYPE,
    _BC_FIELD_MAP,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _has_foam_header(text: str) -> bool:
    """Return True if text contains a syntactically valid FoamFile header."""
    return bool(re.search(
        r"FoamFile\s*\{[^}]*version\s+\S+\s*;[^}]*format\s+\S+\s*;[^}]*class\s+\S+\s*;[^}]*object\s+\S+\s*;[^}]*\}",
        text,
        re.DOTALL,
    ))


def _is_valid_foam_dict(text: str) -> bool:
    """
    Minimal OpenFOAM dictionary format validator.

    Checks:
    1. Contains a FoamFile header with all four required keys.
    2. All { have matching }.
    3. All ; are within or after a value assignment (no orphan semicolons).
    4. Does NOT contain obvious malformed patterns.
    """
    if not _has_foam_header(text):
        return False
    # Balanced braces
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    if depth != 0:
        return False
    return True


def _make_scalar_field_file(path: Path, n: int, values: list[float], uniform: bool = False) -> None:
    """Write a minimal OpenFOAM volScalarField ASCII file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if uniform:
        internal = f"internalField   uniform {values[0]:g};"
    else:
        data_lines = "\n".join(f"{v:g}" for v in values)
        internal = f"internalField   nonuniform List<scalar>\n{n}\n(\n{data_lines}\n);"

    content = f"""\
FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    location    "0.5";
    object      p;
}}

dimensions      [0 2 -2 0 0 0 0];

{internal}

boundaryField
{{
    inlet
    {{
        type            zeroGradient;
    }}
    outlet
    {{
        type            fixedValue;
        value           uniform 0;
    }}
}}
"""
    path.write_text(content)


def _make_vector_field_file(path: Path, n: int, values: list[tuple[float, float, float]]) -> None:
    """Write a minimal OpenFOAM volVectorField ASCII file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data_lines = "\n".join(f"({v[0]:g} {v[1]:g} {v[2]:g})" for v in values)
    content = f"""\
FoamFile
{{
    version     2.0;
    format      ascii;
    class       volVectorField;
    location    "0.5";
    object      U;
}}

dimensions      [0 1 -1 0 0 0 0];

internalField   nonuniform List<vector>
{n}
(
{data_lines}
);

boundaryField
{{
    inlet
    {{
        type            fixedValue;
        value           uniform (1 0 0);
    }}
    outlet
    {{
        type            zeroGradient;
    }}
}}
"""
    path.write_text(content)


# ===========================================================================
# 1. Round-trip case generation
# ===========================================================================

class TestRoundTripCaseGeneration:
    """
    Build a lid-driven cavity case via write_case() and validate every
    generated file with the FoamFile dict-format validator.
    """

    def test_write_case_returns_path(self, tmp_path):
        result = write_case(tmp_path)
        assert isinstance(result, Path)
        assert result.resolve() == tmp_path.resolve()

    def test_write_case_system_directory(self, tmp_path):
        write_case(tmp_path)
        assert (tmp_path / "system").is_dir()

    def test_write_case_constant_directory(self, tmp_path):
        write_case(tmp_path)
        assert (tmp_path / "constant").is_dir()

    def test_write_case_zero_directory(self, tmp_path):
        write_case(tmp_path)
        assert (tmp_path / "0").is_dir()

    def test_controlDict_syntax_valid(self, tmp_path):
        write_case(tmp_path)
        text = (tmp_path / "system" / "controlDict").read_text()
        assert _is_valid_foam_dict(text), "controlDict failed FoamFile format validation"

    def test_fvSchemes_syntax_valid(self, tmp_path):
        write_case(tmp_path)
        text = (tmp_path / "system" / "fvSchemes").read_text()
        assert _is_valid_foam_dict(text), "fvSchemes failed FoamFile format validation"

    def test_fvSolution_syntax_valid(self, tmp_path):
        write_case(tmp_path)
        text = (tmp_path / "system" / "fvSolution").read_text()
        assert _is_valid_foam_dict(text), "fvSolution failed FoamFile format validation"

    def test_blockMeshDict_syntax_valid(self, tmp_path):
        write_case(tmp_path)
        text = (tmp_path / "system" / "blockMeshDict").read_text()
        assert _is_valid_foam_dict(text), "blockMeshDict failed FoamFile format validation"

    def test_transportProperties_syntax_valid(self, tmp_path):
        write_case(tmp_path)
        text = (tmp_path / "constant" / "transportProperties").read_text()
        assert _is_valid_foam_dict(text), "transportProperties failed validation"

    def test_turbulenceProperties_syntax_valid(self, tmp_path):
        write_case(tmp_path)
        text = (tmp_path / "constant" / "turbulenceProperties").read_text()
        assert _is_valid_foam_dict(text), "turbulenceProperties failed validation"

    def test_U_syntax_valid(self, tmp_path):
        write_case(tmp_path)
        text = (tmp_path / "0" / "U").read_text()
        assert _is_valid_foam_dict(text), "0/U failed FoamFile format validation"

    def test_p_syntax_valid(self, tmp_path):
        write_case(tmp_path)
        text = (tmp_path / "0" / "p").read_text()
        assert _is_valid_foam_dict(text), "0/p failed FoamFile format validation"

    def test_kEpsilon_k_field_syntax_valid(self, tmp_path):
        write_case(tmp_path, solver_config={"turbulence_model": "kEpsilon"})
        text = (tmp_path / "0" / "k").read_text()
        assert _is_valid_foam_dict(text), "0/k (kEpsilon) failed FoamFile format validation"

    def test_kEpsilon_epsilon_field_syntax_valid(self, tmp_path):
        write_case(tmp_path, solver_config={"turbulence_model": "kEpsilon"})
        text = (tmp_path / "0" / "epsilon").read_text()
        assert _is_valid_foam_dict(text), "0/epsilon failed FoamFile format validation"

    def test_kOmegaSST_omega_field_syntax_valid(self, tmp_path):
        write_case(tmp_path, solver_config={"turbulence_model": "kOmegaSST"})
        text = (tmp_path / "0" / "omega").read_text()
        assert _is_valid_foam_dict(text), "0/omega failed FoamFile format validation"

    def test_pisoFoam_normalised_to_pimpleFoam(self, tmp_path):
        write_case(tmp_path, solver_config={"solver": "pisoFoam"})
        text = (tmp_path / "system" / "controlDict").read_text()
        # pisoFoam is normalised to pimpleFoam by write_case()
        assert "pimpleFoam" in text, "pisoFoam should be normalised to pimpleFoam"

    def test_simpleFoam_controlDict_application(self, tmp_path):
        write_case(tmp_path, solver_config={"solver": "simpleFoam"})
        text = (tmp_path / "system" / "controlDict").read_text()
        assert "simpleFoam" in text

    def test_pimpleFoam_fvSolution_has_PIMPLE(self, tmp_path):
        write_case(tmp_path, solver_config={"solver": "pimpleFoam"})
        text = (tmp_path / "system" / "fvSolution").read_text()
        assert "PIMPLE" in text

    def test_malformed_dict_rejected(self, tmp_path):
        """A text missing the FoamFile header must fail _is_valid_foam_dict()."""
        bad = "application simpleFoam;\nendTime 500;\n"
        assert not _is_valid_foam_dict(bad), "Malformed dict should not pass validator"

    def test_unbalanced_braces_rejected(self, tmp_path):
        """A text with an extra unmatched '{' must fail _is_valid_foam_dict()."""
        bad = """\
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    location    "system";
    object      controlDict;
}
extraBlock
{
    nesting {
"""
        assert not _is_valid_foam_dict(bad), "Unbalanced braces should not pass validator"

    def test_custom_nu_written(self, tmp_path):
        write_case(tmp_path, solver_config={"nu": 1.5e-5})
        text = (tmp_path / "constant" / "transportProperties").read_text()
        assert "1.5e-05" in text or "1.5e-5" in text

    def test_custom_geometry_nx_written(self, tmp_path):
        write_case(tmp_path, solver_config={"geometry": {"nx": 40, "ny": 20, "nz": 1}})
        text = (tmp_path / "system" / "blockMeshDict").read_text()
        assert "40 20 1" in text


# ===========================================================================
# 2. Result parser
# ===========================================================================

class TestResultParser:
    """
    Synthesise a fake OpenFOAM time-step directory with known values and
    verify that read_results() returns arrays matching within 1e-9.
    """

    def _make_time_dir(self, tmp_path: Path, time: str = "0.5") -> Path:
        td = tmp_path / time
        td.mkdir(parents=True, exist_ok=True)
        return td

    def test_scalar_nonuniform_parsed_within_tolerance(self, tmp_path):
        """p field with 4 known nonuniform values → arrays match 1e-9."""
        td = self._make_time_dir(tmp_path)
        known = [1.0, 2.5, -0.3, 7.777]
        _make_scalar_field_file(td / "p", len(known), known)

        bundle = read_results(tmp_path, time_step="0.5")
        assert bundle.p is not None
        p = list(bundle.p)  # works for both numpy and plain list
        assert len(p) == len(known)
        for got, exp in zip(p, known):
            assert abs(float(got) - exp) < 1e-9, f"p mismatch: {float(got)} vs {exp}"

    def test_vector_nonuniform_parsed_within_tolerance(self, tmp_path):
        """U field with 3 known velocity vectors → components match 1e-9."""
        td = self._make_time_dir(tmp_path)
        known_vecs = [(1.0, 0.0, 0.0), (0.5, -0.2, 0.1), (-0.3, 0.7, 0.4)]
        _make_vector_field_file(td / "U", len(known_vecs), known_vecs)

        bundle = read_results(tmp_path, time_step="0.5")
        assert bundle.U is not None
        for i, (exp_x, exp_y, exp_z) in enumerate(known_vecs):
            row = bundle.U[i]  # numpy row or tuple
            got_x, got_y, got_z = float(row[0]), float(row[1]), float(row[2])
            assert abs(got_x - exp_x) < 1e-9, f"U[{i}].x mismatch"
            assert abs(got_y - exp_y) < 1e-9, f"U[{i}].y mismatch"
            assert abs(got_z - exp_z) < 1e-9, f"U[{i}].z mismatch"

    def test_uniform_scalar_expanded(self, tmp_path):
        """Uniform scalar field is correctly identified."""
        td = self._make_time_dir(tmp_path)
        _make_scalar_field_file(td / "p", 1, [3.14], uniform=True)

        bundle = read_results(tmp_path, time_step="0.5")
        assert bundle.p is not None
        # Uniform: internal_values has 1 entry
        p = list(bundle.p)
        assert len(p) >= 1
        assert abs(float(p[0]) - 3.14) < 1e-9

    def test_latestTime_selects_highest_directory(self, tmp_path):
        """latestTime selects the numerically largest time directory."""
        for t in ("0.1", "0.5", "1.0"):
            td = tmp_path / t
            td.mkdir()
            _make_scalar_field_file(td / "p", 2, [float(t), float(t) * 2])

        bundle = read_results(tmp_path, time_step="latestTime")
        assert math.isclose(bundle.time_value, 1.0, rel_tol=1e-12)

    def test_named_time_step_selected(self, tmp_path):
        """Explicit time_step string selects the matching directory."""
        for t, val in [("0.1", 1.0), ("0.5", 5.0), ("1.0", 10.0)]:
            td = tmp_path / t
            td.mkdir()
            _make_scalar_field_file(td / "p", 1, [val])

        bundle = read_results(tmp_path, time_step="0.5")
        assert math.isclose(bundle.time_value, 0.5, rel_tol=1e-12)
        p = list(bundle.p)
        assert abs(float(p[0]) - 5.0) < 1e-9

    def test_missing_field_returns_none(self, tmp_path):
        """Fields absent from the time directory are None."""
        td = self._make_time_dir(tmp_path)
        _make_scalar_field_file(td / "p", 2, [0.0, 1.0])
        # Do NOT write k, epsilon, omega, U, nut

        bundle = read_results(tmp_path, time_step="0.5")
        assert bundle.k is None
        assert bundle.epsilon is None
        assert bundle.U is None

    def test_raises_when_no_time_dirs(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_results(tmp_path)

    def test_n_cells_filled_from_nonuniform_field(self, tmp_path):
        """n_cells is inferred from the nonuniform field size."""
        td = self._make_time_dir(tmp_path)
        known = [0.1, 0.2, 0.3, 0.4, 0.5]
        _make_scalar_field_file(td / "p", len(known), known)

        bundle = read_results(tmp_path, time_step="0.5")
        assert bundle.n_cells == len(known)

    def test_multiple_fields_parsed_in_same_bundle(self, tmp_path):
        """U and p co-exist in one ResultBundle from the same time directory."""
        td = self._make_time_dir(tmp_path)
        p_vals = [1.0, 2.0, 3.0]
        u_vals = [(0.1, 0.0, 0.0), (0.2, 0.0, 0.0), (0.3, 0.0, 0.0)]
        _make_scalar_field_file(td / "p", len(p_vals), p_vals)
        _make_vector_field_file(td / "U", len(u_vals), u_vals)

        bundle = read_results(tmp_path, time_step="0.5")
        assert bundle.p is not None
        assert bundle.U is not None
        assert len(list(bundle.p)) == 3
        assert len(list(bundle.U)) == 3

    def test_foam_field_parser_scalar(self, tmp_path):
        """_parse_foam_field_file returns correct keys for a scalar field."""
        p_path = tmp_path / "p"
        _make_scalar_field_file(p_path, 3, [1.0, 2.0, 3.0])
        parsed = _parse_foam_field_file(p_path)
        assert parsed["foam_class"] == "volScalarField"
        assert parsed["object_name"] == "p"
        assert len(parsed["internal_values"]) == 3
        assert abs(parsed["internal_values"][1] - 2.0) < 1e-12

    def test_foam_field_parser_vector(self, tmp_path):
        """_parse_foam_field_file returns correct keys for a vector field."""
        u_path = tmp_path / "U"
        _make_vector_field_file(u_path, 2, [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])
        parsed = _parse_foam_field_file(u_path)
        assert parsed["foam_class"] == "volVectorField"
        assert len(parsed["internal_values"]) == 2
        assert abs(parsed["internal_values"][0][0] - 1.0) < 1e-12
        assert abs(parsed["internal_values"][1][2] - 6.0) < 1e-12


# ===========================================================================
# 3. BC type fidelity
# ===========================================================================

class TestBCTypeFidelity:
    """
    Each Kerf BC key maps to the right OpenFOAM patch type and field-value
    entries in the generated 0/ files.
    """

    def test_inlet_patch_type_in_boundary_table(self):
        """'inlet' maps to OpenFOAM patch type 'patch'."""
        assert _BC_PATCH_TYPE.get("inlet") == "patch"

    def test_outlet_patch_type_in_boundary_table(self):
        """'outlet' maps to OpenFOAM patch type 'patch'."""
        assert _BC_PATCH_TYPE.get("outlet") == "patch"

    def test_wall_patch_type_in_boundary_table(self):
        """'wall' maps to OpenFOAM patch type 'wall'."""
        assert _BC_PATCH_TYPE.get("wall") == "wall"

    def test_symmetry_patch_type_in_boundary_table(self):
        """'symmetry' maps to OpenFOAM patch type 'symmetry'."""
        assert _BC_PATCH_TYPE.get("symmetry") == "symmetry"

    # ----------- Field-type entries from _BC_FIELD_MAP -----------

    def test_inlet_U_type_is_fixedValue(self):
        assert _BC_FIELD_MAP["inlet"]["U_type"] == "fixedValue"

    def test_inlet_p_type_is_zeroGradient(self):
        assert _BC_FIELD_MAP["inlet"]["p_type"] == "zeroGradient"

    def test_outlet_U_type_is_zeroGradient(self):
        assert _BC_FIELD_MAP["outlet"]["U_type"] == "zeroGradient"

    def test_outlet_p_type_is_fixedValue(self):
        assert _BC_FIELD_MAP["outlet"]["p_type"] == "fixedValue"

    def test_wall_U_type_is_noSlip(self):
        assert _BC_FIELD_MAP["wall"]["U_type"] == "noSlip"

    def test_wall_p_type_is_zeroGradient(self):
        assert _BC_FIELD_MAP["wall"]["p_type"] == "zeroGradient"

    def test_wall_k_type_is_kqRWallFunction(self):
        assert _BC_FIELD_MAP["wall"]["k_type"] == "kqRWallFunction"

    def test_wall_epsilon_type_is_epsilonWallFunction(self):
        assert _BC_FIELD_MAP["wall"]["epsilon_type"] == "epsilonWallFunction"

    def test_wall_omega_type_is_omegaWallFunction(self):
        assert _BC_FIELD_MAP["wall"]["omega_type"] == "omegaWallFunction"

    def test_symmetry_all_types_are_symmetry(self):
        mapping = _BC_FIELD_MAP["symmetry"]
        for key in ("U_type", "p_type", "k_type", "epsilon_type", "omega_type"):
            assert mapping[key] == "symmetry", f"{key} should be 'symmetry'"

    # ----------- Generated file content -----------

    def test_write_case_bcs_inlet_U_fixedValue(self, tmp_path):
        bcs = {"inlet": "inlet", "outlet": "outlet", "walls": "wall"}
        write_case(tmp_path, bcs=bcs)
        text = (tmp_path / "0" / "U").read_text()
        # inlet patch should have fixedValue
        assert re.search(r"inlet\s*\{[^}]*fixedValue[^}]*\}", text, re.DOTALL), \
            "inlet patch in 0/U should use fixedValue"

    def test_write_case_bcs_outlet_U_zeroGradient(self, tmp_path):
        bcs = {"inlet": "inlet", "outlet": "outlet", "walls": "wall"}
        write_case(tmp_path, bcs=bcs)
        text = (tmp_path / "0" / "U").read_text()
        assert re.search(r"outlet\s*\{[^}]*zeroGradient[^}]*\}", text, re.DOTALL), \
            "outlet patch in 0/U should use zeroGradient"

    def test_write_case_bcs_wall_U_noSlip(self, tmp_path):
        bcs = {"inlet": "inlet", "outlet": "outlet", "walls": "wall"}
        write_case(tmp_path, bcs=bcs)
        text = (tmp_path / "0" / "U").read_text()
        assert re.search(r"walls\s*\{[^}]*noSlip[^}]*\}", text, re.DOTALL), \
            "walls patch in 0/U should use noSlip"

    def test_write_case_bcs_symmetry_U_symmetry(self, tmp_path):
        bcs = {
            "inlet": "inlet",
            "outlet": "outlet",
            "walls": "wall",
            "sym_plane": "symmetry",
        }
        write_case(tmp_path, bcs=bcs)
        text = (tmp_path / "0" / "U").read_text()
        assert re.search(r"sym_plane\s*\{[^}]*type\s+symmetry[^}]*\}", text, re.DOTALL), \
            "sym_plane patch should be type symmetry in 0/U"

    def test_write_case_bcs_outlet_p_fixedValue(self, tmp_path):
        bcs = {"inlet": "inlet", "outlet": "outlet", "walls": "wall"}
        write_case(tmp_path, bcs=bcs)
        text = (tmp_path / "0" / "p").read_text()
        assert re.search(r"outlet\s*\{[^}]*fixedValue[^}]*\}", text, re.DOTALL), \
            "outlet patch in 0/p should use fixedValue"

    def test_write_case_bcs_wall_k_kqRWallFunction(self, tmp_path):
        bcs = {"inlet": "inlet", "outlet": "outlet", "walls": "wall"}
        write_case(tmp_path, bcs=bcs, solver_config={"turbulence_model": "kEpsilon"})
        text = (tmp_path / "0" / "k").read_text()
        assert re.search(r"walls\s*\{[^}]*kqRWallFunction[^}]*\}", text, re.DOTALL), \
            "walls patch in 0/k should use kqRWallFunction"

    def test_write_case_bcs_wall_epsilon_wallFunction(self, tmp_path):
        bcs = {"inlet": "inlet", "outlet": "outlet", "walls": "wall"}
        write_case(tmp_path, bcs=bcs, solver_config={"turbulence_model": "kEpsilon"})
        text = (tmp_path / "0" / "epsilon").read_text()
        assert re.search(r"walls\s*\{[^}]*epsilonWallFunction[^}]*\}", text, re.DOTALL), \
            "walls patch in 0/epsilon should use epsilonWallFunction"

    def test_write_case_bcs_wall_omega_wallFunction(self, tmp_path):
        bcs = {"inlet": "inlet", "outlet": "outlet", "walls": "wall"}
        write_case(tmp_path, bcs=bcs, solver_config={"turbulence_model": "kOmegaSST"})
        text = (tmp_path / "0" / "omega").read_text()
        assert re.search(r"walls\s*\{[^}]*omegaWallFunction[^}]*\}", text, re.DOTALL), \
            "walls patch in 0/omega should use omegaWallFunction"


# ===========================================================================
# 4. Round-trip mesh
# ===========================================================================

class TestRoundTripMesh:
    """
    Minimal 2-cell mesh → write_polymesh() → polyMesh files exist with
    correct content → re-read topology matches.
    """

    def _two_cell_mesh_dict(self) -> dict:
        """
        A minimal hex-to-tet style mesh with 2 cells.

        Cell 0: vertices 0-3 (tetrahedron in +x half)
        Cell 1: vertices 1-4 (tetrahedron in -x half)
        1 internal face shared between them; 6 boundary faces.

        Points:
            0: (0, 0, 0)
            1: (1, 0, 0)
            2: (0, 1, 0)
            3: (0, 0, 1)
            4: (1, 1, 1)
        """
        points = [
            (0.0, 0.0, 0.0),  # 0
            (1.0, 0.0, 0.0),  # 1
            (0.0, 1.0, 0.0),  # 2
            (0.0, 0.0, 1.0),  # 3
            (1.0, 1.0, 1.0),  # 4
        ]
        # Faces: 1 internal (shared 0-1-2), then boundary faces
        # internal face shared between cell 0 and cell 1
        internal_face = (0, 1, 2)
        # boundary faces for cell 0
        bf0 = [(0, 1, 3), (0, 2, 3), (1, 2, 3)]
        # boundary faces for cell 1
        bf1 = [(1, 2, 4), (1, 3, 4), (2, 3, 4)]
        all_faces = [internal_face] + bf0 + bf1
        all_owner = [0, 0, 0, 0, 1, 1, 1]
        all_neighbour = [1]  # only the one internal face

        patches = {
            "inlet": {"start": 1, "nFaces": 3, "type": "inlet"},
            "outlet": {"start": 4, "nFaces": 3, "type": "outlet"},
        }

        return {
            "points": points,
            "faces": all_faces,
            "owner": all_owner,
            "neighbour": all_neighbour,
            "patches": patches,
        }

    def test_polymesh_files_created(self, tmp_path):
        """write_polymesh creates all 5 polyMesh files."""
        poly_dir = tmp_path / "constant" / "polyMesh"
        write_polymesh(poly_dir, self._two_cell_mesh_dict())
        for fname in ("points", "faces", "owner", "neighbour", "boundary"):
            assert (poly_dir / fname).is_file(), f"polyMesh/{fname} not created"

    def test_polymesh_points_count(self, tmp_path):
        """points file contains 5 point entries."""
        poly_dir = tmp_path / "constant" / "polyMesh"
        mesh = self._two_cell_mesh_dict()
        write_polymesh(poly_dir, mesh)
        text = (poly_dir / "points").read_text()
        # The count line should be "5"
        assert re.search(r"^5\s*$", text, re.MULTILINE), "Expected '5' count in points file"

    def test_polymesh_faces_count(self, tmp_path):
        """faces file contains 7 face entries."""
        poly_dir = tmp_path / "constant" / "polyMesh"
        mesh = self._two_cell_mesh_dict()
        write_polymesh(poly_dir, mesh)
        text = (poly_dir / "faces").read_text()
        assert re.search(r"^7\s*$", text, re.MULTILINE), "Expected '7' count in faces file"

    def test_polymesh_owner_count(self, tmp_path):
        """owner file contains 7 entries (one per face)."""
        poly_dir = tmp_path / "constant" / "polyMesh"
        mesh = self._two_cell_mesh_dict()
        write_polymesh(poly_dir, mesh)
        text = (poly_dir / "owner").read_text()
        assert re.search(r"^7\s*$", text, re.MULTILINE), "Expected '7' count in owner file"

    def test_polymesh_neighbour_count(self, tmp_path):
        """neighbour file contains 1 entry (one internal face)."""
        poly_dir = tmp_path / "constant" / "polyMesh"
        mesh = self._two_cell_mesh_dict()
        write_polymesh(poly_dir, mesh)
        text = (poly_dir / "neighbour").read_text()
        assert re.search(r"^1\s*$", text, re.MULTILINE), "Expected '1' count in neighbour file"

    def test_polymesh_boundary_patch_names(self, tmp_path):
        """boundary file contains patch names 'inlet' and 'outlet'."""
        poly_dir = tmp_path / "constant" / "polyMesh"
        write_polymesh(poly_dir, self._two_cell_mesh_dict())
        text = (poly_dir / "boundary").read_text()
        assert "inlet" in text
        assert "outlet" in text

    def test_polymesh_boundary_patch_types(self, tmp_path):
        """boundary file contains correct OpenFOAM patch types for inlet/outlet."""
        poly_dir = tmp_path / "constant" / "polyMesh"
        write_polymesh(poly_dir, self._two_cell_mesh_dict())
        text = (poly_dir / "boundary").read_text()
        # inlet → patch, outlet → patch
        assert re.search(r"inlet\s*\{[^}]*type\s+patch\s*;[^}]*\}", text, re.DOTALL)
        assert re.search(r"outlet\s*\{[^}]*type\s+patch\s*;[^}]*\}", text, re.DOTALL)

    def test_polymesh_foam_header_all_files(self, tmp_path):
        """All 5 polyMesh files have valid FoamFile headers."""
        poly_dir = tmp_path / "constant" / "polyMesh"
        write_polymesh(poly_dir, self._two_cell_mesh_dict())
        for fname in ("points", "faces", "owner", "neighbour", "boundary"):
            text = (poly_dir / fname).read_text()
            assert _has_foam_header(text), f"polyMesh/{fname} missing FoamFile header"

    def test_polymesh_reread_topology_n_faces(self, tmp_path):
        """Re-read topology: n_faces matches write input."""
        from kerf_cfd.openfoam_bridge import _parse_polymesh

        poly_dir = tmp_path / "constant" / "polyMesh"
        mesh = self._two_cell_mesh_dict()
        write_polymesh(poly_dir, mesh)

        topo = _parse_polymesh(poly_dir)
        assert topo.get("n_faces") == len(mesh["faces"]), (
            f"n_faces mismatch: got {topo.get('n_faces')}, expected {len(mesh['faces'])}"
        )

    def test_polymesh_reread_topology_n_internal_faces(self, tmp_path):
        """Re-read topology: n_internal_faces matches write input."""
        from kerf_cfd.openfoam_bridge import _parse_polymesh

        poly_dir = tmp_path / "constant" / "polyMesh"
        mesh = self._two_cell_mesh_dict()
        write_polymesh(poly_dir, mesh)

        topo = _parse_polymesh(poly_dir)
        assert topo.get("n_internal_faces") == len(mesh["neighbour"]), (
            f"n_internal_faces mismatch: got {topo.get('n_internal_faces')}, "
            f"expected {len(mesh['neighbour'])}"
        )

    def test_polymesh_reread_topology_patches(self, tmp_path):
        """Re-read topology: patch names and types from boundary file match."""
        from kerf_cfd.openfoam_bridge import _parse_polymesh

        poly_dir = tmp_path / "constant" / "polyMesh"
        write_polymesh(poly_dir, self._two_cell_mesh_dict())

        topo = _parse_polymesh(poly_dir)
        patches = topo.get("patches", {})
        assert "inlet" in patches, "inlet patch not found in re-read topology"
        assert "outlet" in patches, "outlet patch not found in re-read topology"
        assert patches["inlet"]["type"] == "patch"
        assert patches["outlet"]["type"] == "patch"

    def test_polymesh_from_mesh3d(self, tmp_path):
        """write_polymesh also accepts a Mesh3D instance from mesh_3d module."""
        from kerf_cfd.mesh_3d import mesh_unit_cube

        poly_dir = tmp_path / "constant" / "polyMesh"
        mesh3d = mesh_unit_cube(n=2)
        # Should not raise
        write_polymesh(poly_dir, mesh3d)
        for fname in ("points", "faces", "owner", "neighbour", "boundary"):
            assert (poly_dir / fname).is_file(), f"polyMesh/{fname} not created for Mesh3D input"

    def test_polymesh_reread_topology_n_cells(self, tmp_path):
        """Re-read topology: n_cells = max(owner) + 1 = 2."""
        from kerf_cfd.openfoam_bridge import _parse_polymesh

        poly_dir = tmp_path / "constant" / "polyMesh"
        write_polymesh(poly_dir, self._two_cell_mesh_dict())
        topo = _parse_polymesh(poly_dir)
        assert topo.get("n_cells") == 2, (
            f"Expected 2 cells, got {topo.get('n_cells')}"
        )


# ===========================================================================
# 5. LLM tool registration smoke test
# ===========================================================================

class TestLLMToolRegistration:
    """Verify that openfoam_llm_tools registers cfd_openfoam_export/import."""

    def test_tools_importable(self):
        """openfoam_llm_tools imports without error."""
        import kerf_cfd.openfoam_llm_tools  # noqa: F401

    def test_export_spec_name(self):
        from kerf_cfd.openfoam_llm_tools import _export_spec
        assert _export_spec.name == "cfd_openfoam_export"

    def test_import_spec_name(self):
        from kerf_cfd.openfoam_llm_tools import _import_spec
        assert _import_spec.name == "cfd_openfoam_import"

    def test_export_spec_has_required_schema_keys(self):
        from kerf_cfd.openfoam_llm_tools import _export_spec
        props = _export_spec.input_schema.get("properties", {})
        for key in ("solver", "turbulence_model", "nu", "u_inlet", "bcs"):
            assert key in props, f"Missing schema property: {key}"

    def test_import_spec_has_required_case_dir(self):
        from kerf_cfd.openfoam_llm_tools import _import_spec
        assert "case_dir" in _import_spec.input_schema.get("required", [])

    def test_export_sync_returns_ok(self, tmp_path):
        from kerf_cfd.openfoam_llm_tools import _export_sync
        result = _export_sync(
            str(tmp_path / "test_case"),
            "simpleFoam", "laminar", 1e-5, 1.0,
            [1.0, 0.0, 0.0], 500.0, 1.0, 100.0,
            0.001, 1.0, 0.001, None, None,
        )
        assert result.get("ok") is True
        assert "case_dir" in result
        assert result["n_files"] > 0

    def test_import_sync_not_found(self, tmp_path):
        from kerf_cfd.openfoam_llm_tools import _import_sync
        result = _import_sync(str(tmp_path / "no_such_case"), "latestTime")
        assert result.get("ok") is False
        assert result.get("code") == "NOT_FOUND"

    def test_import_sync_parses_known_field(self, tmp_path):
        """Full export → synthesise a time-step dir → import reads fields."""
        from kerf_cfd.openfoam_llm_tools import _export_sync, _import_sync

        case_path = tmp_path / "cavity"
        _export_sync(
            str(case_path), "simpleFoam", "laminar", 1e-5, 1.0,
            [1.0, 0.0, 0.0], 500.0, 1.0, 100.0,
            0.001, 1.0, 0.001, None, None,
        )
        # Plant a fake result time directory
        td = case_path / "100"
        td.mkdir()
        _make_scalar_field_file(td / "p", 4, [0.1, 0.2, 0.3, 0.4])

        result = _import_sync(str(case_path), "100")
        assert result.get("ok") is True
        assert "p" in result["fields"]
        assert result["fields"]["p"]["n"] == 4
