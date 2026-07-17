"""Local git API (MIT) — a thin subprocess-git wrapper over each project's
own repo.

Per the 2026-07-17 "Addendum: local git only; no OAuth; accounts shrink to
the box" ADR, hosted git dies as a product: a kerf project is a plain git
repo, and collaboration is `git push`/`pull` against whatever remote the
user configures, using the user's own ambient credentials (SSH agent /
credential helper) — never a server-held OAuth token.

Project -> filesystem mapping
------------------------------
Projects are not laid out as an ordinary working-tree directory on disk —
file content lives in the `files` table (inline or offloaded to the object
store), and the git integration kerf already ships
(``kerf_core.storage.git_storer.resolve_project_repo`` /
``kerf_core.storage.materialize.materialize_and_commit``, used by this
package's own ``routes_git_diff.py``) targets a per-project **bare** repo
at ``workspaces/{project_id}/git`` under the storage root. That resolver is
reused here as "how projects map to filesystem paths": ``repo_dir`` is the
``-C <project_dir>`` this module always runs git against.

Because there is no checked-out working tree, two operations necessarily
reuse the existing pygit2-based machinery instead of a literal `git add` +
`git commit` subprocess pair:
  * ``commit`` reuses ``materialize_and_commit`` (already the single place
    that turns the live `files` table into a real git commit).
  * ``status``'s ``dirty`` flag is computed the same way kerf-cloud's
    (now-retired) hosted git status route did: diffing the live `files`
    table against the HEAD tree.
Every other verb (``init``, ``log``, ``remotes``, ``push``, ``pull``) is a
literal ``git -C <repo_dir> ...`` subprocess call, so push/pull pick up the
caller's ambient SSH agent / credential helper exactly like the git CLI.
"""

from __future__ import annotations

import logging
import os
import subprocess
import uuid as uuid_mod
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from kerf_core.db.connection import get_pool_required
from kerf_core.dependencies import require_auth
from kerf_core.storage import get_storage_required
from kerf_core.storage.git_storer import resolve_project_repo
from kerf_core.storage.materialize import FileEntry, materialize_and_commit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/git", tags=["git-local"])

_GIT_TIMEOUT_SECONDS = 30


# ---------------------------------------------------------------------------
# Auth / project helpers (mirrors routes_git_diff.py's pattern: a user may
# only touch projects owned by a workspace they are a member of).
# ---------------------------------------------------------------------------


async def _get_project_and_role(pid: str, user_id: str) -> tuple[dict, str]:
    """Return (project row, caller's workspace role) or raise 404.

    404 (not 403) on non-membership so membership is never revealed, same
    convention as the rest of kerf-api's project routes.
    """
    pool = await get_pool_required()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, workspace_id, name FROM projects WHERE id = $1",
            pid,
        )
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

        ws_id = str(row["workspace_id"])
        member = await conn.fetchrow(
            "SELECT role FROM workspace_members WHERE workspace_id = $1 AND user_id = $2",
            ws_id, user_id,
        )
        if not member:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

        return dict(row), member["role"]


async def _require_editor(pid: str, user_id: str) -> dict:
    project, role = await _get_project_and_role(pid, user_id)
    if role not in ("owner", "editor", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="editor or owner role required")
    return project


# ---------------------------------------------------------------------------
# git subprocess helper
# ---------------------------------------------------------------------------


def _run_git(args: list[str], repo_dir: str, *, check: bool = True) -> subprocess.CompletedProcess:
    """Run ``git -C repo_dir <args>``, inheriting the caller's ambient
    environment (SSH_AUTH_SOCK, credential helpers, GIT_SSH_COMMAND, ...).

    Never raises for a non-zero exit unless ``check`` — callers that want a
    clean 4xx surface the stripped stderr themselves.
    """
    return subprocess.run(
        ["git", "-C", repo_dir, *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
    )


def _clean_stderr(proc: subprocess.CompletedProcess) -> str:
    return (proc.stderr or proc.stdout or "git command failed").strip()


def _repo_dir_for(pid: str) -> str:
    storage = get_storage_required()
    loc = resolve_project_repo(pid, storage)
    # Best-effort hydration for the S3-backed storage mode: the canonical
    # repo lives in the object store and repo_dir is a server-local working
    # copy that may not exist yet on this process.
    if loc.s3_prefix is not None and not os.path.isdir(loc.repo_dir):
        try:
            from kerf_core.storage.s3 import S3Storage
            from kerf_core.storage.git_storer import S3GitStorer

            if isinstance(storage, S3Storage):
                S3GitStorer(storage, storage.bucket, loc.s3_prefix).clone_to_local(loc.repo_dir)
        except Exception as exc:  # pragma: no cover - best effort only
            logger.warning("git-local: S3 hydration failed for %s: %s", pid, exc)
    return loc.repo_dir


def _is_initialized(repo_dir: str) -> bool:
    if not os.path.isdir(repo_dir):
        return False
    proc = _run_git(["rev-parse", "--git-dir"], repo_dir)
    return proc.returncode == 0


# ---------------------------------------------------------------------------
# GET /api/git/{pid}/status
# ---------------------------------------------------------------------------


async def _collect_live_file_map(conn, project_id: str) -> dict[str, bytes]:
    """Materialize project's current file tree (path -> bytes), mirroring the
    now-retired kerf-cloud hosted-git status handler's `_collect_file_entries`.
    """
    rows = await conn.fetch(
        "SELECT id, parent_id, name, kind, content, storage_key "
        "FROM files WHERE project_id = $1 AND deleted_at IS NULL",
        project_id,
    )
    by_id = {r["id"]: r for r in rows}

    def _full_path(row) -> str:
        segs = [row["name"]]
        seen = set()
        cur = row["parent_id"]
        while cur is not None and cur not in seen:
            seen.add(cur)
            parent = by_id.get(cur)
            if parent is None:
                break
            segs.append(parent["name"])
            cur = parent["parent_id"]
        return "/".join(reversed(segs))

    storage = get_storage_required()
    live: dict[str, bytes] = {}
    for r in rows:
        if r["kind"] == "folder":
            continue
        if r["storage_key"]:
            stream, _ct = await storage.get(r["storage_key"])
            try:
                content = stream.read()
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
        else:
            content = (r["content"] or "").encode("utf-8")
        live[_full_path(r)] = content
    return live


def _head_tree_map(repo_dir: str) -> dict[str, bytes]:
    """Walk HEAD's tree via pygit2 (bare repo — no `git diff` working tree
    to compare against, so this mirrors the file-content comparison the
    retired kerf-cloud git-status route used)."""
    import pygit2

    head_map: dict[str, bytes] = {}
    try:
        repo = pygit2.Repository(repo_dir)
        head_ref = repo.head
        head_commit = repo.get(head_ref.target)
    except (pygit2.GitError, KeyError):
        return head_map
    if head_commit is None:
        return head_map

    def _walk(tree, prefix=""):
        for entry in tree:
            full = f"{prefix}{entry.name}" if not prefix else f"{prefix}/{entry.name}"
            obj = repo.get(entry.id)
            if obj is None:
                continue
            if isinstance(obj, pygit2.Tree):
                _walk(obj, full)
            elif isinstance(obj, pygit2.Blob):
                head_map[full] = bytes(obj.data)

    _walk(head_commit.tree)
    return head_map


def _current_branch(repo_dir: str) -> Optional[str]:
    proc = _run_git(["symbolic-ref", "--short", "-q", "HEAD"], repo_dir)
    if proc.returncode == 0:
        name = proc.stdout.strip()
        return name or None
    return None


def _ahead_behind(repo_dir: str, branch: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    if not branch:
        return None, None
    upstream_proc = _run_git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{branch}@{{upstream}}"],
        repo_dir,
    )
    if upstream_proc.returncode != 0:
        return None, None
    upstream = upstream_proc.stdout.strip()
    count_proc = _run_git(
        ["rev-list", "--left-right", "--count", f"{branch}...{upstream}"],
        repo_dir,
    )
    if count_proc.returncode != 0:
        return None, None
    parts = count_proc.stdout.strip().split()
    if len(parts) != 2:
        return None, None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None, None


def _list_remotes(repo_dir: str) -> list[dict]:
    proc = _run_git(["remote", "-v"], repo_dir)
    if proc.returncode != 0:
        return []
    seen: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name, url = parts[0], parts[1]
        seen.setdefault(name, url)
    return [{"name": n, "url": u} for n, u in seen.items()]


@router.get("/{pid}/status")
async def git_status(pid: str, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    await _get_project_and_role(pid, user_id)

    repo_dir = _repo_dir_for(pid)
    if not _is_initialized(repo_dir):
        return {
            "initialized": False,
            "branch": None,
            "dirty": False,
            "ahead": None,
            "behind": None,
            "remotes": [],
        }

    branch = _current_branch(repo_dir)

    pool = await get_pool_required()
    async with pool.acquire() as conn:
        live_map = await _collect_live_file_map(conn, pid)
    head_map = _head_tree_map(repo_dir)
    dirty = live_map != head_map

    ahead, behind = _ahead_behind(repo_dir, branch)

    return {
        "initialized": True,
        "branch": branch,
        "dirty": dirty,
        "ahead": ahead,
        "behind": behind,
        "remotes": _list_remotes(repo_dir),
    }


# ---------------------------------------------------------------------------
# POST /api/git/{pid}/init
# ---------------------------------------------------------------------------


@router.post("/{pid}/init")
async def git_init(pid: str, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    await _require_editor(pid, user_id)

    repo_dir = _repo_dir_for(pid)
    if _is_initialized(repo_dir):
        return await git_status(pid, payload)

    os.makedirs(repo_dir, exist_ok=True)
    proc = _run_git(["init", "--bare", "--initial-branch=main", repo_dir], repo_dir)
    if proc.returncode != 0:
        # Older git (<2.28) doesn't support --initial-branch; fall back.
        proc = _run_git(["init", "--bare", repo_dir], repo_dir)
        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail=_clean_stderr(proc))
        _run_git(["symbolic-ref", "HEAD", "refs/heads/main"], repo_dir)

    return await git_status(pid, payload)


# ---------------------------------------------------------------------------
# POST /api/git/{pid}/commit
# ---------------------------------------------------------------------------


class CommitRequest(BaseModel):
    message: str


@router.post("/{pid}/commit")
async def git_commit(pid: str, body: CommitRequest, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    project = await _require_editor(pid, user_id)

    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    repo_dir = _repo_dir_for(pid)
    branch = _current_branch(repo_dir) or "main"

    pool = await get_pool_required()
    async with pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT name, email FROM users WHERE id = $1", user_id)
        live_map = await _collect_live_file_map(conn, pid)
        entries = [FileEntry(path=p, content=c) for p, c in live_map.items()]

        try:
            result = await materialize_and_commit(
                repo_dir=repo_dir,
                files=entries,
                project_id=uuid_mod.UUID(str(pid)),
                workspace_id=project["workspace_id"],
                storage=get_storage_required(),
                db_conn=conn,
                message=message,
                author_name=(user_row["name"] if user_row else None) or "Kerf",
                author_email=(user_row["email"] if user_row else None) or "noreply@kerf.dev",
                branch=branch,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"commit failed: {exc}")

    return {"sha": result.commit_sha}


# ---------------------------------------------------------------------------
# GET /api/git/{pid}/log
# ---------------------------------------------------------------------------

_LOG_FIELD_SEP = "\x1f"
_LOG_FORMAT = _LOG_FIELD_SEP.join(["%H", "%s", "%an <%ae>", "%at"])


@router.get("/{pid}/log")
async def git_log(pid: str, limit: int = 50, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    await _get_project_and_role(pid, user_id)

    repo_dir = _repo_dir_for(pid)
    if not _is_initialized(repo_dir):
        return []

    limit = max(1, min(limit, 1000))
    proc = _run_git(["log", f"-n{limit}", f"--format={_LOG_FORMAT}"], repo_dir)
    if proc.returncode != 0:
        # Unborn HEAD (no commits yet) — an empty, freshly-init'd repo.
        return []

    commits = []
    for line in proc.stdout.splitlines():
        parts = line.split(_LOG_FIELD_SEP)
        if len(parts) != 4:
            continue
        sha, message, author, ts_raw = parts
        try:
            ts = int(ts_raw)
        except ValueError:
            ts = None
        commits.append({"sha": sha, "message": message, "author": author, "ts": ts})
    return commits


# ---------------------------------------------------------------------------
# GET/POST /api/git/{pid}/remotes, DELETE /api/git/{pid}/remotes/{name}
# ---------------------------------------------------------------------------


class RemoteRequest(BaseModel):
    name: str
    url: str


@router.get("/{pid}/remotes")
async def list_remotes(pid: str, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    await _get_project_and_role(pid, user_id)

    repo_dir = _repo_dir_for(pid)
    if not _is_initialized(repo_dir):
        return []
    return _list_remotes(repo_dir)


@router.post("/{pid}/remotes")
async def add_remote(pid: str, body: RemoteRequest, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    await _require_editor(pid, user_id)

    name = (body.name or "").strip()
    url = (body.url or "").strip()
    if not name or not url:
        raise HTTPException(status_code=400, detail="name and url are required")

    repo_dir = _repo_dir_for(pid)
    if not _is_initialized(repo_dir):
        raise HTTPException(status_code=409, detail="project has no git repo yet — call init first")

    existing = {r["name"] for r in _list_remotes(repo_dir)}
    if name in existing:
        proc = _run_git(["remote", "set-url", name, url], repo_dir)
    else:
        proc = _run_git(["remote", "add", name, url], repo_dir)
    if proc.returncode != 0:
        raise HTTPException(status_code=400, detail=_clean_stderr(proc))

    return {"name": name, "url": url}


@router.delete("/{pid}/remotes/{name}")
async def delete_remote(pid: str, name: str, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    await _require_editor(pid, user_id)

    repo_dir = _repo_dir_for(pid)
    if not _is_initialized(repo_dir):
        raise HTTPException(status_code=404, detail="project has no git repo")

    proc = _run_git(["remote", "remove", name], repo_dir)
    if proc.returncode != 0:
        raise HTTPException(status_code=404, detail=_clean_stderr(proc))

    return {"name": name, "removed": True}


# ---------------------------------------------------------------------------
# POST /api/git/{pid}/push, POST /api/git/{pid}/pull
# ---------------------------------------------------------------------------


class PushPullRequest(BaseModel):
    remote: str
    branch: str


@router.post("/{pid}/push")
async def git_push(pid: str, body: PushPullRequest, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    await _require_editor(pid, user_id)

    remote = (body.remote or "").strip()
    branch = (body.branch or "").strip()
    if not remote or not branch:
        raise HTTPException(status_code=400, detail="remote and branch are required")

    repo_dir = _repo_dir_for(pid)
    if not _is_initialized(repo_dir):
        raise HTTPException(status_code=409, detail="project has no git repo yet — call init first")

    # Ambient credentials only (SSH agent / credential helper) — no stored
    # tokens. subprocess inherits the server process's environment, which is
    # where SSH_AUTH_SOCK / GIT_SSH_COMMAND / credential.helper live.
    proc = _run_git(["push", remote, branch], repo_dir)
    if proc.returncode != 0:
        raise HTTPException(status_code=502, detail=_clean_stderr(proc))

    return {"status": "pushed", "remote": remote, "branch": branch}


@router.post("/{pid}/pull")
async def git_pull(pid: str, body: PushPullRequest, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    await _require_editor(pid, user_id)

    remote = (body.remote or "").strip()
    branch = (body.branch or "").strip()
    if not remote or not branch:
        raise HTTPException(status_code=400, detail="remote and branch are required")

    repo_dir = _repo_dir_for(pid)
    if not _is_initialized(repo_dir):
        raise HTTPException(status_code=409, detail="project has no git repo yet — call init first")

    # `git fetch <remote> <branch>:<branch>` updates the local ref directly
    # (fast-forward only, refuses otherwise) — the right "pull" primitive for
    # a bare repo, which has no working tree to merge into.
    proc = _run_git(["fetch", remote, f"{branch}:{branch}"], repo_dir)
    if proc.returncode != 0:
        raise HTTPException(status_code=502, detail=_clean_stderr(proc))

    return {"status": "pulled", "remote": remote, "branch": branch}
