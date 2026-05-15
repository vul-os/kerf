"""Hermetic tests for the three lifecycle email templates.

Covers:
- Correct subject lines
- CTA URL appears in both HTML and plain-text output
- Non-empty plain-text fallback for every template
- No unrendered ``$Placeholder`` tokens left in rendered output
- Conditional greeting works with and without a name
- (Mock) send dispatches through the provider layer (Resend)

All I/O is mocked — no network, no DB, no SMTP.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from kerf_cloud.email.templates import (
    TEMPLATES,
    renderer,
    template_subjects,
    _render_template,
)
from kerf_cloud.email.providers import send_email, ErrMissingCredential


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_APP_URL = "https://app.kerf.sh"
_VERIFY_URL = "https://app.kerf.sh/verify?token=abc123def456"
_RESET_URL = "https://app.kerf.sh/reset?token=xyz789pqr012"


def _resend_settings(**overrides):
    defaults = dict(
        email_provider="resend",
        email_from="Kerf <noreply@kerf.sh>",
        resend_api_key="re_test_live_key",
        ses_region="",
        ses_access_key_id="",
        ses_secret_access_key="",
        smtp_host="",
        smtp_port=0,
        smtp_username="",
        smtp_password="",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _no_dollar_vars(text: str) -> bool:
    """Return True if there are no unrendered $VarName tokens (uppercase-initial)."""
    return not re.search(r"\$[A-Z][A-Za-z]+", text)


# ---------------------------------------------------------------------------
# verify_email
# ---------------------------------------------------------------------------


class TestVerifyEmail:
    def _render(self, name="Alice", expires="24 hours"):
        return renderer.render(
            "verify_email",
            "alice@example.com",
            {
                "Name": name,
                "VerifyURL": _VERIFY_URL,
                "ExpiresIn": expires,
                "AppURL": _APP_URL,
            },
        )

    def test_subject_is_correct(self):
        msg = self._render()
        assert msg.Subject == "Verify your email for Kerf"

    def test_subject_matches_registry(self):
        assert template_subjects["verify_email"] == "Verify your email for Kerf"

    def test_html_contains_verify_url(self):
        msg = self._render()
        assert _VERIFY_URL in msg.HTML

    def test_text_contains_verify_url(self):
        msg = self._render()
        assert _VERIFY_URL in msg.Text

    def test_text_fallback_is_non_empty(self):
        msg = self._render()
        assert len(msg.Text.strip()) > 50

    def test_no_unrendered_placeholders_html(self):
        msg = self._render()
        assert _no_dollar_vars(msg.HTML), f"Unrendered var in HTML: {re.findall(r'[$][A-Z][A-Za-z]+', msg.HTML)}"

    def test_no_unrendered_placeholders_text(self):
        msg = self._render()
        assert _no_dollar_vars(msg.Text), f"Unrendered var in text: {re.findall(r'[$][A-Z][A-Za-z]+', msg.Text)}"

    def test_expires_in_appears_in_html(self):
        msg = self._render(expires="48 hours")
        assert "48 hours" in msg.HTML

    def test_expires_in_appears_in_text(self):
        msg = self._render(expires="48 hours")
        assert "48 hours" in msg.Text

    def test_html_contains_kerf_branding(self):
        msg = self._render()
        html_lower = msg.HTML.lower()
        assert "kerf" in html_lower

    def test_renders_without_name(self):
        """No name should not leave a dangling comma."""
        msg = renderer.render(
            "verify_email",
            "anon@example.com",
            {"VerifyURL": _VERIFY_URL, "ExpiresIn": "12 hours"},
        )
        # Should not contain ", ." — a rendered empty name greeting
        assert ", ." not in msg.HTML
        assert _VERIFY_URL in msg.HTML


# ---------------------------------------------------------------------------
# welcome (onboarding)
# ---------------------------------------------------------------------------


class TestWelcomeEmail:
    def _render(self, name="Bob"):
        return renderer.render(
            "welcome",
            "bob@example.com",
            {"Name": name, "AppURL": _APP_URL},
        )

    def test_subject_is_correct(self):
        msg = self._render()
        assert msg.Subject == template_subjects["welcome"]
        assert "Welcome to Kerf" in msg.Subject
        assert "build something" in msg.Subject

    def test_subject_matches_registry(self):
        assert "Welcome to Kerf" in template_subjects["welcome"]

    def test_html_contains_start_designing_link(self):
        msg = self._render()
        assert f"{_APP_URL}/projects" in msg.HTML

    def test_text_contains_start_designing_link(self):
        msg = self._render()
        assert f"{_APP_URL}/projects" in msg.Text

    def test_text_fallback_is_non_empty(self):
        msg = self._render()
        assert len(msg.Text.strip()) > 80

    def test_no_unrendered_placeholders_html(self):
        msg = self._render()
        assert _no_dollar_vars(msg.HTML), f"Unrendered var in HTML: {re.findall(r'[$][A-Z][A-Za-z]+', msg.HTML)}"

    def test_no_unrendered_placeholders_text(self):
        msg = self._render()
        assert _no_dollar_vars(msg.Text), f"Unrendered var in text: {re.findall(r'[$][A-Z][A-Za-z]+', msg.Text)}"

    def test_docs_link_present_in_html(self):
        msg = self._render()
        assert "kerf.sh/docs" in msg.HTML

    def test_github_link_present_in_html(self):
        msg = self._render()
        assert "github.com/kerf-sh/kerf" in msg.HTML

    def test_workshop_link_present_in_html(self):
        msg = self._render()
        assert "workshop" in msg.HTML.lower()

    def test_renders_without_name(self):
        msg = renderer.render(
            "welcome",
            "anon@example.com",
            {"AppURL": _APP_URL},
        )
        assert f"{_APP_URL}/projects" in msg.HTML
        assert _no_dollar_vars(msg.HTML)

    def test_name_appears_in_greeting_when_provided(self):
        msg = self._render(name="Zanele")
        assert "Zanele" in msg.HTML


# ---------------------------------------------------------------------------
# password_reset
# ---------------------------------------------------------------------------


class TestPasswordResetEmail:
    def _render(self, expires="1 hour"):
        return renderer.render(
            "password_reset",
            "carol@example.com",
            {
                "ResetURL": _RESET_URL,
                "ExpiresIn": expires,
            },
        )

    def test_subject_is_correct(self):
        msg = self._render()
        assert msg.Subject == "Reset your Kerf password"

    def test_subject_matches_registry(self):
        assert template_subjects["password_reset"] == "Reset your Kerf password"

    def test_html_contains_reset_url(self):
        msg = self._render()
        assert _RESET_URL in msg.HTML

    def test_text_contains_reset_url(self):
        msg = self._render()
        assert _RESET_URL in msg.Text

    def test_text_fallback_is_non_empty(self):
        msg = self._render()
        assert len(msg.Text.strip()) > 50

    def test_no_unrendered_placeholders_html(self):
        msg = self._render()
        assert _no_dollar_vars(msg.HTML), f"Unrendered var in HTML: {re.findall(r'[$][A-Z][A-Za-z]+', msg.HTML)}"

    def test_no_unrendered_placeholders_text(self):
        msg = self._render()
        assert _no_dollar_vars(msg.Text), f"Unrendered var in text: {re.findall(r'[$][A-Z][A-Za-z]+', msg.Text)}"

    def test_expiry_appears_in_html(self):
        msg = self._render(expires="2 hours")
        assert "2 hours" in msg.HTML

    def test_expiry_appears_in_text(self):
        msg = self._render(expires="2 hours")
        assert "2 hours" in msg.Text


# ---------------------------------------------------------------------------
# Template registry completeness
# ---------------------------------------------------------------------------


class TestTemplateRegistry:
    def test_all_lifecycle_templates_in_registry(self):
        for name in ("verify_email", "welcome", "password_reset"):
            assert name in TEMPLATES

    def test_all_lifecycle_subjects_present(self):
        for name in ("verify_email", "welcome", "password_reset"):
            assert name in template_subjects
            assert len(template_subjects[name]) > 5

    def test_no_crlf_in_any_subject(self):
        for name, subj in template_subjects.items():
            assert "\n" not in subj, f"Subject for {name!r} has LF"
            assert "\r" not in subj, f"Subject for {name!r} has CR"


# ---------------------------------------------------------------------------
# Mock dispatch through provider layer (Resend)
# ---------------------------------------------------------------------------


class TestProviderDispatch:
    """Verify that rendered lifecycle emails travel through providers.send_email."""

    def _fake_urlopen(self, captured):
        import urllib.request

        class FakeResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self, n=256):
                return b'{"id":"msg_test"}'

        def _urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            import json

            captured["body"] = json.loads(req.data)
            return FakeResp()

        return _urlopen

    def test_verify_email_dispatches_via_resend(self):
        captured = {}
        cfg = _resend_settings()
        msg = renderer.render(
            "verify_email",
            "alice@example.com",
            {"VerifyURL": _VERIFY_URL, "ExpiresIn": "24 hours"},
        )
        with patch("urllib.request.urlopen", self._fake_urlopen(captured)):
            send_email(
                to="alice@example.com",
                subject=msg.Subject,
                html=msg.HTML,
                text=msg.Text,
                settings=cfg,
            )
        assert captured["url"] == "https://api.resend.com/emails"
        assert captured["body"]["to"] == ["alice@example.com"]
        assert captured["body"]["subject"] == "Verify your email for Kerf"
        assert _VERIFY_URL in captured["body"]["html"]
        assert _VERIFY_URL in captured["body"]["text"]

    def test_welcome_dispatches_via_resend(self):
        captured = {}
        cfg = _resend_settings()
        msg = renderer.render(
            "welcome",
            "bob@example.com",
            {"Name": "Bob", "AppURL": _APP_URL},
        )
        with patch("urllib.request.urlopen", self._fake_urlopen(captured)):
            send_email(
                to="bob@example.com",
                subject=msg.Subject,
                html=msg.HTML,
                text=msg.Text,
                settings=cfg,
            )
        assert "Welcome to Kerf" in captured["body"]["subject"]
        assert f"{_APP_URL}/projects" in captured["body"]["html"]

    def test_password_reset_dispatches_via_resend(self):
        captured = {}
        cfg = _resend_settings()
        msg = renderer.render(
            "password_reset",
            "carol@example.com",
            {"ResetURL": _RESET_URL, "ExpiresIn": "1 hour"},
        )
        with patch("urllib.request.urlopen", self._fake_urlopen(captured)):
            send_email(
                to="carol@example.com",
                subject=msg.Subject,
                html=msg.HTML,
                text=msg.Text,
                settings=cfg,
            )
        assert captured["body"]["subject"] == "Reset your Kerf password"
        assert _RESET_URL in captured["body"]["html"]
        assert _RESET_URL in captured["body"]["text"]

    def test_missing_api_key_raises_before_network(self):
        cfg = _resend_settings(resend_api_key="")
        msg = renderer.render(
            "verify_email",
            "x@example.com",
            {"VerifyURL": _VERIFY_URL, "ExpiresIn": "1 hour"},
        )
        with pytest.raises(ErrMissingCredential):
            send_email(
                to="x@example.com",
                subject=msg.Subject,
                html=msg.HTML,
                settings=cfg,
            )
