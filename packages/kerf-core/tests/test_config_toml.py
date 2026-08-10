"""
kerf.toml loading — Settings.load(config_path)
================================================
Settings.load() used to accept ``config_path`` and silently discard it (its
own docstring admitted TOML support didn't exist yet). These tests cover
the loader added to close that gap:

  * path resolution — explicit config_path beats KERF_CONFIG beats ./kerf.toml
    beats ~/.kerf/kerf.toml beats "no file at all".
  * value precedence — env vars beat kerf.toml beat the built-in field
    default, enforced by Settings.settings_customise_sources().
  * every section kerf.example.toml documents actually lands on the right
    Settings field.
  * a missing file falls through to defaults silently; a malformed one
    (bad TOML syntax, or an auth.*_ttl that isn't a "15m"/"720h" duration)
    raises RuntimeError naming the file.

All hermetic — no DB, no network. Every test uses monkeypatch so env vars
and cwd are restored automatically; nothing here touches the developer's
real ~/.kerf or repo-root kerf.toml.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kerf_core.config import Settings

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _clear_relevant_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings reads these directly from the environment; a leaked value
    from the developer's shell (or a previous test) would make these tests
    flaky. Start every test from a known-clean slate.
    """
    for name in (
        "KERF_CONFIG",
        "PORT",
        "DATABASE_URL",
        "LOCAL_MODE",
        "JWT_SECRET",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _clear_relevant_env(monkeypatch)
    # Isolate cwd- and home-based resolution from whatever real kerf.toml
    # happens to exist on the machine running these tests (the repo root
    # has a real, gitignored, developer kerf.toml; ~/.kerf/kerf.toml may
    # or may not exist depending on the box). Every test that wants a
    # ./kerf.toml or ~/.kerf/kerf.toml candidate writes one explicitly.
    isolated_home = tmp_path / "_isolated_home"
    isolated_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: isolated_home)
    monkeypatch.chdir(tmp_path)
    yield


def _write_toml(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "kerf.toml"
    p.write_text(text)
    return p


# ---------------------------------------------------------------------------
# Missing file
# ---------------------------------------------------------------------------


def test_missing_explicit_file_falls_through_to_defaults(tmp_path):
    missing = tmp_path / "does-not-exist.toml"
    s = Settings.load(str(missing))
    assert s.port == "8080"  # field default, untouched
    assert s.local_mode is True  # field default


def test_no_config_at_all_uses_defaults(tmp_path, monkeypatch):
    # No config_path, no KERF_CONFIG, and cwd has no kerf.toml.
    monkeypatch.chdir(tmp_path)
    s = Settings.load()
    assert s.port == "8080"


# ---------------------------------------------------------------------------
# Malformed file — must fail loudly, not silently ignore
# ---------------------------------------------------------------------------


def test_malformed_toml_syntax_raises_with_path(tmp_path):
    bad = _write_toml(tmp_path, '[server]\nport = "unterminated\n')
    with pytest.raises(RuntimeError) as exc_info:
        Settings.load(str(bad))
    msg = str(exc_info.value)
    assert str(bad) in msg


def test_malformed_duration_raises_with_path(tmp_path):
    bad = _write_toml(
        tmp_path,
        '[auth]\naccess_ttl = "not-a-duration"\n',
    )
    with pytest.raises(RuntimeError) as exc_info:
        Settings.load(str(bad))
    msg = str(exc_info.value)
    assert str(bad) in msg
    assert "access_ttl" in msg


# ---------------------------------------------------------------------------
# Path resolution order
# ---------------------------------------------------------------------------


def test_explicit_config_path_overrides_kerf_config_env(tmp_path, monkeypatch):
    explicit = _write_toml(tmp_path, '[server]\nport = "1111"\n')
    stale_env_path = tmp_path / "stale.toml"
    stale_env_path.write_text('[server]\nport = "2222"\n')
    monkeypatch.setenv("KERF_CONFIG", str(stale_env_path))

    s = Settings.load(str(explicit))
    assert s.port == "1111"


def test_kerf_config_env_used_when_no_explicit_path(tmp_path, monkeypatch):
    via_env = _write_toml(tmp_path, '[server]\nport = "3333"\n')
    monkeypatch.setenv("KERF_CONFIG", str(via_env))

    s = Settings.load()
    assert s.port == "3333"


def test_cwd_kerf_toml_used_when_nothing_else_set(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_toml(tmp_path, '[server]\nport = "4444"\n')  # ./kerf.toml

    s = Settings.load()
    assert s.port == "4444"


def test_home_kerf_toml_used_as_last_resort(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    (fake_home / ".kerf").mkdir(parents=True)
    (fake_home / ".kerf" / "kerf.toml").write_text('[server]\nport = "5555"\n')

    empty_cwd = tmp_path / "cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    s = Settings.load()
    assert s.port == "5555"


# ---------------------------------------------------------------------------
# Value precedence: env > kerf.toml > default
# ---------------------------------------------------------------------------


def test_precedence_default_then_toml_then_env(tmp_path, monkeypatch):
    # Named/located so it is NOT picked up by the ./kerf.toml cwd fallback —
    # this test's first assertion needs "no TOML resolves at all".
    other_dir = tmp_path / "elsewhere"
    other_dir.mkdir()
    toml_path = _write_toml(other_dir, '[server]\nport = "6060"\n')

    # 1. Neither TOML nor env set for this run -> default.
    assert Settings.load().port == "8080"

    # 2. TOML set, no env -> TOML wins over default.
    assert Settings.load(str(toml_path)).port == "6060"

    # 3. TOML set AND env set -> env wins over TOML.
    monkeypatch.setenv("PORT", "7070")
    assert Settings.load(str(toml_path)).port == "7070"


# ---------------------------------------------------------------------------
# Section-by-section mapping (kerf.example.toml's documented shape)
# ---------------------------------------------------------------------------


def test_server_section(tmp_path):
    toml_path = _write_toml(
        tmp_path,
        """
        [server]
        port = "9090"
        env = "dev"
        cors_origin = "https://example.test"
        local_mode = false
        """,
    )
    s = Settings.load(str(toml_path))
    assert s.port == "9090"
    assert s.env == "dev"
    assert s.cors_origin == "https://example.test"
    assert s.local_mode is False


def test_server_port_tolerates_bare_integer(tmp_path):
    # kerf.example.toml documents port as a quoted string, but a bare TOML
    # integer is a natural typo — Settings.port is typed str, so coerce.
    toml_path = _write_toml(tmp_path, "[server]\nport = 9191\n")
    s = Settings.load(str(toml_path))
    assert s.port == "9191"


def test_database_section(tmp_path):
    toml_path = _write_toml(
        tmp_path,
        '[database]\nurl = "postgres://u:p@localhost:5432/kerf?sslmode=disable"\n',
    )
    s = Settings.load(str(toml_path))
    assert s.database_url == "postgres://u:p@localhost:5432/kerf?sslmode=disable"


def test_auth_section(tmp_path):
    toml_path = _write_toml(
        tmp_path,
        """
        [auth]
        jwt_secret = "toml-secret"
        access_ttl = "15m"
        refresh_ttl = "720h"
        password_pepper = "toml-pepper"

          [auth.google]
          client_id = "toml-google-id"
          client_secret = "toml-google-secret"
          redirect_url = "https://example.test/auth/google/callback"
        """,
    )
    s = Settings.load(str(toml_path))
    assert s.jwt_secret == "toml-secret"
    assert s.jwt_access_ttl_minutes == 15
    assert s.jwt_refresh_ttl_days == 30  # 720h == 30d
    assert s.password_pepper == "toml-pepper"
    assert s.google_client_id == "toml-google-id"
    assert s.google_client_secret == "toml-google-secret"
    assert s.google_redirect_url == "https://example.test/auth/google/callback"


def test_storage_section(tmp_path):
    toml_path = _write_toml(
        tmp_path,
        """
        [storage]
        backend = "filesystem"
        local_path = "./toml-storage"
        filesystem_root = "/tmp/toml-projects"
        cdn_base_url = "https://cdn.example.test"

          [storage.s3]
          bucket = "toml-bucket"
          region = "toml-region"
          access_key_id = "toml-key"
          secret_access_key = "toml-secret"
          endpoint = "https://s3.example.test"
          public_url_base = "https://public.example.test"
        """,
    )
    s = Settings.load(str(toml_path))
    assert s.storage_backend == "filesystem"
    assert s.local_storage_path == "./toml-storage"
    assert s.filesystem_root == "/tmp/toml-projects"
    assert s.cdn_base_url == "https://cdn.example.test"
    assert s.s3_bucket == "toml-bucket"
    assert s.s3_region == "toml-region"
    assert s.s3_access_key_id == "toml-key"
    assert s.s3_secret_access_key == "toml-secret"
    assert s.s3_endpoint == "https://s3.example.test"
    assert s.s3_public_url_base == "https://public.example.test"


def test_llm_section(tmp_path):
    toml_path = _write_toml(
        tmp_path,
        """
        [llm]
        default_model = "toml-model"

          [llm.anthropic]
          api_key = "toml-anthropic-key"

          [llm.openai]
          api_key = "toml-openai-key"

          [llm.moonshot]
          api_key = "toml-moonshot-key"

          [llm.gemini]
          api_key = "toml-gemini-key"
        """,
    )
    s = Settings.load(str(toml_path))
    assert s.default_model == "toml-model"
    assert s.anthropic_api_key == "toml-anthropic-key"
    assert s.openai_api_key == "toml-openai-key"
    assert s.moonshot_api_key == "toml-moonshot-key"
    assert s.gemini_api_key == "toml-gemini-key"


def test_usage_section(tmp_path):
    toml_path = _write_toml(tmp_path, "[usage]\nenabled = false\n")
    s = Settings.load(str(toml_path))
    assert s.usage_enabled is False


def test_limits_section(tmp_path):
    toml_path = _write_toml(
        tmp_path,
        """
        [limits]
        max_threads_per_project = 99
        file_revisions_max = 50
        step_max_bytes = 123456
        upload_chunk_size = 654321
        upload_session_ttl_hours = 4
        step_tessellate_workers = 3
        step_tessellate_timeout_sec = 111
        """,
    )
    s = Settings.load(str(toml_path))
    assert s.max_threads_per_project == 99
    assert s.file_revisions_max == 50
    assert s.step_max_bytes == 123456
    assert s.upload_chunk_size == 654321
    assert s.upload_session_ttl_hours == 4
    assert s.step_tessellate_workers == 3
    assert s.step_tessellate_timeout_sec == 111


def test_system_user_section(tmp_path):
    toml_path = _write_toml(
        tmp_path,
        """
        [system_user]
        email = "toml-user@example.test"
        name = "TOML User"
        password = "toml-password"
        """,
    )
    s = Settings.load(str(toml_path))
    assert s.system_user_email == "toml-user@example.test"
    assert s.system_user_name == "TOML User"
    assert s.system_user_password == "toml-password"


def test_unmapped_keys_are_ignored_not_errors(tmp_path):
    # step_tessellate_node_bin / step_tessellate_script are documented in
    # kerf.example.toml but have no Settings field anywhere in the
    # codebase (see decisions.md) — a TOML file that sets them must not
    # error, it should just have no effect.
    toml_path = _write_toml(
        tmp_path,
        """
        [limits]
        step_tessellate_node_bin = "/usr/bin/node"
        step_tessellate_script = "./scripts/step-tessellate.mjs"
        """,
    )
    s = Settings.load(str(toml_path))  # must not raise
    assert not hasattr(s, "step_tessellate_node_bin")


def test_kerf_example_toml_parses_without_error():
    # Regression guard: the shipped example file (README/docs point users
    # at it) must always be loadable as-is.
    example = _REPO_ROOT / "kerf.example.toml"
    assert example.is_file(), f"expected {example} to exist"
    s = Settings.load(str(example))
    assert s.port == "8080"
    assert s.storage_backend == "local"
    assert s.default_model == "claude-opus-4-7"
