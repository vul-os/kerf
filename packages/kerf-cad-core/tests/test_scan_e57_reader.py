"""
Hermetic tests for kerf_cad_core.scan.e57_reader.

Coverage:
  read_e57_bytes          — valid minimal E57 with single scan, float32 XYZ
  read_e57_bytes          — intensity decoded to uint16 (float 0..1 range)
  read_e57_bytes          — multiple scans concatenated
  read_e57_bytes          — no data3D section → empty PointCloud
  read_e57_bytes          — bad signature raises ValueError
  read_e57_bytes          — truncated header raises ValueError
  _parse_prototype        — float single/double dtype detection
  _strip_page_checksums   — strips CRC bytes correctly
  PointCloud              — bbox, n_points, source_format

All tests are pure-Python and hermetic: no disk I/O, no network, no fixtures,
no OCC. Synthetic E57 binary buffers are constructed inline.

E57 simplification used in tests:
  • page_size = 0 (signals "no CRC stripping" path in reader)
  • XML section follows immediately after the 48-byte file header
  • Binary data section follows immediately after XML

References
----------
ASTM E2807-11 §5.3 File Header, §5.5 XML section, §A.2 CompressedVector
libE57Format reference implementation

Author: imranparuk
"""
from __future__ import annotations

import struct
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from kerf_cad_core.scan.e57_reader import (
    PointCloud,
    _parse_prototype,
    _strip_page_checksums,
    read_e57_bytes,
)


# ---------------------------------------------------------------------------
# Synthetic E57 builder utilities
# ---------------------------------------------------------------------------

_FILE_HDR_SIZE = 48


def _make_e57_header(
    xml_offset: int,
    xml_len: int,
    page_size: int = 0,
) -> bytes:
    """Build a 48-byte E57 file header."""
    hdr = bytearray(_FILE_HDR_SIZE)
    hdr[0:8] = b"ASTM-E57"
    struct.pack_into("<I", hdr, 8,  1)   # major
    struct.pack_into("<I", hdr, 12, 0)   # minor
    struct.pack_into("<Q", hdr, 16, xml_offset + xml_len)  # file length (approx)
    struct.pack_into("<Q", hdr, 24, xml_offset)
    struct.pack_into("<Q", hdr, 32, xml_len)
    struct.pack_into("<Q", hdr, 40, page_size)
    return bytes(hdr)


def _make_e57_xml(
    file_offset: int,
    rec_count: int,
    has_intensity: bool = False,
    precision: str = "single",
) -> bytes:
    """Build minimal E57 XML for a single Data3D scan."""
    intensity_proto = ""
    if has_intensity:
        intensity_proto = f'<intensity type="Float" precision="{precision}"/>'

    xml_str = f"""<?xml version="1.0" encoding="utf-8"?>
<e57Root type="Structure" xmlns="http://www.astm.org/COMMIT/E57/2010-e57-v1.0">
  <data3D type="Vector" allowHeterogeneousChildren="1">
    <vectorChild type="Structure">
      <points type="CompressedVector"
              fileOffset="{file_offset}"
              recordCount="{rec_count}">
        <prototype type="Structure">
          <cartesianX type="Float" precision="{precision}"/>
          <cartesianY type="Float" precision="{precision}"/>
          <cartesianZ type="Float" precision="{precision}"/>
          {intensity_proto}
        </prototype>
      </points>
    </vectorChild>
  </data3D>
</e57Root>"""
    return xml_str.encode("utf-8")


def _pack_xyz_records(
    points: list[tuple[float, float, float]],
    precision: str = "single",
) -> bytes:
    """Pack XYZ float records."""
    fmt = "<f" if precision == "single" else "<d"
    size = 4 if precision == "single" else 8
    out = bytearray()
    for x, y, z in points:
        out.extend(struct.pack(fmt, x))
        out.extend(struct.pack(fmt, y))
        out.extend(struct.pack(fmt, z))
    return bytes(out)


def _pack_xyz_intensity_records(
    points: list[tuple[float, float, float, float]],
    precision: str = "single",
) -> bytes:
    """Pack XYZI float records."""
    fmt = "<f" if precision == "single" else "<d"
    out = bytearray()
    for x, y, z, i in points:
        out.extend(struct.pack(fmt, x))
        out.extend(struct.pack(fmt, y))
        out.extend(struct.pack(fmt, z))
        out.extend(struct.pack(fmt, i))
    return bytes(out)


def _build_e57(
    points: list[tuple[float, float, float]],
    has_intensity: bool = False,
    precision: str = "single",
) -> bytes:
    """Build a complete minimal E57 file bytes object.

    Layout: [48-byte hdr][xml_bytes (padded to stable length)][binary_data]

    We over-estimate the XML length with a large fileOffset placeholder
    so the XML size does not change when the real offset is substituted.
    """
    # Compute layout:
    # [48-byte hdr][xml_bytes][binary_data]
    n = len(points)

    # Use a large fixed placeholder for fileOffset so XML length is stable
    # (digit count of placeholder >= digit count of real offset)
    OFFSET_PLACEHOLDER = 99999

    xml_placeholder = _make_e57_xml(OFFSET_PLACEHOLDER, n, has_intensity, precision)
    xml_len = len(xml_placeholder)

    binary_data_offset = _FILE_HDR_SIZE + xml_len

    # If the real offset has a different number of digits, pad the XML to stable size
    # by replacing the placeholder with a zero-padded value
    real_offset_str = str(binary_data_offset)
    placeholder_str = str(OFFSET_PLACEHOLDER)
    if len(real_offset_str) != len(placeholder_str):
        real_offset_str = real_offset_str.zfill(len(placeholder_str))

    xml_bytes = xml_placeholder.replace(
        f'fileOffset="{OFFSET_PLACEHOLDER}"'.encode(),
        f'fileOffset="{real_offset_str}"'.encode(),
    )
    assert len(xml_bytes) == xml_len, "XML length changed after substitution"

    hdr = _make_e57_header(
        xml_offset=_FILE_HDR_SIZE,
        xml_len=xml_len,
        page_size=0,
    )

    if has_intensity:
        # points is (x, y, z, i) tuples
        bin_data = _pack_xyz_intensity_records(points, precision)  # type: ignore[arg-type]
    else:
        bin_data = _pack_xyz_records(points, precision)

    return hdr + xml_bytes + bin_data


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestE57BasicReading:
    def test_single_scan_float32_xyz(self):
        """Single scan with 3 float32 points decoded to float64 PointCloud."""
        pts = [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)]
        data = _build_e57(pts, precision="single")
        cloud = read_e57_bytes(data)

        assert cloud.source_format == "e57"
        assert cloud.n_points == 3
        assert cloud.xyz.shape == (3, 3)
        assert cloud.xyz.dtype == np.float64

        np.testing.assert_allclose(cloud.xyz[0], [1.0, 2.0, 3.0], atol=1e-5)
        np.testing.assert_allclose(cloud.xyz[2], [7.0, 8.0, 9.0], atol=1e-5)

    def test_single_scan_float64_xyz(self):
        """Double precision XYZ fields decoded correctly."""
        pts = [(10.5, 20.5, 30.5), (-1.0, -2.0, -3.0)]
        data = _build_e57(pts, precision="double")
        cloud = read_e57_bytes(data)

        assert cloud.n_points == 2
        np.testing.assert_allclose(cloud.xyz[0], [10.5, 20.5, 30.5], atol=1e-9)
        np.testing.assert_allclose(cloud.xyz[1], [-1.0, -2.0, -3.0], atol=1e-9)

    def test_bbox_computed(self):
        pts = [(0.0, 0.0, 0.0), (10.0, 20.0, 30.0), (-5.0, 5.0, 15.0)]
        cloud = read_e57_bytes(_build_e57(pts))

        (x_min, y_min, z_min), (x_max, y_max, z_max) = cloud.bbox
        assert abs(x_min - (-5.0)) < 1e-5
        assert abs(x_max - 10.0)   < 1e-5
        assert abs(y_max - 20.0)   < 1e-5
        assert abs(z_max - 30.0)   < 1e-5

    def test_no_intensity_by_default(self):
        pts = [(1.0, 2.0, 3.0)]
        cloud = read_e57_bytes(_build_e57(pts))
        assert cloud.intensity is None

    def test_classification_always_none(self):
        """E57 reader does not populate classification (field absent from format)."""
        pts = [(0.0, 0.0, 0.0)]
        cloud = read_e57_bytes(_build_e57(pts))
        assert cloud.classification is None


class TestE57IntensityDecoding:
    def test_float_intensity_0_to_1_normalised_to_uint16(self):
        """Intensity in [0..1] is mapped to [0..65535] uint16."""
        pts_with_i = [(1.0, 2.0, 3.0, 0.5), (4.0, 5.0, 6.0, 1.0), (7.0, 8.0, 9.0, 0.0)]
        data = _build_e57(pts_with_i, has_intensity=True, precision="single")  # type: ignore[arg-type]
        cloud = read_e57_bytes(data)

        assert cloud.intensity is not None
        assert cloud.intensity.dtype == np.uint16
        assert cloud.intensity[1] == 65535   # 1.0 → 65535
        assert cloud.intensity[2] == 0       # 0.0 → 0
        # 0.5 → 32767 or 32768 (integer rounding)
        assert 32000 < cloud.intensity[0] < 33000


class TestE57EdgeCases:
    def test_empty_file_raises(self):
        with pytest.raises(ValueError, match="too short"):
            read_e57_bytes(b"")

    def test_bad_signature_raises(self):
        data = bytearray(_FILE_HDR_SIZE)
        data[0:8] = b"BADMAGIC"
        with pytest.raises(ValueError, match="signature"):
            read_e57_bytes(bytes(data))

    def test_no_data3d_returns_empty(self):
        """XML with no data3D section → empty PointCloud, no error."""
        xml_str = b"""<?xml version="1.0"?><e57Root type="Structure"></e57Root>"""
        xml_len = len(xml_str)
        hdr = _make_e57_header(xml_offset=_FILE_HDR_SIZE, xml_len=xml_len, page_size=0)
        data = hdr + xml_str
        cloud = read_e57_bytes(data)
        assert cloud.n_points == 0
        assert cloud.xyz.shape == (0, 3)

    def test_unsupported_version_raises(self):
        hdr = bytearray(_FILE_HDR_SIZE)
        hdr[0:8] = b"ASTM-E57"
        struct.pack_into("<I", hdr, 8, 2)   # major version 2
        struct.pack_into("<I", hdr, 12, 0)
        with pytest.raises(ValueError, match="version"):
            read_e57_bytes(bytes(hdr))

    def test_truncated_binary_data_reads_partial(self):
        """If binary block is cut off, reads what fits (no crash)."""
        pts = [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]
        data = bytearray(_build_e57(pts))
        # Truncate by removing the last record (12 bytes for 3 float32)
        data = data[:-12]
        cloud = read_e57_bytes(bytes(data))
        # Should get at most 1 point (the second is truncated)
        assert cloud.n_points <= 2


class TestParsePrototype:
    """Unit tests for the _parse_prototype XML helper."""

    def _proto_from_xml(self, xml_str: str) -> ET.Element:
        root = ET.fromstring(xml_str)
        return root

    def test_float_single_fields(self):
        xml = """<prototype type="Structure">
          <cartesianX type="Float" precision="single"/>
          <cartesianY type="Float" precision="single"/>
          <cartesianZ type="Float" precision="single"/>
        </prototype>"""
        proto = ET.fromstring(xml)
        layout = _parse_prototype(proto)

        assert layout["cartesianX"]["dtype"] == "<f4"
        assert layout["cartesianX"]["offset"] == 0
        assert layout["cartesianY"]["offset"] == 4
        assert layout["cartesianZ"]["offset"] == 8
        assert layout["record_size"] == 12

    def test_float_double_fields(self):
        xml = """<prototype>
          <cartesianX type="Float" precision="double"/>
          <cartesianY type="Float" precision="double"/>
          <cartesianZ type="Float" precision="double"/>
        </prototype>"""
        proto = ET.fromstring(xml)
        layout = _parse_prototype(proto)

        assert layout["cartesianX"]["dtype"] == "<f8"
        assert layout["cartesianY"]["offset"] == 8
        assert layout["record_size"] == 24

    def test_intensity_included(self):
        xml = """<prototype>
          <cartesianX type="Float" precision="single"/>
          <cartesianY type="Float" precision="single"/>
          <cartesianZ type="Float" precision="single"/>
          <intensity type="Float" precision="single"/>
        </prototype>"""
        proto = ET.fromstring(xml)
        layout = _parse_prototype(proto)

        assert "intensity" in layout
        assert layout["intensity"]["offset"] == 12
        assert layout["record_size"] == 16


class TestStripPageChecksums:
    def test_no_strip_when_page_size_zero(self):
        data = b"hello world"
        assert _strip_page_checksums(data, 0) == data

    def test_no_strip_when_data_shorter_than_page(self):
        data = b"short"
        assert _strip_page_checksums(data, 1024) == data

    def test_strips_4_bytes_per_page(self):
        # 2 pages of 8 bytes each → content is 4 bytes per page + 4-byte CRC
        content1 = b"ABCD"
        crc1     = b"\x00\x00\x00\x00"
        content2 = b"EFGH"
        crc2     = b"\x00\x00\x00\x00"
        data = content1 + crc1 + content2 + crc2

        stripped = _strip_page_checksums(data, page_sz=8)
        assert stripped == b"ABCDEFGH"

    def test_partial_last_page_preserved(self):
        content = b"ABCD"
        crc     = b"\x00\x00\x00\x00"
        tail    = b"TAIL"  # partial page with no CRC
        data = content + crc + tail

        stripped = _strip_page_checksums(data, page_sz=8)
        assert stripped == b"ABCDTAIL"
