"""Slice 9: the Workshop fork counter was always 0.

POST /workshop/:slug/fork cloned a project but never recorded lineage,
and the project queries never counted forks — so forks_count fell back
to 0 in _project_to_workshop_row. This pins the wiring: a tracked
source column, the fork endpoint setting it, and the read queries
computing forks_count. Source/AST-level (no DB) — same approach as the
other DB-wiring regressions in this repo.
"""
import ast
import pathlib

import kerf_api.routes as api_routes
import kerf_core.db.queries.projects as proj_q

_MIG = (
    pathlib.Path(api_routes.__file__).parents[3]
    / "kerf-core/src/kerf_core/db/migrations/0009_workshop_gallery.sql"
)


def test_migration_tracks_fork_lineage():
    sql = _MIG.read_text().lower()
    assert "forked_from_project_id uuid" in sql
    assert "references projects(id) on delete set null" in sql
    assert "projects_forked_from_idx" in sql


def test_fork_endpoint_records_the_source():
    src = pathlib.Path(api_routes.__file__).read_text()
    # The fork INSERT must name the lineage column and pass the source id.
    i = src.index("def workshop_fork(")
    body = src[i:i + 4000]
    assert "forked_from_project_id" in body
    assert "source_project_id," in body


def test_queries_compute_forks_count():
    src = pathlib.Path(proj_q.__file__).read_text()
    # Both list_public_projects and get_public_project (viewer + anon)
    # must select forks_count and join the fork-count subquery.
    assert src.count("COALESCE(fk.forks_count, 0) AS forks_count") == 3
    assert src.count("SELECT forked_from_project_id AS project_id, COUNT(*) AS forks_count") == 3


def test_projects_py_still_parses():
    ast.parse(pathlib.Path(proj_q.__file__).read_text())
    ast.parse(pathlib.Path(api_routes.__file__).read_text())
