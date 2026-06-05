"""
Tests for the Constraint Manager spreadsheet UI tools.

Covers:
  - constraint_table_get:  returns all columns + builtin net-class rows
  - constraint_table_set:  round-trip (set then get returns updated value)
  - constraint_table_set:  validation rejects out-of-range numbers and bad via_type
  - constraint_table_set:  per-net override round-trip
  - constraint_table_set:  null value clears optional field
"""

import json
import pytest

from kerf_electronics.constraint_manager.tools import (
    COLUMNS,
    constraint_table_get,
    constraint_table_set,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def board():
    return {"type": "pcb_board", "width": 100, "height": 80}


async def call(fn, **kwargs):
    result = await fn(None, json.dumps(kwargs).encode())
    return json.loads(result)


def find_row(rows, name):
    return next((r for r in rows if r["name"] == name), None)


# ── constraint_table_get ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_returns_all_columns():
    r = await call(constraint_table_get, circuit_json=board())
    assert r["columns"] == COLUMNS


@pytest.mark.asyncio
async def test_get_returns_five_builtin_classes():
    r = await call(constraint_table_get, circuit_json=board())
    names = {row["name"] for row in r["rows"]}
    assert {"Default", "Power", "Signal", "HighSpeed", "Differential"} <= names


@pytest.mark.asyncio
async def test_get_net_class_rows_have_kind_net_class():
    r = await call(constraint_table_get, circuit_json=board())
    default_row = find_row(r["rows"], "Default")
    assert default_row is not None
    assert default_row["kind"] == "net_class"


@pytest.mark.asyncio
async def test_get_default_trace_width():
    r = await call(constraint_table_get, circuit_json=board())
    default_row = find_row(r["rows"], "Default")
    assert default_row["trace_width_mm"] == 0.25


# ── constraint_table_set round-trips ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_net_class_trace_width_roundtrip():
    """Set Power.trace_width_mm then get should return updated value."""
    r_set = await call(
        constraint_table_set,
        circuit_json=board(),
        edits=[{"row_name": "Power", "col": "trace_width_mm", "value": 0.8}],
    )
    assert r_set.get("applied")
    assert r_set["applied"][0]["value"] == 0.8

    updated_cj = r_set["circuit_json"]
    r_get = await call(constraint_table_get, circuit_json=updated_cj)
    power_row = find_row(r_get["rows"], "Power")
    assert power_row["trace_width_mm"] == 0.8


@pytest.mark.asyncio
async def test_set_per_net_override_roundtrip():
    """Set per-net override then get should include the net row."""
    r_set = await call(
        constraint_table_set,
        circuit_json=board(),
        edits=[{"row_name": "GND", "col": "trace_width_mm", "value": 1.0, "kind": "net"}],
    )
    assert r_set.get("applied")

    updated_cj = r_set["circuit_json"]
    r_get = await call(constraint_table_get, circuit_json=updated_cj)
    gnd_row = find_row(r_get["rows"], "GND")
    assert gnd_row is not None
    assert gnd_row["kind"] == "net"
    assert gnd_row["trace_width_mm"] == 1.0


@pytest.mark.asyncio
async def test_set_multiple_edits_applied():
    """Multiple edits in one call are all applied."""
    r_set = await call(
        constraint_table_set,
        circuit_json=board(),
        edits=[
            {"row_name": "Signal", "col": "clearance_mm", "value": 0.15},
            {"row_name": "Signal", "col": "via_diameter_mm", "value": 0.55},
        ],
    )
    assert len(r_set["applied"]) == 2


@pytest.mark.asyncio
async def test_set_optional_field_via_type_roundtrip():
    r_set = await call(
        constraint_table_set,
        circuit_json=board(),
        edits=[{"row_name": "HighSpeed", "col": "via_type", "value": "blind"}],
    )
    assert r_set.get("applied")

    r_get = await call(constraint_table_get, circuit_json=r_set["circuit_json"])
    hs_row = find_row(r_get["rows"], "HighSpeed")
    assert hs_row["via_type"] == "blind"


@pytest.mark.asyncio
async def test_set_length_match_group_roundtrip():
    r_set = await call(
        constraint_table_set,
        circuit_json=board(),
        edits=[{"row_name": "Differential", "col": "length_match_group", "value": "DDR4_DQS"}],
    )
    assert r_set.get("applied")
    diff_row = find_row(r_set["table"]["rows"], "Differential")
    assert diff_row["length_match_group"] == "DDR4_DQS"


@pytest.mark.asyncio
async def test_set_null_clears_optional_field():
    """Setting null for an optional column removes it."""
    # First set impedance
    r1 = await call(
        constraint_table_set,
        circuit_json=board(),
        edits=[{"row_name": "HighSpeed", "col": "target_impedance_ohms", "value": 75.0}],
    )
    cj1 = r1["circuit_json"]

    # Then clear it
    r2 = await call(
        constraint_table_set,
        circuit_json=cj1,
        edits=[{"row_name": "HighSpeed", "col": "target_impedance_ohms", "value": None}],
    )
    assert r2.get("applied")
    hs_row = find_row(r2["table"]["rows"], "HighSpeed")
    assert hs_row.get("target_impedance_ohms") is None


# ── validation rejects bad values ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_trace_width_out_of_range_rejected():
    """trace_width_mm = 50 exceeds max 25.0 → rejected."""
    r = await call(
        constraint_table_set,
        circuit_json=board(),
        edits=[{"row_name": "Default", "col": "trace_width_mm", "value": 50.0}],
    )
    assert "error" in r or r.get("rejected")
    if "rejected" in r:
        assert len(r["rejected"]) == 1
        assert "out of range" in r["rejected"][0]["reason"]


@pytest.mark.asyncio
async def test_set_invalid_via_type_rejected():
    """Unknown via_type 'laser' must be rejected."""
    r = await call(
        constraint_table_set,
        circuit_json=board(),
        edits=[{"row_name": "Default", "col": "via_type", "value": "laser"}],
    )
    assert "error" in r or (r.get("rejected") and len(r["rejected"]) == 1)


@pytest.mark.asyncio
async def test_set_readonly_col_rejected():
    """Attempting to write 'name' column must be rejected."""
    r = await call(
        constraint_table_set,
        circuit_json=board(),
        edits=[{"row_name": "Default", "col": "name", "value": "Hacked"}],
    )
    assert "error" in r or r.get("rejected")


@pytest.mark.asyncio
async def test_set_clearance_non_numeric_rejected():
    r = await call(
        constraint_table_set,
        circuit_json=board(),
        edits=[{"row_name": "Default", "col": "clearance_mm", "value": "wide"}],
    )
    assert "error" in r or r.get("rejected")


@pytest.mark.asyncio
async def test_set_partial_apply_some_rejected():
    """One good edit + one bad edit — good one applied, bad one rejected."""
    r = await call(
        constraint_table_set,
        circuit_json=board(),
        edits=[
            {"row_name": "Power", "col": "trace_width_mm", "value": 0.6},   # good
            {"row_name": "Power", "col": "clearance_mm",   "value": -1.0},  # bad
        ],
    )
    assert len(r.get("applied", [])) == 1
    assert len(r.get("rejected", [])) == 1
    # Applied edit should have been committed
    power_row = find_row(r["table"]["rows"], "Power")
    assert power_row["trace_width_mm"] == 0.6


@pytest.mark.asyncio
async def test_set_new_user_class():
    """Can create a brand-new net class via the constraint table."""
    r = await call(
        constraint_table_set,
        circuit_json=board(),
        edits=[
            {"row_name": "USB3", "col": "trace_width_mm", "value": 0.22, "kind": "net_class"},
            {"row_name": "USB3", "col": "clearance_mm",   "value": 0.18, "kind": "net_class"},
        ],
    )
    assert len(r.get("applied", [])) == 2
    usb3_row = find_row(r["table"]["rows"], "USB3")
    assert usb3_row is not None
    assert usb3_row["trace_width_mm"] == 0.22


@pytest.mark.asyncio
async def test_get_missing_circuit_json():
    r = await call(constraint_table_get, circuit_json=None)
    assert "error" in r


@pytest.mark.asyncio
async def test_set_missing_circuit_json():
    r = await call(constraint_table_set, circuit_json=None,
                   edits=[{"row_name": "Default", "col": "trace_width_mm", "value": 0.3}])
    assert "error" in r
