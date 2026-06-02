"""
tests/test_bcf.py — BCF 3.0 issue-manager tests.

Covers:
  - create_topic → exists in project
  - add_comment → comment count ++
  - add_viewpoint
  - update_topic_status
  - invalid status / priority / topic_type raise ValueError
  - export_bcf_zip → valid ZIP with expected structure
  - import_bcf_zip → round-trip preserves topics / comments / viewpoints
  - status update reflected on export + re-import
  - summarize_project counts
  - import of empty project
"""

from __future__ import annotations

import json
import os
import tempfile
import zipfile

import pytest

from kerf_bim.bcf import (
    BcfProject,
    add_comment,
    add_viewpoint,
    create_topic,
    export_bcf_zip,
    import_bcf_zip,
    summarize_project,
    update_topic_status,
    _new_guid,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_project(name: str = "Test Project") -> BcfProject:
    return BcfProject(project_id=_new_guid(), name=name)


# ── 1. create_topic → topic exists in project ─────────────────────────────────

def test_create_topic_appends():
    p = _make_project()
    assert len(p.topics) == 0
    t = create_topic(p, title="Beam clash at grid A1", topic_type="Clash")
    assert len(p.topics) == 1
    assert p.topics[0].guid == t.guid
    assert p.topics[0].title == "Beam clash at grid A1"


def test_create_topic_defaults():
    p = _make_project()
    t = create_topic(p, title="Issue")
    assert t.topic_type == "Issue"
    assert t.priority == "Normal"
    assert t.status == "Open"


def test_create_topic_all_types():
    p = _make_project()
    for tp in ("Clash", "Issue", "Request", "Fault", "Inquiry"):
        create_topic(p, title=f"Type {tp}", topic_type=tp)
    assert len(p.topics) == 5


def test_create_topic_invalid_type_raises():
    p = _make_project()
    with pytest.raises(ValueError, match="topic_type"):
        create_topic(p, title="Bad", topic_type="Blocker")


def test_create_topic_invalid_priority_raises():
    p = _make_project()
    with pytest.raises(ValueError, match="priority"):
        create_topic(p, title="Bad", priority="High")


def test_create_topic_invalid_status_raises():
    p = _make_project()
    with pytest.raises(ValueError, match="status"):
        create_topic(p, title="Bad", status="Pending")


# ── 2. add_comment → comment count ++ ────────────────────────────────────────

def test_add_comment_increments():
    p = _make_project()
    t = create_topic(p, title="Clash")
    assert len(p.comments) == 0
    add_comment(p, t.guid, "First comment", author="alice@example.com")
    assert len(p.comments) == 1
    add_comment(p, t.guid, "Follow-up", author="bob@example.com")
    assert len(p.comments) == 2


def test_add_comment_unknown_topic_raises():
    p = _make_project()
    with pytest.raises(ValueError, match="not found"):
        add_comment(p, _new_guid(), "Orphan comment")


def test_add_comment_fields():
    p = _make_project()
    t = create_topic(p, title="X")
    c = add_comment(p, t.guid, "Some text", author="dev@example.com")
    assert c.comment == "Some text"
    assert c.author == "dev@example.com"
    assert c.topic_guid == t.guid


# ── 3. add_viewpoint ─────────────────────────────────────────────────────────

def test_add_viewpoint_appends():
    p = _make_project()
    t = create_topic(p, title="Vp test")
    vp = add_viewpoint(p, t.guid, (1, 2, 3), (4, 5, 6), field_of_view_deg=45.0)
    assert len(p.viewpoints) == 1
    assert vp.camera_position_xyz == (1, 2, 3)
    assert vp.camera_target_xyz == (4, 5, 6)
    assert vp.field_of_view_deg == 45.0


# ── 4. update_topic_status ───────────────────────────────────────────────────

def test_update_topic_status_success():
    p = _make_project()
    t = create_topic(p, title="Status test", status="Open")
    ok = update_topic_status(p, t.guid, "Resolved")
    assert ok is True
    assert p.topics[0].status == "Resolved"


def test_update_topic_status_not_found():
    p = _make_project()
    result = update_topic_status(p, _new_guid(), "Closed")
    assert result is False


def test_update_topic_status_invalid_raises():
    p = _make_project()
    t = create_topic(p, title="X")
    with pytest.raises(ValueError, match="new_status"):
        update_topic_status(p, t.guid, "Done")


# ── 5. export_bcf_zip produces a valid ZIP ───────────────────────────────────

def test_export_produces_zip():
    p = _make_project("Export Test")
    t = create_topic(p, title="Clash 1", topic_type="Clash", priority="Critical")
    add_comment(p, t.guid, "Needs fix", author="eng@example.com")
    add_viewpoint(p, t.guid, (0, 0, 10), (5, 5, 0))

    with tempfile.NamedTemporaryFile(suffix=".bcf", delete=False) as f:
        path = f.name
    try:
        result = export_bcf_zip(p, path)
        assert result["topics"] == 1
        assert result["comments"] == 1
        assert result["viewpoints"] == 1
        assert result["path"] == path

        assert zipfile.is_zipfile(path)
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            assert "bcf.version" in names
            assert "project.bcfp" in names
            assert f"{t.guid}/markup.bcf" in names

            version = json.loads(zf.read("bcf.version"))
            assert version["VersionId"] == "3.0"

            project_meta = json.loads(zf.read("project.bcfp"))
            assert project_meta["Project"]["Name"] == "Export Test"
    finally:
        os.unlink(path)


# ── 6. import_bcf_zip round-trip ──────────────────────────────────────────────

def test_round_trip_topics():
    p = _make_project("RoundTrip")
    t1 = create_topic(p, title="Clash A", topic_type="Clash", priority="Critical",
                      assigned_to="alice@example.com")
    t2 = create_topic(p, title="Issue B", topic_type="Issue", priority="Minor",
                      status="In Progress")
    add_comment(p, t1.guid, "First", author="alice@example.com")
    add_comment(p, t1.guid, "Second", author="bob@example.com")
    add_viewpoint(p, t2.guid, (1, 2, 3), (0, 0, 0))

    with tempfile.NamedTemporaryFile(suffix=".bcf", delete=False) as f:
        path = f.name
    try:
        export_bcf_zip(p, path)
        p2 = import_bcf_zip(path)

        assert len(p2.topics) == 2
        assert len(p2.comments) == 2
        assert len(p2.viewpoints) == 1

        guids_out = {t.guid for t in p2.topics}
        assert t1.guid in guids_out
        assert t2.guid in guids_out

        topic_a = next(t for t in p2.topics if t.guid == t1.guid)
        assert topic_a.title == "Clash A"
        assert topic_a.topic_type == "Clash"
        assert topic_a.priority == "Critical"
        assert topic_a.assigned_to == "alice@example.com"

        topic_b = next(t for t in p2.topics if t.guid == t2.guid)
        assert topic_b.status == "In Progress"
    finally:
        os.unlink(path)


def test_round_trip_comments():
    p = _make_project()
    t = create_topic(p, title="T")
    add_comment(p, t.guid, "Hello", author="x@example.com")
    add_comment(p, t.guid, "World", author="y@example.com")

    with tempfile.NamedTemporaryFile(suffix=".bcf", delete=False) as f:
        path = f.name
    try:
        export_bcf_zip(p, path)
        p2 = import_bcf_zip(path)
        comments = [c for c in p2.comments if c.topic_guid == t.guid]
        texts = {c.comment for c in comments}
        assert "Hello" in texts
        assert "World" in texts
    finally:
        os.unlink(path)


def test_round_trip_viewpoints():
    p = _make_project()
    t = create_topic(p, title="V")
    add_viewpoint(p, t.guid, (10, 20, 30), (0, 0, 0), field_of_view_deg=75.0)

    with tempfile.NamedTemporaryFile(suffix=".bcf", delete=False) as f:
        path = f.name
    try:
        export_bcf_zip(p, path)
        p2 = import_bcf_zip(path)
        assert len(p2.viewpoints) == 1
        vp = p2.viewpoints[0]
        assert vp.camera_position_xyz == (10.0, 20.0, 30.0)
        assert vp.field_of_view_deg == 75.0
    finally:
        os.unlink(path)


# ── 7. Status update reflected on export + re-import ─────────────────────────

def test_status_update_persists_through_round_trip():
    p = _make_project()
    t = create_topic(p, title="Update test", status="Open")
    update_topic_status(p, t.guid, "Resolved")

    with tempfile.NamedTemporaryFile(suffix=".bcf", delete=False) as f:
        path = f.name
    try:
        export_bcf_zip(p, path)
        p2 = import_bcf_zip(path)
        imported_topic = next(t2 for t2 in p2.topics if t2.guid == t.guid)
        assert imported_topic.status == "Resolved"
    finally:
        os.unlink(path)


# ── 8. summarize_project ──────────────────────────────────────────────────────

def test_summarize_project():
    p = _make_project()
    t1 = create_topic(p, title="C1", status="Open", priority="Critical")
    t2 = create_topic(p, title="C2", status="Open", priority="Normal")
    t3 = create_topic(p, title="C3", status="Resolved", priority="Minor")
    add_comment(p, t1.guid, "c")
    add_comment(p, t1.guid, "d")
    add_viewpoint(p, t2.guid, (0, 0, 1), (0, 0, 0))

    s = summarize_project(p)
    assert s["total_topics"] == 3
    assert s["total_comments"] == 2
    assert s["total_viewpoints"] == 1
    assert s["status_open"] == 2
    assert s["status_resolved"] == 1
    assert s["priority_critical"] == 1
    assert s["priority_normal"] == 1
    assert s["priority_minor"] == 1


# ── 9. Import of empty project ────────────────────────────────────────────────

def test_import_empty_project():
    p = _make_project("Empty")
    with tempfile.NamedTemporaryFile(suffix=".bcf", delete=False) as f:
        path = f.name
    try:
        export_bcf_zip(p, path)
        p2 = import_bcf_zip(path)
        assert p2.name == "Empty"
        assert len(p2.topics) == 0
        assert len(p2.comments) == 0
        assert len(p2.viewpoints) == 0
    finally:
        os.unlink(path)


# ── 10. Multiple topics with independent comments ─────────────────────────────

def test_comments_scoped_to_correct_topic():
    p = _make_project()
    t1 = create_topic(p, title="T1")
    t2 = create_topic(p, title="T2")
    add_comment(p, t1.guid, "for T1")
    add_comment(p, t2.guid, "for T2")

    t1_comments = [c for c in p.comments if c.topic_guid == t1.guid]
    t2_comments = [c for c in p.comments if c.topic_guid == t2.guid]
    assert len(t1_comments) == 1
    assert len(t2_comments) == 1
    assert t1_comments[0].comment == "for T1"
    assert t2_comments[0].comment == "for T2"
