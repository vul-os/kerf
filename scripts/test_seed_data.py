"""Pytest suite for seed_dev_data.py.

Runs against an in-process SQLite database — no real Postgres required.
Skips gracefully if SQLAlchemy is not installed.
"""
from __future__ import annotations

import importlib
import os
import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Skip the whole module if SQLAlchemy is absent
# ---------------------------------------------------------------------------
sa = pytest.importorskip("sqlalchemy", reason="sqlalchemy not installed — skipping seed tests")


# ---------------------------------------------------------------------------
# Point DATABASE_URL at a transient SQLite DB (no Postgres needed in CI/tests)
# ---------------------------------------------------------------------------
os.environ.setdefault("DATABASE_URL", "sqlite:///")  # in-memory SQLite


def _load_seed_module() -> types.ModuleType:
    """Import scripts/seed_dev_data.py as a module regardless of PYTHONPATH."""
    scripts_dir = os.path.join(os.path.dirname(__file__))
    seed_path = os.path.join(scripts_dir, "seed_dev_data.py")
    spec = importlib.util.spec_from_file_location("seed_dev_data", seed_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixture: in-memory SQLite engine (shared across the test session)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def seed_engine():
    from sqlalchemy import create_engine
    return create_engine("sqlite://", future=True)


@pytest.fixture(scope="module")
def seeded_conn(seed_engine):
    """Run seed once, return an open connection for inspection."""
    mod = _load_seed_module()

    # Patch DATABASE_URL inside the module to use our sqlite engine
    original_url = mod.DATABASE_URL

    def patched_get_engine():
        return seed_engine

    mod._get_engine = patched_get_engine

    with seed_engine.begin() as conn:
        mod._ensure_tables(conn)
        user_id = mod._upsert_user(conn)
        workspace_id = mod._upsert_workspace(conn, user_id)

        mod.seed_bim_project(conn, workspace_id)
        mod.seed_mechanical_project(conn, workspace_id)
        mod.seed_pcb_project(conn, workspace_id)
        mod.seed_library_project(conn, workspace_id)

    # Return a connection for queries
    conn = seed_engine.connect()
    yield conn, workspace_id
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_four_projects_created(seeded_conn):
    from sqlalchemy import text
    conn, workspace_id = seeded_conn
    rows = conn.execute(
        text("SELECT name FROM projects WHERE workspace_id = :wid ORDER BY name"),
        {"wid": workspace_id},
    ).fetchall()
    names = [r[0] for r in rows]
    assert len(names) == 4, f"Expected 4 seed projects, got {len(names)}: {names}"


def test_all_seed_prefixes_present(seeded_conn):
    from sqlalchemy import text
    conn, workspace_id = seeded_conn
    rows = conn.execute(
        text("SELECT name FROM projects WHERE workspace_id = :wid AND name LIKE '_seed_%'"),
        {"wid": workspace_id},
    ).fetchall()
    names = {r[0] for r in rows}
    assert "_seed_BIM Example" in names
    assert "_seed_Mechanical Part" in names
    assert "_seed_PCB Example" in names
    assert "_seed_Component Library" in names


def test_bim_project_has_files(seeded_conn):
    from sqlalchemy import text
    conn, workspace_id = seeded_conn
    project = conn.execute(
        text("SELECT id FROM projects WHERE workspace_id = :wid AND name = '_seed_BIM Example'"),
        {"wid": workspace_id},
    ).fetchone()
    assert project is not None
    files = conn.execute(
        text("SELECT COUNT(*) FROM files WHERE project_id = :pid"),
        {"pid": project[0]},
    ).scalar()
    assert files >= 6, f"BIM project should have ≥6 files, got {files}"


def test_mechanical_project_has_features(seeded_conn):
    import json
    from sqlalchemy import text
    conn, workspace_id = seeded_conn
    project = conn.execute(
        text("SELECT id FROM projects WHERE workspace_id = :wid AND name = '_seed_Mechanical Part'"),
        {"wid": workspace_id},
    ).fetchone()
    assert project is not None
    part_file = conn.execute(
        text("SELECT content FROM files WHERE project_id = :pid AND kind = 'part'"),
        {"pid": project[0]},
    ).fetchone()
    assert part_file is not None
    content = json.loads(part_file[0])
    features = content.get("features", [])
    assert len(features) == 5, f"Mechanical part should have 5 features, got {len(features)}"


def test_pcb_project_has_three_components(seeded_conn):
    import json
    from sqlalchemy import text
    conn, workspace_id = seeded_conn
    project = conn.execute(
        text("SELECT id FROM projects WHERE workspace_id = :wid AND name = '_seed_PCB Example'"),
        {"wid": workspace_id},
    ).fetchone()
    assert project is not None
    circuit = conn.execute(
        text("SELECT content FROM files WHERE project_id = :pid AND kind = 'circuit'"),
        {"pid": project[0]},
    ).fetchone()
    assert circuit is not None
    content = json.loads(circuit[0])
    components = content["schematic"]["components"]
    assert len(components) == 3, f"PCB should have 3 components, got {len(components)}"
    refs = {c["ref"] for c in components}
    assert refs == {"R1", "C1", "D1"}


def test_library_project_has_ten_parts(seeded_conn):
    from sqlalchemy import text
    conn, workspace_id = seeded_conn
    project = conn.execute(
        text("SELECT id FROM projects WHERE workspace_id = :wid AND name = '_seed_Component Library'"),
        {"wid": workspace_id},
    ).fetchone()
    assert project is not None
    count = conn.execute(
        text("SELECT COUNT(*) FROM files WHERE project_id = :pid AND kind = 'part'"),
        {"pid": project[0]},
    ).scalar()
    assert count == 10, f"Library should have 10 parts, got {count}"


def test_idempotent_re_run(seeded_conn, seed_engine):
    """Re-running the seed should not create duplicate projects."""
    from sqlalchemy import text
    conn, workspace_id = seeded_conn
    mod = _load_seed_module()

    def patched_get_engine():
        return seed_engine

    mod._get_engine = patched_get_engine

    # Run again — all should be skipped
    with seed_engine.begin() as conn2:
        r0 = mod.seed_bim_project(conn2, workspace_id)
        r1 = mod.seed_mechanical_project(conn2, workspace_id)
        r2 = mod.seed_pcb_project(conn2, workspace_id)
        r3 = mod.seed_library_project(conn2, workspace_id)

    assert r0 == 0 and r1 == 0 and r2 == 0 and r3 == 0, "All re-runs should skip (idempotent)"

    # Still only 4 projects
    total = conn.execute(
        text("SELECT COUNT(*) FROM projects WHERE workspace_id = :wid"),
        {"wid": workspace_id},
    ).scalar()
    assert total == 4
