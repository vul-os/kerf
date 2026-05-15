"""Automatic attribution / provenance — fully hermetic.

Builds a tiny throwaway git repo in a tmp dir with commits authored by
KNOWN names/emails/dates (via ``git -c user.name=... -c user.email=...`` +
``GIT_AUTHOR_DATE``), points the provenance helper at it, and asserts the
fallback chain end to end. NO network, NO real upstream clone.
"""
import os
import subprocess
from pathlib import Path

import pytest

from kerf_parts.manifest import Source
from kerf_parts.provenance import (
    UNKNOWN_AUTHOR,
    build_attribution,
    file_history,
    notice_lines_for_parts,
    repo_authorship,
)

SRC = Source(
    "kicad-symbols",
    "https://gitlab.com/kicad/libraries/kicad-symbols.git",
    "9.0.9",
    "CC-BY-SA-4.0 WITH KiCad-Library-Exception",
    "kicad-sym",
    "kicad",
)


def _git(repo: Path, *args, author=None, date=None):
    env = dict(os.environ)
    env.setdefault("GIT_CONFIG_NOSYSTEM", "1")
    if date:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    cfg = []
    if author:
        name, email = author
        cfg = ["-c", f"user.name={name}", "-c", f"user.email={email}"]
    cp = subprocess.run(
        ["git", *cfg, *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert cp.returncode == 0, f"git {args} failed: {cp.stderr or cp.stdout}"
    return cp


@pytest.fixture
def known_repo(tmp_path):
    """A repo where:
      - Device.kicad_sym CREATED by Ada Lovelace (2001), edited by Grace
        Hopper (2002), edited again by Ada (2003) -> original=Ada, last=Ada.
      - Footprint created by Linus Torvalds (2010), only ever touched once.
      - LICENSE carries a copyright holder for the repo-level fallback.
    """
    repo = tmp_path / "clone"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "remote", "add", "origin",
         "https://gitlab.com/kicad/libraries/kicad-symbols.git")

    (repo / "LICENSE").write_text(
        "Creative Commons Attribution-ShareAlike 4.0\n"
        "Copyright (c) 2001-2024 The KiCad Librarian Team\n",
        encoding="utf-8",
    )
    _git(repo, "add", "LICENSE")
    _git(repo, "commit", "-q", "-m", "license",
         author=("Repo Bot", "bot@kicad.org"),
         date="2000-01-01T00:00:00 +0000")

    sym = repo / "Device.kicad_sym"
    sym.write_text("(kicad_symbol_lib (generator kicad_symbol_editor))\n",
                    encoding="utf-8")
    _git(repo, "add", "Device.kicad_sym")
    _git(repo, "commit", "-q", "-m", "add Device",
         author=("Ada Lovelace", "ada@analytical.engine"),
         date="2001-06-01T09:00:00 +0000")

    sym.write_text("(kicad_symbol_lib (generator kicad_symbol_editor) ;e\n)\n",
                    encoding="utf-8")
    _git(repo, "add", "Device.kicad_sym")
    _git(repo, "commit", "-q", "-m", "tweak Device",
         author=("Grace Hopper", "grace@cobol.mil"),
         date="2002-06-01T09:00:00 +0000")

    sym.write_text("(kicad_symbol_lib (generator kicad_symbol_editor) ;e2\n)\n",
                    encoding="utf-8")
    _git(repo, "add", "Device.kicad_sym")
    _git(repo, "commit", "-q", "-m", "tweak Device again",
         author=("Ada Lovelace", "ada@analytical.engine"),
         date="2003-06-01T09:00:00 +0000")

    pretty = repo / "Resistor_SMD.pretty"
    pretty.mkdir()
    (pretty / "R_0805_2012Metric.kicad_mod").write_text(
        "(footprint R_0805 (generator pcbnew))\n", encoding="utf-8"
    )
    _git(repo, "add", "Resistor_SMD.pretty/R_0805_2012Metric.kicad_mod")
    _git(repo, "commit", "-q", "-m", "add 0805",
         author=("Linus Torvalds", "torvalds@linux-foundation.org"),
         date="2010-03-03T03:03:03 +0000")
    return repo


# ---- per-file git authorship --------------------------------------------

def test_original_author_is_the_creating_commit(known_repo):
    h = file_history(known_repo, "Device.kicad_sym")
    assert h.found
    assert h.original_author == "Ada Lovelace <ada@analytical.engine>"
    assert h.original_date.startswith("2001-06-01")


def test_last_author_is_most_recent_commit(known_repo):
    h = file_history(known_repo, "Device.kicad_sym")
    assert h.last_author == "Ada Lovelace <ada@analytical.engine>"
    assert h.last_date.startswith("2003-06-01")


def test_contributors_deduped(known_repo):
    h = file_history(known_repo, "Device.kicad_sym")
    # Ada twice + Grace once -> Ada once, Grace once.
    assert set(h.contributors) == {
        "Ada Lovelace <ada@analytical.engine>",
        "Grace Hopper <grace@cobol.mil>",
    }
    assert len(h.contributors) == 2


def test_single_commit_file_history(known_repo):
    h = file_history(known_repo, "Resistor_SMD.pretty/R_0805_2012Metric.kicad_mod")
    assert h.original_author == "Linus Torvalds <torvalds@linux-foundation.org>"
    assert h.last_author == h.original_author
    assert h.contributors == ["Linus Torvalds <torvalds@linux-foundation.org>"]


def test_no_history_for_unknown_path(known_repo):
    h = file_history(known_repo, "Does/Not/Exist.kicad_sym")
    assert not h.found
    assert h.original_author == ""


# ---- repo-level authorship fallback -------------------------------------

def test_repo_authorship_from_license(known_repo):
    holders = repo_authorship(known_repo)
    assert "The KiCad Librarian Team" in holders


def test_repo_authorship_authors_file(tmp_path):
    (tmp_path / "AUTHORS").write_text(
        "Authors\n=======\n* Jane Doe <jane@x.org>\n* Jane Doe <jane@x.org>\n"
        "John Roe\n",
        encoding="utf-8",
    )
    holders = repo_authorship(tmp_path)
    assert holders[0] == "Jane Doe <jane@x.org>"
    assert "John Roe" in holders
    # deduped (case-insensitive)
    assert holders.count("Jane Doe <jane@x.org>") == 1


# ---- build_attribution: full chain --------------------------------------

def test_attribution_prefers_per_file_git_author(known_repo):
    a = build_attribution(SRC, known_repo, "Device.kicad_sym")
    assert a["original_author"] == "Ada Lovelace <ada@analytical.engine>"
    assert a["author_source"] == "git-file-history"
    assert a["source_project"] == "kicad-symbols"
    # remote reconciled from the clone, commit = real HEAD sha (40 hex)
    assert a["source_url"].endswith("kicad-symbols.git")
    assert len(a["upstream_commit"]) == 40
    assert a["license"] == SRC.license
    assert a["license_url"] == "https://creativecommons.org/licenses/by-sa/4.0/"
    assert "Ada Lovelace" in a["attribution_text"]
    assert a["retrieved_at"].endswith("Z")


def test_attribution_falls_back_to_repo_holder(known_repo):
    # A path with NO git history -> per-file chain misses -> repo LICENSE
    # holder is used (NOT blank, NOT the manifest sentinel).
    a = build_attribution(SRC, known_repo, "Unknown.kicad_sym")
    assert a["original_author"] == "The KiCad Librarian Team"
    assert a["author_source"] == "repo-authors-file"
    assert a["source_url"]


def test_attribution_falls_back_to_manifest_when_no_repo_info(tmp_path):
    # Not a git repo, no LICENSE/AUTHORS -> manifest fallback, still
    # non-empty url + a clear "unknown — see source repository" author.
    bare = tmp_path / "plain"
    bare.mkdir()
    a = build_attribution(SRC, bare, "whatever.kicad_sym")
    assert a["original_author"] == UNKNOWN_AUTHOR
    assert a["author_source"] == "manifest-fallback"
    assert a["source_url"] == SRC.git_url
    assert a["upstream_commit"] == SRC.ref  # falls back to pinned ref
    assert a["license"] == SRC.license


def test_attribution_never_empty_invariant(known_repo, tmp_path):
    for repo, path in [
        (known_repo, "Device.kicad_sym"),
        (known_repo, "no/such/file"),
        (tmp_path, "x"),
    ]:
        a = build_attribution(SRC, repo, path)
        assert a["original_author"], "original_author must never be blank"
        assert a["source_url"], "source_url must never be blank"
        assert a["source_project"]
        assert a["attribution_text"]
        assert "retrieved_at" in a


def test_in_file_metadata_is_extra_signal_not_author(known_repo):
    a = build_attribution(
        SRC, known_repo, "Device.kicad_sym",
        in_file_meta={"generator": "kicad_symbol_editor", "blank": ""},
    )
    assert a["in_file_metadata"] == {"generator": "kicad_symbol_editor"}
    # in-file generator must NOT have become the author
    assert a["original_author"] == "Ada Lovelace <ada@analytical.engine>"


# ---- shallow clone caveat ------------------------------------------------

def test_shallow_clone_is_flagged_and_does_not_emit_wrong_author(tmp_path):
    """A --depth 1 clone that cannot be deepened (no network) must flag
    history_truncated and fall back rather than blaming the tip committer.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    f = origin / "Device.kicad_sym"
    f.write_text("v1\n", encoding="utf-8")
    _git(origin, "add", "Device.kicad_sym")
    _git(origin, "commit", "-q", "-m", "orig",
         author=("Original Person", "orig@x.org"),
         date="2001-01-01T00:00:00 +0000")
    f.write_text("v2\n", encoding="utf-8")
    _git(origin, "add", "Device.kicad_sym")
    _git(origin, "commit", "-q", "-m", "tip",
         author=("Tip Person", "tip@x.org"),
         date="2020-01-01T00:00:00 +0000")
    (origin / "LICENSE").write_text(
        "Copyright (c) 2001 Upstream Holder\n", encoding="utf-8"
    )
    _git(origin, "add", "LICENSE")
    _git(origin, "commit", "-q", "-m", "lic",
         author=("Tip Person", "tip@x.org"),
         date="2020-01-02T00:00:00 +0000")

    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "file://" + str(origin),
         str(shallow)],
        capture_output=True, text=True, check=True,
    )
    # Sever the remote so unshallow/deepen genuinely can't help (offline).
    subprocess.run(["git", "remote", "remove", "origin"], cwd=str(shallow),
                    capture_output=True, text=True, check=True)

    h = file_history(shallow, "Device.kicad_sym")
    assert h.history_truncated, "shallow + un-deepenable must be flagged"

    a = build_attribution(SRC, shallow, "Device.kicad_sym")
    # Must NOT misattribute to the tip committer; falls to repo LICENSE.
    assert a["original_author"] != "Tip Person <tip@x.org>"
    assert a["original_author"] == "Upstream Holder"
    assert a["history_truncated"] is True
    assert "history truncated" in a["attribution_text"]


def test_unshallow_recovers_full_history(tmp_path):
    """When the remote IS reachable, a shallow clone is unshallowed and the
    real original author is recovered.
    """
    origin = tmp_path / "origin2"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    f = origin / "Device.kicad_sym"
    f.write_text("a\n", encoding="utf-8")
    _git(origin, "add", "Device.kicad_sym")
    _git(origin, "commit", "-q", "-m", "create",
         author=("Real Original", "real@x.org"),
         date="1999-09-09T09:09:09 +0000")
    f.write_text("b\n", encoding="utf-8")
    _git(origin, "add", "Device.kicad_sym")
    _git(origin, "commit", "-q", "-m", "tip",
         author=("Recent Editor", "recent@x.org"),
         date="2021-01-01T00:00:00 +0000")

    shallow = tmp_path / "shallow2"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "file://" + str(origin),
         str(shallow)],
        capture_output=True, text=True, check=True,
    )
    h = file_history(shallow, "Device.kicad_sym")
    assert not h.history_truncated
    assert h.original_author == "Real Original <real@x.org>"


# ---- NOTICE regenerates from the SAME structured blocks -----------------

def test_notice_lines_built_from_attribution_blocks(known_repo):
    a1 = build_attribution(SRC, known_repo, "Device.kicad_sym")
    a2 = build_attribution(
        SRC, known_repo, "Resistor_SMD.pretty/R_0805_2012Metric.kicad_mod"
    )
    lines = "\n".join(notice_lines_for_parts([a1, a2]))
    assert "kicad-symbols  (2 part(s))" in lines
    assert "Ada Lovelace <ada@analytical.engine>" in lines
    assert "Linus Torvalds <torvalds@linux-foundation.org>" in lines
    assert SRC.git_url in lines or "kicad-symbols.git" in lines
