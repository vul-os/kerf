"""Slice 6: Workshop media is files-in-repo, not a DB gallery.

The project_workshop_images table + its 6 endpoints + the
_enrich_with_primary_images helper are retired. Gallery images are now
image files under a project `workshop/` folder and a renderable file
there is surfaced as the 3D model pointer. Cover/thumbnail defaults are
unchanged (slice 4).
"""
import ast
import asyncio
import pathlib
from unittest.mock import AsyncMock

import kerf_api.routes as routes
from kerf_api.routes import _attach_workshop_media, _project_to_workshop_row

_MIG = (
    pathlib.Path(routes.__file__).parents[3]
    / "kerf-core/src/kerf_core/db/migrations/0009_workshop_gallery.sql"
)


def _run(c):
    return asyncio.get_event_loop().run_until_complete(c)


def test_gallery_table_and_dead_code_retired():
    sql = _MIG.read_text().lower()
    assert "create table if not exists project_workshop_images" not in sql
    src = pathlib.Path(routes.__file__).read_text()
    # No query against the dropped table, no resurrected helper, and the
    # old per-image endpoint path is gone.
    tree = ast.parse(src)
    assert not hasattr(routes, "_enrich_with_primary_images")
    assert "from project_workshop_images" not in src
    assert "/workshop-images" not in src
    # The replacement public route exists.
    assert "/projects/{pid}/workshop-media/{file_id}" in src
    ast.parse(src)  # still parses


def test_attach_workshop_media_derives_images_and_model():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[
        {"id": "img-1", "name": "a.png"},
        {"id": "img-2", "name": "b.jpg"},
    ])
    conn.fetchrow = AsyncMock(return_value={"id": "mdl-1", "name": "workshop.jscad"})
    proj = {}
    _run(_attach_workshop_media(conn, "pid-1", proj))
    assert [i["name"] for i in proj["workshop_images"]] == ["a.png", "b.jpg"]
    assert proj["workshop_model_id"] == "mdl-1"
    assert proj["workshop_model_name"] == "workshop.jscad"


def test_attach_handles_no_media():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    proj = {}
    _run(_attach_workshop_media(conn, "pid-1", proj))
    assert proj["workshop_images"] == []
    assert "workshop_model_id" not in proj


def test_row_maps_images_model_and_drops_primary_image_id():
    row = _project_to_workshop_row({
        "id": "p1", "name": "P", "created_at": None, "updated_at": None,
        "thumbnail_storage_key": "tkey",
        "workshop_images": [{"id": "i1", "name": "x.png"}],
        "workshop_model_id": "m1", "workshop_model_name": "workshop.stl",
    })
    assert "primary_image_id" not in row
    assert row["thumbnail_url"] == "/api/projects/p1/thumbnail"
    assert row["images"] == [
        {"id": "i1", "name": "x.png", "url": "/api/projects/p1/workshop-media/i1"}
    ]
    assert row["model_file_id"] == "m1"
    assert row["model_name"] == "workshop.stl"


def test_row_empty_media_is_safe():
    row = _project_to_workshop_row({
        "id": "p2", "name": "Q", "created_at": None, "updated_at": None,
    })
    assert row["images"] == []
    assert row["model_file_id"] is None
    assert row["thumbnail_url"] is None
