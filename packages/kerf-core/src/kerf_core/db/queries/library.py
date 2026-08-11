import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

import asyncpg


async def list_public_parts(
    conn: asyncpg.Connection,
    search: Optional[str] = None,
    category: Optional[str] = None,
    verified_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """List parts (kind='part') from public projects.

    Returns {rows: [...], limit, total} matching the frontend shape:
      rows: [{file_id, project_id, slug, name, manufacturer, mpn,
               category, primary_photo_url, author}]
    """
    conditions = [
        "p.visibility = 'public'",
        "f.kind = 'part'",
        "f.deleted_at IS NULL",
    ]
    params: List[Any] = []
    param_idx = 1

    if verified_only:
        conditions.append("u.is_verified_publisher = TRUE")

    if category:
        conditions.append(f"(f.content::jsonb->>'category') ILIKE ${param_idx}")
        params.append(f"%{category}%")
        param_idx += 1

    if search:
        conditions.append(
            f"(f.name ILIKE ${param_idx} OR (f.content::jsonb->>'manufacturer') ILIKE ${param_idx} OR (f.content::jsonb->>'mpn') ILIKE ${param_idx})"
        )
        params.append(f"%{search}%")
        param_idx += 1

    where_clause = "WHERE " + " AND ".join(conditions)

    count_query = f"""
        SELECT COUNT(*) FROM files f
        JOIN projects p ON p.id = f.project_id
        JOIN workspaces w ON w.id = p.workspace_id
        JOIN users u ON u.id = w.created_by
        {where_clause}
    """
    total = await conn.fetchval(count_query, *params)

    limit_ph = f"${param_idx}"
    offset_ph = f"${param_idx + 1}"
    params.extend([limit, offset])

    query = f"""
        SELECT
            f.id            AS file_id,
            f.project_id,
            f.name,
            w.slug          AS workspace_slug,
            p.name          AS project_name,
            u.name          AS author,
            u.is_verified_publisher,
            f.content::jsonb->>'manufacturer'     AS manufacturer,
            f.content::jsonb->>'mpn'              AS mpn,
            f.content::jsonb->>'category'         AS category,
            f.content::jsonb->>'primary_photo_url' AS primary_photo_url,
            f.updated_at
        FROM files f
        JOIN projects p ON p.id = f.project_id
        JOIN workspaces w ON w.id = p.workspace_id
        JOIN users u ON u.id = w.created_by
        {where_clause}
        ORDER BY u.is_verified_publisher DESC, f.updated_at DESC
        LIMIT {limit_ph} OFFSET {offset_ph}
    """

    rows = await conn.fetch(query, *params)
    result_rows = []
    for row in rows:
        d = dict(row)
        d["file_id"] = str(d["file_id"])
        d["project_id"] = str(d["project_id"])
        # build slug: <workspace_slug>/<project_name_slugified>/<file_name>
        ws_slug = d.pop("workspace_slug", "")
        proj_name = d.pop("project_name", "")
        d["slug"] = f"{ws_slug}/{proj_name}/{d['name']}"
        result_rows.append(d)

    return {"rows": result_rows, "limit": limit, "total": int(total or 0)}


async def get_public_part(
    conn: asyncpg.Connection,
    file_id: uuid.UUID,
) -> Optional[Dict[str, Any]]:
    """Fetch a single part detail by file_id."""
    row = await conn.fetchrow(
        """
        SELECT
            f.id            AS file_id,
            f.project_id,
            f.name,
            f.content,
            w.slug          AS workspace_slug,
            p.name          AS project_name,
            u.name          AS author,
            u.is_verified_publisher,
            f.updated_at
        FROM files f
        JOIN projects p ON p.id = f.project_id
        JOIN workspaces w ON w.id = p.workspace_id
        JOIN users u ON u.id = w.created_by
        WHERE f.id = $1 AND f.kind = 'part' AND f.deleted_at IS NULL AND p.visibility = 'public'
        """,
        file_id,
    )
    return _shape_part_detail(row) if row else None


def _shape_part_detail(row) -> Dict[str, Any]:
    """Turn a part-detail row into the response body.

    Shared by both lookups so a part fetched by slug and the same part fetched
    by file_id are byte-identical — including the ``slug`` field, which is what
    the caller will use for the canonical URL.
    """
    d = dict(row)
    d["file_id"] = str(d["file_id"])
    d["project_id"] = str(d["project_id"])
    ws_slug = d.pop("workspace_slug", "")
    proj_name = d.pop("project_name", "")
    d["slug"] = f"{ws_slug}/{proj_name}/{d['name']}"
    # parse content JSON for the detail fields
    try:
        content_obj = json.loads(d.get("content") or "{}")
    except Exception:
        content_obj = {}
    d["content"] = content_obj
    d["manufacturer"] = content_obj.get("manufacturer")
    d["mpn"] = content_obj.get("mpn")
    d["category"] = content_obj.get("category")
    d["primary_photo_url"] = content_obj.get("primary_photo_url")
    d["description"] = content_obj.get("description")
    d["datasheet_url"] = content_obj.get("datasheet_url")
    d["photos"] = content_obj.get("photos", [])
    d["distributors"] = content_obj.get("distributors", [])
    d["source_project_slug"] = f"{ws_slug}/{proj_name}" if ws_slug and proj_name else None
    return d


_PART_DETAIL_SELECT = """
        SELECT
            f.id            AS file_id,
            f.project_id,
            f.name,
            f.content,
            w.slug          AS workspace_slug,
            p.name          AS project_name,
            u.name          AS author,
            u.is_verified_publisher,
            f.updated_at
        FROM files f
        JOIN projects p ON p.id = f.project_id
        JOIN workspaces w ON w.id = p.workspace_id
        JOIN users u ON u.id = w.created_by
"""


async def get_public_part_by_slug(
    conn: asyncpg.Connection,
    workspace_slug: str,
    project_name: str,
    file_name: str,
) -> Optional[Dict[str, Any]]:
    """Fetch a single part detail by its human-readable slug.

    The catalogue has always advertised parts as
    ``<workspace_slug>/<project_name>/<file_name>`` — that is what
    :func:`list_public_parts` puts in every row's ``slug`` and what the
    frontend navigates to. Nothing could resolve it: the detail route parsed
    the slug as a UUID and 404'd on anything else, with a comment calling
    path lookup "a future enhancement". So every click from the catalogue
    into a part landed on a 404.

    Matching is on the same three columns the slug is built from, so a part is
    reachable by exactly the identifier it was listed under.
    """
    row = await conn.fetchrow(
        _PART_DETAIL_SELECT + """
        WHERE w.slug = $1
          AND p.name = $2
          AND f.name = $3
          AND f.kind = 'part'
          AND f.deleted_at IS NULL
          AND p.visibility = 'public'
        """,
        workspace_slug, project_name, file_name,
    )
    return _shape_part_detail(row) if row else None


async def create_library_submission(
    conn: asyncpg.Connection,
    submitter_user_id: uuid.UUID,
    target_workspace_id: uuid.UUID,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    row = await conn.fetchrow(
        """
        INSERT INTO library_part_submissions (submitter_user_id, target_workspace_id, payload)
        VALUES ($1, $2, $3)
        RETURNING *
        """,
        submitter_user_id,
        target_workspace_id,
        # Serialised here, not passed as a dict. `payload` is jsonb, and
        # asyncpg does not encode a dict for it — it raises DataError
        # "expected str, got dict", so every submission 500'd on Postgres. It
        # worked on SQLite only because that backend's adapt_param serialises
        # dicts on the way through, which is the kind of asymmetry that hides
        # a bug on whichever backend the tests do not run against.
        json.dumps(payload if payload is not None else {}),
    )
    return dict(row)


async def get_library_submission(
    conn: asyncpg.Connection,
    submission_id: uuid.UUID,
) -> Optional[Dict[str, Any]]:
    row = await conn.fetchrow(
        "SELECT * FROM library_part_submissions WHERE id = $1",
        submission_id,
    )
    return dict(row) if row else None


async def list_library_submissions(
    conn: asyncpg.Connection,
    status: Optional[str] = None,
    target_workspace_id: Optional[uuid.UUID] = None,
    submitter_user_id: Optional[uuid.UUID] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    conditions = []
    params = []
    param_idx = 1

    if status:
        conditions.append(f"status = ${param_idx}")
        params.append(status)
        param_idx += 1

    if target_workspace_id:
        conditions.append(f"target_workspace_id = ${param_idx}")
        params.append(target_workspace_id)
        param_idx += 1

    if submitter_user_id:
        conditions.append(f"submitter_user_id = ${param_idx}")
        params.append(submitter_user_id)
        param_idx += 1

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    query = f"""
        SELECT * FROM library_part_submissions
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
    """
    params.extend([limit, offset])

    rows = await conn.fetch(query, *params)
    return [dict(row) for row in rows]


async def approve_library_submission(
    conn: asyncpg.Connection,
    submission_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    review_note: str = "",
) -> Optional[Dict[str, Any]]:
    row = await conn.fetchrow(
        """
        UPDATE library_part_submissions
        SET status = 'approved', reviewer_id = $2, review_note = $3, updated_at = now()
        WHERE id = $1 AND status = 'pending'
        RETURNING *
        """,
        submission_id,
        reviewer_id,
        review_note,
    )
    return dict(row) if row else None


async def reject_library_submission(
    conn: asyncpg.Connection,
    submission_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    review_note: str = "",
) -> Optional[Dict[str, Any]]:
    row = await conn.fetchrow(
        """
        UPDATE library_part_submissions
        SET status = 'rejected', reviewer_id = $2, review_note = $3, updated_at = now()
        WHERE id = $1 AND status = 'pending'
        RETURNING *
        """,
        submission_id,
        reviewer_id,
        review_note,
    )
    return dict(row) if row else None
