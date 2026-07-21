"""Wake — content-free, sender-blind push for the Workshop (substrate
capability ⑤; `dmtap/substrate/ROLES.md` §8, profile of DMTAP core §4.9).

**What this is.** kerf-pub's Workshop is pull-only today: a node re-crawls
every followed feed's head (`kerf_pub.router_local.workshop_feed`) to notice a
new revision. Wake is an OPTIONAL, self-hostable latency optimization on top
of that pull model — never a replacement for it (DMTAP's "push is a latency
optimization, not delivery", ROLES.md §8: "wake-and-fetch, never
deliver-in-push"). A follower registers a Web Push subscription for a feed it
follows; when that feed's author publishes, the node emits an **opaque,
content-free "sync now" token** to every registered subscription — no
announce id, no artifact name, no author identity, nothing beyond a fresh
random nonce. The follower's client still pulls (resolves) the feed over the
ordinary public-object HTTP endpoint (§22.5.1, the "PUB server" profile —
distinct from the §7 legacy-mail gateway role) to find out what actually
changed.

**Fail-safe off.** A node with no VAPID keypair configured never touches
this module beyond :func:`default_wake_config` returning ``None`` — same
zero-socket-by-default posture as :mod:`kerf_pub.ipfs`'s IPFS gateway config.
No VAPID keys means the subscribe endpoint (`kerf_pub.router.subscribe_feed`)
refuses new subscriptions and publish() skips the notify step entirely.

**Config** (env vars, per-node, no config file — same convention as
:mod:`kerf_pub.ipfs`):

    KERF_PUB_VAPID_PRIVATE_KEY   base64url, the raw 32-byte P-256 private
                                 scalar (RFC 8292 application-server key)
    KERF_PUB_VAPID_SUBJECT       a contact URI required by RFC 8292's `sub`
                                 claim, e.g. "mailto:ops@example.com" or
                                 "https://example.com/contact"

Generate a keypair once with :func:`generate_vapid_private_key_b64`.

**Crypto is RFC 8291 (Web Push message encryption) + RFC 8292 (VAPID)**,
built on the `cryptography` library primitives kerf-pub already depends on
— no extra dependency. :func:`seal_wake_token`'s HKDF/AES-GCM derivation is
verified byte-for-byte against the RFC 8291 Appendix A worked example in
``tests/test_wake.py``.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger(__name__)

ENV_VAPID_PRIVATE_KEY = "KERF_PUB_VAPID_PRIVATE_KEY"
ENV_VAPID_SUBJECT = "KERF_PUB_VAPID_SUBJECT"

# RFC 8292 recommends a VAPID JWT lifetime of at most 24h; kerf uses a
# conservative 12h so a long-idle node doesn't hand out a near-expiry token.
VAPID_JWT_TTL_S = 12 * 60 * 60

# RFC 8291 §4: an application server MUST encrypt with a single record; 4096
# is the record-size ceiling the RFC's own worked example uses.
_RECORD_SIZE = 4096

# ROLES.md §8.4 wake error codes (DMTAP core §4.9, already-registered — kerf
# reuses the names/codes for traceability, not because kerf-pub owns them).
ERR_PUSH_SUBSCRIPTION_SIG_INVALID = 0x0312
ERR_WAKEPING_CONTENT_PRESENT = 0x0313
ERR_WAKEPING_AUTH_FAILED = 0x0314
ERR_WAKEPING_RATE_LIMITED = 0x0315
ERR_WAKEPING_REPLAY = 0x0316


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


# ── VAPID application-server identity (RFC 8292) ──────────────────────────────


@dataclass(frozen=True)
class VapidConfig:
    """This node's own VAPID keypair (ROLES.md §8: "Node holds its own VAPID
    keypair"). Never the subscriber's — that's the per-subscription P-256 key
    + auth secret a browser's Push API generates, carried in `PushSubscription`."""

    private_key: ec.EllipticCurvePrivateKey
    public_key_raw: bytes  # 65-byte uncompressed P-256 point
    subject: str


def generate_vapid_private_key_b64() -> str:
    """One-time node setup helper: a fresh P-256 private key, base64url-encoded
    as the raw 32-byte scalar — the exact shape `KERF_PUB_VAPID_PRIVATE_KEY`
    expects. Not called at runtime; a node operator runs this once and pastes
    the result into their environment."""
    key = ec.generate_private_key(ec.SECP256R1())
    d = key.private_numbers().private_value
    return _b64url_encode(d.to_bytes(32, "big"))


def default_wake_config() -> VapidConfig | None:
    """The per-node VAPID config, or ``None`` if unconfigured (fail-safe off
    — a node with no wake config never sends or accepts a wake subscription,
    mirroring `kerf_pub.ipfs.default_ipfs_gateway_url`'s zero-socket default)."""
    raw = os.environ.get(ENV_VAPID_PRIVATE_KEY, "").strip()
    subject = os.environ.get(ENV_VAPID_SUBJECT, "").strip()
    if not raw or not subject:
        return None
    try:
        d = int.from_bytes(_b64url_decode(raw), "big")
        private_key = ec.derive_private_key(d, ec.SECP256R1())
    except Exception:
        logger.warning("kerf-pub wake: %s is set but not a valid P-256 scalar", ENV_VAPID_PRIVATE_KEY)
        return None
    public_key_raw = private_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    )
    return VapidConfig(private_key=private_key, public_key_raw=public_key_raw, subject=subject)


def vapid_public_key_b64(config: VapidConfig) -> str:
    """This node's own VAPID public key (RFC 8292 application server key),
    base64url-encoded — the one piece of state a prospective subscriber's
    browser needs before it can call `PushManager.subscribe({
    applicationServerKey})` (`kerf_pub.router`'s anonymous ``GET
    /.well-known/dmtap-pub/wake-key``, docs/distributed-workshop.md's Wake
    section). Same bytes embedded in :func:`vapid_headers`'s ``Crypto-Key``
    header — this just exposes them to a caller ahead of time."""
    return _b64url_encode(config.public_key_raw)


def _jwt_es256(header: dict, claims: dict, private_key: ec.EllipticCurvePrivateKey) -> str:
    def _seg(obj: dict) -> str:
        return _b64url_encode(json.dumps(obj, separators=(",", ":")).encode("utf-8"))

    signing_input = f"{_seg(header)}.{_seg(claims)}".encode("ascii")
    der_sig = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_sig)
    # JWS ES256 wants a fixed-width raw r||s (64 bytes), not DER (RFC 7518 §3.4).
    raw_sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{signing_input.decode('ascii')}.{_b64url_encode(raw_sig)}"


def vapid_headers(endpoint: str, config: VapidConfig, *, now_s: int | None = None) -> dict[str, str]:
    """RFC 8292 `Authorization` header for a push request to ``endpoint``."""
    from urllib.parse import urlsplit

    parts = urlsplit(endpoint)
    aud = f"{parts.scheme}://{parts.netloc}"
    now = now_s if now_s is not None else int(time.time())
    claims = {"aud": aud, "exp": now + VAPID_JWT_TTL_S, "sub": config.subject}
    jwt = _jwt_es256({"typ": "JWT", "alg": "ES256"}, claims, config.private_key)
    return {
        "Authorization": f"vapid t={jwt}, k={_b64url_encode(config.public_key_raw)}",
        "Crypto-Key": f"p256ecdsa={_b64url_encode(config.public_key_raw)}",
    }


# ── RFC 8291 Web Push message encryption ──────────────────────────────────────


def seal_wake_token(
    p256dh_b64: str,
    auth_secret_b64: str,
    token: bytes,
    *,
    _ephemeral_key: ec.EllipticCurvePrivateKey | None = None,
    _salt: bytes | None = None,
) -> bytes:
    """Seal an opaque ``token`` to the subscriber's push key per RFC 8291
    (aes128gcm content coding, RFC 8188). Returns the full push message body:
    ``salt(16) || rs(4, big-endian) || idlen(1) || as_public(65) || ciphertext``.

    ``token`` MUST carry no content beyond a fresh random nonce (ROLES.md §8.1,
    §8.4 `ERR_WAKEPING_CONTENT_PRESENT`) — this function does not enforce
    that; callers (:func:`send_wake`) are responsible for passing only an
    opaque token.

    ``_ephemeral_key``/``_salt`` exist ONLY so ``tests/test_wake.py`` can
    reproduce the RFC 8291 Appendix A worked example byte-for-byte; real
    callers MUST NOT pass them — a fresh ephemeral EC key and a fresh random
    salt are REQUIRED per message (reusing either breaks the AEAD's security
    guarantees).
    """
    ua_public_raw = _b64url_decode(p256dh_b64)
    auth_secret = _b64url_decode(auth_secret_b64)
    if len(ua_public_raw) != 65 or ua_public_raw[0] != 0x04:
        raise ValueError("p256dh must be an uncompressed P-256 point (65 bytes, leading 0x04)")
    if len(auth_secret) != 16:
        raise ValueError("auth secret must be 16 bytes")

    # Also validates the point is actually on the curve (raises ValueError
    # otherwise) — RFC 8291 §7 requires this before ECDH.
    ua_public_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public_raw)

    as_private = _ephemeral_key if _ephemeral_key is not None else ec.generate_private_key(ec.SECP256R1())
    as_public_raw = as_private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    )

    ecdh_secret = as_private.exchange(ec.ECDH(), ua_public_key)

    # RFC 8291 §3.3/§3.4: combine the ECDH secret with the subscriber's auth
    # secret into the IKM that RFC 8188's content-coding derivation consumes.
    key_info = b"WebPush: info\x00" + ua_public_raw + as_public_raw
    ikm = HKDF(algorithm=hashes.SHA256(), length=32, salt=auth_secret, info=key_info).derive(ecdh_secret)

    salt = _salt if _salt is not None else os.urandom(16)

    cek = HKDF(
        algorithm=hashes.SHA256(), length=16, salt=salt,
        info=b"Content-Encoding: aes128gcm\x00",
    ).derive(ikm)
    nonce = HKDF(
        algorithm=hashes.SHA256(), length=12, salt=salt,
        info=b"Content-Encoding: nonce\x00",
    ).derive(ikm)

    # RFC 8188 §2: a single, final record carries the 0x02 padding delimiter
    # (no further padding needed for a token this small).
    padded_plaintext = token + b"\x02"
    ciphertext = AESGCM(cek).encrypt(nonce, padded_plaintext, None)

    header = salt + _RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public_raw)]) + as_public_raw
    return header + ciphertext


# ── subscription registration input ───────────────────────────────────────────


@dataclass(frozen=True)
class PushSubscription:
    """The follower-supplied half of ROLES.md §8.1's `PushSubscription`
    object — endpoint + P-256 public key + auth secret, exactly the shape a
    browser's `PushManager.subscribe()` returns (`{endpoint, keys: {p256dh,
    auth}}`). kerf-pub does not verify a device-key signature over this
    object today (ROLES.md's `ERR_PUSH_SUBSCRIPTION_SIG_INVALID` gate is a
    documented next-step, see docs/distributed-workshop.md) — the abuse
    surface is bounded instead by requiring https + capping subscriptions
    per feed (see `kerf_pub.router.subscribe_feed`)."""

    endpoint: str
    p256dh: str
    auth: str


def validate_subscription(sub: PushSubscription) -> None:
    """Minimal shape/SSRF guard before persisting a subscription: an
    ``endpoint`` a node will later POST to on a publish MUST be an https URL
    (never plaintext http, never a non-http(s) scheme a local urllib could be
    tricked into treating specially)."""
    from urllib.parse import urlsplit

    parts = urlsplit(sub.endpoint)
    if parts.scheme != "https" or not parts.netloc:
        raise ValueError("push subscription endpoint must be an https:// URL")
    try:
        p256dh_raw = _b64url_decode(sub.p256dh)
        auth_raw = _b64url_decode(sub.auth)
    except Exception:
        raise ValueError("p256dh/auth must be base64url") from None
    if len(p256dh_raw) != 65 or p256dh_raw[0] != 0x04:
        raise ValueError("p256dh must be an uncompressed P-256 point (65 bytes)")
    if len(auth_raw) != 16:
        raise ValueError("auth secret must be 16 bytes")


# Bound the abuse surface of an anonymous, open subscribe endpoint: a single
# feed accepts at most this many live wake subscriptions. Not in any spec —
# a pragmatic, self-hostable-node default, not a tuned production constant.
MAX_SUBSCRIPTIONS_PER_FEED = 500


# ── sending a wake (best-effort, never blocks or fails a publish) ────────────


def _http_post(url: str, headers: dict[str, str], body: bytes, timeout_s: float = 10.0) -> bool:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            return 200 <= resp.status < 300
    except Exception as exc:
        logger.info("kerf-pub wake: send failed for %s: %s", url, exc)
        return False


async def send_wake(
    subscription: PushSubscription,
    config: VapidConfig,
    *,
    poster=None,
) -> bool:
    """Send one content-free WakePing to ``subscription``. Best-effort: never
    raises — a dead/unreachable push endpoint is logged and reported False,
    never surfaced as a publish failure (a wake is a latency optimization,
    not a delivery guarantee, ROLES.md §8). ``poster`` is an injection point
    for tests (``(url, headers, body) -> bool``); defaults to a real HTTP
    POST via `urllib` (matches `kerf_pub.client`/`kerf_pub.ipfs`'s existing
    zero-extra-dependency HTTP style)."""
    import asyncio

    token = os.urandom(16)  # fresh nonce every send (ROLES.md §8.4 replay-dedup)
    try:
        body = seal_wake_token(subscription.p256dh, subscription.auth, token)
    except ValueError as exc:
        logger.warning("kerf-pub wake: cannot seal token for %s: %s", subscription.endpoint, exc)
        return False

    headers = dict(vapid_headers(subscription.endpoint, config))
    headers["Content-Encoding"] = "aes128gcm"
    headers["Content-Type"] = "application/octet-stream"
    headers["TTL"] = "86400"

    post = poster if poster is not None else _http_post
    try:
        result = post(subscription.endpoint, headers, body)
        if asyncio.iscoroutine(result):
            result = await result
        return bool(result)
    except Exception as exc:
        logger.info("kerf-pub wake: send raised for %s: %s", subscription.endpoint, exc)
        return False


async def notify_subscribers(
    subscriptions: list[PushSubscription],
    config: VapidConfig | None,
    *,
    poster=None,
) -> int:
    """Send a wake to every subscriber of a feed that just published a new
    revision. Fail-safe off: a ``None`` config (no VAPID keys configured) is a
    silent no-op — kerf never sends an unauthenticated push, and a node
    operator who hasn't configured wake never has an outbound wake attempted.
    Returns the count of pings reported delivered (best-effort telemetry
    only, never load-bearing)."""
    if config is None or not subscriptions:
        return 0
    import asyncio

    results = await asyncio.gather(
        *(send_wake(sub, config, poster=poster) for sub in subscriptions),
        return_exceptions=True,
    )
    return sum(1 for r in results if r is True)
