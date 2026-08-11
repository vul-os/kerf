import base64
import os
import re
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic import Field, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import PydanticBaseSettingsSource

from kerf_core.db.config import default_database_url

_REPO_ROOT_ENV = str(Path(__file__).resolve().parent.parent / ".env")


# =============================================================================
# kerf.toml support
#
# tomllib is stdlib (Python 3.11+, which this project already requires — see
# pyproject.toml's requires-python), so no tomli dependency is added.
# =============================================================================

# Duration strings as used by kerf.example.toml's [auth] section, e.g.
# "15m", "720h". Deliberately simple (one number + one unit) — matches what
# the example file documents; not a general ISO-8601/Go-duration parser.
_DURATION_RE = re.compile(r"^\s*(\d+)\s*(s|m|h|d|w)\s*$")
_DURATION_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _resolve_toml_path() -> Optional[Path]:
    """Pick the kerf.toml path to load, or None if none applies.

    Resolution order (highest wins):
      1. KERF_CONFIG env var — set unconditionally by Settings.load() when
         an explicit config_path is passed, so an explicit --config always
         beats a pre-existing KERF_CONFIG in the environment.
      2. ./kerf.toml (current working directory)
      3. ~/.kerf/kerf.toml

    Candidates 2 and 3 are implicit defaults, not user directives, so they
    are only used if the file actually exists there. Candidate 1 is a user
    directive (explicit path or KERF_CONFIG) — if it doesn't exist, that is
    handled as a missing file (fall through to defaults silently), not an
    error; see _KerfTomlSettingsSource.__call__.
    """
    explicit = os.environ.get("KERF_CONFIG", "")
    if explicit:
        return Path(explicit).expanduser()
    cwd_candidate = Path("kerf.toml")
    if cwd_candidate.is_file():
        return cwd_candidate
    home_candidate = Path.home() / ".kerf" / "kerf.toml"
    if home_candidate.is_file():
        return home_candidate
    return None


def _parse_duration_seconds(value: str, toml_path: Path, key: str) -> int:
    """Parse a "15m" / "720h" style duration string into whole seconds.

    Raises RuntimeError (not ValueError) so it reads the same as the
    TOMLDecodeError path below: a malformed kerf.toml value fails loudly,
    with the file path and the offending key, instead of booting on a
    silently-wrong default.
    """
    match = _DURATION_RE.match(str(value))
    if not match:
        raise RuntimeError(
            f"Malformed kerf.toml at {toml_path}: {key} = {value!r} is not a "
            "duration like '15m' or '720h' (supported suffixes: s, m, h, d, w)"
        )
    amount, unit = match.groups()
    return int(amount) * _DURATION_UNIT_SECONDS[unit]


def _flatten_kerf_toml(data: dict, toml_path: Path) -> dict[str, Any]:
    """Map the [section] structure documented in kerf.example.toml onto
    Settings' flat field names.

    Only keys kerf.example.toml actually documents are mapped here. A
    couple of keys it documents (step_tessellate_node_bin,
    step_tessellate_script) have no corresponding Settings field anywhere
    in the codebase — they are deliberately left unmapped rather than
    inventing a field for them; see decisions.md.
    """
    out: dict[str, Any] = {}

    server = data.get("server", {})
    if "port" in server:
        # Settings.port is typed str; tolerate a bare TOML integer
        # (port = 8080) as well as the documented quoted form.
        out["port"] = str(server["port"])
    if "env" in server:
        out["env"] = server["env"]
    if "cors_origin" in server:
        out["cors_origin"] = server["cors_origin"]
    if "local_mode" in server:
        out["local_mode"] = server["local_mode"]

    database = data.get("database", {})
    if "url" in database:
        out["database_url"] = database["url"]

    auth = data.get("auth", {})
    if "jwt_secret" in auth:
        out["jwt_secret"] = auth["jwt_secret"]
    if "access_ttl" in auth:
        out["jwt_access_ttl_minutes"] = (
            _parse_duration_seconds(auth["access_ttl"], toml_path, "auth.access_ttl") // 60
        )
    if "refresh_ttl" in auth:
        out["jwt_refresh_ttl_days"] = (
            _parse_duration_seconds(auth["refresh_ttl"], toml_path, "auth.refresh_ttl") // 86400
        )
    if "password_pepper" in auth:
        out["password_pepper"] = auth["password_pepper"]
    google = auth.get("google", {})
    if "client_id" in google:
        out["google_client_id"] = google["client_id"]
    if "client_secret" in google:
        out["google_client_secret"] = google["client_secret"]
    if "redirect_url" in google:
        out["google_redirect_url"] = google["redirect_url"]

    storage = data.get("storage", {})
    if "backend" in storage:
        out["storage_backend"] = storage["backend"]
    if "local_path" in storage:
        out["local_storage_path"] = storage["local_path"]
    if "filesystem_root" in storage:
        out["filesystem_root"] = storage["filesystem_root"]
    if "cdn_base_url" in storage:
        out["cdn_base_url"] = storage["cdn_base_url"]
    s3 = storage.get("s3", {})
    if "bucket" in s3:
        out["s3_bucket"] = s3["bucket"]
    if "region" in s3:
        out["s3_region"] = s3["region"]
    if "access_key_id" in s3:
        out["s3_access_key_id"] = s3["access_key_id"]
    if "secret_access_key" in s3:
        out["s3_secret_access_key"] = s3["secret_access_key"]
    if "endpoint" in s3:
        out["s3_endpoint"] = s3["endpoint"]
    if "public_url_base" in s3:
        out["s3_public_url_base"] = s3["public_url_base"]

    llm = data.get("llm", {})
    if "default_model" in llm:
        out["default_model"] = llm["default_model"]
    for provider, field_name in (
        ("anthropic", "anthropic_api_key"),
        ("openai", "openai_api_key"),
        ("moonshot", "moonshot_api_key"),
        ("gemini", "gemini_api_key"),
    ):
        section = llm.get(provider, {})
        if "api_key" in section:
            out[field_name] = section["api_key"]

    usage = data.get("usage", {})
    if "enabled" in usage:
        out["usage_enabled"] = usage["enabled"]

    terminal = data.get("terminal", {})
    if "enabled" in terminal:
        out["terminal_enabled"] = bool(terminal["enabled"])

    # [rate_limits] — one entry per rate_limit() key_prefix, e.g.
    #   [rate_limits]
    #   "auth:register" = 50
    # 0 disables that bucket. Keys are free text so a new limiter needs no
    # config change to become tunable.
    rate_limits = data.get("rate_limits", {})
    if rate_limits:
        out["rate_limit_overrides"] = {
            str(k): int(v) for k, v in rate_limits.items()
        }

    limits = data.get("limits", {})
    for key in (
        "max_threads_per_project",
        "file_revisions_max",
        "step_max_bytes",
        "upload_chunk_size",
        "upload_session_ttl_hours",
        "step_tessellate_workers",
        "step_tessellate_timeout_sec",
    ):
        if key in limits:
            out[key] = limits[key]

    system_user = data.get("system_user", {})
    if "email" in system_user:
        out["system_user_email"] = system_user["email"]
    if "name" in system_user:
        out["system_user_name"] = system_user["name"]
    if "password" in system_user:
        out["system_user_password"] = system_user["password"]

    return out


class _KerfTomlSettingsSource(PydanticBaseSettingsSource):
    """pydantic-settings source that loads kerf.toml, if one resolves.

    This class only knows how to FIND and PARSE the file. Where it ranks
    relative to env vars / .env / defaults is decided entirely by its
    position in the tuple Settings.settings_customise_sources() returns —
    see that method for the actual precedence decision and rationale.
    """

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        # Unused: __call__ is overridden below to return one fully-built
        # dict in a single pass, because TOML keys are renamed and nested
        # (e.g. [auth.google].client_id -> google_client_id) rather than a
        # 1:1 field-name lookup this method could answer per-field.
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        path = _resolve_toml_path()
        if path is None or not path.is_file():
            # No kerf.toml resolves anywhere — fall through to defaults
            # (or whatever env vars/.env already provide) silently. Most
            # installs never create a kerf.toml at all.
            return {}
        try:
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            # The file exists but doesn't parse: almost certainly a typo,
            # not an absent config. Fail loudly with the path so it's
            # obvious which file is broken, rather than silently booting
            # on defaults and leaving the user to wonder why their
            # settings never took effect.
            raise RuntimeError(f"Malformed kerf.toml at {path}: {exc}") from exc
        return _flatten_kerf_toml(data, path)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_REPO_ROOT_ENV, env_file_encoding='utf-8', extra='ignore')
    env: str = "local"
    port: str = "8080"
    # Embedded SQLite by default (zero-dependency local install); set
    # DATABASE_URL=postgres://… to opt into the Postgres scale backend.
    database_url: str = Field(default_factory=default_database_url)
    jwt_secret: str = "dev-secret-change-in-production"
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_days: int = 30
    password_pepper: str = "dev-pepper"
    cors_origin: str = "http://localhost:5173"
    local_mode: bool = True
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_url: str = "http://localhost:8080/auth/google/callback"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    moonshot_api_key: str = ""
    gemini_api_key: str = ""
    default_model: str = "claude-opus-4-7"

    storage_backend: str = "local"
    local_storage_path: str = "./.kerf-storage"
    filesystem_root: str = "~/kerf-projects"
    s3_bucket: str = ""
    s3_region: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_endpoint: str = ""
    s3_public_url_base: str = ""
    cdn_base_url: str = ""

    # Public CDN bucket — a SEPARATE S3/R2 bucket (own credentials) that holds
    # only world-readable assets (user avatars). The private bucket above is
    # never made public; avatars live here because they render as direct
    # <img src>. When unset, public assets fall back to the private bucket.
    cdn_s3_bucket: str = ""
    cdn_s3_region: str = ""
    cdn_s3_access_key_id: str = ""
    cdn_s3_secret_access_key: str = ""
    cdn_s3_endpoint: str = ""

    usage_enabled: bool = False
    # A terminal is a shell with the server process's full authority — the
    # filesystem as that user, the environment, and kerf.toml with its secrets.
    # On a loopback bind that grants nothing the user did not have, so it is
    # allowed there without this flag. On any other bind it is refused unless
    # the operator sets this, having read what it means.
    terminal_enabled: bool = False
    # Per-bucket rate-limit overrides, keyed on rate_limit()'s key_prefix.
    # Empty means every limiter uses the number declared at its call site.
    rate_limit_overrides: dict[str, int] = Field(default_factory=dict)
    max_threads_per_project: int = 50
    file_revisions_max: int = 200

    # RunPod Serverless GPU backend.
    # Set RUNPOD_API_KEY + RUNPOD_ENDPOINT_ID in the environment or .env to enable
    # managed GPU renders.  When empty, RunPodGPUBackend raises RunPodAuthError /
    # RunPodError on first use rather than crashing at startup.
    runpod_api_key: str = ""
    runpod_endpoint_id: str = ""

    # Compute-worker dispatch endpoint (pythonOCC + FEM + CAM + topo subprocess).
    pyworker_url: str = "http://localhost:8090"
    step_max_bytes: int = 200_000_000
    git_inline_max_bytes: int = 1_048_576
    upload_chunk_size: int = 5_242_880
    upload_session_ttl_hours: int = 24

    step_tessellate_workers: int = 2
    step_tessellate_timeout_sec: int = 300
    fem_workers: int = 2
    fem_timeout_sec: int = 600
    sim_workers: int = 2
    sim_timeout_sec: int = 600

    system_user_email: str = ""
    system_user_name: str = ""
    system_user_password: str = ""

    cloud_git_prefix: str = "git"
    cloud_github_client_id: str = ""
    cloud_github_client_secret: str = ""
    cloud_github_redirect_url: str = "http://localhost:8080/auth/github/callback"
    # GitHub App fields (repo-connect / installation token flow).
    # Leave empty to disable; the app degrades gracefully when unset.
    cloud_github_app_id: str = ""
    cloud_github_app_slug: str = ""
    cloud_github_private_key_b64: str = ""

    # GitLab OAuth App fields (repo-mirror flow via GitLabProvider).
    # Leave empty to disable; GitLabProvider.is_configured() gates on these.
    # cloud_gitlab_host: override when using a self-hosted GitLab instance;
    #   defaults to https://gitlab.com when empty.
    cloud_gitlab_app_id: str = ""
    cloud_gitlab_app_secret: str = ""
    cloud_gitlab_host: str = ""

    @property
    def github_private_key_pem(self) -> str:
        """Decode the base64 private key. Returns '' if unset."""
        raw = self.cloud_github_private_key_b64.strip()
        if not raw:
            return ""
        try:
            return base64.b64decode(raw).decode()
        except Exception:
            return ""

    # ---------------------------------------------------------------------------
    # Transactional email — pluggable provider + credentials.
    # email_provider: "smtp" (self-host default, zero-vendor) | "resend" | "ses".
    #   New providers slot in here (add to _VALID_PROVIDERS + a
    #   _send_<name>); no other code changes needed.
    # Our hosted cloud runs Resend today (EMAIL_PROVIDER=resend in the deploy
    #   env); the planned migration to SES is a pure env flip — set
    #   EMAIL_PROVIDER=ses + the ses_* fields, no code change.
    # email_from: default From address, e.g. "Kerf <noreply@kerf.sh>"
    # ---------------------------------------------------------------------------
    email_provider: str = "smtp"
    email_from: str = ""
    # SMTP (self-host / generic). STARTTLS is always negotiated; username and
    # password are optional for open relays.
    smtp_host: str = ""
    smtp_port: int = 0
    smtp_username: str = ""
    smtp_password: str = ""
    # Resend (current hosted provider).
    resend_api_key: str = ""
    # Amazon SES (planned hosted migration).
    ses_region: str = ""
    ses_access_key_id: str = ""
    ses_secret_access_key: str = ""

    # LLM prompt-caching controls.
    # When True (default), the Anthropic provider attaches cache_control
    # breakpoints to the system-prompt block and the tools block so that
    # repeated conversation turns reuse the cached prefix.  Set to False to
    # disable without restarting if cost-tracking or debugging is needed.
    anthropic_prompt_cache: bool = True

    @model_validator(mode="after")
    def _enforce_prod_secrets(self):
        """Refuse to start in production with dev-default secrets."""
        if self.env.lower() not in ("local", "dev", "development", "test"):
            _DEV_JWT = "dev-secret-change-in-production"
            _DEV_PEPPER = "dev-pepper"
            if self.jwt_secret == _DEV_JWT or self.password_pepper == _DEV_PEPPER:
                raise RuntimeError(
                    f"FATAL: Running in env={self.env!r} with dev-default secrets. "
                    "Set JWT_SECRET and PASSWORD_PEPPER to production values."
                )
        return self

    @model_validator(mode="after")
    def _s3_env_aliases(self):
        # Storage secrets are provisioned/staged as KERF_STORAGE_S3_*
        # (Tigris/S3 convention), but the code reads s3_* (env S3_*). Map the
        # former onto the latter when the canonical var is unset.
        _aliases = {
            "s3_bucket": "KERF_STORAGE_S3_BUCKET",
            "s3_region": "KERF_STORAGE_S3_REGION",
            "s3_access_key_id": "KERF_STORAGE_S3_ACCESS_KEY",
            "s3_secret_access_key": "KERF_STORAGE_S3_SECRET_KEY",
            "s3_endpoint": "KERF_STORAGE_S3_ENDPOINT",
            "cdn_s3_bucket": "KERF_STORAGE_CDN_BUCKET",
            "cdn_s3_region": "KERF_STORAGE_CDN_REGION",
            "cdn_s3_access_key_id": "KERF_STORAGE_CDN_ACCESS_KEY",
            "cdn_s3_secret_access_key": "KERF_STORAGE_CDN_SECRET_KEY",
            "cdn_s3_endpoint": "KERF_STORAGE_CDN_ENDPOINT",
        }
        for field, env_name in _aliases.items():
            if not getattr(self, field):
                val = os.environ.get(env_name, "")
                if val:
                    setattr(self, field, val)
        return self

    @model_validator(mode="after")
    def _google_client_id_single_source(self):
        # The Google OAuth client ID is a public value the frontend needs
        # at build time (VITE_GOOGLE_CLIENT_ID). Rather than duplicate it,
        # the backend falls back to that same var when GOOGLE_CLIENT_ID is
        # unset — one value to configure.
        if not self.google_client_id:
            self.google_client_id = os.environ.get("VITE_GOOGLE_CLIENT_ID", "")
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """Wire kerf.toml into the source chain, deliberately below env/.env.

        pydantic-settings gives earlier tuple entries higher priority. We
        insert the TOML source between dotenv_settings and
        file_secret_settings, producing (highest to lowest):

          init kwargs (tests) > env vars > .env file > kerf.toml > defaults

        Env vars and .env sit ABOVE kerf.toml on purpose: 12-factor
        deployments expect `docker run -e PORT=...`-style overrides to win
        no matter what's baked into a config file, and every existing Kerf
        deployment already relies on that. kerf.toml sits ABOVE the
        built-in field defaults so that writing a value there actually
        changes behaviour — closing the gap this class used to have, where
        config_path was accepted and silently discarded. See decisions.md
        for the record of this choice.
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _KerfTomlSettingsSource(settings_cls),
            file_secret_settings,
        )

    @classmethod
    def load(cls, config_path: str = "") -> "Settings":
        """Load a Settings instance, applying kerf.toml if one resolves.

        Path resolution for *which file* to read (highest wins):
          1. ``config_path`` — explicit --config flag, or
             create_app(config_path=...). Forces KERF_CONFIG so it wins
             over any KERF_CONFIG already set in the environment.
          2. KERF_CONFIG environment variable
          3. ./kerf.toml (current working directory)
          4. ~/.kerf/kerf.toml
          5. none — Settings falls back to env vars / .env / defaults only.

        Precedence for the *value* of any individual setting (highest
        wins), enforced by settings_customise_sources() above:
          1. real process environment variables
          2. the .env file (model_config's env_file)
          3. kerf.toml, resolved per the path rules above
          4. the field default declared on Settings

        A missing kerf.toml is not an error (most installs never create
        one). A *present but malformed* kerf.toml raises immediately —
        RuntimeError with the file path and the parser error — rather than
        silently booting on defaults.
        """
        if config_path:
            os.environ["KERF_CONFIG"] = config_path
        return cls()


# Public alias — kerf-core's contract expects ``Config``.
Config = Settings


def is_production_env(env: str) -> bool:
    """Return True when *env* is not a recognised dev/test environment.

    Dev-safe values: "local", "dev", "development", "test".
    Any other value (e.g. "production", "staging", "prod") is treated as
    production so that the fail-closed secret checks fire.
    """
    return env.lower() not in ("local", "dev", "development", "test")


@lru_cache
def get_settings() -> Settings:
    return Settings()
