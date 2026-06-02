"""test_markup.py — pytest suite for the markup / redline engine."""
import importlib.util
import os
import sys
import tempfile
import types
import uuid
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Load markup.py without kerf_core / kerf_chat on the path
# ---------------------------------------------------------------------------

_MARKUP_PATH = os.path.join(
    os.path.dirname(__file__),
    "..", "src", "kerf_bim", "markup.py",
)

_spec = importlib.util.spec_from_file_location("kerf_bim.markup", _MARKUP_PATH)
_markup_mod = importlib.util.module_from_spec(_spec)
sys.modules["kerf_bim.markup"] = _markup_mod
_spec.loader.exec_module(_markup_mod)

MarkupShape = _markup_mod.MarkupShape
MarkupAnnotation = _markup_mod.MarkupAnnotation
MarkupLayer = _markup_mod.MarkupLayer
MarkupSession = _markup_mod.MarkupSession
add_annotation = _markup_mod.add_annotation
remove_annotation = _markup_mod.remove_annotation
set_layer_visibility = _markup_mod.set_layer_visibility
export_to_svg_overlay = _markup_mod.export_to_svg_overlay
export_to_pdf_overlay = _markup_mod.export_to_pdf_overlay
import_pdf_annotations = _markup_mod.import_pdf_annotations
merge_sessions = _markup_mod.merge_sessions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_circle(author="alice", page="1"):
    return MarkupAnnotation(
        guid=str(uuid.uuid4()),
        shape=MarkupShape.CIRCLE,
        xy_mm=[(50.0, 50.0), (60.0, 50.0)],
        color_rgb=(255, 0, 0),
        thickness_mm=0.5,
        author=author,
        page_or_view_id=page,
    )


def _make_session(target_id="dwg-001", target_type="drawing"):
    return MarkupSession(target_type=target_type, target_id=target_id)


# ---------------------------------------------------------------------------
# Test: add_annotation
# ---------------------------------------------------------------------------

class TestAddAnnotation:
    def test_circle_exists_in_layer(self):
        """Add a circle → it must exist in the named layer."""
        session = _make_session()
        ann = _make_circle()
        result = add_annotation(session, "review-1", ann)

        assert len(session.layers) == 1
        layer = session.layers[0]
        assert layer.name == "review-1"
        assert len(layer.annotations) == 1
        assert layer.annotations[0].shape == MarkupShape.CIRCLE
        assert result.guid == ann.guid

    def test_guid_assigned_when_empty(self):
        """A blank guid must be auto-assigned."""
        session = _make_session()
        ann = _make_circle()
        ann.guid = ""
        result = add_annotation(session, "layer-a", ann)
        assert result.guid != ""
        assert len(result.guid) == 36  # UUID4 canonical form

    def test_layer_auto_created(self):
        """Layer is created automatically if absent."""
        session = _make_session()
        add_annotation(session, "new-layer", _make_circle())
        assert any(l.name == "new-layer" for l in session.layers)

    def test_multiple_annotations_same_layer(self):
        """Multiple annotations accumulate in the same layer."""
        session = _make_session()
        for _ in range(3):
            add_annotation(session, "marks", _make_circle())
        assert len(session.layers) == 1
        assert len(session.layers[0].annotations) == 3

    def test_different_layers_stay_separate(self):
        """Annotations added to different layers don't bleed across."""
        session = _make_session()
        add_annotation(session, "layer-a", _make_circle())
        add_annotation(session, "layer-b", _make_circle())
        assert len(session.layers) == 2
        for l in session.layers:
            assert len(l.annotations) == 1


# ---------------------------------------------------------------------------
# Test: remove_annotation
# ---------------------------------------------------------------------------

class TestRemoveAnnotation:
    def test_remove_existing(self):
        session = _make_session()
        ann = add_annotation(session, "rev", _make_circle())
        ok = remove_annotation(session, ann.guid)
        assert ok is True
        assert len(session.layers[0].annotations) == 0

    def test_remove_missing_returns_false(self):
        session = _make_session()
        ok = remove_annotation(session, "nonexistent-guid")
        assert ok is False


# ---------------------------------------------------------------------------
# Test: set_layer_visibility
# ---------------------------------------------------------------------------

class TestSetLayerVisibility:
    def test_hide_layer(self):
        session = _make_session()
        add_annotation(session, "layer-x", _make_circle())
        ok = set_layer_visibility(session, "layer-x", False)
        assert ok is True
        assert session.layers[0].visible is False

    def test_missing_layer_returns_false(self):
        session = _make_session()
        ok = set_layer_visibility(session, "ghost", False)
        assert ok is False


# ---------------------------------------------------------------------------
# Test: export_to_svg_overlay
# ---------------------------------------------------------------------------

class TestExportSvgOverlay:
    def test_valid_xml_produced(self):
        """SVG export must produce parseable XML."""
        session = _make_session()
        for shape in [MarkupShape.CIRCLE, MarkupShape.RECTANGLE, MarkupShape.ARROW,
                      MarkupShape.FREEHAND, MarkupShape.TEXT, MarkupShape.HIGHLIGHT,
                      MarkupShape.STAMP]:
            ann = MarkupAnnotation(
                guid=str(uuid.uuid4()),
                shape=shape,
                xy_mm=[(10.0, 10.0), (30.0, 30.0)],
                color_rgb=(0, 0, 255),
                text_content="TEST",
            )
            add_annotation(session, "shapes", ann)

        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            out_path = f.name
        try:
            export_to_svg_overlay(session, out_path)
            tree = ET.parse(out_path)
            root = tree.getroot()
            assert root.tag.endswith("svg")
        finally:
            os.unlink(out_path)

    def test_svg_contains_paths_or_shapes(self):
        """SVG must have at least one child element for visible annotations."""
        session = _make_session()
        add_annotation(session, "layer", _make_circle())

        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            out_path = f.name
        try:
            export_to_svg_overlay(session, out_path)
            with open(out_path) as f:
                content = f.read()
            # At minimum a <g> layer wrapper and one shape element
            assert "<circle" in content or "<g" in content
        finally:
            os.unlink(out_path)

    def test_hidden_layer_excluded(self):
        """Annotations on a hidden layer must not appear in the SVG."""
        session = _make_session()
        add_annotation(session, "hidden-layer", _make_circle())
        set_layer_visibility(session, "hidden-layer", False)

        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            out_path = f.name
        try:
            export_to_svg_overlay(session, out_path)
            with open(out_path) as f:
                content = f.read()
            assert "hidden-layer" not in content
        finally:
            os.unlink(out_path)


# ---------------------------------------------------------------------------
# Test: export_to_pdf_overlay
# ---------------------------------------------------------------------------

class TestExportPdfOverlay:
    def test_pdf_file_written(self):
        """A PDF (or fallback stub) must be written to disk."""
        session = _make_session(target_type="pdf")
        add_annotation(session, "review", _make_circle())

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            out_path = f.name
        try:
            result = export_to_pdf_overlay(session, "/dev/null", out_path)
            assert result == out_path
            assert os.path.exists(out_path)
            assert os.path.getsize(out_path) > 0
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)


# ---------------------------------------------------------------------------
# Test: import_pdf_annotations
# ---------------------------------------------------------------------------

class TestImportPdfAnnotations:
    def test_returns_session_object(self):
        """import_pdf_annotations always returns a MarkupSession."""
        # Use a dummy path — pypdf won't be available so we get a stub session
        session = import_pdf_annotations("/nonexistent/dummy.pdf")
        assert isinstance(session, MarkupSession)
        assert session.target_type == "pdf"

    def test_target_id_is_filename(self):
        session = import_pdf_annotations("/some/path/drawing.pdf")
        assert session.target_id == "drawing.pdf"


# ---------------------------------------------------------------------------
# Test: merge_sessions
# ---------------------------------------------------------------------------

class TestMergeSessions:
    def _make_reviewer_session(self, reviewer: str, n: int = 2) -> MarkupSession:
        session = _make_session(target_id="shared-dwg")
        for i in range(n):
            ann = MarkupAnnotation(
                guid=str(uuid.uuid4()),
                shape=MarkupShape.CIRCLE,
                xy_mm=[(float(i * 10), float(i * 10))],
                color_rgb=(255, 0, 0),
                author=reviewer,
            )
            add_annotation(session, f"reviewer-{reviewer}", ann)
        return session

    def test_three_reviewers_combine(self):
        """Merge 3 sessions from different reviewers; all annotations present."""
        s1 = self._make_reviewer_session("alice", 2)
        s2 = self._make_reviewer_session("bob", 3)
        s3 = self._make_reviewer_session("carol", 1)

        merged = merge_sessions([s1, s2, s3])
        total = sum(len(l.annotations) for l in merged.layers)
        assert total == 6  # 2 + 3 + 1

    def test_same_layer_name_concatenated(self):
        """Annotations in same-named layers are concatenated, not duplicated as layers."""
        s1 = _make_session()
        s2 = _make_session()
        add_annotation(s1, "shared", _make_circle())
        add_annotation(s2, "shared", _make_circle())

        merged = merge_sessions([s1, s2])
        shared = [l for l in merged.layers if l.name == "shared"]
        assert len(shared) == 1
        assert len(shared[0].annotations) == 2

    def test_status_resolved_only_when_all_resolved(self):
        s1 = _make_session()
        s2 = _make_session()
        s1.status = "resolved"
        s2.status = "resolved"
        merged = merge_sessions([s1, s2])
        assert merged.status == "resolved"

    def test_status_draft_if_any_not_resolved(self):
        s1 = _make_session()
        s2 = _make_session()
        s1.status = "resolved"
        s2.status = "draft"
        merged = merge_sessions([s1, s2])
        assert merged.status == "draft"

    def test_empty_list_returns_empty_session(self):
        merged = merge_sessions([])
        assert isinstance(merged, MarkupSession)
        assert merged.layers == []
