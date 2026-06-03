"""
Hermetic tests for kerf_cad_core.scan.las_reader.

Coverage:
  read_las_bytes          — valid LAS 1.2 format-0 binary, intensity, classification
  read_las_bytes          — LAS 1.4 format-6 variant with 64-bit point count
  read_las_bytes          — zero-point file returns empty PointCloud
  read_las_bytes          — bad signature raises ValueError
  read_las_bytes          — truncated header raises ValueError
  PointCloud dataclass    — bbox computation, n_points, source_format
  Coordinate scaling      — scale + offset applied correctly

All tests are pure-Python and hermetic: no disk I/O, no network, no fixtures,
no OCC dependency. Synthetic LAS binary buffers are constructed inline.

References
----------
ASPRS LAS 1.4-R15 (2019) §2.3 Public Header Block
ASPRS LAS 1.2 (2008) §2.3

Author: imranparuk
"""
from __future__ import annotations

import struct

import numpy as np
import pytest

from kerf_cad_core.scan.las_reader import PointCloud, read_las_bytes


# ---------------------------------------------------------------------------
# Synthetic LAS builder
# ---------------------------------------------------------------------------

def _make_las12_header(
    point_count: int,
    point_format: int,
    record_len: int,
    scale: tuple[float, float, float] = (0.001, 0.001, 0.001),
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> bytes:
    """Build a minimal 227-byte LAS 1.2 public header block."""
    hdr = bytearray(227)
    # Signature
    hdr[0:4] = b"LASF"
    # File source ID + reserved
    # Version 1.2
    hdr[24] = 1   # major
    hdr[25] = 2   # minor
    # System identifier (32 bytes) — zeroes
    # Generating software (32 bytes) — zeroes
    # File creation day / year — zeroes
    # Header size
    struct.pack_into("<H", hdr, 94, 227)
    # Offset to point data: header + 0 VLRs
    struct.pack_into("<I", hdr, 96, 227)
    # Number of VLRs
    struct.pack_into("<I", hdr, 100, 0)
    # Point data format
    hdr[104] = point_format
    # Point data record length
    struct.pack_into("<H", hdr, 105, record_len)
    # Point count
    struct.pack_into("<I", hdr, 107, point_count)
    # Scale factors
    struct.pack_into("<d", hdr, 131, scale[0])
    struct.pack_into("<d", hdr, 139, scale[1])
    struct.pack_into("<d", hdr, 147, scale[2])
    # Offsets
    struct.pack_into("<d", hdr, 155, offset[0])
    struct.pack_into("<d", hdr, 163, offset[1])
    struct.pack_into("<d", hdr, 171, offset[2])
    return bytes(hdr)


def _make_fmt0_record(
    xi: int, yi: int, zi: int,
    intensity: int = 0,
    classification: int = 2,
) -> bytes:
    """Build a 20-byte Point Data Record Format 0."""
    rec = bytearray(20)
    struct.pack_into("<i", rec, 0, xi)   # X int32
    struct.pack_into("<i", rec, 4, yi)   # Y int32
    struct.pack_into("<i", rec, 8, zi)   # Z int32
    struct.pack_into("<H", rec, 12, intensity)  # intensity uint16
    rec[14] = 0x11   # return number bits: return 1 of 1
    rec[15] = classification  # classification uint8
    rec[16] = 0   # scan angle rank
    rec[17] = 0   # user data
    struct.pack_into("<H", rec, 18, 0)  # point source ID
    return bytes(rec)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBasicLasReading:
    def test_single_point_format0(self):
        """A single-point LAS 1.2 file is decoded correctly."""
        # scale=0.001 offset=0  →  X_world = int * 0.001
        hdr = _make_las12_header(1, 0, 20, scale=(0.001, 0.001, 0.001))
        rec = _make_fmt0_record(xi=1000, yi=2000, zi=3000,
                                intensity=512, classification=5)
        data = hdr + rec
        cloud = read_las_bytes(data)

        assert cloud.source_format == "las"
        assert cloud.n_points == 1
        assert cloud.xyz.shape == (1, 3)
        assert cloud.xyz.dtype == np.float64

        # X=1000*0.001=1.0, Y=2000*0.001=2.0, Z=3000*0.001=3.0
        assert abs(cloud.xyz[0, 0] - 1.0) < 1e-9
        assert abs(cloud.xyz[0, 1] - 2.0) < 1e-9
        assert abs(cloud.xyz[0, 2] - 3.0) < 1e-9

    def test_intensity_extracted(self):
        hdr = _make_las12_header(1, 0, 20)
        rec = _make_fmt0_record(1000, 2000, 3000, intensity=65535)
        cloud = read_las_bytes(hdr + rec)
        assert cloud.intensity is not None
        assert cloud.intensity[0] == 65535

    def test_classification_extracted(self):
        hdr = _make_las12_header(1, 0, 20)
        rec = _make_fmt0_record(0, 0, 0, classification=12)
        cloud = read_las_bytes(hdr + rec)
        assert cloud.classification is not None
        assert cloud.classification[0] == 12

    def test_multiple_points(self):
        n = 5
        hdr = _make_las12_header(n, 0, 20)
        recs = b"".join(
            _make_fmt0_record(i * 1000, i * 2000, i * 3000, intensity=i * 100)
            for i in range(n)
        )
        cloud = read_las_bytes(hdr + recs)
        assert cloud.n_points == n
        assert cloud.xyz.shape == (n, 3)
        # Point 3: X=3000*0.001=3.0
        assert abs(cloud.xyz[3, 0] - 3.0) < 1e-9

    def test_offset_applied(self):
        """Offset is added after scale multiplication."""
        hdr = _make_las12_header(
            1, 0, 20,
            scale=(1.0, 1.0, 1.0),
            offset=(100.0, 200.0, 300.0),
        )
        rec = _make_fmt0_record(xi=5, yi=10, zi=15)
        cloud = read_las_bytes(hdr + rec)
        assert abs(cloud.xyz[0, 0] - 105.0) < 1e-9
        assert abs(cloud.xyz[0, 1] - 210.0) < 1e-9
        assert abs(cloud.xyz[0, 2] - 315.0) < 1e-9

    def test_bbox_correct(self):
        n = 4
        coords = [(0, 0, 0), (10000, 0, 0), (0, 20000, 0), (0, 0, 30000)]
        hdr = _make_las12_header(n, 0, 20, scale=(0.001, 0.001, 0.001))
        recs = b"".join(_make_fmt0_record(x, y, z) for x, y, z in coords)
        cloud = read_las_bytes(hdr + recs)

        (x_min, y_min, z_min), (x_max, y_max, z_max) = cloud.bbox
        assert abs(x_min) < 1e-9
        assert abs(x_max - 10.0) < 1e-9
        assert abs(y_max - 20.0) < 1e-9
        assert abs(z_max - 30.0) < 1e-9

    def test_negative_coords(self):
        """Negative int32 XYZ values decode to negative world coords."""
        hdr = _make_las12_header(1, 0, 20, scale=(0.001, 0.001, 0.001))
        rec = _make_fmt0_record(xi=-5000, yi=-10000, zi=-15000)
        cloud = read_las_bytes(hdr + rec)
        assert abs(cloud.xyz[0, 0] - (-5.0)) < 1e-9
        assert abs(cloud.xyz[0, 1] - (-10.0)) < 1e-9
        assert abs(cloud.xyz[0, 2] - (-15.0)) < 1e-9


class TestLasEdgeCases:
    def test_zero_point_count_infers_from_data(self):
        """n_points=0 in header → infer from data length."""
        hdr = _make_las12_header(0, 0, 20)
        rec = _make_fmt0_record(1000, 2000, 3000)
        cloud = read_las_bytes(hdr + rec)
        assert cloud.n_points == 1

    def test_empty_data_section(self):
        """Point count=0 and no data → empty PointCloud."""
        hdr = _make_las12_header(0, 0, 20)
        cloud = read_las_bytes(hdr)
        assert cloud.n_points == 0
        assert cloud.xyz.shape == (0, 3)
        assert cloud.intensity is None
        assert cloud.classification is None

    def test_bad_signature_raises(self):
        hdr = bytearray(_make_las12_header(0, 0, 20))
        hdr[0:4] = b"XXXX"
        with pytest.raises(ValueError, match="signature"):
            read_las_bytes(bytes(hdr))

    def test_truncated_header_raises(self):
        with pytest.raises(ValueError):
            read_las_bytes(b"LASF" + b"\x00" * 10)

    def test_point_count_clamped_to_available_bytes(self):
        """If header says more points than fit in file, we read what's there."""
        hdr = _make_las12_header(100, 0, 20)  # claims 100 but only 2 records follow
        rec = _make_fmt0_record(0, 0, 0) + _make_fmt0_record(1000, 2000, 3000)
        cloud = read_las_bytes(hdr + rec)
        assert cloud.n_points == 2


class TestLasFormat6:
    """LAS 1.4 format 6 — extended return bits; class offset at byte 16."""

    def _make_fmt6_record(
        self,
        xi: int, yi: int, zi: int,
        intensity: int = 0,
        classification: int = 1,
    ) -> bytes:
        """Build a 30-byte Point Data Record Format 6."""
        rec = bytearray(30)
        struct.pack_into("<i", rec, 0, xi)
        struct.pack_into("<i", rec, 4, yi)
        struct.pack_into("<i", rec, 8, zi)
        struct.pack_into("<H", rec, 12, intensity)
        rec[14] = 0x01   # return number bits
        rec[15] = 0x00   # flags
        rec[16] = classification
        # remaining fields zero
        return bytes(rec)

    def _make_las14_header(
        self,
        point_count: int,
        point_format: int = 6,
        record_len: int = 30,
    ) -> bytes:
        """Build a 375-byte LAS 1.4 header with 64-bit point count."""
        hdr = bytearray(375)
        hdr[0:4] = b"LASF"
        hdr[24] = 1  # major
        hdr[25] = 4  # minor
        struct.pack_into("<H", hdr, 94, 375)
        struct.pack_into("<I", hdr, 96, 375)   # offset to data
        struct.pack_into("<I", hdr, 100, 0)    # VLR count
        hdr[104] = point_format
        struct.pack_into("<H", hdr, 105, record_len)
        struct.pack_into("<I", hdr, 107, 0)    # legacy count = 0
        # scale 0.001 × 3
        for off in (131, 139, 147):
            struct.pack_into("<d", hdr, off, 0.001)
        # offset 0 × 3
        for off in (155, 163, 171):
            struct.pack_into("<d", hdr, off, 0.0)
        # 64-bit point count at offset 247
        struct.pack_into("<Q", hdr, 247, point_count)
        return bytes(hdr)

    def test_las14_format6_decode(self):
        hdr = self._make_las14_header(2)
        rec0 = self._make_fmt6_record(1000, 2000, 3000, intensity=100, classification=6)
        rec1 = self._make_fmt6_record(4000, 5000, 6000, intensity=200, classification=3)
        cloud = read_las_bytes(hdr + rec0 + rec1)
        assert cloud.n_points == 2
        assert abs(cloud.xyz[0, 0] - 1.0) < 1e-9
        assert abs(cloud.xyz[1, 2] - 6.0) < 1e-9
        assert cloud.intensity[0] == 100
        assert cloud.intensity[1] == 200
        assert cloud.classification[0] == 6
        assert cloud.classification[1] == 3


class TestPointCloudDataclass:
    def test_dataclass_fields_exist(self):
        pc = PointCloud(
            xyz=np.zeros((0, 3)),
            intensity=None,
            classification=None,
            bbox=((0., 0., 0.), (0., 0., 0.)),
            n_points=0,
            source_format="las",
        )
        assert pc.source_format == "las"
        assert pc.n_points == 0
        assert pc.xyz.shape == (0, 3)
        assert pc.intensity is None
        assert pc.classification is None

    def test_intensity_dtype(self):
        hdr = _make_las12_header(1, 0, 20)
        rec = _make_fmt0_record(0, 0, 0, intensity=32768)
        cloud = read_las_bytes(hdr + rec)
        assert cloud.intensity.dtype == np.uint16

    def test_classification_dtype(self):
        hdr = _make_las12_header(1, 0, 20)
        rec = _make_fmt0_record(0, 0, 0, classification=7)
        cloud = read_las_bytes(hdr + rec)
        assert cloud.classification.dtype == np.uint8
