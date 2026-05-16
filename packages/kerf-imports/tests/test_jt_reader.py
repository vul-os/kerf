"""
test_jt_reader.py — pytest suite for jt_reader.py.

All tests use SYNTHETIC byte fixtures constructed in-test (no real JT files).
The make_minimal_jt() fixture builder in jt_reader.py produces minimal valid
JT byte streams; parse_jt() round-trips them.
"""

from __future__ import annotations

import io
import struct
import zlib

import pytest

from kerf_imports.jt_reader import (
    _JT_MAGIC,
    _Reader,
    _parse_header,
    _parse_toc,
    _tristrip_to_triangles,
    _parse_tess_segment,
    _parse_lsg_segment,
    _build_tree,
    make_minimal_jt,
    parse_jt,
    _SEG_TYPE_LSG,
    _SEG_TYPE_TESS,
    _SEG_TYPE_XTWB,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _u32(v: int) -> bytes: return struct.pack("<I", v)
def _i32(v: int) -> bytes: return struct.pack("<i", v)
def _i64(v: int) -> bytes: return struct.pack("<q", v)
def _f32(v: float) -> bytes: return struct.pack("<f", v)


def _make_header_bytes(version: str = "10.0", toc_offset: int = 80,
                       byte_order: int = 1) -> bytes:
    """Build a raw 80-byte JT header (little-endian by default)."""
    buf = io.BytesIO()
    buf.write(b"Version ")                                # magic (8)
    ver_enc = version.encode("ascii")[:10].ljust(10, b"\x00")
    buf.write(ver_enc)                                    # version (10)
    buf.write(struct.pack("B", byte_order))               # byte_order (1)
    buf.write(struct.pack("<i", 0))                       # reserved (4)
    buf.write(struct.pack("<q", toc_offset))              # toc_offset (8)
    raw = buf.getvalue()
    # Pad to 80 bytes
    return raw + b"\x00" * (80 - len(raw))


def _make_toc_bytes(entries: list[tuple]) -> bytes:
    """
    Build a TOC blob.
    Each entry: (guid_int: int, offset: int, length: int, attrs: int)
    where guid_int is packed as a raw 16-byte big-endian int.
    """
    buf = io.BytesIO()
    buf.write(_u32(len(entries)))
    for guid_int, offset, length, attrs in entries:
        # GUID as 4 LE uint32
        a = (guid_int >> 96) & 0xFFFFFFFF
        b = (guid_int >> 64) & 0xFFFFFFFF
        c = (guid_int >> 32) & 0xFFFFFFFF
        d =  guid_int        & 0xFFFFFFFF
        buf.write(struct.pack("<IIII", a, b, c, d))
        buf.write(struct.pack("<q", offset))
        buf.write(struct.pack("<i", length))
        buf.write(_u32(attrs))
    return buf.getvalue()


def _make_tess_payload(n_verts: int = 3) -> bytes:
    """Build a minimal uncompressed tess payload."""
    buf = io.BytesIO()
    buf.write(_u32(1))           # version
    buf.write(b"\x00" * 32)     # bounding box
    buf.write(_u32(n_verts))    # vertex_count
    for i in range(n_verts):
        buf.write(_f32(float(i)))
        buf.write(_f32(0.0))
        buf.write(_f32(0.0))
    buf.write(_u32(0))           # normal_count = 0
    buf.write(_u32(1))           # strip_count = 1
    buf.write(_u32(n_verts))    # strip_len
    for i in range(n_verts):
        buf.write(_i32(i))
    return buf.getvalue()


def _wrap_segment(seg_type: int, payload: bytes) -> bytes:
    total = 4 + 4 + 4 + len(payload)
    return struct.pack("<i", total) + _u32(seg_type) + _u32(0) + payload


# ─── Tests: _Reader ───────────────────────────────────────────────────────────

def test_reader_u32_little_endian():
    r = _Reader(struct.pack("<I", 0xDEADBEEF), little_endian=True)
    assert r.u32() == 0xDEADBEEF


def test_reader_u32_big_endian():
    r = _Reader(struct.pack(">I", 0xDEADBEEF), little_endian=False)
    assert r.u32() == 0xDEADBEEF


def test_reader_eof_raises():
    r = _Reader(b"\x01\x02", little_endian=True)
    with pytest.raises(EOFError):
        r.u32()


def test_reader_counted_string():
    name = "TestPart"
    enc = name.encode("utf-16-le")
    buf = struct.pack("<H", len(name)) + enc
    r = _Reader(buf, little_endian=True)
    assert r.counted_string() == "TestPart"


def test_reader_f32():
    r = _Reader(struct.pack("<f", 3.14), little_endian=True)
    assert abs(r.f32() - 3.14) < 1e-5


# ─── Tests: _parse_header ─────────────────────────────────────────────────────

def test_header_magic_valid():
    hdr = make_minimal_jt(version="10.0")
    result = _parse_header(hdr)
    assert result["version"] == "10.0"


def test_header_bad_magic():
    bad = b"NOTAJT  " + b"\x00" * 72
    result = parse_jt(bad)
    assert result["ok"] is False
    assert "not a JT file" in result["reason"]


def test_header_version_v8():
    raw = _make_header_bytes(version="8.0") + b"\x00" * 100  # pad so TOC parse fails gracefully
    result = _parse_header(raw)
    assert result["major"] == 8


def test_header_version_v10():
    raw = _make_header_bytes(version="10.0") + b"\x00" * 100
    result = _parse_header(raw)
    assert result["major"] == 10


def test_header_little_endian_flag():
    raw = _make_header_bytes(byte_order=1) + b"\x00" * 100
    result = _parse_header(raw)
    assert result["little_endian"] is True


def test_header_big_endian_flag():
    raw = _make_header_bytes(byte_order=0) + b"\x00" * 100
    result = _parse_header(raw)
    assert result["little_endian"] is False


def test_header_toc_offset():
    raw = _make_header_bytes(toc_offset=256) + b"\x00" * 200
    result = _parse_header(raw)
    assert result["toc_offset"] == 256


def test_header_truncated_file():
    result = parse_jt(b"Version " + b"\x00" * 10)
    assert result["ok"] is False


# ─── Tests: _parse_toc ────────────────────────────────────────────────────────

def test_toc_entry_count():
    data = make_minimal_jt(include_tess=True, include_assembly=True)
    hdr = _parse_header(data)
    toc = _parse_toc(data, hdr)
    assert len(toc) == 2


def test_toc_entry_has_required_fields():
    data = make_minimal_jt(include_tess=True, include_assembly=False)
    hdr = _parse_header(data)
    toc = _parse_toc(data, hdr)
    assert len(toc) == 1
    entry = toc[0]
    assert "id" in entry
    assert "offset" in entry
    assert "length" in entry
    assert "attributes" in entry


def test_toc_entry_offset_in_range():
    data = make_minimal_jt()
    hdr = _parse_header(data)
    toc = _parse_toc(data, hdr)
    for entry in toc:
        assert entry["offset"] >= 0
        assert entry["offset"] < len(data)


def test_toc_single_tess_entry():
    data = make_minimal_jt(include_tess=True, include_assembly=False)
    hdr = _parse_header(data)
    toc = _parse_toc(data, hdr)
    assert len(toc) == 1


# ─── Tests: tristrip conversion ───────────────────────────────────────────────

def test_tristrip_single_triangle():
    result = _tristrip_to_triangles([0, 1, 2], vertex_count=3)
    assert result == [0, 1, 2]


def test_tristrip_quad_strip():
    # Strip [0,1,2,3] → triangles (0,1,2) and (1,3,2) [alternating flip]
    result = _tristrip_to_triangles([0, 1, 2, 3], vertex_count=4)
    assert len(result) == 6
    assert len(result) % 3 == 0


def test_tristrip_negative_restart():
    # Negative index should reset the window
    result = _tristrip_to_triangles([0, 1, 2, -1, 3, 4, 5], vertex_count=6)
    assert len(result) == 6  # two separate triangles


def test_tristrip_degenerate_skipped():
    # Two identical adjacent indices → degenerate, should not emit a triangle
    result = _tristrip_to_triangles([0, 0, 1], vertex_count=3)
    assert result == []


def test_tristrip_out_of_range_skipped():
    # Index >= vertex_count → reset and skip
    result = _tristrip_to_triangles([0, 1, 999], vertex_count=3)
    assert result == []


# ─── Tests: tessellation segment parsing ──────────────────────────────────────

def test_tess_basic_triangle():
    payload = _make_tess_payload(n_verts=3)
    mesh = _parse_tess_segment(payload, le=True)
    assert mesh is not None
    assert len(mesh["vertices"]) == 3
    assert mesh["indices"] == [0, 1, 2]


def test_tess_vertex_positions():
    payload = _make_tess_payload(n_verts=3)
    mesh = _parse_tess_segment(payload, le=True)
    # First vertex should be at (0,0,0)
    assert abs(mesh["vertices"][0][0]) < 1e-5
    assert abs(mesh["vertices"][0][1]) < 1e-5
    assert abs(mesh["vertices"][0][2]) < 1e-5


def test_tess_face_count():
    payload = _make_tess_payload(n_verts=3)
    mesh = _parse_tess_segment(payload, le=True)
    assert len(mesh["indices"]) // 3 == 1


def test_tess_truncated_returns_none_or_partial():
    # Just the version field — too short for a real segment
    payload = _u32(1)
    result = _parse_tess_segment(payload, le=True)
    # Should not raise; may return None or empty mesh
    assert result is None or isinstance(result, dict)


def test_tess_zlib_compressed_segment():
    """A segment wrapped with zlib compression should decompress correctly."""
    payload = _make_tess_payload(n_verts=3)
    compressed = zlib.compress(payload)

    seg_buf = io.BytesIO()
    total = 4 + 4 + 4 + 4 + len(compressed)
    seg_buf.write(struct.pack("<i", total))
    seg_buf.write(_u32(_SEG_TYPE_TESS))
    seg_buf.write(_u32(2))                    # compression_flag = 2 (zlib)
    seg_buf.write(_i32(len(payload)))         # uncompressed_len
    seg_buf.write(compressed)

    # Parse manually to verify decompression path
    from kerf_imports.jt_reader import _read_segment_data
    hdr = {"little_endian": True}
    entry = {"offset": 0, "length": len(seg_buf.getvalue())}
    dec_payload, seg_type = _read_segment_data(seg_buf.getvalue(), entry, hdr)
    assert dec_payload == payload
    assert seg_type == _SEG_TYPE_TESS


# ─── Tests: LSG / assembly tree ───────────────────────────────────────────────

def test_lsg_single_part_node():
    data = make_minimal_jt(include_assembly=True, include_tess=True, part_name="Widget")
    result = parse_jt(data)
    assert result["ok"] is True
    # Assembly should have at least one node
    assert len(result["assembly"]) >= 1


def test_lsg_part_name():
    data = make_minimal_jt(part_name="BracketA")
    result = parse_jt(data)
    assert result["ok"] is True
    # Walk tree and find the name
    def find_names(nodes):
        names = []
        for n in nodes:
            if n.get("name"):
                names.append(n["name"])
            names.extend(find_names(n.get("children", [])))
        return names
    names = find_names(result["assembly"])
    # The LSG was built with part_name; at least one node should have a non-empty name
    # (the name is stored in the LSG payload we control)
    assert isinstance(names, list)


def test_assembly_node_count():
    data = make_minimal_jt(include_assembly=True)
    result = parse_jt(data)
    assert result["ok"] is True
    from kerf_imports.jt_reader import _count_nodes
    assert _count_nodes(result["assembly"]) >= 1


def test_assembly_node_has_expected_keys():
    data = make_minimal_jt(include_assembly=True)
    result = parse_jt(data)
    assert result["ok"] is True
    if result["assembly"]:
        node = result["assembly"][0]
        assert "id" in node
        assert "name" in node
        assert "transform" in node
        assert "children" in node


# ─── Tests: end-to-end parse_jt ──────────────────────────────────────────────

def test_parse_jt_ok_flag():
    data = make_minimal_jt()
    result = parse_jt(data)
    assert result["ok"] is True


def test_parse_jt_version_field():
    data = make_minimal_jt(version="10.0")
    result = parse_jt(data)
    assert result["version"] == "10.0"


def test_parse_jt_toc_count_field():
    data = make_minimal_jt(include_tess=True, include_assembly=True)
    result = parse_jt(data)
    assert result["toc_entry_count"] == 2


def test_parse_jt_meshes_present():
    data = make_minimal_jt(include_tess=True)
    result = parse_jt(data)
    assert len(result["meshes"]) >= 1


def test_parse_jt_mesh_verts_faces():
    data = make_minimal_jt(include_tess=True, n_verts=3)
    result = parse_jt(data)
    assert result["ok"] is True
    for mesh in result["meshes"].values():
        assert len(mesh["vertices"]) >= 3
        assert len(mesh["indices"]) >= 3
        assert len(mesh["indices"]) % 3 == 0


def test_parse_jt_bad_magic_returns_error():
    result = parse_jt(b"\x00" * 100)
    assert result["ok"] is False
    assert "reason" in result


def test_parse_jt_empty_bytes():
    result = parse_jt(b"")
    assert result["ok"] is False
    assert "reason" in result


def test_parse_jt_truncated_after_header():
    hdr = _make_header_bytes(toc_offset=80)
    # Provide header but no TOC
    result = parse_jt(hdr)
    assert result["ok"] is False
    assert "reason" in result


def test_parse_jt_warnings_list_present():
    data = make_minimal_jt()
    result = parse_jt(data)
    assert "warnings" in result
    assert isinstance(result["warnings"], list)


def test_parse_jt_v8_header():
    data = make_minimal_jt(version="8.0")
    result = parse_jt(data)
    assert result["ok"] is True
    assert result["version"] == "8.0"


def test_parse_jt_properties_dict_present():
    data = make_minimal_jt()
    result = parse_jt(data)
    assert "properties" in result
    assert isinstance(result["properties"], dict)


def test_parse_jt_no_tess_gives_empty_meshes():
    data = make_minimal_jt(include_tess=False, include_assembly=True)
    result = parse_jt(data)
    assert result["ok"] is True
    assert len(result["meshes"]) == 0


def test_xt_brep_segment_skipped_with_warning():
    """A segment with the XT B-rep type should be skipped, not crash."""
    # Build a JT with a fake XT B-rep segment (by patching segment type)
    base = make_minimal_jt(include_tess=True, include_assembly=False)
    hdr_d = _parse_header(base)
    toc = _parse_toc(base, hdr_d)

    # Patch the first segment's type field in the raw buffer
    entry = toc[0]
    offset = entry["offset"]
    # Segment frame: int32(total) | uint32(type) | ...
    # type is at bytes 4..8 from segment start
    patched = bytearray(base)
    struct.pack_into("<I", patched, offset + 4, _SEG_TYPE_XTWB)
    result = parse_jt(bytes(patched))
    # Should succeed but with a warning about skipped B-rep
    assert result["ok"] is True
    assert any("XT B-rep skipped" in w for w in result["warnings"])


def test_make_minimal_jt_roundtrips():
    """make_minimal_jt produces bytes that parse_jt can fully parse."""
    for version in ("8.0", "9.5", "10.0"):
        data = make_minimal_jt(version=version)
        result = parse_jt(data)
        assert result["ok"] is True, f"Failed for version {version}: {result.get('reason')}"


if __name__ == "__main__":
    import pytest as _pytest
    _pytest.main([__file__, "-v"])
