"""Deterministic CBOR: roundtrip + strict-decode rejections (§18.1.1)."""

import pytest

from kerf_pub import cbor
from kerf_pub.cbor import CBORError


def test_roundtrip_fixed_schema():
    obj = {1: 0, 2: 23, 3: 24, 4: 255, 5: 256, 6: 65536, 7: 2**40,
           8: b"\x00\xff", 9: "héllo", 10: [1, 2, b"x"], 11: True, 12: False}
    assert cbor.decode(cbor.encode(obj)) == obj


def test_map_keys_sorted_by_encoded_bytes():
    # Insertion order must not matter; output is canonical.
    a = cbor.encode({3: "c", 1: "a", 2: "b"})
    b = cbor.encode({1: "a", 2: "b", 3: "c"})
    assert a == b
    # keys 0x01,0x02,0x03 appear in ascending order right after the map head.
    assert a[0] == 0xA3  # map of 3 pairs


def test_text_keyed_map_sorted():
    # meta map uses text keys — sorted by encoded bytes ascending.
    enc = cbor.encode({"zzz": 1, "a": 2, "artifact": 3})
    assert cbor.decode(enc) == {"zzz": 1, "a": 2, "artifact": 3}


def test_reject_non_minimal_int():
    # 0x18 0x05 encodes 5 in two bytes — not the shortest form.
    with pytest.raises(CBORError):
        cbor.decode(b"\x18\x05")


def test_reject_indefinite_length():
    with pytest.raises(CBORError):
        cbor.decode(b"\x5f\xff")  # indefinite byte string


def test_reject_unsorted_map_keys():
    # map(2) with keys 2 then 1 — out of order.
    with pytest.raises(CBORError):
        cbor.decode(b"\xa2\x02\x00\x01\x00")


def test_reject_duplicate_map_keys():
    with pytest.raises(CBORError):
        cbor.decode(b"\xa2\x01\x00\x01\x00")


def test_reject_null_on_wire():
    with pytest.raises(CBORError):
        cbor.decode(b"\xf6")


def test_reject_trailing_bytes():
    with pytest.raises(CBORError):
        cbor.decode(b"\x00\x00")


def test_bool_not_confused_with_int():
    assert cbor.encode(True) == b"\xf5"
    assert cbor.encode(1) == b"\x01"
