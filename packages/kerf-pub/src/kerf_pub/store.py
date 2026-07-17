"""Local pin store + availability state for DMTAP-PUB objects.

A holder serves ONLY pinned/local objects (§22.5, §22.6.2). This module is that
local store, in two interchangeable backends:

* :class:`InMemoryPubStore` — dict-backed, zero-dependency, the default and the
  one the tests and the zero-socket local node use.
* :class:`PostgresPubStore` — asyncpg-backed, over the tables created by
  kerf-core migration ``0015_pub_objects.sql`` (clean-baseline CREATE TABLE, no
  ALTER shims), for a persistent hosted gateway.

Both persist the four content-addressed object classes (chunk / manifest /
announce / feed-entry) as raw bytes keyed by content address, the mutable
signed feed head per author, the per-author accepted-``seq`` anti-rollback
watermark (§22.4.2), and a per-artifact availability record (§22.6).

The interface is async so the two backends are drop-in interchangeable; the
in-memory one simply does no awaiting of I/O.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# Derived availability status vocabulary (§22.6 serving posture).
STATUS_ON_NODE = "on-node"        # we pin it locally
STATUS_AVAILABLE = "available"    # a holder verified it recently
STATUS_STALE = "stale"           # holders known but not verified recently
STATUS_UNREACHABLE = "unreachable"  # no local pin, no known holder

DEFAULT_STALE_AFTER_MS = 24 * 60 * 60 * 1000  # 24h


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Availability:
    """Per-artifact availability (§22.6): local pin + known holders."""

    local_pinned: bool = False
    known_holders: dict[str, int] = field(default_factory=dict)  # url -> last_verified_ms

    def status(self, now_ms: int | None = None,
               stale_after_ms: int = DEFAULT_STALE_AFTER_MS) -> str:
        if self.local_pinned:
            return STATUS_ON_NODE
        if not self.known_holders:
            return STATUS_UNREACHABLE
        now = now_ms if now_ms is not None else _now_ms()
        if any(now - ts <= stale_after_ms for ts in self.known_holders.values()):
            return STATUS_AVAILABLE
        return STATUS_STALE


# ── abstract interface ────────────────────────────────────────────────────────

class PubStore:
    """Abstract local pin store. All methods are async for backend parity."""

    # content-addressed objects
    async def put_chunk(self, h: bytes, data: bytes) -> None: ...
    async def get_chunk(self, h: bytes) -> bytes | None: ...
    async def put_manifest(self, mid: bytes, raw: bytes) -> None: ...
    async def get_manifest(self, mid: bytes) -> bytes | None: ...
    async def put_announce(self, aid: bytes, raw: bytes) -> None: ...
    async def get_announce(self, aid: bytes) -> bytes | None: ...

    # feed (per author `pub`)
    async def put_feed_entry(self, pub: bytes, seq: int, entry_id: bytes,
                             raw: bytes) -> None: ...
    async def get_feed_entry_by_seq(self, pub: bytes, seq: int) -> bytes | None: ...
    async def get_feed_range(self, pub: bytes, from_seq: int,
                             to_seq: int) -> list[bytes]: ...
    async def put_feed_head(self, pub: bytes, raw: bytes) -> None: ...
    async def get_feed_head(self, pub: bytes) -> bytes | None: ...

    # anti-rollback watermark (§22.4.2)
    async def get_accepted_seq(self, pub: bytes) -> int | None: ...
    async def set_accepted_seq(self, pub: bytes, seq: int) -> None: ...

    # availability (§22.6)
    async def get_availability(self, aid: bytes) -> Availability: ...
    async def set_pinned(self, aid: bytes, pinned: bool) -> None: ...
    async def note_holder(self, aid: bytes, url: str,
                          verified_ms: int | None = None) -> None: ...

    # followed feeds (node-local convenience layer, kerf_pub.router_local)
    async def put_follow(self, pub: bytes, label: str, gateway_url: str,
                         added_ts: int) -> None: ...
    async def list_follows(self) -> list[dict]: ...
    async def delete_follow(self, pub: bytes) -> None: ...


# ── in-memory backend ─────────────────────────────────────────────────────────

class InMemoryPubStore(PubStore):
    def __init__(self) -> None:
        self._chunks: dict[bytes, bytes] = {}
        self._manifests: dict[bytes, bytes] = {}
        self._announces: dict[bytes, bytes] = {}
        # feed entries: pub -> {seq: raw}
        self._feed_entries: dict[bytes, dict[int, bytes]] = {}
        self._feed_heads: dict[bytes, bytes] = {}
        self._accepted_seq: dict[bytes, int] = {}
        self._avail: dict[bytes, Availability] = {}
        self._follows: dict[bytes, dict] = {}

    async def put_chunk(self, h: bytes, data: bytes) -> None:
        self._chunks[bytes(h)] = bytes(data)

    async def get_chunk(self, h: bytes) -> bytes | None:
        return self._chunks.get(bytes(h))

    async def put_manifest(self, mid: bytes, raw: bytes) -> None:
        self._manifests[bytes(mid)] = bytes(raw)

    async def get_manifest(self, mid: bytes) -> bytes | None:
        return self._manifests.get(bytes(mid))

    async def put_announce(self, aid: bytes, raw: bytes) -> None:
        self._announces[bytes(aid)] = bytes(raw)

    async def get_announce(self, aid: bytes) -> bytes | None:
        return self._announces.get(bytes(aid))

    async def put_feed_entry(self, pub: bytes, seq: int, entry_id: bytes,
                             raw: bytes) -> None:
        self._feed_entries.setdefault(bytes(pub), {})[seq] = bytes(raw)

    async def get_feed_entry_by_seq(self, pub: bytes, seq: int) -> bytes | None:
        return self._feed_entries.get(bytes(pub), {}).get(seq)

    async def get_feed_range(self, pub: bytes, from_seq: int,
                             to_seq: int) -> list[bytes]:
        entries = self._feed_entries.get(bytes(pub), {})
        return [entries[s] for s in range(from_seq, to_seq + 1) if s in entries]

    async def put_feed_head(self, pub: bytes, raw: bytes) -> None:
        self._feed_heads[bytes(pub)] = bytes(raw)

    async def get_feed_head(self, pub: bytes) -> bytes | None:
        return self._feed_heads.get(bytes(pub))

    async def get_accepted_seq(self, pub: bytes) -> int | None:
        return self._accepted_seq.get(bytes(pub))

    async def set_accepted_seq(self, pub: bytes, seq: int) -> None:
        self._accepted_seq[bytes(pub)] = seq

    async def get_availability(self, aid: bytes) -> Availability:
        return self._avail.get(bytes(aid), Availability())

    async def set_pinned(self, aid: bytes, pinned: bool) -> None:
        rec = self._avail.setdefault(bytes(aid), Availability())
        rec.local_pinned = pinned

    async def note_holder(self, aid: bytes, url: str,
                          verified_ms: int | None = None) -> None:
        rec = self._avail.setdefault(bytes(aid), Availability())
        rec.known_holders[url] = verified_ms if verified_ms is not None else _now_ms()

    async def put_follow(self, pub: bytes, label: str, gateway_url: str,
                         added_ts: int) -> None:
        self._follows[bytes(pub)] = {
            "pub": bytes(pub), "label": label, "gateway_url": gateway_url,
            "added_ts": added_ts,
        }

    async def list_follows(self) -> list[dict]:
        return sorted(self._follows.values(), key=lambda f: f["added_ts"])

    async def delete_follow(self, pub: bytes) -> None:
        self._follows.pop(bytes(pub), None)


# ── postgres backend ──────────────────────────────────────────────────────────

class PostgresPubStore(PubStore):
    """asyncpg-backed store over migration 0015_pub_objects.sql tables.

    Takes an existing asyncpg pool (``ctx.pool``); does no schema DDL of its own
    — tables are owned by the kerf-core migration runner, per repo convention.
    """

    def __init__(self, pool: Any):
        self._pool = pool

    async def put_chunk(self, h: bytes, data: bytes) -> None:
        await self._pool.execute(
            "INSERT INTO pub_chunks (h, data) VALUES ($1, $2) "
            "ON CONFLICT (h) DO NOTHING",
            bytes(h), bytes(data),
        )

    async def get_chunk(self, h: bytes) -> bytes | None:
        row = await self._pool.fetchrow(
            "SELECT data FROM pub_chunks WHERE h = $1", bytes(h))
        return bytes(row["data"]) if row else None

    async def put_manifest(self, mid: bytes, raw: bytes) -> None:
        await self._pool.execute(
            "INSERT INTO pub_manifests (id, body) VALUES ($1, $2) "
            "ON CONFLICT (id) DO NOTHING",
            bytes(mid), bytes(raw),
        )

    async def get_manifest(self, mid: bytes) -> bytes | None:
        row = await self._pool.fetchrow(
            "SELECT body FROM pub_manifests WHERE id = $1", bytes(mid))
        return bytes(row["body"]) if row else None

    async def put_announce(self, aid: bytes, raw: bytes) -> None:
        await self._pool.execute(
            "INSERT INTO pub_announces (id, body) VALUES ($1, $2) "
            "ON CONFLICT (id) DO NOTHING",
            bytes(aid), bytes(raw),
        )

    async def get_announce(self, aid: bytes) -> bytes | None:
        row = await self._pool.fetchrow(
            "SELECT body FROM pub_announces WHERE id = $1", bytes(aid))
        return bytes(row["body"]) if row else None

    async def put_feed_entry(self, pub: bytes, seq: int, entry_id: bytes,
                             raw: bytes) -> None:
        await self._pool.execute(
            "INSERT INTO pub_feed_entries (pub, seq, entry_id, body) "
            "VALUES ($1, $2, $3, $4) ON CONFLICT (pub, seq) DO NOTHING",
            bytes(pub), seq, bytes(entry_id), bytes(raw),
        )

    async def get_feed_entry_by_seq(self, pub: bytes, seq: int) -> bytes | None:
        row = await self._pool.fetchrow(
            "SELECT body FROM pub_feed_entries WHERE pub = $1 AND seq = $2",
            bytes(pub), seq,
        )
        return bytes(row["body"]) if row else None

    async def get_feed_range(self, pub: bytes, from_seq: int,
                             to_seq: int) -> list[bytes]:
        rows = await self._pool.fetch(
            "SELECT body FROM pub_feed_entries "
            "WHERE pub = $1 AND seq BETWEEN $2 AND $3 ORDER BY seq",
            bytes(pub), from_seq, to_seq,
        )
        return [bytes(r["body"]) for r in rows]

    async def put_feed_head(self, pub: bytes, raw: bytes) -> None:
        await self._pool.execute(
            "INSERT INTO pub_feed_heads (pub, body) VALUES ($1, $2) "
            "ON CONFLICT (pub) DO UPDATE SET body = EXCLUDED.body",
            bytes(pub), bytes(raw),
        )

    async def get_feed_head(self, pub: bytes) -> bytes | None:
        row = await self._pool.fetchrow(
            "SELECT body FROM pub_feed_heads WHERE pub = $1", bytes(pub))
        return bytes(row["body"]) if row else None

    async def get_accepted_seq(self, pub: bytes) -> int | None:
        row = await self._pool.fetchrow(
            "SELECT accepted_seq FROM pub_feed_heads WHERE pub = $1", bytes(pub))
        return int(row["accepted_seq"]) if row and row["accepted_seq"] is not None else None

    async def set_accepted_seq(self, pub: bytes, seq: int) -> None:
        await self._pool.execute(
            "INSERT INTO pub_feed_heads (pub, accepted_seq) VALUES ($1, $2) "
            "ON CONFLICT (pub) DO UPDATE SET accepted_seq = EXCLUDED.accepted_seq",
            bytes(pub), seq,
        )

    async def get_availability(self, aid: bytes) -> Availability:
        row = await self._pool.fetchrow(
            "SELECT local_pinned, known_holders FROM pub_availability WHERE aid = $1",
            bytes(aid),
        )
        if not row:
            return Availability()
        import json
        holders = row["known_holders"]
        if isinstance(holders, str):
            holders = json.loads(holders)
        return Availability(
            local_pinned=bool(row["local_pinned"]),
            known_holders={k: int(v) for k, v in (holders or {}).items()},
        )

    async def set_pinned(self, aid: bytes, pinned: bool) -> None:
        await self._pool.execute(
            "INSERT INTO pub_availability (aid, local_pinned) VALUES ($1, $2) "
            "ON CONFLICT (aid) DO UPDATE SET local_pinned = EXCLUDED.local_pinned",
            bytes(aid), pinned,
        )

    async def note_holder(self, aid: bytes, url: str,
                          verified_ms: int | None = None) -> None:
        import json
        rec = await self.get_availability(aid)
        rec.known_holders[url] = verified_ms if verified_ms is not None else _now_ms()
        await self._pool.execute(
            "INSERT INTO pub_availability (aid, known_holders) VALUES ($1, $2) "
            "ON CONFLICT (aid) DO UPDATE SET known_holders = EXCLUDED.known_holders",
            bytes(aid), json.dumps(rec.known_holders),
        )

    async def put_follow(self, pub: bytes, label: str, gateway_url: str,
                         added_ts: int) -> None:
        await self._pool.execute(
            "INSERT INTO pub_follows (pub, label, gateway_url, added_ts) "
            "VALUES ($1, $2, $3, $4) ON CONFLICT (pub) DO UPDATE SET "
            "label = EXCLUDED.label, gateway_url = EXCLUDED.gateway_url",
            bytes(pub), label, gateway_url, added_ts,
        )

    async def list_follows(self) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT pub, label, gateway_url, added_ts FROM pub_follows ORDER BY added_ts")
        return [
            {
                "pub": bytes(r["pub"]), "label": r["label"],
                "gateway_url": r["gateway_url"], "added_ts": int(r["added_ts"]),
            }
            for r in rows
        ]

    async def delete_follow(self, pub: bytes) -> None:
        await self._pool.execute("DELETE FROM pub_follows WHERE pub = $1", bytes(pub))
