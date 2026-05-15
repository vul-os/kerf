"""Fetcher — clones pinned upstream parts repos into the gitignored
``<repo_root>/.parts-cache/<name>/`` directory.

NOTHING fetched here is ever committed. ``.parts-cache/`` is in the repo
root .gitignore (added by this package).

The clone-vs-update *decision* is a pure function (:func:`decide_action`)
so it is unit-testable without touching the network or a real git repo.
The actual subprocess git calls live in :func:`fetch_source` /
:func:`run_git`, which the tests mock.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from .manifest import Source, load_manifest, select_sources

# Repo root = three levels up from this file: src/kerf_parts/ -> kerf-parts/
# -> packages/ -> <repo_root>.
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CACHE_DIR = REPO_ROOT / ".parts-cache"


class Action(str, Enum):
    SKIP = "skip"          # cache already at the pinned ref
    CLONE = "clone"        # no cache dir -> fresh clone
    REFRESH = "refresh"    # cache exists but wrong/unknown ref -> re-fetch


@dataclass(frozen=True)
class CloneState:
    """The minimal filesystem facts the decision needs (so tests can fake it)."""

    cache_exists: bool
    is_git_repo: bool
    current_ref: Optional[str]  # resolved tag/branch name in the cache, if known


def decide_action(state: CloneState, wanted_ref: str) -> Action:
    """Pure: given the on-disk state + the pinned ref, decide what to do.

    - no dir / not a git repo  -> CLONE
    - git repo already at the wanted ref -> SKIP (idempotent)
    - git repo at some other / unknown ref -> REFRESH
    """
    if not state.cache_exists or not state.is_git_repo:
        return Action.CLONE
    if state.current_ref is not None and state.current_ref == wanted_ref:
        return Action.SKIP
    return Action.REFRESH


# --------------------------------------------------------------------------
# git plumbing (mocked in tests)
# --------------------------------------------------------------------------

def run_git(args: list[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )


def _resolve_current_ref(dest: Path, runner: Callable = run_git) -> Optional[str]:
    """Best-effort: what tag/branch is the cache currently checked out at?

    We stored the pinned ref as a local tag/branch at clone time via
    ``--branch``; ``git describe --tags --exact-match`` or the branch name
    recovers it. Returns None if it can't be determined (-> REFRESH).
    """
    cp = runner(["describe", "--tags", "--exact-match"], cwd=dest)
    if cp.returncode == 0 and cp.stdout.strip():
        return cp.stdout.strip()
    cp = runner(["rev-parse", "--abbrev-ref", "HEAD"], cwd=dest)
    if cp.returncode == 0:
        name = cp.stdout.strip()
        if name and name != "HEAD":
            return name
    return None


def inspect_cache(dest: Path, runner: Callable = run_git) -> CloneState:
    """Probe the filesystem/git state of one cached source."""
    if not dest.exists():
        return CloneState(cache_exists=False, is_git_repo=False, current_ref=None)
    is_git = (dest / ".git").exists()
    if not is_git:
        return CloneState(cache_exists=True, is_git_repo=False, current_ref=None)
    return CloneState(
        cache_exists=True,
        is_git_repo=True,
        current_ref=_resolve_current_ref(dest, runner),
    )


@dataclass
class FetchResult:
    name: str
    action: Action
    ok: bool
    message: str


def fetch_source(
    source: Source,
    cache_dir: Path,
    *,
    runner: Callable = run_git,
    log: Callable[[str], None] = print,
) -> FetchResult:
    """Fetch one source into ``cache_dir/<name>``. Idempotent."""
    dest = cache_dir / source.name
    state = inspect_cache(dest, runner)
    action = decide_action(state, source.ref)

    if action is Action.SKIP:
        log(f"  [{source.name}] up to date at ref {source.ref} — skip")
        return FetchResult(source.name, action, True, "up to date")

    cache_dir.mkdir(parents=True, exist_ok=True)

    if action is Action.CLONE:
        log(f"  [{source.name}] cloning {source.git_url} @ {source.ref} (depth 1)")
        cp = runner(
            [
                "clone", "--depth", "1", "--branch", source.ref,
                source.git_url, str(dest),
            ]
        )
        if cp.returncode != 0:
            msg = cp.stderr.strip() or cp.stdout.strip() or "git clone failed"
            log(f"  [{source.name}] CLONE FAILED: {msg}")
            return FetchResult(source.name, action, False, msg)
        log(f"  [{source.name}] cloned")
        return FetchResult(source.name, action, True, "cloned")

    # REFRESH: shallow-fetch the pinned ref and hard-checkout it.
    log(f"  [{source.name}] refreshing to ref {source.ref}")
    fp = runner(
        ["fetch", "--depth", "1", "--tags", "origin", source.ref], cwd=dest
    )
    if fp.returncode != 0:
        # Fall back to a clean re-clone if the in-place fetch fails.
        log(f"  [{source.name}] fetch failed, re-cloning")
        _rmtree(dest)
        return fetch_source(source, cache_dir, runner=runner, log=log)
    co = runner(["checkout", "-f", source.ref], cwd=dest)
    if co.returncode != 0:
        co = runner(["checkout", "-f", "FETCH_HEAD"], cwd=dest)
    if co.returncode != 0:
        msg = co.stderr.strip() or "git checkout failed"
        log(f"  [{source.name}] REFRESH FAILED: {msg}")
        return FetchResult(source.name, action, False, msg)
    log(f"  [{source.name}] refreshed")
    return FetchResult(source.name, action, True, "refreshed")


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


def fetch_all(
    sources: list[Source],
    cache_dir: Path,
    *,
    runner: Callable = run_git,
    log: Callable[[str], None] = print,
) -> list[FetchResult]:
    results: list[FetchResult] = []
    for s in sources:
        results.append(fetch_source(s, cache_dir, runner=runner, log=log))
    return results


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _parse_ref_overrides(values: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for v in values or []:
        if "=" not in v:
            raise SystemExit(f"--ref expects NAME=REF, got {v!r}")
        name, ref = v.split("=", 1)
        out[name.strip()] = ref.strip()
    return out


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kerf-parts-fetch",
        description=(
            "Clone pinned open-source CAD parts repos into the gitignored "
            ".parts-cache/. Contributor tooling — fetched data is never "
            "committed."
        ),
    )
    p.add_argument(
        "--only",
        default="",
        help="comma-separated subset of source names to fetch",
    )
    p.add_argument(
        "--heavy",
        action="store_true",
        help="include heavy (multi-GB) sources like kicad-packages3D",
    )
    p.add_argument(
        "--cache-dir",
        default="",
        help=f"override cache dir (default: {DEFAULT_CACHE_DIR})",
    )
    p.add_argument(
        "--ref",
        action="append",
        default=[],
        metavar="NAME=REF",
        help="override a source's pinned ref for this run (repeatable)",
    )
    p.add_argument(
        "--manifest",
        default="",
        help="path to an alternate parts-sources.toml",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    manifest = load_manifest(Path(args.manifest) if args.manifest else None)
    only = [x.strip() for x in args.only.split(",") if x.strip()] or None
    overrides = _parse_ref_overrides(args.ref)
    cache_dir = Path(args.cache_dir) if args.cache_dir else DEFAULT_CACHE_DIR

    selected = select_sources(
        manifest,
        only=only,
        include_heavy=args.heavy,
        ref_overrides=overrides,
    )
    if not selected:
        print("nothing selected (heavy sources need --heavy)")
        return 0

    print(f"fetching {len(selected)} source(s) into {cache_dir}")
    results = fetch_all(selected, cache_dir)

    failed = [r for r in results if not r.ok]
    for r in results:
        flag = "ok " if r.ok else "ERR"
        print(f"  {flag} {r.name}: {r.action.value} — {r.message}")
    if failed:
        print(f"{len(failed)} source(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
