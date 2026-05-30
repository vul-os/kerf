"""Tests for PLM multi-cavity tool effectivity (PROSTEP-iViP SIG §6)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from kerf_plm.multi_cavity_effectivity import (
    CavityInsert,
    MultiCavityTool,
    ToolCavity,
    query_multi_cavity_effectivity,
    HONEST_FLAG,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_uniform_tool(n: int, revision: str) -> MultiCavityTool:
    """Return a tool with *n* cavities all carrying a single open-ended insert."""
    return MultiCavityTool(
        tool_id="MOLD-TEST",
        cavities=[
            ToolCavity(cavity_id=i, inserts=[CavityInsert(revision=revision)])
            for i in range(1, n + 1)
        ],
    )


# ---------------------------------------------------------------------------
# Test 1 — uniform tool: all 4 cavities at R5
# ---------------------------------------------------------------------------

class TestUniformTool:
    def test_all_cavities_r5(self):
        """Depth-bar: 4-cavity tool, all at R5 → [(1,R5),(2,R5),(3,R5),(4,R5)]."""
        tool = _make_uniform_tool(4, "R5")
        result = query_multi_cavity_effectivity(tool, date(2026, 1, 1))

        assert result.tool_id == "MOLD-TEST"
        assert result.query_date == date(2026, 1, 1)
        assert result.as_tuples() == [(1, "R5"), (2, "R5"), (3, "R5"), (4, "R5")]
        assert result.effective_count == 4

    def test_honest_flag_present(self):
        tool = _make_uniform_tool(2, "R1")
        result = query_multi_cavity_effectivity(tool, date(2025, 6, 1))
        assert "wear" in result.honest_flag.lower()

    def test_cavity_ids_sorted(self):
        """Cavities returned in cavity_id order regardless of input order."""
        tool = MultiCavityTool(
            tool_id="T1",
            cavities=[
                ToolCavity(cavity_id=4, inserts=[CavityInsert("R1")]),
                ToolCavity(cavity_id=2, inserts=[CavityInsert("R1")]),
                ToolCavity(cavity_id=1, inserts=[CavityInsert("R1")]),
                ToolCavity(cavity_id=3, inserts=[CavityInsert("R1")]),
            ],
        )
        result = query_multi_cavity_effectivity(tool, date(2026, 1, 1))
        cids = [r.cavity_id for r in result.per_cavity_revisions]
        assert cids == [1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Test 2 — mid-revision swap: cavity 3 goes R5 → R6 from 2026-04-01
# ---------------------------------------------------------------------------

class TestMidRevisionSwap:
    @pytest.fixture
    def tool_with_swap(self) -> MultiCavityTool:
        cavities = [
            ToolCavity(cavity_id=i, inserts=[CavityInsert("R5")]) for i in range(1, 5)
        ]
        # Cavity 3 (index 2): add R6 insert effective from 2026-04-01
        cavities[2].inserts.append(
            CavityInsert("R6", effective_from=date(2026, 4, 1))
        )
        return MultiCavityTool(tool_id="MOLD-SWAP", cavities=cavities)

    def test_after_swap_date(self, tool_with_swap):
        """Query 2026-05-01 → cavity 3 is R6; others R5."""
        result = query_multi_cavity_effectivity(tool_with_swap, date(2026, 5, 1))
        assert result.as_tuples() == [(1, "R5"), (2, "R5"), (3, "R6"), (4, "R5")]
        assert result.effective_count == 4

    def test_before_swap_date(self, tool_with_swap):
        """Query 2026-03-15 → all cavities still R5."""
        result = query_multi_cavity_effectivity(tool_with_swap, date(2026, 3, 15))
        assert result.as_tuples() == [(1, "R5"), (2, "R5"), (3, "R5"), (4, "R5")]
        assert result.effective_count == 4

    def test_on_swap_date(self, tool_with_swap):
        """Query exactly 2026-04-01 → cavity 3 is R6 (effective_from inclusive)."""
        result = query_multi_cavity_effectivity(tool_with_swap, date(2026, 4, 1))
        assert result.as_tuples() == [(1, "R5"), (2, "R5"), (3, "R6"), (4, "R5")]

    def test_latest_wins_on_overlap(self):
        """When two inserts are both effective on a date, the last-declared wins."""
        cavity = ToolCavity(
            cavity_id=1,
            inserts=[
                CavityInsert("R5"),                          # open-ended, always effective
                CavityInsert("R6", effective_from=date(2026, 1, 1)),  # also effective from Jan
            ],
        )
        tool = MultiCavityTool(tool_id="T", cavities=[cavity])
        result = query_multi_cavity_effectivity(tool, date(2026, 6, 1))
        assert result.as_tuples() == [(1, "R6")]  # last-declared wins


# ---------------------------------------------------------------------------
# Test 3 — out-of-range query: no insert effective on the query date
# ---------------------------------------------------------------------------

class TestOutOfRange:
    @pytest.fixture
    def bounded_tool(self) -> MultiCavityTool:
        """4-cavity tool; all inserts bounded 2026-01-01 to 2026-12-31."""
        cavities = [
            ToolCavity(
                cavity_id=i,
                inserts=[
                    CavityInsert(
                        "R5",
                        effective_from=date(2026, 1, 1),
                        effective_to=date(2026, 12, 31),
                    )
                ],
            )
            for i in range(1, 5)
        ]
        return MultiCavityTool(tool_id="MOLD-BOUNDED", cavities=cavities)

    def test_before_range(self, bounded_tool):
        """Query 2025-12-31 → no cavities active."""
        result = query_multi_cavity_effectivity(bounded_tool, date(2025, 12, 31))
        assert all(r.revision is None for r in result.per_cavity_revisions)
        assert all(not r.effective for r in result.per_cavity_revisions)
        assert result.effective_count == 0

    def test_after_range(self, bounded_tool):
        """Query 2027-01-01 → no cavities active."""
        result = query_multi_cavity_effectivity(bounded_tool, date(2027, 1, 1))
        assert result.effective_count == 0

    def test_within_range(self, bounded_tool):
        """Query 2026-06-15 → all 4 cavities active."""
        result = query_multi_cavity_effectivity(bounded_tool, date(2026, 6, 15))
        assert result.effective_count == 4

    def test_on_last_day(self, bounded_tool):
        """Query 2026-12-31 (effective_to inclusive) → all active."""
        result = query_multi_cavity_effectivity(bounded_tool, date(2026, 12, 31))
        assert result.effective_count == 4

    def test_partial_out_of_range(self):
        """Some cavities active, some not — mixed date windows."""
        tool = MultiCavityTool(
            tool_id="MOLD-MIXED",
            cavities=[
                ToolCavity(
                    cavity_id=1,
                    inserts=[CavityInsert("R5", effective_from=date(2026, 1, 1))],
                ),
                ToolCavity(
                    cavity_id=2,
                    inserts=[CavityInsert("R5", effective_to=date(2025, 12, 31))],
                ),
            ],
        )
        result = query_multi_cavity_effectivity(tool, date(2026, 6, 1))
        revisions = dict(result.as_tuples())
        assert revisions[1] == "R5"   # active
        assert revisions[2] is None   # expired
        assert result.effective_count == 1


# ---------------------------------------------------------------------------
# Test 4 — per-cavity revision mismatch (compatible_revisions constraint)
# ---------------------------------------------------------------------------

class TestCompatibilityMismatch:
    def test_compatible_revisions_tracked(self):
        """compatible_revisions is returned in the CavityResolution."""
        cavity = ToolCavity(
            cavity_id=1,
            inserts=[
                CavityInsert("R5", compatible_revisions={"R4", "R5"}),
            ],
        )
        tool = MultiCavityTool(tool_id="T", cavities=[cavity])
        result = query_multi_cavity_effectivity(tool, date(2026, 1, 1))
        res = result.per_cavity_revisions[0]
        assert res.revision == "R5"
        assert res.compatible_revisions == {"R4", "R5"}

    def test_require_revision_option_count(self):
        """require_revision option filters effective_count but not per_cavity_revisions."""
        cavities = [
            ToolCavity(cavity_id=1, inserts=[CavityInsert("R5")]),
            ToolCavity(cavity_id=2, inserts=[CavityInsert("R5")]),
            ToolCavity(cavity_id=3, inserts=[CavityInsert("R6")]),
            ToolCavity(cavity_id=4, inserts=[CavityInsert("R5")]),
        ]
        tool = MultiCavityTool(tool_id="MOLD-MIX", cavities=cavities)
        result = query_multi_cavity_effectivity(
            tool, date(2026, 1, 1), options={"require_revision": "R6"}
        )
        # All 4 cavities still in per_cavity_revisions
        assert len(result.per_cavity_revisions) == 4
        # Only cavity 3 (R6) counts toward effective_count
        assert result.effective_count == 1

    def test_require_revision_list(self):
        """require_revision accepts a list of revision labels."""
        cavities = [
            ToolCavity(cavity_id=1, inserts=[CavityInsert("R5")]),
            ToolCavity(cavity_id=2, inserts=[CavityInsert("R6")]),
            ToolCavity(cavity_id=3, inserts=[CavityInsert("R7")]),
        ]
        tool = MultiCavityTool(tool_id="T", cavities=cavities)
        result = query_multi_cavity_effectivity(
            tool, date(2026, 1, 1), options={"require_revision": ["R5", "R6"]}
        )
        assert result.effective_count == 2  # R5 + R6, not R7

    def test_incompatible_insert_still_returned(self):
        """A cavity that can't produce the required revision is still in per_cavity_revisions."""
        cavity_a = ToolCavity(cavity_id=1, inserts=[CavityInsert("R5", compatible_revisions={"R4", "R5"})])
        cavity_b = ToolCavity(cavity_id=2, inserts=[CavityInsert("R6", compatible_revisions={"R6"})])
        tool = MultiCavityTool(tool_id="T", cavities=[cavity_a, cavity_b])
        result = query_multi_cavity_effectivity(
            tool, date(2026, 1, 1), options={"require_revision": "R5"}
        )
        # cavity_b (R6) still present in per_cavity_revisions but not counted
        revisions = dict(result.as_tuples())
        assert revisions[1] == "R5"
        assert revisions[2] == "R6"
        assert result.effective_count == 1  # only R5 matches


# ---------------------------------------------------------------------------
# Test 5 — LLM tool handler round-trip
# ---------------------------------------------------------------------------

class TestToolHandler:
    @pytest.mark.asyncio
    async def test_handler_uniform_4cavity(self):
        from kerf_plm._tools_module import run_plm_query_multi_cavity
        from kerf_plm._compat import ProjectCtx

        payload = {
            "tool_id": "MOLD-001",
            "query_date": "2026-05-01",
            "cavities": [
                {"cavity_id": i, "inserts": [{"revision": "R5"}]}
                for i in range(1, 5)
            ],
        }
        ctx = ProjectCtx()
        raw = await run_plm_query_multi_cavity(ctx, json.dumps(payload).encode())
        resp = json.loads(raw)
        assert resp["effective_count"] == 4
        revs = {r["cavity_id"]: r["revision"] for r in resp["per_cavity_revisions"]}
        assert revs == {1: "R5", 2: "R5", 3: "R5", 4: "R5"}

    @pytest.mark.asyncio
    async def test_handler_swap_cavity3(self):
        from kerf_plm._tools_module import run_plm_query_multi_cavity
        from kerf_plm._compat import ProjectCtx

        cavities = [
            {"cavity_id": i, "inserts": [{"revision": "R5"}]}
            for i in range(1, 5)
        ]
        # Cavity 3 gets R6 from 2026-04-01
        cavities[2]["inserts"].append({"revision": "R6", "effective_from": "2026-04-01"})

        ctx = ProjectCtx()
        # After swap
        payload = {"tool_id": "M1", "query_date": "2026-05-01", "cavities": cavities}
        resp = json.loads(
            await run_plm_query_multi_cavity(ctx, json.dumps(payload).encode())
        )
        revs = {r["cavity_id"]: r["revision"] for r in resp["per_cavity_revisions"]}
        assert revs[3] == "R6"
        assert revs[1] == revs[2] == revs[4] == "R5"

        # Before swap
        payload["query_date"] = "2026-03-15"
        resp2 = json.loads(
            await run_plm_query_multi_cavity(ctx, json.dumps(payload).encode())
        )
        revs2 = {r["cavity_id"]: r["revision"] for r in resp2["per_cavity_revisions"]}
        assert all(v == "R5" for v in revs2.values())

    @pytest.mark.asyncio
    async def test_handler_bad_args(self):
        from kerf_plm._tools_module import run_plm_query_multi_cavity
        from kerf_plm._compat import ProjectCtx

        ctx = ProjectCtx()
        resp = json.loads(
            await run_plm_query_multi_cavity(ctx, b"not-json")
        )
        assert resp.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_handler_missing_tool_id(self):
        from kerf_plm._tools_module import run_plm_query_multi_cavity
        from kerf_plm._compat import ProjectCtx

        ctx = ProjectCtx()
        payload = {"tool_id": "", "query_date": "2026-01-01", "cavities": []}
        resp = json.loads(
            await run_plm_query_multi_cavity(ctx, json.dumps(payload).encode())
        )
        assert resp.get("code") == "BAD_ARGS"

    @pytest.mark.asyncio
    async def test_handler_honest_flag_in_response(self):
        from kerf_plm._tools_module import run_plm_query_multi_cavity
        from kerf_plm._compat import ProjectCtx

        ctx = ProjectCtx()
        payload = {
            "tool_id": "T",
            "query_date": "2026-01-01",
            "cavities": [{"cavity_id": 1, "inserts": [{"revision": "R1"}]}],
        }
        resp = json.loads(
            await run_plm_query_multi_cavity(ctx, json.dumps(payload).encode())
        )
        assert "honest_flag" in resp
        assert "wear" in resp["honest_flag"].lower()
