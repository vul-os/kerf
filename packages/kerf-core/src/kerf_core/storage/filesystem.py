"""Storage backend that lays objects out as a tree a human can read.

``LocalStorage`` writes every object at its raw storage key. That is right for
a cache directory and wrong for a directory a person is meant to live in: an
uploaded part arrives as ``<uuid>-bracket.step``, a project's renders and
exports land in sibling top-level directories, and content-addressed blobs sit
among them under 64 hex characters.

``FilesystemStorage`` keeps the same Storage contract but maps those keys onto
a tree you can ``cd`` into: one directory per project, files under the names
they were uploaded with, and the content-addressed objects tucked away under a
hidden ``.kerf`` directory so they do not drown the ones that have names.

The key -> path mapping is pure — only the key decides where bytes land — so
``get`` finds what ``put`` wrote without a side index. The database still holds
the index and the revision history; this tree is a readable projection of the
object store, not a second source of truth, and nothing reads changes back out
of it.

Because the tree is meant to be edited from outside, a file that has gone
missing or grown unexpected contents is ordinary: reads fail exactly the way
``LocalStorage`` fails for an object that was never written.
"""

import os
import re
import shutil
import uuid as _uuid
from pathlib import Path

from .local import LocalStorage

# Everything the app needs but a person does not want to look at lives here.
PRIVATE_DIR = ".kerf"
OBJECT_DIR = "objects"
UPLOAD_DIR = "uploads"

# Key prefixes that name project-scoped artifacts; these fold into the
# project's own directory so a project is one tree you can git. The same names
# are therefore reserved as the third segment of a ``projects/<id>/…`` key.
PROJECT_SCOPED_KINDS = frozenset({"renders", "exports", "photos", "topo", "model3d"})

# A leaf whose stem is this many hex characters or more is a digest, not a
# name — 32 covers md5-length keys and up, and is long enough that a real
# filename will not trip it.
_DIGEST_MIN_CHARS = 32
_DIGEST_RE = re.compile(r"^[0-9a-f]{%d,}$" % _DIGEST_MIN_CHARS, re.IGNORECASE)

# Upload keys carry a UUID in front of the user's filename to keep two uploads
# of "bracket.step" apart. The name goes first and the UUID becomes a short
# suffix, so the directory sorts and tab-completes by what the file is called.
_UUID_PREFIX_RE = re.compile(
    r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})-(.+)$"
)
_ID_SUFFIX_CHARS = 12


def _is_digest(leaf: str) -> bool:
    stem = os.path.splitext(leaf)[0]
    return bool(_DIGEST_RE.match(stem))


def _is_uuid(segment: str) -> bool:
    try:
        _uuid.UUID(segment)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _readable_leaf(leaf: str) -> str:
    m = _UUID_PREFIX_RE.match(leaf)
    if not m:
        return leaf
    ident, name = m.group(1), m.group(2)
    stem, ext = os.path.splitext(name)
    if not stem:
        return leaf
    short = ident.replace("-", "")[:_ID_SUFFIX_CHARS]
    return f"{stem}-{short}{ext}"


class FilesystemStorage(LocalStorage):
    """LocalStorage's write path, a readable layout instead of raw keys."""

    def __init__(self, root: str, cdn_url: str = ""):
        # The documented default is "~/kerf-projects"; a config file is the
        # one place a tilde is expected to survive to the filesystem.
        super().__init__(str(Path(root).expanduser()), cdn_url=cdn_url)

    # -- key -> path ------------------------------------------------------

    def _segments(self, key: str) -> list[str]:
        parts = [p for p in key.replace("\\", "/").split("/") if p not in ("", ".")]
        if not parts:
            raise ValueError(f"Invalid key: {key}")
        if ".." in parts:
            raise ValueError(f"Path traversal detected: {key}")
        if parts[0] == PRIVATE_DIR:
            raise ValueError(f"Reserved key prefix {PRIVATE_DIR!r}: {key}")
        return parts

    def _fold(self, parts: list[str]) -> list[str]:
        """Move ``<kind>/<project-id>/…`` under ``projects/<project-id>/``.

        Two segments is enough, and that matters: a *prefix* is one segment
        shorter than the keys under it. ``routes.py`` deletes a project's photos
        with ``delete_prefix("photos/<pid>/")`` — two segments — while the keys
        it is trying to reach are ``photos/<pid>/<fid>/<uuid>.jpg``. Requiring
        three folded the keys and not the prefix, so the delete looked in
        ``photos/<pid>`` (which nothing writes) and left every photo of every
        deleted project on disk.

        Folding at two is safe because the guard is ``_is_uuid(parts[1])``: a
        real two-segment key has a filename there, not a project id.
        """
        if len(parts) >= 2 and parts[0] in PROJECT_SCOPED_KINDS and _is_uuid(parts[1]):
            return ["projects", parts[1], parts[0], *parts[2:]]
        return parts

    def _relative(self, key: str) -> Path:
        parts = self._segments(key)
        if _is_digest(parts[-1]):
            return Path(PRIVATE_DIR, OBJECT_DIR, *parts)
        parts = self._fold(parts)
        return Path(*parts[:-1], _readable_leaf(parts[-1]))

    def _inside_root(self, path: Path, key: str) -> Path:
        # The tree is user-editable, so a directory on the way down may have
        # been replaced with a symlink pointing somewhere else entirely.
        resolved = path.resolve()
        if resolved != self.root and not str(resolved).startswith(str(self.root) + os.sep):
            raise ValueError(f"Path traversal detected: {key}")
        return path

    def _safe_path(self, key: str) -> Path:
        return self._inside_root(self.root / self._relative(key), key)

    def _chunk_dir(self, upload_key: str) -> Path:
        if not upload_key or any(c in upload_key for c in "/\\") or upload_key in (".", ".."):
            raise ValueError(f"Invalid upload key: {upload_key}")
        return self.root / PRIVATE_DIR / UPLOAD_DIR / upload_key

    # -- prefix deletes ---------------------------------------------------

    async def delete_prefix(self, prefix: str) -> int:
        """Delete everything *prefix* could have been mapped to.

        A prefix is not a key: ``projects/<id>`` names a directory of the
        readable tree, while ``blobs/ab`` names a directory of the hidden
        object store, and a full key maps to a renamed leaf. All three forms
        are tried; each is best-effort, as the protocol requires.
        """
        parts = self._segments(prefix)
        candidates = [
            self._inside_root(self.root / Path(*self._fold(parts)), prefix),
            self._safe_path(prefix),
            self._inside_root(self.root / PRIVATE_DIR / OBJECT_DIR / Path(*parts), prefix),
        ]

        deleted = 0
        seen: set[Path] = set()
        for target in candidates:
            if target in seen:
                continue
            seen.add(target)
            if target.is_dir():
                for entry in list(target.rglob("*")):
                    if entry.is_file():
                        try:
                            entry.unlink()
                            deleted += 1
                        except OSError:
                            pass
                shutil.rmtree(target, ignore_errors=True)
            elif target.is_file():
                try:
                    target.unlink()
                    deleted += 1
                except OSError:
                    pass
        return deleted
