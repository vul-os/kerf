"""CAD artifact profile: embed/extract, canonical-source rule, units (§23)."""

import pytest

from kerf_pub import (
    ArtifactMetadata, ArtifactFormat, Units, AssemblyStructure, AssemblyChild,
    PubManifest, ProfileError, embed_artifact, extract_artifact,
)
from kerf_pub.objects import (
    KIND_PART, KIND_ASSEMBLY, FMT_NATIVE, FMT_STEP, FMT_GLTF,
    FMT_ASSEMBLY_STRUCTURE, ROLE_CANONICAL, ROLE_DERIVED, ROLE_STRUCTURE,
    REF_PIN, REF_TRACK,
)


def _root(b: bytes) -> bytes:
    return PubManifest.build(b).id


def _valid_part() -> ArtifactMetadata:
    native = _root(b"native-source")
    step = _root(b"step-export")
    return ArtifactMetadata(
        name="Bracket",
        description="A mounting bracket",
        artifact_kind=KIND_PART,
        formats=[
            ArtifactFormat(FMT_NATIVE, native, ROLE_CANONICAL),
            ArtifactFormat(FMT_STEP, step, ROLE_DERIVED, derived_from_format=native),
            ArtifactFormat(FMT_GLTF, _root(b"mesh"), ROLE_DERIVED,
                           derived_from_format=native),
        ],
        units=Units(length_unit="mm"),
        license="CERN-OHL-S-2.0",
    )


def test_embed_extract_roundtrip():
    am = _valid_part()
    am.validate()
    meta = embed_artifact({}, am)
    assert isinstance(meta["artifact"], (bytes, bytearray))
    back = extract_artifact(meta)
    assert back.name == "Bracket"
    assert back.license == "CERN-OHL-S-2.0"
    assert back.units.length_unit == "mm"
    assert len(back.formats) == 3
    back.validate()


def test_units_length_required():
    with pytest.raises(ProfileError) as ei:
        Units.from_map({2: "deg"})  # no length_unit
    assert ei.value.rule == "CAD-6"


def test_license_required():
    am = _valid_part()
    am.license = ""
    with pytest.raises(ProfileError) as ei:
        am.validate()
    assert ei.value.rule == "CAD-1"


def test_mesh_never_canonical():
    am = _valid_part()
    am.formats = [ArtifactFormat(FMT_GLTF, _root(b"m"), ROLE_CANONICAL)]
    with pytest.raises(ProfileError) as ei:
        am.validate()
    assert ei.value.rule == "CAD-4"


def test_derived_requires_derived_from_format():
    am = _valid_part()
    am.formats[1].derived_from_format = None
    with pytest.raises(ProfileError) as ei:
        am.validate()
    assert ei.value.rule == "CAD-5"


def test_exactly_one_canonical_source():
    am = _valid_part()
    am.formats.append(ArtifactFormat(FMT_NATIVE, _root(b"n2"), ROLE_CANONICAL))
    with pytest.raises(ProfileError) as ei:
        am.validate()
    assert ei.value.rule == "CAD-3"


def test_step_canonical_only_without_native():
    # STEP as canonical is fine when it is the only source...
    step = _root(b"only-step")
    ok = ArtifactMetadata(
        name="I", description="", artifact_kind=KIND_PART,
        formats=[ArtifactFormat(FMT_STEP, step, ROLE_CANONICAL)],
        units=Units(length_unit="mm"), license="MIT",
    )
    ok.validate()
    # ...but not when a native source is also published.
    ok.formats.append(ArtifactFormat(FMT_NATIVE, _root(b"n"), ROLE_DERIVED,
                                     derived_from_format=step))
    with pytest.raises(ProfileError) as ei:
        ok.validate()
    assert ei.value.rule == "CAD-3"


def test_deprecated_requires_reason():
    am = _valid_part()
    am.deprecated = True
    with pytest.raises(ProfileError) as ei:
        am.validate()
    assert ei.value.rule == "CAD-7"
    am.deprecation_reason = "superseded by v2"
    am.validate()


def test_assembly_requires_structure_entry():
    am = ArtifactMetadata(
        name="Gearbox", description="", artifact_kind=KIND_ASSEMBLY,
        formats=[ArtifactFormat(FMT_NATIVE, _root(b"asm"), ROLE_CANONICAL)],
        units=Units(length_unit="mm"), license="MIT",
    )
    with pytest.raises(ProfileError) as ei:
        am.validate()
    assert ei.value.rule == "CAD-3"


def test_assembly_valid_with_structure():
    struct_root = _root(b"structure-blob")
    am = ArtifactMetadata(
        name="Gearbox", description="", artifact_kind=KIND_ASSEMBLY,
        formats=[
            ArtifactFormat(FMT_ASSEMBLY_STRUCTURE, struct_root, ROLE_STRUCTURE),
            ArtifactFormat(FMT_NATIVE, _root(b"asm"), ROLE_CANONICAL),
        ],
        units=Units(length_unit="mm"), license="MIT",
    )
    am.validate()


def test_assembly_structure_roundtrip():
    struct = AssemblyStructure(children=[
        AssemblyChild(REF_PIN, _root(b"bolt"), quantity=4),
        AssemblyChild(REF_TRACK, _root(b"sub-assembly"), quantity=1,
                      transform=b"\x00" * 12),
    ])
    back = AssemblyStructure.from_cbor(struct.to_cbor())
    assert len(back.children) == 2
    assert back.children[0].quantity == 4
    assert back.children[1].ref_kind == REF_TRACK
    assert back.children[1].transform == b"\x00" * 12


def test_assembly_child_quantity_min():
    from kerf_pub import cbor
    # quantity 0 is malformed (§23.6.2 — omit the child instead of a zero count).
    bad = cbor.encode({1: [{1: REF_PIN, 2: _root(b"x"), 3: 0}]})
    with pytest.raises(ProfileError):
        AssemblyStructure.from_cbor(bad)


def test_assembly_empty_children_rejected():
    from kerf_pub import cbor
    with pytest.raises(ProfileError):
        AssemblyStructure.from_cbor(cbor.encode({1: []}))
