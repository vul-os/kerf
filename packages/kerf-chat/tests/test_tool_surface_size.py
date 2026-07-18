"""
T-308: Verify the LLM tool surface stays within budget.

The TOOL_CATALOG in kerf_chat.tools.catalog is the authoritative list.
This test loads it and asserts the count is within the target budget.

Budget history:
  - T-308 set the original ceiling at 14 tools (12 core + duplicate_object +
    delete_object for JSCAD array editing).
  - commit 9a07504a ("feat(subd): auto-detect hard creases + feature curves
    from mesh dihedral angles") deliberately registered a 15th tool,
    subd_auto_classify, so the SubD modelling workflow has an LLM entry
    point. Ceiling raised to 15 to match; this is a conscious increase of
    the surface, not drift.
"""
from kerf_chat.tools.catalog import TOOL_CATALOG
from kerf_chat.tools.executor import specs


def test_catalog_within_budget():
    """The catalog must have at most 15 tools."""
    assert len(TOOL_CATALOG) <= 15, (
        f"TOOL_CATALOG has {len(TOOL_CATALOG)} tools; budget is 15. "
        f"Tools: {[t.name for t in TOOL_CATALOG]}"
    )


def test_catalog_minimum():
    """The catalog must have at least 12 tools (the target surface)."""
    assert len(TOOL_CATALOG) >= 12, (
        f"TOOL_CATALOG has only {len(TOOL_CATALOG)} tools; expected at least 12."
    )


def test_catalog_names_are_unique():
    names = [t.name for t in TOOL_CATALOG]
    assert len(names) == len(set(names)), (
        f"Duplicate tool names in TOOL_CATALOG: {names}"
    )


def test_catalog_required_tools_present():
    """All 12 mandated tools must be present."""
    required = {
        "read_file",
        "write_file",
        "edit_file",
        "list_files",
        "search_files",
        "create_file",
        "describe_part",
        "search_kerf_docs",
        "run_compute",
        "poll_compute",
        "import_step",
        "export_artifact",
    }
    names = {t.name for t in TOOL_CATALOG}
    missing = required - names
    assert not missing, f"Missing required tools: {missing}"


def test_specs_editor_role():
    """specs('editor') returns the full catalog."""
    result = specs("editor")
    assert len(result) == len(TOOL_CATALOG)


def test_specs_viewer_role_excludes_write_tools():
    """specs('viewer') excludes write-capable tools."""
    write_tools = {
        "write_file",
        "edit_file",
        "create_file",
        "import_step",
        "export_artifact",
        "duplicate_object",
        "delete_object",
        "run_compute",
    }
    result = specs("viewer")
    returned_names = {t.name for t in result}
    overlap = returned_names & write_tools
    assert not overlap, f"Viewer should not see write tools: {overlap}"


def test_each_tool_has_description():
    for t in TOOL_CATALOG:
        assert t.description, f"Tool '{t.name}' has no description"


def test_each_tool_has_input_schema():
    for t in TOOL_CATALOG:
        assert isinstance(t.input_schema, dict), f"Tool '{t.name}' input_schema is not a dict"
        assert t.input_schema.get("type") == "object", (
            f"Tool '{t.name}' input_schema should have type='object'"
        )
