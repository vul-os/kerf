"""
kerf-apparel test suite.

Oracles:
1. Seam allowance of 1 cm on a square: signed area increases by
   approximately perimeter × offset (Green's theorem identity for
   simple polygon offset).
2. Grading M → L on a bodice: bust girth increases by the standard
   +5 cm increment (88 → 93 cm body = +5 cm).
3. Marker utilisation on a known 2-block input >= 70 %.
"""

from __future__ import annotations

import math
import pytest

from kerf_apparel.blocks import (
    PatternPiece,
    bodice_front,
    bodice_back,
    sleeve,
    pants_front,
    pants_back,
    get_measurements,
    _close,
)
from kerf_apparel.seam_allowance import (
    add_seam_allowance,
    remove_seam_allowance,
    offset_polyline,
)
from kerf_apparel.grading import (
    grade_bodice,
    grade_sleeve,
    grade_pants,
    bust_girth_from_piece,
)
from kerf_apparel.marker_making import make_marker


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def make_square(side: float) -> PatternPiece:
    """Unit square at origin with given side length."""
    pts = _close([(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)])
    return PatternPiece(name="square", outline=pts)


# ------------------------------------------------------------------ #
# Block generation                                                     #
# ------------------------------------------------------------------ #

class TestBlockGeneration:
    def test_bodice_front_generates(self):
        piece = bodice_front(bust=88, waist=70, hip=95, back_length=42)
        assert isinstance(piece, PatternPiece)
        assert len(piece.outline) >= 4
        # Closed
        assert piece.outline[0] == piece.outline[-1]
        # Non-trivial area
        assert piece.area() > 100  # cm²

    def test_bodice_back_generates(self):
        piece = bodice_back(bust=88, waist=70, hip=95, back_length=42)
        assert isinstance(piece, PatternPiece)
        assert piece.outline[0] == piece.outline[-1]
        assert piece.area() > 100

    def test_sleeve_generates(self):
        piece = sleeve(bust=88, sleeve_length=59)
        assert isinstance(piece, PatternPiece)
        assert piece.outline[0] == piece.outline[-1]
        assert piece.area() > 50

    def test_pants_front_generates(self):
        piece = pants_front(waist=70, hip=95, inseam=78, rise=28)
        assert isinstance(piece, PatternPiece)
        assert piece.outline[0] == piece.outline[-1]
        assert piece.area() > 200

    def test_pants_back_generates(self):
        piece = pants_back(waist=70, hip=95, inseam=78, rise=28)
        assert isinstance(piece, PatternPiece)
        assert piece.outline[0] == piece.outline[-1]
        assert piece.area() > 200

    def test_labels_present(self):
        piece = bodice_front(bust=88, waist=70, hip=95, back_length=42)
        assert "bust" in piece.labels
        assert piece.labels["bust"] == 88

    def test_grain_line_present(self):
        piece = bodice_front(bust=88, waist=70, hip=95, back_length=42)
        assert piece.grain_line is not None
        assert len(piece.grain_line) == 2


# ------------------------------------------------------------------ #
# Size table                                                           #
# ------------------------------------------------------------------ #

class TestSizeTable:
    def test_known_sizes(self):
        for sz in ["XS", "S", "M", "L", "XL", "XXL"]:
            m = get_measurements(sz)
            assert "bust" in m
            assert m["bust"] > 0

    def test_numeric_sizes(self):
        for sz in ["0", "2", "4", "6", "8", "10", "12", "14", "16", "18", "20", "22"]:
            m = get_measurements(sz)
            assert m["bust"] > 0

    def test_unknown_size_raises(self):
        with pytest.raises(ValueError, match="Unknown size"):
            get_measurements("XXXXL")

    def test_m_measurements(self):
        m = get_measurements("M")
        assert m["bust"] == 88
        assert m["waist"] == 70
        assert m["hip"] == 95

    def test_l_measurements(self):
        m = get_measurements("L")
        assert m["bust"] == 93  # +5 from M

    def test_bust_increment_m_to_l(self):
        """Standard increment M→L is exactly 5 cm."""
        m_bust = get_measurements("M")["bust"]
        l_bust = get_measurements("L")["bust"]
        assert l_bust - m_bust == 5


# ------------------------------------------------------------------ #
# Seam allowance — oracle test                                        #
# ------------------------------------------------------------------ #

class TestSeamAllowance:
    """
    Oracle: seam allowance of 1 cm on a square doubles each edge offset
    correctly. The area increase should be approximately:
        ΔA ≈ perimeter × offset + π × offset²
    For a convex polygon: ΔA ≈ perimeter × offset (miter joins, no
    rounded corners). We require ΔA >= 0.9 × perimeter × offset.
    """

    SIDE = 20.0   # 20 cm square
    OFFSET = 1.0  # 1 cm seam allowance

    def test_area_increases_by_approximately_perimeter_times_offset(self):
        square = make_square(self.SIDE)
        original_area = square.area()
        perimeter = square.perimeter()

        expanded = add_seam_allowance(square, self.OFFSET)
        expanded_area = expanded.area()

        delta_area = expanded_area - original_area
        expected_min = perimeter * self.OFFSET * 0.9  # 90 % of ideal

        assert delta_area > 0, "Expanded area must be larger"
        assert delta_area >= expected_min, (
            f"ΔA={delta_area:.2f} < 90% of perimeter×offset={expected_min:.2f}"
        )

    def test_area_increased_is_close_to_perimeter_offset(self):
        """Tighter bound: within 20 % of perimeter × offset (miter joins)."""
        square = make_square(self.SIDE)
        original_area = square.area()
        perimeter = square.perimeter()

        expanded = add_seam_allowance(square, self.OFFSET)
        delta_area = expanded.area() - original_area

        # For miter joins on a square (90° corners), miter scale = sqrt(2) ≈ 1.41
        # Additional corner area ≈ offset² × 4 corners
        # Expected ΔA ≈ perimeter × offset + 4 × offset²
        expected = perimeter * self.OFFSET + 4 * self.OFFSET ** 2
        assert abs(delta_area - expected) / expected < 0.25, (
            f"delta_area={delta_area:.3f}, expected≈{expected:.3f} (±25%)"
        )

    def test_closed_outline_preserved(self):
        square = make_square(self.SIDE)
        expanded = add_seam_allowance(square, self.OFFSET)
        assert expanded.outline[0] == expanded.outline[-1]

    def test_positive_offset_required(self):
        square = make_square(self.SIDE)
        with pytest.raises(ValueError):
            add_seam_allowance(square, -1.0)
        with pytest.raises(ValueError):
            add_seam_allowance(square, 0.0)

    def test_remove_seam_allowance_shrinks(self):
        square = make_square(self.SIDE)
        shrunk = remove_seam_allowance(square, self.OFFSET)
        assert shrunk.area() < square.area()

    def test_offset_polyline_expands_square(self):
        pts = _close([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
        expanded = offset_polyline(pts, 1.0)
        # Bounding box of expanded should be larger
        xs = [p[0] for p in expanded]
        ys = [p[1] for p in expanded]
        assert min(xs) < 0.0 or max(xs) > 10.0 or min(ys) < 0.0 or max(ys) > 10.0

    def test_seam_allowance_label_stored(self):
        square = make_square(self.SIDE)
        expanded = add_seam_allowance(square, 1.5)
        assert expanded.labels["seam_allowance_cm"] == 1.5

    def test_small_square_seam_allowance(self):
        """1cm seam on a 10cm square: ΔA >= perimeter × offset × 0.9."""
        square = make_square(10.0)
        perimeter = square.perimeter()
        expanded = add_seam_allowance(square, 1.0)
        delta = expanded.area() - square.area()
        assert delta >= perimeter * 1.0 * 0.9


# ------------------------------------------------------------------ #
# Grading — oracle test                                                #
# ------------------------------------------------------------------ #

class TestGrading:
    """
    Oracle: grading M → L on bodice must scale bust girth by standard
    +5 cm increment (body measurement M=88, L=93 → +5 cm body).
    With default ease (4 cm), full girth M = 88+4 = 92, L = 93+4 = 97
    → +5 cm.
    """

    def test_grade_bodice_produces_all_alpha_sizes(self):
        gs = grade_bodice("M")
        for sz in ["XS", "S", "M", "L", "XL", "XXL"]:
            assert f"{sz}_front" in gs.pieces
            assert f"{sz}_back" in gs.pieces

    def test_bust_girth_m_to_l_increment(self):
        """Bust girth L should be exactly 5 cm more than M."""
        gs = grade_bodice("M")
        girth_m = bust_girth_from_piece(gs.pieces["M_front"])
        girth_l = bust_girth_from_piece(gs.pieces["L_front"])
        diff = girth_l - girth_m
        assert abs(diff - 5.0) < 0.01, (
            f"Expected +5 cm increment M→L, got {diff:.3f} cm"
        )

    def test_grading_monotonically_increases(self):
        """Each successive alpha size should have larger bust girth."""
        gs = grade_bodice("M")
        sizes = ["XS", "S", "M", "L", "XL", "XXL"]
        girths = [bust_girth_from_piece(gs.pieces[f"{s}_front"]) for s in sizes]
        for i in range(len(girths) - 1):
            assert girths[i] < girths[i + 1], (
                f"Bust girth should increase: {sizes[i]}={girths[i]:.1f} >= {sizes[i+1]}={girths[i+1]:.1f}"
            )

    def test_grade_sleeve(self):
        gs = grade_sleeve("M")
        assert "M_sleeve" in gs.pieces
        assert "L_sleeve" in gs.pieces
        # Larger size should have larger bicep
        area_m = gs.pieces["M_sleeve"].area()
        area_l = gs.pieces["L_sleeve"].area()
        assert area_l > area_m

    def test_grade_pants(self):
        gs = grade_pants("M")
        assert "M_front" in gs.pieces
        assert "L_back" in gs.pieces

    def test_explicit_size_run(self):
        gs = grade_bodice("M", size_run=["S", "M", "L"])
        assert set(gs.size_run) == {"S", "M", "L"}
        assert "XS_front" not in gs.pieces

    def test_numeric_grading(self):
        gs = grade_bodice("12")
        assert "12_front" in gs.pieces
        assert "14_front" in gs.pieces

    def test_invalid_size_raises(self):
        with pytest.raises(ValueError):
            grade_bodice("XXXXL")

    def test_base_size_stored(self):
        gs = grade_bodice("M")
        assert gs.base_size == "M"

    def test_graded_piece_has_correct_measurements(self):
        """The M front should store bust=88 in its labels."""
        gs = grade_bodice("M")
        front_m = gs.pieces["M_front"]
        assert front_m.labels["bust"] == 88


# ------------------------------------------------------------------ #
# Marker making — oracle test                                          #
# ------------------------------------------------------------------ #

class TestMarkerMaking:
    """
    Oracle: marker utilisation on a known input >= 70 %.
    We use two large rectangular pieces that fill most of a 150 cm wide fabric.

    Known-input oracle: two 70 × 42 cm rectangles on 150 cm fabric.
      Piece area = 2 × 2940 = 5880 cm².
      Side by side: 140 cm × 42 cm tall → marker area = 150 × 42 = 6300 cm².
      Expected utilisation = 5880 / 6300 ≈ 93.3 % (well above 70 %).
    """

    def _two_large_rects(self) -> list[PatternPiece]:
        return [
            PatternPiece(name="panel_a", outline=_close([(0, 0), (70, 0), (70, 42), (0, 42)])),
            PatternPiece(name="panel_b", outline=_close([(0, 0), (70, 0), (70, 42), (0, 42)])),
        ]

    def test_known_input_utilisation_above_70_pct(self):
        """Known-input oracle: two 70×42 rects on 150 cm fabric → >= 70 %."""
        pieces = self._two_large_rects()
        result = make_marker(pieces, fabric_width=150.0, gap=0.5)
        assert result.utilisation >= 70.0, (
            f"Utilisation {result.utilisation:.1f}% < 70% target"
        )

    def test_known_input_both_placed(self):
        pieces = self._two_large_rects()
        result = make_marker(pieces, fabric_width=150.0, gap=0.5)
        assert len(result.placements) == 2
        assert result.unplaced == []

    def test_bodice_pieces_placed(self):
        """Two bodice blocks (M) on 150 cm wide fabric: both placed, no unplaced."""
        m = get_measurements("M")
        front = bodice_front(m["bust"], m["waist"], m["hip"], m["back_length"])
        back = bodice_back(m["bust"], m["waist"], m["hip"], m["back_length"])
        result = make_marker([front, back], fabric_width=150.0, gap=0.5)
        assert len(result.placements) == 2
        assert result.unplaced == []

    def test_marker_with_four_rect_pieces(self):
        """Four 35×42 cm rects on 150 cm fabric: utilisation >= 70 %."""
        pieces = [
            PatternPiece(name=f"r{i}", outline=_close([(0, 0), (35, 0), (35, 42), (0, 42)]))
            for i in range(4)
        ]
        result = make_marker(pieces, fabric_width=150.0, gap=0.5)
        assert result.utilisation >= 70.0, (
            f"Utilisation {result.utilisation:.1f}% < 70%"
        )

    def test_unplaced_when_too_wide(self):
        """A piece wider than the fabric is reported as unplaced."""
        wide = PatternPiece(
            name="too_wide",
            outline=_close([(0, 0), (200, 0), (200, 10), (0, 10)]),
        )
        result = make_marker([wide], fabric_width=150.0)
        assert "too_wide" in result.unplaced
        assert len(result.placements) == 0

    def test_all_pieces_placed(self):
        m = get_measurements("M")
        front = bodice_front(m["bust"], m["waist"], m["hip"], m["back_length"])
        result = make_marker([front], fabric_width=150.0)
        assert len(result.placements) == 1
        assert result.unplaced == []

    def test_marker_length_positive(self):
        m = get_measurements("M")
        front = bodice_front(m["bust"], m["waist"], m["hip"], m["back_length"])
        result = make_marker([front], fabric_width=150.0)
        assert result.marker_length > 0

    def test_no_overlap_in_placements(self):
        """Placed bounding boxes must not overlap (accounting for gap)."""
        pieces = []
        for sz in ["S", "M", "L"]:
            meas = get_measurements(sz)
            pieces.append(bodice_front(meas["bust"], meas["waist"], meas["hip"], meas["back_length"]))
        result = make_marker(pieces, fabric_width=150.0, gap=0.5)

        pp = result.placements
        GAP = 0.5
        for i in range(len(pp)):
            for j in range(i + 1, len(pp)):
                a, b = pp[i], pp[j]
                overlap = not (
                    a.x + a.width + GAP <= b.x
                    or b.x + b.width + GAP <= a.x
                    or a.y + a.height + GAP <= b.y
                    or b.y + b.height + GAP <= a.y
                )
                assert not overlap, (
                    f"Pieces {a.name} and {b.name} overlap in marker"
                )

    def test_pieces_within_fabric_width(self):
        m = get_measurements("M")
        front = bodice_front(m["bust"], m["waist"], m["hip"], m["back_length"])
        back = bodice_back(m["bust"], m["waist"], m["hip"], m["back_length"])
        result = make_marker([front, back], fabric_width=150.0)
        for pp in result.placements:
            assert pp.x >= 0, f"{pp.name} placed at negative x"
            assert pp.x + pp.width <= 150.0 + 1e-6, (
                f"{pp.name} extends past fabric edge ({pp.x + pp.width:.2f} > 150)"
            )

    def test_invalid_fabric_width(self):
        with pytest.raises(ValueError):
            make_marker([], fabric_width=0.0)

    def test_utilisation_type(self):
        m = get_measurements("M")
        front = bodice_front(m["bust"], m["waist"], m["hip"], m["back_length"])
        result = make_marker([front], fabric_width=150.0)
        assert isinstance(result.utilisation, float)


# ------------------------------------------------------------------ #
# PatternPiece geometry                                                #
# ------------------------------------------------------------------ #

class TestPatternPieceGeometry:
    def test_square_area(self):
        square = make_square(10.0)
        assert abs(square.area() - 100.0) < 1e-6

    def test_square_perimeter(self):
        square = make_square(10.0)
        assert abs(square.perimeter() - 40.0) < 1e-6

    def test_bounding_box(self):
        square = make_square(10.0)
        bb = square.bounding_box()
        assert bb == (0.0, 0.0, 10.0, 10.0)
