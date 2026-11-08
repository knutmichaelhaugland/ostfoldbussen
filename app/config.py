"""Konfigurasjon for Østfoldbussen.

Ren stdlib. All konfigurasjon kommer fra miljøvariabler (lastes fra
en env-fil i drift, eller --env-file lokalt).
Ingen hemmeligheter har standardverdier; funksjoner som er skrudd PÅ uten
nødvendige hemmeligheter feiler ved oppstart (fail-closed).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(Exception):
    """Ugyldig eller ufullstendig konfigurasjon."""


def _str(env: dict, key: str, default: str = "") -> str:
    value = env.get(key)
    return default if value is None or value == "" else value


def _bool(env: dict, key: str, default: bool = False) -> bool:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{key} må være true/false, fikk {raw!r}")


def _int(env: dict, key: str, default: int | None = None) -> int | None:
    raw = env.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError as exc:
        raise ConfigError(f"{key} må være heltall, fikk {raw!r}") from exc


def _float(env: dict, key: str, default: float | None = None) -> float | None:
    raw = env.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(str(raw).strip())
    except ValueError as exc:
        raise ConfigError(f"{key} må være tall, fikk {raw!r}") from exc


def _read_secret(env: dict, key: str, default: str = "") -> str:
    """Les hemmelighet fra fil (foretrukket) eller miljøvariabel.

    Rekkefølge: <KEY>_FILE → SECRETS_DIR/<key> (lowercase) → miljøvariabel.
    Filer unngår Compose-substitusjon av `$` og gir bedre tilgangskontroll.
    """
    explicit = env.get(key + "_FILE")
    if explicit:
        try:
            with open(explicit, "r", encoding="utf-8") as handle:
                value = handle.read().strip()
        except OSError as exc:
            raise ConfigError(f"{key}_FILE er satt, men filen kan ikke leses: {explicit}") from exc
        if not value:
            raise ConfigError(f"{key}_FILE er satt, men filen er tom: {explicit}")
        return value
    secrets_dir = env.get("SECRETS_DIR")
    if secrets_dir:
        path = os.path.join(secrets_dir, key.lower())
        try:
            with open(path, "r", encoding="utf-8") as handle:
                value = handle.read().strip()
            if value:
                return value
        except OSError:
            pass
    return env.get(key) or default


def load_env_file(path: str, environ: dict | None = None) -> dict:
    """Les KEY=VALUE-fil. Eksisterende miljøvariabler vinner (secrets overstyrer ikke)."""
    env = os.environ if environ is None else environ
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export "):].strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in env:
                env[key] = value
    return env


@dataclass(frozen=True)
class Config:
    # App
    app_env: str = "development"
    app_timezone: str = "Europe/Oslo"
    host: str = "127.0.0.1"
    port: int = 8000
    database_path: str = "/var/lib/ostfoldbussen/app.db"
    log_level: str = "INFO"
    build_sha: str = "unknown"
    public_base_url: str = ""
    public_sms_number: str = ""
    public_sms_enabled: bool = False
    public_contact_email: str = ""
    status_notice: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "hjelp@ostfoldbussen.no"
    contact_to: str = "hjelp@ostfoldbussen.no"
    smtp_starttls: bool = True
    contact_rate_limit_per_hour: int = 5
    public_matomo_enabled: bool = False
    public_matomo_url: str = ""
    public_matomo_site_id: str = "1"
    inmobile_webhook_enabled: bool = False
    inmobile_webhook_key_id: str = ""
    inmobile_webhook_public_key: str = ""
    inmobile_api_key: str = ""
    inmobile_from: str = ""
    inmobile_outbound_enabled: bool = False
    trust_proxy: bool = False
    trusted_proxy_ips: tuple[str, ...] = ()
    cookie_secure: bool = True
    # HTTP-vern
    max_body_bytes: int = 8192
    max_message_chars: int = 1600
    request_timeout_s: float = 20.0
    # /api/simulate er en testflate: krever admin som standard.
    simulate_require_auth: bool = True
    simulate_rate_limit_per_hour: int = 60
    # Entur
    entur_client_name: str = "ostfoldbussen-selfhosted"
    entur_geocoder_url: str = "https://api.entur.io/geocoder/v3"
    entur_journey_url: str = "https://api.entur.io/journey-planner/v3/graphql"
    entur_timeout_s: float = 15.0
    entur_max_retries: int = 3
    # Terskler (produktvalg er IKKE vedtatt; trygge defaults)
    transfer_slack_s: int = 120  # API-default, ikke produktvalg
    minimum_transfer_s: int | None = None  # None => transfer_slack_s
    warn_transfer_below_s: int = 300
    max_walk_m: float | None = None
    max_walk_leg_m: float | None = None
    max_walk_time_s: int | None = None
    num_trip_patterns: int = 10
    search_window_minutes: int | None = None
    scope_policy: str = "flag_only"  # "flag_only" | "require_in_scope"
    # SMS-felles kostnadsvern (leverandøradapteren eier transporten)
    daily_sms_limit: int = 0
    rate_limit_per_hour: int = 5
    inbound_rate_limit_per_hour: int = 30
    inbound_daily_limit: int = 200
    sms_unit_cost_nok: str = ""  # tom => vises som UKJENT (ingen oppdiktede priser)
    llm_unit_cost_nok: str = ""
    # LLM (provider-nøytral, AV som standard)
    llm_enabled: bool = False
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_timeout_s: float = 10.0
    llm_max_input_chars: int = 500
    llm_max_output_tokens: int = 400
    llm_reasoning_effort: str = "none"
    message_hash_key: str = ""
    bineric_enabled: bool = False
    bineric_base_url: str = ""
    bineric_model: str = ""
    bineric_api_key: str = ""
    bineric_timeout_s: float = 20.0
    bineric_max_output_tokens: int = 192
    bineric_max_concurrency: int = 2
    bineric_requests_per_minute: int = 60
    bineric_max_retries: int = 2
    bineric_daily_budget_usd: float = 5.0
    # Admin
    admin_user: str = ""
    admin_password_hash: str = ""
    session_secret: str = ""
    session_ttl_s: int = 8 * 3600
    session_cookie: str = "ob_session"
    csrf_cookie: str = "ob_csrf"
    # Personvern
    pseudonym_salt: str = ""
    conversation_ttl_minutes: int = 30
    retention_requests_days: int = 30
    retention_deliveries_days: int = 30
    retention_reviews_days: int = 90
    # Helse
    health_entur_check: bool = True
    health_entur_cache_s: int = 60
    health_entur_timeout_s: float = 3.0

    # -- avledede verdier ------------------------------------------------
    @property
    def effective_min_transfer_s(self) -> int:
        return (
            self.minimum_transfer_s
            if self.minimum_transfer_s is not None
            else self.transfer_slack_s
        )

    @property
    def contact_form_ready(self) -> bool:
        return bool(self.smtp_host and self.smtp_from and self.contact_to)

    def thresholds(self):
        from prototype import config as proto_config

        return proto_config.Thresholds(
            transfer_slack_s=self.transfer_slack_s,
            minimum_transfer_s=self.effective_min_transfer_s,
            warn_transfer_below_s=self.warn_transfer_below_s,
            max_walk_m=self.max_walk_m,
            max_walk_leg_m=self.max_walk_leg_m,
            max_walk_time_s=self.max_walk_time_s,
            num_trip_patterns=self.num_trip_patterns,
            search_window_minutes=self.search_window_minutes,
        )

    def validate(self) -> None:
        if self.scope_policy not in {"flag_only", "require_in_scope"}:
            raise ConfigError(
                f"SCOPE_POLICY må være flag_only eller require_in_scope, fikk {self.scope_policy!r}"
            )
        if not self.pseudonym_salt or len(self.pseudonym_salt) < 16:
            raise ConfigError("PSEUDONYM_SALT mangler eller er for kort (min 16 tegn)")
        if not self.session_secret or len(self.session_secret) < 32:
            raise ConfigError("SESSION_SECRET mangler eller er for kort (min 32 tegn)")
        if not self.admin_user or not self.admin_password_hash:
            raise ConfigError("ADMIN_USER og ADMIN_PASSWORD_HASH må være satt")
        if not self.admin_password_hash.startswith("pbkdf2_sha256$"):
            raise ConfigError("ADMIN_PASSWORD_HASH må være pbkdf2_sha256$... (bruk app auth-hash)")
        if self.llm_enabled:
            if not (self.llm_base_url and self.llm_model and self.llm_api_key):
                raise ConfigError(
                    "LLM_ENABLED=true krever LLM_BASE_URL, LLM_MODEL og LLM_API_KEY"
                )
        if self.bineric_enabled:
            if not (self.bineric_base_url and self.bineric_model and self.bineric_api_key):
                raise ConfigError(
                    "BINERIC_ENABLED=true krever BINERIC_BASE_URL, BINERIC_MODEL og BINERIC_API_KEY"
                )
        if self.daily_sms_limit < 0:
            raise ConfigError("DAILY_SMS_LIMIT kan ikke være negativ")
        if self.inmobile_outbound_enabled and self.daily_sms_limit <= 0:
            raise ConfigError("INMOBILE_OUTBOUND_ENABLED krever DAILY_SMS_LIMIT > 0")
        # Port 465 bruker implicit TLS (SMTP_SSL); andre porter krever
        # STARTTLS i produksjon. Sertifikatvalidering håndheves i contact.py.
        if (
            self.app_env == "production"
            and self.smtp_host
            and int(self.smtp_port) != 465
            and not self.smtp_starttls
        ):
            raise ConfigError(
                "SMTP uten STARTTLS er ikke tillatt i produksjon (port 465 bruker implicit TLS)"
            )
        if self.simulate_rate_limit_per_hour < 0:
            raise ConfigError("SIMULATE_RATE_LIMIT_PER_HOUR kan ikke være negativ")
        if self.rate_limit_per_hour < 0:
            raise ConfigError("RATE_LIMIT_PER_HOUR kan ikke være negativ")
        if not (1 <= self.max_message_chars <= 5000):
            raise ConfigError("MAX_MESSAGE_CHARS må være 1..5000")
        if not (1 <= self.llm_max_input_chars <= 5000):
            raise ConfigError("LLM_MAX_INPUT_CHARS må være 1..5000")
        if self.message_hash_key and len(self.message_hash_key) < 32:
            raise ConfigError("MESSAGE_HASH_KEY må være minst 32 tegn når den er satt")
        if self.app_env == "production":
            if not self.cookie_secure:
                raise ConfigError("COOKIE_SECURE må være true i produksjon")
            if self.inmobile_webhook_enabled and not (
                self.inmobile_webhook_key_id and self.inmobile_webhook_public_key
            ):
                raise ConfigError("inMobile-webhook krever KEY_ID og PUBLIC_KEY")
            if self.inmobile_outbound_enabled and not (
                self.inmobile_api_key and self.inmobile_from
            ):
                raise ConfigError("inMobile-utgående krever API_KEY og FROM")
            if self.llm_enabled and not self.llm_base_url.startswith("https://"):
                raise ConfigError("LLM_BASE_URL må bruke HTTPS i produksjon")
            if self.bineric_enabled and not self.bineric_base_url.startswith("https://"):
                raise ConfigError("BINERIC_BASE_URL må bruke HTTPS i produksjon")


def from_env(env: dict | None = None) -> Config:
    env = os.environ if env is None else env
    config = Config(
        app_env=_str(env, "APP_ENV", "development"),
        app_timezone=_str(env, "APP_TIMEZONE", "Europe/Oslo"),
        host=_str(env, "HOST", "127.0.0.1"),
        port=_int(env, "PORT", 8000),
        database_path=_str(env, "DATABASE_PATH", "/var/lib/ostfoldbussen/app.db"),
        log_level=_str(env, "LOG_LEVEL", "INFO"),
        build_sha=_str(env, "BUILD_SHA", "unknown"),
        public_base_url=_str(env, "PUBLIC_BASE_URL", ""),
        public_sms_number=_str(env, "PUBLIC_SMS_NUMBER", ""),
        public_sms_enabled=_bool(env, "PUBLIC_SMS_ENABLED", False),
        public_contact_email=_str(env, "PUBLIC_CONTACT_EMAIL", ""),
        status_notice=_str(env, "STATUS_NOTICE", ""),
        smtp_host=_str(env, "SMTP_HOST", ""),
        smtp_port=_int(env, "SMTP_PORT", 587),
        smtp_user=_str(env, "SMTP_USER", ""),
        smtp_password=_read_secret(env, "SMTP_PASSWORD", ""),
        smtp_from=_str(env, "SMTP_FROM", "hjelp@ostfoldbussen.no"),
        contact_to=_str(env, "CONTACT_TO", "hjelp@ostfoldbussen.no"),
        smtp_starttls=_bool(env, "SMTP_STARTTLS", True),
        contact_rate_limit_per_hour=_int(env, "CONTACT_RATE_LIMIT_PER_HOUR", 5),
        public_matomo_enabled=_bool(env, "PUBLIC_MATOMO_ENABLED", False),
        public_matomo_url=_str(env, "PUBLIC_MATOMO_URL", ""),
        public_matomo_site_id=_str(env, "PUBLIC_MATOMO_SITE_ID", "1"),
        inmobile_webhook_enabled=_bool(env, "INMOBILE_WEBHOOK_ENABLED", False),
        inmobile_webhook_key_id=_read_secret(env, "INMOBILE_WEBHOOK_KEY_ID", ""),
        inmobile_webhook_public_key=_read_secret(env, "INMOBILE_WEBHOOK_PUBLIC_KEY", ""),
        inmobile_api_key=_read_secret(env, "INMOBILE_API_KEY", ""),
        inmobile_from=_str(env, "INMOBILE_FROM", ""),
        inmobile_outbound_enabled=_bool(env, "INMOBILE_OUTBOUND_ENABLED", False),
        trust_proxy=_bool(env, "TRUST_PROXY", False),
        trusted_proxy_ips=tuple(
            item.strip() for item in _str(env, "TRUSTED_PROXY_IPS", "").split(",")
            if item.strip()
        ),
        cookie_secure=_bool(env, "COOKIE_SECURE", True),
        max_body_bytes=_int(env, "MAX_BODY_BYTES", 8192),
        max_message_chars=_int(env, "MAX_MESSAGE_CHARS", 1600),
        request_timeout_s=_float(env, "REQUEST_TIMEOUT_S", 20.0),
        simulate_require_auth=_bool(env, "SIMULATE_REQUIRE_AUTH", True),
        simulate_rate_limit_per_hour=_int(env, "SIMULATE_RATE_LIMIT_PER_HOUR", 60),
        entur_client_name=_str(env, "ENTUR_CLIENT_NAME", "ostfoldbussen-selfhosted"),
        entur_geocoder_url=_str(env, "ENTUR_GEOCODER_URL", "https://api.entur.io/geocoder/v3"),
        entur_journey_url=_str(
            env, "ENTUR_JOURNEY_PLANNER_URL", "https://api.entur.io/journey-planner/v3/graphql"
        ),
        entur_timeout_s=_float(env, "ENTUR_TIMEOUT_S", 15.0),
        entur_max_retries=_int(env, "ENTUR_MAX_RETRIES", 3),
        transfer_slack_s=_int(env, "TRANSFER_SLACK_S", 120),
        minimum_transfer_s=_int(env, "MIN_TRANSFER_S", None),
        warn_transfer_below_s=_int(env, "WARN_TRANSFER_BELOW_S", 300),
        max_walk_m=_float(env, "MAX_WALK_M", None),
        max_walk_leg_m=_float(env, "MAX_WALK_LEG_M", None),
        max_walk_time_s=_int(env, "MAX_WALK_TIME_S", None),
        num_trip_patterns=_int(env, "NUM_TRIP_PATTERNS", 10),
        search_window_minutes=_int(env, "SEARCH_WINDOW_MINUTES", None),
        scope_policy=_str(env, "SCOPE_POLICY", "flag_only"),
        daily_sms_limit=_int(env, "DAILY_SMS_LIMIT", 0),
        rate_limit_per_hour=_int(env, "RATE_LIMIT_PER_HOUR", 5),
        inbound_rate_limit_per_hour=_int(env, "INBOUND_RATE_LIMIT_PER_HOUR", 30),
        inbound_daily_limit=_int(env, "INBOUND_DAILY_LIMIT", 200),
        sms_unit_cost_nok=_str(env, "SMS_UNIT_COST_NOK", ""),
        llm_unit_cost_nok=_str(env, "LLM_UNIT_COST_NOK", ""),
        llm_enabled=_bool(env, "LLM_ENABLED", False),
        llm_base_url=_str(env, "LLM_BASE_URL", ""),
        llm_model=_str(env, "LLM_MODEL", ""),
        llm_api_key=_read_secret(env, "LLM_API_KEY", ""),
        llm_timeout_s=_float(env, "LLM_TIMEOUT_S", 10.0),
        llm_max_input_chars=_int(env, "LLM_MAX_INPUT_CHARS", 500),
        llm_max_output_tokens=_int(env, "LLM_MAX_OUTPUT_TOKENS", 400),
        llm_reasoning_effort=_str(env, "LLM_REASONING_EFFORT", "none"),
        message_hash_key=_read_secret(env, "MESSAGE_HASH_KEY", ""),
        bineric_enabled=_bool(env, "BINERIC_ENABLED", False),
        bineric_base_url=_str(env, "BINERIC_BASE_URL", ""),
        bineric_model=_str(env, "BINERIC_MODEL", ""),
        bineric_api_key=_read_secret(env, "BINERIC_API_KEY", ""),
        bineric_timeout_s=_float(env, "BINERIC_TIMEOUT_S", 20.0),
        bineric_max_output_tokens=_int(env, "BINERIC_MAX_OUTPUT_TOKENS", 192),
        bineric_max_concurrency=_int(env, "BINERIC_MAX_CONCURRENCY", 2),
        bineric_requests_per_minute=_int(env, "BINERIC_REQUESTS_PER_MINUTE", 60),
        bineric_max_retries=_int(env, "BINERIC_MAX_RETRIES", 2),
        bineric_daily_budget_usd=_float(env, "BINERIC_DAILY_BUDGET_USD", 5.0),
        admin_user=_str(env, "ADMIN_USER", ""),
        admin_password_hash=_read_secret(env, "ADMIN_PASSWORD_HASH", ""),
        session_secret=_read_secret(env, "SESSION_SECRET", ""),
        session_ttl_s=_int(env, "SESSION_TTL_S", 8 * 3600),
        session_cookie=_str(env, "SESSION_COOKIE", "ob_session"),
        csrf_cookie=_str(env, "CSRF_COOKIE", "ob_csrf"),
        pseudonym_salt=_read_secret(env, "PSEUDONYM_SALT", ""),
        conversation_ttl_minutes=_int(env, "CONVERSATION_TTL_MINUTES", 30),
        retention_requests_days=_int(env, "RETENTION_REQUESTS_DAYS", 30),
        retention_deliveries_days=_int(env, "RETENTION_DELIVERIES_DAYS", 30),
        retention_reviews_days=_int(env, "RETENTION_REVIEWS_DAYS", 90),
        health_entur_check=_bool(env, "HEALTH_ENTUR_CHECK", True),
        health_entur_cache_s=_int(env, "HEALTH_ENTUR_CACHE_S", 60),
        health_entur_timeout_s=_float(env, "HEALTH_ENTUR_TIMEOUT_S", 3.0),
    )
    config.validate()
    return config
