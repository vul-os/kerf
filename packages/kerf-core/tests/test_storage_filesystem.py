"""Tests for kerf_core.storage.filesystem — the human-readable disk backend.

The point of this backend is the layout: the docs promise a directory you can
cd into, grep, and git. So these cover the round-trip (bytes survive the
rename), the layout itself (an uploaded part keeps its name; digests stay out
of the way), the refusal to write outside the root, and that a missing file —
ordinary in a tree people edit by hand — fails the way LocalStorage does.

Pure filesystem I/O: no DB, no network.
"""
from __future__ import annotations

import io
import os

import pytest

from kerf_core.storage.factory import create_storage
from kerf_core.storage.filesystem import FilesystemStorage
from kerf_core.storage.local import LocalStorage

PROJECT_ID = "5c1a2f7e-9f1c-4a2b-8d3e-0b7e2a41c9d0"
ASSET_UUID = "3f2a91c4-0b7e-4d21-9a55-6c8e11ab77df"
DIGEST = "4d7a214614ab2935c943f9e0ff69d22eadbb8f32eb2bf690167fe7ee3520c9b2"


@pytest.fixture()
def store(tmp_path) -> FilesystemStorage:
    return FilesystemStorage(root=str(tmp_path / "projects"))


def body(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)


def relative_files(store: FilesystemStorage) -> set[str]:
    return {
        str(p.relative_to(store.root))
        for p in store.root.rglob("*")
        if p.is_file()
    }


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


async def test_put_get_round_trip(store):
    """Bytes must survive the key -> path rename in both directions."""
    key = f"projects/{PROJECT_ID}/assets/{ASSET_UUID}-bracket.step"
    data = b"ISO-10303-21;\nHEADER;\n"

    result = await store.put(key, body(data), "", len(data))
    assert result.size == len(data)
    assert result.content_type == "model/step"

    stream, content_type = await store.get(key)
    assert stream.read() == data
    assert content_type == "model/step"


async def test_head_and_delete(store):
    """head() reports the object the readable path holds; delete() removes it."""
    key = f"projects/{PROJECT_ID}/assets/{ASSET_UUID}-plate.jscad"
    await store.put(key, body(b"cube();"), "", 7)

    head = await store.head(key)
    assert head.exists and head.size == 7

    await store.delete(key)
    assert (await store.head(key)).exists is False


# ---------------------------------------------------------------------------
# Layout — the reason this backend exists
# ---------------------------------------------------------------------------


async def test_uploaded_file_keeps_its_name(store):
    """The UUID moves behind the filename, so the directory reads as a directory."""
    key = f"projects/{PROJECT_ID}/assets/{ASSET_UUID}-bracket.step"
    await store.put(key, body(b"x"), "", 1)

    assert relative_files(store) == {
        f"projects/{PROJECT_ID}/assets/bracket-3f2a91c40b7e.step"
    }


async def test_two_uploads_of_the_same_name_do_not_collide(store):
    """Same filename, different upload: both must survive, both must read back."""
    other_uuid = "8b44c1de-2f90-4c77-90aa-51e0c3d9b612"
    a = f"projects/{PROJECT_ID}/assets/{ASSET_UUID}-bracket.step"
    b = f"projects/{PROJECT_ID}/assets/{other_uuid}-bracket.step"

    await store.put(a, body(b"first"), "", 5)
    await store.put(b, body(b"second"), "", 6)

    assert len(relative_files(store)) == 2
    assert (await store.get(a))[0].read() == b"first"
    assert (await store.get(b))[0].read() == b"second"


async def test_project_scoped_artifacts_fold_into_the_project_directory(store):
    """A project must be one tree — otherwise `git init` there misses its renders."""
    await store.put(f"renders/{PROJECT_ID}/front.png", body(b"png"), "", 3)
    await store.put(f"exports/{PROJECT_ID}/{ASSET_UUID}/out.stl", body(b"stl"), "", 3)

    assert relative_files(store) == {
        f"projects/{PROJECT_ID}/renders/front.png",
        f"projects/{PROJECT_ID}/exports/{ASSET_UUID}/out.stl",
    }


async def test_content_addressed_blobs_stay_out_of_the_readable_tree(store):
    """Hex-named objects have no name to show; they must not clutter the tree."""
    key = f"blobs/{DIGEST[:2]}/{DIGEST}"
    await store.put(key, body(b"blob"), "application/octet-stream", 4)

    assert relative_files(store) == {f".kerf/objects/blobs/{DIGEST[:2]}/{DIGEST}"}
    assert (await store.get(key))[0].read() == b"blob"


async def test_user_scoped_keys_are_not_mistaken_for_projects(store):
    """A user id is a UUID too — folding must not turn an avatar into a project."""
    uid = "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed"
    await store.put(f"users/{uid}/avatar.jpg", body(b"jpg"), "image/jpeg", 3)

    assert relative_files(store) == {f"users/{uid}/avatar.jpg"}


async def test_chunks_are_hidden_while_the_upload_is_in_flight(store):
    """Half-uploaded chunks are noise to a human; only the joined file is theirs."""
    upload_key = "up-123"
    await store.put_chunk(upload_key, 0, body(b"AAA"))
    await store.put_chunk(upload_key, 1, body(b"BBB"))
    assert await store.list_chunks(upload_key) == [0, 1]
    assert all(f.startswith(".kerf/uploads/") for f in relative_files(store))

    dst = f"projects/{PROJECT_ID}/assets/{ASSET_UUID}-joined.bin"
    total = await store.concat_chunks_to(upload_key, dst)
    assert total == 6
    await store.delete_upload(upload_key)

    assert relative_files(store) == {
        f"projects/{PROJECT_ID}/assets/joined-3f2a91c40b7e.bin"
    }


async def test_public_url_still_addresses_the_key(store):
    """The key stays the API-level identity; the layout is an internal detail."""
    key = f"projects/{PROJECT_ID}/assets/{ASSET_UUID}-bracket.step"
    assert store.public_url(key) == "/api/blobs/" + key


# ---------------------------------------------------------------------------
# Traversal — a key must never escape filesystem_root
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "../escaped.step",
        "projects/../../escaped.step",
        "/etc/passwd/../../escaped.step",
        "projects/..",
        "..\\escaped.step",
        "",
        "/",
    ],
)
async def test_traversal_keys_are_refused(store, key):
    """Nothing a caller can put in a key may write outside filesystem_root."""
    with pytest.raises(ValueError):
        await store.put(key, body(b"pwn"), "", 3)
    assert relative_files(store) == set()


async def test_absolute_key_is_written_inside_the_root(store):
    """A leading slash names a key, not a path: it stays under the root."""
    await store.put("/projects/x/note.txt", body(b"hi"), "", 2)
    assert relative_files(store) == {"projects/x/note.txt"}


async def test_symlinked_directory_cannot_be_used_to_escape(store, tmp_path):
    """The tree is user-editable, so a directory may have become a symlink."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.root / "projects").mkdir(parents=True, exist_ok=True)
    os.symlink(outside, store.root / "projects" / "linked")

    with pytest.raises(ValueError):
        await store.put("projects/linked/leak.step", body(b"leak"), "", 4)
    assert list(outside.iterdir()) == []


async def test_private_directory_is_reserved(store):
    """Callers must not be able to write into the hidden object store by key."""
    with pytest.raises(ValueError):
        await store.put(".kerf/objects/forged", body(b"x"), "", 1)


async def test_upload_key_cannot_traverse(store):
    """Chunk directories are named by the upload key — it must stay one segment."""
    for bad in ("../up", "a/b", ".."):
        with pytest.raises(ValueError):
            await store.put_chunk(bad, 0, body(b"x"))


# ---------------------------------------------------------------------------
# Missing / hand-edited files are ordinary, not exceptional
# ---------------------------------------------------------------------------


async def test_get_missing_key_raises_filenotfound_like_localstorage(store, tmp_path):
    """Same failure as LocalStorage — callers already handle exactly this."""
    key = f"projects/{PROJECT_ID}/assets/{ASSET_UUID}-gone.step"
    local = LocalStorage(root=str(tmp_path / "local"))

    with pytest.raises(FileNotFoundError):
        await store.get(key)
    with pytest.raises(FileNotFoundError):
        await local.get(key)


async def test_head_of_missing_key_reports_absence(store):
    """head() must answer, not raise, for a file a user deleted by hand."""
    head = await store.head(f"projects/{PROJECT_ID}/assets/{ASSET_UUID}-gone.step")
    assert head.exists is False and head.size == 0


async def test_delete_missing_key_is_a_no_op(store):
    """Deleting what someone already removed with `rm` is not an error."""
    await store.delete(f"projects/{PROJECT_ID}/assets/{ASSET_UUID}-gone.step")


async def test_hand_edited_contents_are_returned_verbatim(store):
    """Whatever is on disk is the answer; the backend does not police it."""
    key = f"projects/{PROJECT_ID}/assets/{ASSET_UUID}-bracket.step"
    await store.put(key, body(b"original"), "", 8)

    path = store.root / "projects" / PROJECT_ID / "assets" / "bracket-3f2a91c40b7e.step"
    path.write_bytes(b"edited by hand")

    assert (await store.get(key))[0].read() == b"edited by hand"
    assert (await store.head(key)).size == 14


async def test_delete_prefix_removes_a_project_and_its_objects(store):
    """Purging a project must reach both the readable tree and the hidden one."""
    await store.put(f"projects/{PROJECT_ID}/assets/{ASSET_UUID}-a.step", body(b"a"), "", 1)
    await store.put(f"renders/{PROJECT_ID}/front.png", body(b"p"), "", 1)
    keep = "projects/8b44c1de-2f90-4c77-90aa-51e0c3d9b612/assets/keep.step"
    await store.put(keep, body(b"k"), "", 1)

    assert await store.delete_prefix(f"projects/{PROJECT_ID}") == 2
    assert relative_files(store) == {keep}


async def test_delete_prefix_reaches_the_object_store(store):
    """Content-addressed keys live under .kerf; a prefix delete must find them."""
    await store.put(f"blobs/{DIGEST[:2]}/{DIGEST}", body(b"blob"), "", 4)
    assert await store.delete_prefix(f"blobs/{DIGEST[:2]}") == 1
    assert relative_files(store) == set()


# ---------------------------------------------------------------------------
# Factory wiring — the docs tell people to set backend = "filesystem"
# ---------------------------------------------------------------------------


def test_factory_returns_filesystem_storage(tmp_path):
    """backend = "filesystem" must stop silently resolving to LocalStorage."""
    storage = create_storage(
        backend="filesystem", filesystem_root=str(tmp_path / "kerf-projects")
    )
    assert isinstance(storage, FilesystemStorage)
    assert storage.root == (tmp_path / "kerf-projects").resolve()


def test_factory_expands_tilde_in_filesystem_root(monkeypatch, tmp_path):
    """The documented default is "~/kerf-projects" — a literal "~" dir is a bug."""
    monkeypatch.setenv("HOME", str(tmp_path))
    storage = create_storage(backend="filesystem", filesystem_root="~/kerf-projects")

    assert storage.root == (tmp_path / "kerf-projects").resolve()
    assert not (tmp_path / "~").exists()


def test_factory_local_backend_is_unchanged(tmp_path):
    """The additive change must not move the "local" backend's bytes."""
    storage = create_storage(backend="local", local_storage_path=str(tmp_path / "objs"))
    assert type(storage) is LocalStorage


def test_factory_rejects_unknown_backend():
    with pytest.raises(ValueError):
        create_storage(backend="nfs")


# ---------------------------------------------------------------------------
# The shapes production actually passes
# ---------------------------------------------------------------------------


async def test_delete_prefix_reaches_the_two_segment_photo_prefix(store):
    """A prefix is one segment shorter than the keys beneath it.

    kerf_api.routes deletes a project's photos with
    ``delete_prefix(f"photos/{pid}/")`` — two segments — while the keys it must
    reach are ``photos/<pid>/<fid>/<uuid>.jpg``. The fold originally required
    three segments, so the keys folded into ``projects/<pid>/photos/`` and the
    prefix did not: the delete looked in ``photos/<pid>``, found nothing, and
    every photo of every deleted project stayed on disk forever.

    The other delete_prefix tests only pass the already-folded ``projects/<pid>``
    form, which is why they missed it.
    """
    key = f"photos/{PROJECT_ID}/{ASSET_UUID}/9f8e7d6c-shot.jpg"
    await store.put(key, body(b"JPEG"), "", 4)
    assert relative_files(store)

    deleted = await store.delete_prefix(f"photos/{PROJECT_ID}/")

    assert deleted == 1
    assert relative_files(store) == set()


async def test_delete_prefix_works_without_the_trailing_slash(store):
    key = f"renders/{PROJECT_ID}/{ASSET_UUID}.png"
    await store.put(key, body(b"PNG"), "", 3)

    assert await store.delete_prefix(f"renders/{PROJECT_ID}") == 1
    assert relative_files(store) == set()


async def test_a_two_segment_key_that_is_not_a_project_is_not_folded(store):
    """The fold is guarded on the second segment being a UUID, so an ordinary
    ``renders/<filename>`` must not be mistaken for a project prefix."""
    await store.put("renders/monthly-report.png", body(b"PNG"), "", 3)

    assert "renders/monthly-report.png" in relative_files(store)
    assert await store.delete_prefix("renders/monthly-report.png") == 1


def test_wire_storage_passes_the_configured_filesystem_root(tmp_path):
    """`[storage].filesystem_root` was parsed, stored on Settings and unit
    tested — then dropped by app._wire_storage, which enumerates
    create_storage's kwargs by hand. Four docs told users to set it, and it did
    nothing; every node used the default root."""
    from kerf_core.app import _wire_storage

    class _Cfg:
        storage_backend = "filesystem"
        s3_bucket = s3_region = s3_access_key_id = s3_secret_access_key = ""
        s3_endpoint = s3_public_url_base = cdn_base_url = cdn_s3_bucket = ""
        cdn_s3_region = cdn_s3_access_key_id = cdn_s3_secret_access_key = ""
        cdn_s3_endpoint = ""
        local_storage_path = "./.kerf-storage"
        filesystem_root = str(tmp_path / "my-shop")

    storage = _wire_storage(_Cfg())

    assert isinstance(storage, FilesystemStorage)
    assert os.path.realpath(str(storage.root)) == os.path.realpath(_Cfg.filesystem_root)
