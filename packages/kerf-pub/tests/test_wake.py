"""Wake — content-free push notifications for the Workshop (kerf_pub.wake,
substrate capability ⑤, `dmtap/substrate/ROLES.md` §8).

Covers:
* RFC 8291 message encryption verified BYTE-FOR-BYTE against the RFC's own
  Appendix A worked example (not just a round-trip self-check).
* RFC 8292 VAPID JWT shape + signature verification.
* Fail-safe-off config loading (no env -> None, never touches the network).
* Subscription validation (https-only, key-shape).
* The subscription registry on InMemoryPubStore.
* The anonymous subscribe/unsubscribe gateway endpoints.
* Best-effort send/notify semantics (never raises, config=None is a no-op).
"""
from __future__ import annotations

import base64
import json
import os

import asyncio

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kerf_pub.store import InMemoryPubStore
from kerf_pub.router import router
from kerf_pub import wake


def _b64u(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _b64u_enc(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


# ---------------------------------------------------------------------------
# RFC 8291 Appendix A worked example (exact byte match, not a round-trip)
# ---------------------------------------------------------------------------


class TestRfc8291Vector:
    """https://www.rfc-editor.org/rfc/rfc8291.txt Section 5 + Appendix A."""

    AS_PRIVATE_B64 = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
    UA_PUBLIC_B64 = (
        "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
    )
    AUTH_SECRET_B64 = "BTBZMqHH6r4Tts7J_aSIgg"
    SALT_B64 = "DGv6ra1nlYgDCS1FRnbzlw"
    PLAINTEXT = b"When I grow up, I want to be a watermelon"
    EXPECTED_BODY_B64 = (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
        "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT"
        "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
    )

    def _as_private_key(self) -> ec.EllipticCurvePrivateKey:
        d = int.from_bytes(_b64u(self.AS_PRIVATE_B64), "big")
        return ec.derive_private_key(d, ec.SECP256R1())

    def test_seal_matches_rfc_vector_exactly(self):
        out = wake.seal_wake_token(
            self.UA_PUBLIC_B64, self.AUTH_SECRET_B64, self.PLAINTEXT,
            _ephemeral_key=self._as_private_key(), _salt=_b64u(self.SALT_B64),
        )
        assert out == _b64u(self.EXPECTED_BODY_B64)

    def test_header_shape(self):
        out = wake.seal_wake_token(
            self.UA_PUBLIC_B64, self.AUTH_SECRET_B64, self.PLAINTEXT,
            _ephemeral_key=self._as_private_key(), _salt=_b64u(self.SALT_B64),
        )
        salt = out[:16]
        rs = int.from_bytes(out[16:20], "big")
        idlen = out[20]
        keyid = out[21:21 + idlen]
        assert salt == _b64u(self.SALT_B64)
        assert rs == 4096
        assert idlen == 65
        assert keyid[0] == 0x04  # uncompressed EC point

    def test_fresh_ephemeral_key_and_salt_by_default(self):
        # Two calls with the real (non-test) code path never collide.
        a = wake.seal_wake_token(self.UA_PUBLIC_B64, self.AUTH_SECRET_B64, b"x")
        b = wake.seal_wake_token(self.UA_PUBLIC_B64, self.AUTH_SECRET_B64, b"x")
        assert a != b

    def test_rejects_bad_p256dh_shape(self):
        with pytest.raises(ValueError):
            wake.seal_wake_token(_b64u_enc(b"\x04" + b"\x00" * 10), self.AUTH_SECRET_B64, b"x")

    def test_rejects_bad_auth_secret_length(self):
        with pytest.raises(ValueError):
            wake.seal_wake_token(self.UA_PUBLIC_B64, _b64u_enc(b"\x00" * 4), b"x")


# ---------------------------------------------------------------------------
# VAPID (RFC 8292)
# ---------------------------------------------------------------------------


class TestVapid:
    def test_default_config_none_when_unset(self, monkeypatch):
        monkeypatch.delenv(wake.ENV_VAPID_PRIVATE_KEY, raising=False)
        monkeypatch.delenv(wake.ENV_VAPID_SUBJECT, raising=False)
        assert wake.default_wake_config() is None

    def test_default_config_none_when_only_one_var_set(self, monkeypatch):
        monkeypatch.setenv(wake.ENV_VAPID_PRIVATE_KEY, wake.generate_vapid_private_key_b64())
        monkeypatch.delenv(wake.ENV_VAPID_SUBJECT, raising=False)
        assert wake.default_wake_config() is None

    def test_default_config_none_on_garbage_key(self, monkeypatch):
        monkeypatch.setenv(wake.ENV_VAPID_PRIVATE_KEY, "not-valid-base64url-scalar!!")
        monkeypatch.setenv(wake.ENV_VAPID_SUBJECT, "mailto:ops@example.com")
        assert wake.default_wake_config() is None

    def test_configured_roundtrip(self, monkeypatch):
        monkeypatch.setenv(wake.ENV_VAPID_PRIVATE_KEY, wake.generate_vapid_private_key_b64())
        monkeypatch.setenv(wake.ENV_VAPID_SUBJECT, "mailto:ops@example.com")
        config = wake.default_wake_config()
        assert config is not None
        assert len(config.public_key_raw) == 65
        assert config.public_key_raw[0] == 0x04

    def test_jwt_signature_verifies_and_claims_shape(self):
        priv_b64 = wake.generate_vapid_private_key_b64()
        d = int.from_bytes(_b64u(priv_b64), "big")
        private_key = ec.derive_private_key(d, ec.SECP256R1())
        public_key_raw = private_key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
        )
        config = wake.VapidConfig(private_key=private_key, public_key_raw=public_key_raw,
                                  subject="mailto:ops@example.com")
        headers = wake.vapid_headers("https://push.example.net/push/abc123", config, now_s=1_700_000_000)
        auth = headers["Authorization"]
        assert auth.startswith("vapid t=")
        jwt = auth.split("t=", 1)[1].split(",", 1)[0]
        header_b64, claims_b64, sig_b64 = jwt.split(".")

        header = json.loads(_b64u(header_b64))
        assert header == {"typ": "JWT", "alg": "ES256"}
        claims = json.loads(_b64u(claims_b64))
        assert claims["aud"] == "https://push.example.net"
        assert claims["sub"] == "mailto:ops@example.com"
        assert claims["exp"] == 1_700_000_000 + wake.VAPID_JWT_TTL_S

        sig_raw = _b64u(sig_b64)
        assert len(sig_raw) == 64
        r = int.from_bytes(sig_raw[:32], "big")
        s = int.from_bytes(sig_raw[32:], "big")
        der = encode_dss_signature(r, s)
        signing_input = f"{header_b64}.{claims_b64}".encode("ascii")
        private_key.public_key().verify(der, signing_input, ec.ECDSA(hashes.SHA256()))  # raises if bad

        assert headers["Crypto-Key"] == f"p256ecdsa={_b64u_enc(public_key_raw)}"


# ---------------------------------------------------------------------------
# Subscription validation
# ---------------------------------------------------------------------------


def _valid_sub(endpoint: str = "https://push.example.net/ep/abc") -> wake.PushSubscription:
    ua_key = ec.generate_private_key(ec.SECP256R1())
    from cryptography.hazmat.primitives import serialization
    p256dh_raw = ua_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return wake.PushSubscription(
        endpoint=endpoint, p256dh=_b64u_enc(p256dh_raw), auth=_b64u_enc(os.urandom(16)),
    )


class TestValidateSubscription:
    def test_accepts_well_formed_https_subscription(self):
        wake.validate_subscription(_valid_sub())  # no raise

    def test_rejects_http_endpoint(self):
        with pytest.raises(ValueError):
            wake.validate_subscription(_valid_sub(endpoint="http://push.example.net/ep/abc"))

    def test_rejects_non_url_endpoint(self):
        with pytest.raises(ValueError):
            wake.validate_subscription(_valid_sub(endpoint="not-a-url"))

    def test_rejects_bad_p256dh(self):
        sub = _valid_sub()
        bad = wake.PushSubscription(endpoint=sub.endpoint, p256dh=_b64u_enc(b"\x00" * 10), auth=sub.auth)
        with pytest.raises(ValueError):
            wake.validate_subscription(bad)

    def test_rejects_bad_auth_length(self):
        sub = _valid_sub()
        bad = wake.PushSubscription(endpoint=sub.endpoint, p256dh=sub.p256dh, auth=_b64u_enc(b"\x00" * 4))
        with pytest.raises(ValueError):
            wake.validate_subscription(bad)


# ---------------------------------------------------------------------------
# Store round-trip (InMemoryPubStore)
# ---------------------------------------------------------------------------


class TestStoreRoundTrip:
    async def test_put_list_count_delete(self):
        store = InMemoryPubStore()
        pub = os.urandom(32)
        assert await store.count_wake_subscriptions(pub) == 0

        await store.put_wake_subscription(pub, "https://a.example/ep1", "p256dh-a", "auth-a", 100)
        await store.put_wake_subscription(pub, "https://b.example/ep2", "p256dh-b", "auth-b", 200)
        assert await store.count_wake_subscriptions(pub) == 2

        rows = await store.list_wake_subscriptions(pub)
        assert [r["endpoint"] for r in rows] == ["https://a.example/ep1", "https://b.example/ep2"]
        assert rows[0]["p256dh"] == "p256dh-a"
        assert rows[0]["auth"] == "auth-a"

        await store.delete_wake_subscription(pub, "https://a.example/ep1")
        rows = await store.list_wake_subscriptions(pub)
        assert len(rows) == 1
        assert rows[0]["endpoint"] == "https://b.example/ep2"

    async def test_put_is_idempotent_upsert(self):
        store = InMemoryPubStore()
        pub = os.urandom(32)
        await store.put_wake_subscription(pub, "https://a.example/ep1", "old", "old-auth", 100)
        await store.put_wake_subscription(pub, "https://a.example/ep1", "new", "new-auth", 150)
        rows = await store.list_wake_subscriptions(pub)
        assert len(rows) == 1
        assert rows[0]["p256dh"] == "new"

    async def test_subscriptions_are_scoped_per_pub(self):
        store = InMemoryPubStore()
        pub_a, pub_b = os.urandom(32), os.urandom(32)
        await store.put_wake_subscription(pub_a, "https://a.example/ep", "x", "y", 1)
        assert await store.count_wake_subscriptions(pub_b) == 0


# ---------------------------------------------------------------------------
# Anonymous subscribe/unsubscribe gateway endpoints
# ---------------------------------------------------------------------------


def _app(store) -> TestClient:
    app = FastAPI()
    app.state.pub_store = store
    app.include_router(router)
    return TestClient(app)


class TestWakeKeyEndpoint:
    def test_fails_safe_off_when_unconfigured(self, monkeypatch):
        monkeypatch.delenv(wake.ENV_VAPID_PRIVATE_KEY, raising=False)
        monkeypatch.delenv(wake.ENV_VAPID_SUBJECT, raising=False)
        tc = _app(InMemoryPubStore())
        r = tc.get("/.well-known/dmtap-pub/wake-key")
        assert r.status_code == 503

    def test_returns_public_key_when_configured(self, monkeypatch):
        raw = wake.generate_vapid_private_key_b64()
        monkeypatch.setenv(wake.ENV_VAPID_PRIVATE_KEY, raw)
        monkeypatch.setenv(wake.ENV_VAPID_SUBJECT, "mailto:ops@example.com")
        tc = _app(InMemoryPubStore())
        r = tc.get("/.well-known/dmtap-pub/wake-key")
        assert r.status_code == 200
        body = r.json()
        config = wake.default_wake_config()
        assert body == {"public_key": wake.vapid_public_key_b64(config)}
        # The exposed key really is usable as a P-256 applicationServerKey —
        # 65 raw uncompressed-point bytes once base64url-decoded.
        assert len(_b64u(body["public_key"])) == 65


class TestSubscribeEndpoint:
    def test_fails_safe_off_when_unconfigured(self, monkeypatch):
        monkeypatch.delenv(wake.ENV_VAPID_PRIVATE_KEY, raising=False)
        monkeypatch.delenv(wake.ENV_VAPID_SUBJECT, raising=False)
        store = InMemoryPubStore()
        tc = _app(store)
        pub = _b64u_enc(os.urandom(32))
        sub = _valid_sub()
        r = tc.post(f"/.well-known/dmtap-pub/feed/{pub}/subscribe", json={
            "endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
        })
        assert r.status_code == 503

    def _configure(self, monkeypatch):
        monkeypatch.setenv(wake.ENV_VAPID_PRIVATE_KEY, wake.generate_vapid_private_key_b64())
        monkeypatch.setenv(wake.ENV_VAPID_SUBJECT, "mailto:ops@example.com")

    def test_subscribe_then_unsubscribe(self, monkeypatch):
        self._configure(monkeypatch)
        store = InMemoryPubStore()
        tc = _app(store)
        pub_bytes = os.urandom(32)
        pub = _b64u_enc(pub_bytes)
        sub = _valid_sub()

        r = tc.post(f"/.well-known/dmtap-pub/feed/{pub}/subscribe", json={
            "endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
        })
        assert r.status_code == 200
        assert r.json() == {"pub": pub, "subscribed": True}

        # No dedicated list endpoint (subscriptions are write-only from the
        # subscriber's perspective) — assert persistence via the store directly.
        assert asyncio.run(store.count_wake_subscriptions(pub_bytes)) == 1

        r = tc.request("DELETE", f"/.well-known/dmtap-pub/feed/{pub}/subscribe", json={
            "endpoint": sub.endpoint,
        })
        assert r.status_code == 200
        assert r.json() == {"pub": pub, "subscribed": False}
        assert asyncio.run(store.count_wake_subscriptions(pub_bytes)) == 0

    def test_rejects_bad_pub_length(self, monkeypatch):
        self._configure(monkeypatch)
        tc = _app(InMemoryPubStore())
        sub = _valid_sub()
        r = tc.post("/.well-known/dmtap-pub/feed/not-32-bytes/subscribe", json={
            "endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
        })
        assert r.status_code == 400

    def test_rejects_http_endpoint(self, monkeypatch):
        self._configure(monkeypatch)
        tc = _app(InMemoryPubStore())
        pub = _b64u_enc(os.urandom(32))
        sub = _valid_sub(endpoint="http://push.example.net/ep/abc")
        r = tc.post(f"/.well-known/dmtap-pub/feed/{pub}/subscribe", json={
            "endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
        })
        assert r.status_code == 400

    def test_enforces_per_feed_cap(self, monkeypatch):
        self._configure(monkeypatch)
        monkeypatch.setattr(wake, "MAX_SUBSCRIPTIONS_PER_FEED", 1)
        # router.py imported the name directly, so patch it there too.
        import kerf_pub.router as router_mod
        monkeypatch.setattr(router_mod, "MAX_SUBSCRIPTIONS_PER_FEED", 1)

        store = InMemoryPubStore()
        tc = _app(store)
        pub = _b64u_enc(os.urandom(32))

        sub1 = _valid_sub(endpoint="https://a.example/ep1")
        r1 = tc.post(f"/.well-known/dmtap-pub/feed/{pub}/subscribe", json={
            "endpoint": sub1.endpoint, "keys": {"p256dh": sub1.p256dh, "auth": sub1.auth},
        })
        assert r1.status_code == 200

        sub2 = _valid_sub(endpoint="https://b.example/ep2")
        r2 = tc.post(f"/.well-known/dmtap-pub/feed/{pub}/subscribe", json={
            "endpoint": sub2.endpoint, "keys": {"p256dh": sub2.p256dh, "auth": sub2.auth},
        })
        assert r2.status_code == 429

        # Re-subscribing the SAME endpoint (a renewal) is not blocked by the cap.
        r3 = tc.post(f"/.well-known/dmtap-pub/feed/{pub}/subscribe", json={
            "endpoint": sub1.endpoint, "keys": {"p256dh": sub1.p256dh, "auth": sub1.auth},
        })
        assert r3.status_code == 200


# ---------------------------------------------------------------------------
# send_wake / notify_subscribers — best-effort semantics
# ---------------------------------------------------------------------------


class TestSendAndNotify:
    def _config(self, monkeypatch) -> wake.VapidConfig:
        monkeypatch.setenv(wake.ENV_VAPID_PRIVATE_KEY, wake.generate_vapid_private_key_b64())
        monkeypatch.setenv(wake.ENV_VAPID_SUBJECT, "mailto:ops@example.com")
        return wake.default_wake_config()

    async def test_send_wake_calls_poster_with_sealed_body_and_vapid_auth(self, monkeypatch):
        config = self._config(monkeypatch)
        sub = _valid_sub()
        calls = []

        def fake_poster(url, headers, body):
            calls.append((url, headers, body))
            return True

        ok = await wake.send_wake(sub, config, poster=fake_poster)
        assert ok is True
        assert len(calls) == 1
        url, headers, body = calls[0]
        assert url == sub.endpoint
        assert headers["Authorization"].startswith("vapid t=")
        assert headers["Content-Encoding"] == "aes128gcm"
        # header (86 bytes for a 65-byte keyid) + AEAD tag (16) + >=1 byte ciphertext
        assert len(body) > 86 + 16

    async def test_send_wake_never_raises_on_poster_failure(self, monkeypatch):
        config = self._config(monkeypatch)
        sub = _valid_sub()

        def failing_poster(url, headers, body):
            raise ConnectionError("boom")

        ok = await wake.send_wake(sub, config, poster=failing_poster)
        assert ok is False

    async def test_send_wake_supports_async_poster(self, monkeypatch):
        config = self._config(monkeypatch)
        sub = _valid_sub()

        async def async_poster(url, headers, body):
            return True

        assert await wake.send_wake(sub, config, poster=async_poster) is True

    async def test_notify_subscribers_noop_when_unconfigured(self):
        sent = await wake.notify_subscribers([_valid_sub()], None, poster=lambda *a: True)
        assert sent == 0

    async def test_notify_subscribers_counts_successes(self, monkeypatch):
        config = self._config(monkeypatch)
        subs = [_valid_sub(f"https://n{i}.example/ep") for i in range(3)]

        def flaky_poster(url, headers, body):
            return "n1." not in url  # one endpoint always fails

        sent = await wake.notify_subscribers(subs, config, poster=flaky_poster)
        assert sent == 2

    async def test_notify_subscribers_empty_list_is_noop(self, monkeypatch):
        config = self._config(monkeypatch)
        assert await wake.notify_subscribers([], config) == 0
