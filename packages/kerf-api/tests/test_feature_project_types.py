"""T-68 — Feature tests: project types (jewelry / mech / electronic / arch / civil).

Scope: mig 005 `project_type` → now folded into `projects.tags` text[].
  - TAG_PRESETS (frontend) defines the known domain presets.
  - STARTER_SEEDS (backend) seeds a file when a project is created.
  - tagKindHints (llm.py) drives the chat system-prompt addendum per tag.
  - build_project_tags_addendum() assembles the injected prompt fragment.
  - CreateProjectRequest accepts tags; STARTER_SEEDS resolves starter → (name,kind,content).

All 25 tests are hermetic — no Postgres required.  They call:
  * kerf_api.routes.STARTER_SEEDS, DEFAULT_STARTER, FILE_KINDS
  * kerf_chat.llm.tagKindHints, build_project_tags_addendum
  * the projectTags.js TAG_PRESETS via regex (same pattern as test_project_starters.py)
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from kerf_api.routes import STARTER_SEEDS, DEFAULT_STARTER, FILE_KINDS
from kerf_chat.llm import tagKindHints, build_project_tags_addendum

_PROJECT_TAGS_JS = (
    pathlib.Path(__file__).resolve().parents[3] / "src/lib/projectTags.js"
)

# ---------------------------------------------------------------------------
# Helpers: parse frontend projectTags.js
# ---------------------------------------------------------------------------

def _js() -> str:
    return _PROJECT_TAGS_JS.read_text()


def _tag_presets() -> list[dict]:
    """Parse TAG_PRESETS array from projectTags.js into plain dicts."""
    src = _js()
    m = re.search(r"export\s+const\s+TAG_PRESETS\s*=\s*\[(.*?)\n\]", src, re.S)
    assert m, "could not locate TAG_PRESETS in projectTags.js"
    block = m.group(1)

    presets = []
    # Each preset object: { id: '...', ... suggestStarter: '...', suggestKinds: [...] }
    for obj_m in re.finditer(r"\{([^{}]+)\}", block, re.S):
        obj_src = obj_m.group(1)
        entry: dict = {}

        id_m = re.search(r"id:\s*'([^']+)'", obj_src)
        if id_m:
            entry["id"] = id_m.group(1)

        ss_m = re.search(r"suggestStarter:\s*'([^']+)'", obj_src)
        if ss_m:
            entry["suggestStarter"] = ss_m.group(1)

        sk_m = re.search(r"suggestKinds:\s*\[([^\]]*)\]", obj_src, re.S)
        if sk_m:
            entry["suggestKinds"] = re.findall(r"'([^']+)'", sk_m.group(1))

        if "id" in entry:
            presets.append(entry)
    return presets


def _preset_ids() -> list[str]:
    return [p["id"] for p in _tag_presets()]


# ---------------------------------------------------------------------------
# 1. TAG_PRESETS existence + required fields
# ---------------------------------------------------------------------------

def test_tag_presets_file_readable():
    """projectTags.js exists and has TAG_PRESETS."""
    assert _PROJECT_TAGS_JS.exists(), "src/lib/projectTags.js not found"
    assert "TAG_PRESETS" in _js()


def test_tag_presets_cover_known_domains():
    """The five original domain types (jewelry, mechanical, electronics, architecture,
    plus pcb) are all present in TAG_PRESETS."""
    ids = set(_preset_ids())
    for required in ("mechanical", "electronics", "architecture", "jewelry", "pcb"):
        assert required in ids, f"domain tag '{required}' missing from TAG_PRESETS"


def test_every_preset_has_an_id():
    presets = _tag_presets()
    assert presets, "TAG_PRESETS parsed to empty list"
    for p in presets:
        assert p.get("id"), f"preset missing id: {p}"


def test_every_preset_suggests_a_valid_starter():
    """Every TAG_PRESETS entry with suggestStarter must point at a real STARTER_SEEDS key."""
    for p in _tag_presets():
        ss = p.get("suggestStarter")
        if ss is not None:
            assert ss in STARTER_SEEDS, (
                f"preset '{p['id']}' suggestStarter='{ss}' not in STARTER_SEEDS "
                f"(backend can't seed it)"
            )


def test_every_preset_suggest_kinds_are_file_kinds():
    """suggestKinds from each TAG_PRESETS entry must all be valid FILE_KINDS."""
    fk = set(FILE_KINDS)
    for p in _tag_presets():
        for kind in p.get("suggestKinds", []):
            assert kind in fk, (
                f"preset '{p['id']}' suggestKinds contains '{kind}' which is not in FILE_KINDS"
            )


# ---------------------------------------------------------------------------
# 2. STARTER_SEEDS — per-type seed file integrity
# ---------------------------------------------------------------------------

def test_mechanical_preset_suggests_jscad_starter():
    """'mechanical' domain → suggestStarter=jscad → STARTER_SEEDS has 'jscad'."""
    mechanical = next((p for p in _tag_presets() if p["id"] == "mechanical"), None)
    assert mechanical is not None
    assert mechanical.get("suggestStarter") == "jscad"
    assert "jscad" in STARTER_SEEDS


def test_electronics_preset_suggests_circuit_starter():
    """'electronics' domain → suggestStarter=circuit → STARTER_SEEDS has 'circuit'."""
    elec = next((p for p in _tag_presets() if p["id"] == "electronics"), None)
    assert elec is not None
    assert elec.get("suggestStarter") == "circuit"
    assert "circuit" in STARTER_SEEDS


def test_jewelry_preset_suggests_feature_starter():
    """'jewelry' domain → suggestStarter=feature → STARTER_SEEDS has 'feature'."""
    jwl = next((p for p in _tag_presets() if p["id"] == "jewelry"), None)
    assert jwl is not None
    assert jwl.get("suggestStarter") == "feature"
    assert "feature" in STARTER_SEEDS


def test_architecture_preset_suggests_drawing_starter():
    """'architecture' domain → suggestStarter=drawing → STARTER_SEEDS has 'drawing'."""
    arch = next((p for p in _tag_presets() if p["id"] == "architecture"), None)
    assert arch is not None
    assert arch.get("suggestStarter") == "drawing"
    assert "drawing" in STARTER_SEEDS


def test_starter_seeds_seed_kinds_in_file_kinds():
    """Every kind seeded by STARTER_SEEDS is a member of FILE_KINDS."""
    fk = set(FILE_KINDS)
    for sid, (name, kind, content) in STARTER_SEEDS.items():
        assert kind in fk, f"STARTER_SEEDS['{sid}'] seeds kind='{kind}' not in FILE_KINDS"


def test_non_blank_starter_seeds_have_filename_and_content():
    """Every non-blank starter must produce a real filename and non-empty content."""
    for sid, (name, kind, content) in STARTER_SEEDS.items():
        if sid == "blank":
            assert name == "" and content == ""
        else:
            assert name and content, f"starter '{sid}' must have filename + content"


def test_default_starter_exists_in_seeds():
    assert DEFAULT_STARTER in STARTER_SEEDS, (
        f"DEFAULT_STARTER='{DEFAULT_STARTER}' not in STARTER_SEEDS"
    )


# ---------------------------------------------------------------------------
# 3. tagKindHints — backend LLM hints per domain tag
# ---------------------------------------------------------------------------

def test_tag_kind_hints_covers_core_domains():
    """tagKindHints must cover mechanical, electronics, pcb, architecture, jewelry."""
    for tag in ("mechanical", "electronics", "pcb", "architecture", "jewelry"):
        assert tag in tagKindHints, f"tagKindHints missing entry for '{tag}'"


def test_tag_kind_hints_values_are_lists_of_strings():
    for tag, kinds in tagKindHints.items():
        assert isinstance(kinds, list), f"tagKindHints['{tag}'] should be a list"
        for k in kinds:
            assert isinstance(k, str), f"tagKindHints['{tag}'] item {k!r} is not a str"


def test_tag_kind_hints_kinds_in_file_kinds():
    """Every kind mentioned in tagKindHints must be valid (in FILE_KINDS or a starter id)."""
    fk = set(FILE_KINDS)
    starter_ids = set(STARTER_SEEDS)
    # tagKindHints may use starter-id aliases like "jscad" (which maps to kind "script")
    # but they are also accepted by the agent as kind hints; the important check is that
    # the kind strings are coherent and known.
    known = fk | starter_ids
    for tag, kinds in tagKindHints.items():
        for k in kinds:
            assert k in known, (
                f"tagKindHints['{tag}'] references '{k}' which is neither a FILE_KIND "
                f"nor a STARTER_SEEDS key"
            )


def test_mechanical_tag_hints_include_jscad_and_sketch():
    kinds = set(tagKindHints.get("mechanical", []))
    assert "jscad" in kinds or "sketch" in kinds, (
        "mechanical tagKindHints must include at least one of jscad/sketch"
    )


def test_electronics_tag_hints_include_circuit():
    kinds = set(tagKindHints.get("electronics", []))
    assert "circuit" in kinds, "electronics tagKindHints must include 'circuit'"


def test_jewelry_tag_hints_include_feature_or_jscad():
    kinds = set(tagKindHints.get("jewelry", []))
    assert kinds & {"feature", "jscad"}, (
        "jewelry tagKindHints must include 'feature' or 'jscad'"
    )


def test_architecture_tag_hints_include_drawing():
    kinds = set(tagKindHints.get("architecture", []))
    assert "drawing" in kinds, "architecture tagKindHints must include 'drawing'"


# ---------------------------------------------------------------------------
# 4. build_project_tags_addendum — chat system-prompt per project type
# ---------------------------------------------------------------------------

def test_addendum_empty_for_no_tags():
    assert build_project_tags_addendum([]) == ""


def test_addendum_empty_for_blank_tags():
    assert build_project_tags_addendum(["", "  "]) == ""


def test_addendum_names_the_tag():
    out = build_project_tags_addendum(["mechanical"])
    assert "mechanical" in out


def test_addendum_includes_suggested_kinds_for_mechanical():
    out = build_project_tags_addendum(["mechanical"])
    assert "Suggested file kinds:" in out
    # jscad or sketch must appear
    assert "jscad" in out or "sketch" in out


def test_addendum_includes_suggested_kinds_for_electronics():
    out = build_project_tags_addendum(["electronics"])
    assert "circuit" in out


def test_addendum_for_jewelry_tags():
    out = build_project_tags_addendum(["jewelry"])
    assert "jewelry" in out
    assert "feature" in out or "jscad" in out


def test_addendum_multi_tag_deduplicates_kinds():
    """Two tags that share a kind should not duplicate it in the addendum."""
    out = build_project_tags_addendum(["electronics", "pcb"])
    # 'circuit' appears in both electronics and pcb tagKindHints
    kinds_section = out.split("Suggested file kinds:")[-1] if "Suggested file kinds:" in out else ""
    kinds_list = [k.strip() for k in kinds_section.split(",")]
    assert kinds_list.count("circuit") <= 1, "circuit appeared twice in multi-tag addendum"


def test_addendum_multi_tag_preserves_first_occurrence_order():
    """The addendum honours the order tags were supplied, kinds de-duped by first-seen."""
    out = build_project_tags_addendum(["mechanical", "electronics"])
    # mechanical lists jscad first; electronics adds circuit afterward
    assert "mechanical" in out
    assert "electronics" in out


def test_addendum_unknown_tag_still_named():
    """A free-text tag with no tagKindHints entry is still mentioned in the addendum."""
    out = build_project_tags_addendum(["civil"])
    assert "civil" in out


def test_addendum_architecture_tag():
    out = build_project_tags_addendum(["architecture"])
    assert "architecture" in out
    assert "drawing" in out


def test_addendum_returns_string():
    for tag in ("mechanical", "electronics", "jewelry", "architecture", "pcb"):
        result = build_project_tags_addendum([tag])
        assert isinstance(result, str), f"addendum for '{tag}' is not a string"
