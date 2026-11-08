"""HTTP-lag for Østfoldbussen (ThreadingHTTPServer, ren stdlib).

Bindes til 127.0.0.1 bak Caddy. Ingen statiske filer serveres, så path
traversal er ikke mulig. Maks request-body, Content-Type-krav og timeouts
håndheves eksplisitt.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import auth, templates
from .config import Config
from .db import Database, utc_now
from .health import HealthService
from .observability import ObservabilityService
from .inmobile_adapter import InmobileAdapter
from .inmobile_sender import InmobileSender
from .contact import ContactNotConfigured, ContactSendError, send_contact_email
from .vcard import build_vcard, content_disposition
from .logging_setup import elapsed_ms, log
from .pipeline import Pipeline, pseudonymize
from .sms_adapter import SmsAdapter

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'unsafe-inline'; img-src 'self' data:; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
}

# Inbound webhook bodies are size-limited per adapter.
INMOBILE_WEBHOOK_MAX_BODY = 32 * 1024
LOGIN_MAX_ATTEMPTS = 10
LOGIN_WINDOW_S = 300
LOGIN_BLOCK_S = 300
LOGIN_POST_WINDOW_S = 60
LOGIN_POST_MAX = 30
RATE_STATE_MAX_KEYS = 4096


@dataclass
class AppContext:
    config: Config
    db: Database
    pipeline: Pipeline
    health: HealthService
    observability: ObservabilityService
    sms_adapter: SmsAdapter
    inmobile_sender: InmobileSender
    started_at: float = field(default_factory=time.monotonic)
    login_attempts: dict = field(default_factory=dict)  # ip -> [timestamps]
    login_blocked: dict = field(default_factory=dict)  # ip -> until
    login_posts: dict = field(default_factory=dict)  # ip -> [timestamps]
    simulate_hits: dict = field(default_factory=dict)  # ip -> [timestamps]
    contact_hits: dict = field(default_factory=dict)  # ip -> [timestamps]
    rate_lock: threading.Lock = field(default_factory=threading.Lock)
    rate_pruned_at: float = 0.0

    def prune_rate_state(self, now: float | None = None, *, force: bool = False) -> None:
        """Fjern utløpt rate-state og begrens antall IP-nøkler.

        Kalles med jevne mellomrom; aktive login-blokkeringer bevares.
        """
        now = time.time() if now is None else now
        with self.rate_lock:
            if not force and now - self.rate_pruned_at < 60:
                return
            self.rate_pruned_at = now
            for attr, window in (("simulate_hits", 3600), ("contact_hits", 3600)):
                state = getattr(self, attr)
                for key in list(state):
                    state[key] = [t for t in state[key] if now - t < window]
                    if not state[key]:
                        state.pop(key, None)
            for key in list(self.login_attempts):
                self.login_attempts[key] = [
                    t for t in self.login_attempts[key] if now - t < LOGIN_WINDOW_S
                ]
                if not self.login_attempts[key]:
                    self.login_attempts.pop(key, None)
            for key in list(self.login_posts):
                self.login_posts[key] = [
                    t for t in self.login_posts[key] if now - t < LOGIN_POST_WINDOW_S
                ]
                if not self.login_posts[key]:
                    self.login_posts.pop(key, None)
            for key in list(self.login_blocked):
                if self.login_blocked[key] <= now:
                    self.login_blocked.pop(key, None)
            # En hard øvre grense hindrer minnevekst ved mange unike IP-er.
            for state in (self.simulate_hits, self.contact_hits,
                          self.login_attempts, self.login_blocked, self.login_posts):
                while len(state) > RATE_STATE_MAX_KEYS:
                    removed = False
                    for key in list(state):
                        if state is self.login_blocked and state[key] > now:
                            continue
                        state.pop(key, None)
                        removed = True
                        break
                    if not removed:
                        break


def create_app(
    config: Config,
    *,
    deps=None,
    entur_probe=None,
    inmobile_http_post=None,
    sms_adapter=None,
    now_fn=None,
    interpreter=None,
) -> AppContext:
    db = Database(config.database_path)
    db.init()
    pipeline = Pipeline(config, db, deps=deps, interpreter=interpreter, now_fn=now_fn)
    health = HealthService(config, db, probe=entur_probe)
    observability = ObservabilityService(config, db, health)
    inmobile_sender = InmobileSender(config, db, http_post=inmobile_http_post)
    if sms_adapter is None:
        sms_adapter = InmobileAdapter(config, db, inmobile_sender)
    log("app_started", build_sha=config.build_sha, app_env=config.app_env)
    return AppContext(
        config=config, db=db, pipeline=pipeline, health=health,
        observability=observability, sms_adapter=sms_adapter,
        inmobile_sender=inmobile_sender,
    )


def make_server(ctx: AppContext, host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    handler_class = type("BoundHandler", (OstfoldHandler,), {"app": ctx})
    server = ThreadingHTTPServer(
        (host if host is not None else ctx.config.host, port if port is not None else ctx.config.port),
        handler_class,
    )
    server.daemon_threads = True
    return server


class OstfoldHandler(BaseHTTPRequestHandler):
    app: AppContext = None  # type: ignore[assignment]
    server_version = "ostfoldbussen"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # -- livssyklus ------------------------------------------------------
    def handle_one_request(self):
        try:
            self.connection.settimeout(self.app.config.request_timeout_s)
        except OSError:
            pass
        return super().handle_one_request()

    def log_message(self, format, *args):  # noqa: A002 - stdlib-signatur
        log(
            "http_access",
            method=getattr(self, "command", ""),
            path=urlparse(getattr(self, "path", "")).path,
            detail=format % args,
        )

    def log_request(self, code="-", size="-"):
        log(
            "http_request",
            method=self.command,
            path=urlparse(self.path).path,
            status=int(code) if str(code).isdigit() else code,
            bytes=size,
        )

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._method_not_allowed()

    def do_DELETE(self):
        self._method_not_allowed()

    def do_PATCH(self):
        self._method_not_allowed()

    def do_HEAD(self):
        self._method_not_allowed()

    # -- dispatch --------------------------------------------------------
    def _dispatch(self, method: str) -> None:
        self._request_id = uuid.uuid4().hex[:12]
        self._set_cookies: list[str] = []
        try:
            self._route(method)
        except BrokenPipeError:
            pass
        except Exception as exc:  # pragma: no cover - siste skanse
            log("http_unhandled", error=type(exc).__name__, path=urlparse(self.path).path)
            try:
                self._send_json(500, {"error": "internal_error"})
            except Exception:
                pass

    def _route(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        ctx = self.app
        config = ctx.config

        if path == "/healthz" and method == "GET":
            snapshot = ctx.health.snapshot()
            self._send_json(200 if snapshot["status"] == "ok" else 503, snapshot)
            return
        if path == "/favicon.ico" and method == "GET":
            self._send_bytes(204, b"", "image/x-icon")
            return
        if path == "/ostfoldbussen.vcf" and method == "GET":
            public = self._public_context()
            if not public.get("sms_enabled"):
                self._send_html(404, templates.error_page(
                    404, "Fant ikke siden", "Siden finnes ikke."))
                return
            try:
                card = build_vcard(public.get("sms_number", ""))
            except ValueError:
                self._send_html(404, templates.error_page(
                    404, "Fant ikke siden", "Siden finnes ikke."))
                return
            self._send_raw(
                200, card.encode("utf-8"), "text/vcard; charset=utf-8",
                extra_headers={"Content-Disposition": content_disposition()},
            )
            return
        if path == "/sitemap.xml" and method == "GET":
            self._send_raw(200, templates.sitemap_xml().encode("utf-8"),
                           "application/xml; charset=utf-8")
            return
        if path == "/robots.txt" and method == "GET":
            self._send_raw(200, templates.robots_txt().encode("utf-8"),
                           "text/plain; charset=utf-8")
            return
        if path in {"/about", "/about/"} and method == "GET":
            self._send_raw(301, b"", "text/plain; charset=utf-8",
                           extra_headers={"Location": "/om"})
            return
        if path == "/og-image.png" and method == "GET":
            image = Path(__file__).resolve().parent / "static" / "og-image.png"
            if image.is_file():
                self._send_raw(200, image.read_bytes(), "image/png",
                               extra_headers={"Cache-Control": "public, max-age=86400"})
            else:
                self._send_html(404, templates.error_page(
                    404, "Fant ikke siden", "Siden finnes ikke."))
            return
        if path == "/matomo-init.js" and method == "GET":
            script = (
                "(function(){var s=document.currentScript||document.querySelector('script[data-matomo-url]');"
                "if(!s)return;var u=s.getAttribute('data-matomo-url')||'';"
                "var id=s.getAttribute('data-matomo-site')||'1';if(!u)return;"
                "if(u.slice(-1)!=='/')u+='/';"
                "var q=window._paq=window._paq||[];"
                "q.push(['setTrackerUrl',u+'matomo.php']);q.push(['setSiteId',id]);"
                "q.push(['disableCookies']);q.push(['trackPageView']);q.push(['enableLinkTracking']);"
                "var d=document,g=d.createElement('script');g.async=true;g.src=u+'matomo.js';"
                "(d.head||d.documentElement).appendChild(g);})();"
            )
            self._send_raw(200, script.encode("utf-8"),
                           "text/javascript; charset=utf-8", no_store=False)
            return

        if method == "GET":
            public = self._public_context()
            if path == "/":
                self._send_html(200, templates.home(public))
            elif path == "/slik-fungerer-det":
                self._send_html(200, templates.how_it_works(public))
            elif path == "/om":
                self._send_html(200, templates.about(public))
            elif path == "/personvern":
                self._send_html(200, templates.privacy(public))
            elif path == "/data":
                self._send_html(200, templates.data_page(public))
            elif path == "/kontakt":
                query = parse_qs(parsed.query)
                sent = query.get("sendt", ["0"])[0] == "1"
                self._send_html(200, templates.contact(public, sent=sent))
            elif path == "/status":
                self._send_html(200, templates.status_page(self._public_snapshot(), public))
            elif path == "/admin":
                self._handle_admin_index()
            elif path == "/admin/login":
                self._redirect("/admin")
            elif path == "/admin/logout":
                self._method_not_allowed()
            elif path.startswith("/admin/"):
                self._handle_admin_page(path)
            elif path.startswith("/api/"):
                self._method_not_allowed()
            else:
                self._send_html(404, templates.error_page(404, "Fant ikke siden", "Siden finnes ikke."))
            return

        if method == "POST":
            if path == "/api/simulate":
                self._handle_simulate()
                return
            if path == "/kontakt":
                self._handle_contact()
                return
            if path == "/api/webhooks/inmobile":
                self._handle_inmobile_webhook()
                return
            if path == "/admin/login":
                self._handle_login()
                return
            if path == "/admin/logout":
                self._handle_logout()
                return
            if path == "/admin/errors":
                self._handle_error_review_update()
                return
            if path.startswith("/admin/"):
                self._require_admin()
                return
            self._send_html(404, templates.error_page(404, "Fant ikke siden", "Siden finnes ikke."))
            return

        self._method_not_allowed()

    # -- offentlig status (sanitert) -------------------------------------
    def _public_snapshot(self) -> dict:
        snapshot = self.app.health.snapshot()
        components = {
            key: {
                "state": value.get("state", "UNKNOWN"),
                "last_success": value.get("last_success"),
            }
            for key, value in snapshot.get("components", {}).items()
        }
        return {
            "status": snapshot.get("status"),
            "build_sha": snapshot.get("build_sha"),
            "uptime_s": snapshot.get("uptime_s"),
            "checked_at": snapshot.get("checked_at"),
            "components": components,
        }

    # -- klient-IP og rate limits ---------------------------------------
    def _client_ip(self) -> str:
        """Returner klient-IP; XFF brukes bare fra eksplisitt betrodde peers."""
        peer = self.client_address[0] if self.client_address else "unknown"
        if self.app.config.trust_proxy:
            import ipaddress

            allowed = self.app.config.trusted_proxy_ips
            trusted = False
            if allowed:
                for network in allowed:
                    try:
                        if ipaddress.ip_address(peer) in ipaddress.ip_network(network, strict=False):
                            trusted = True
                            break
                    except ValueError:
                        continue
            # Caddy 2.11.9 overskriver klientens XFF med den faktiske
            # proxy-klienten. Siste verdi er derfor riktig for én betrodd proxy.
            forwarded = self.headers.get("X-Forwarded-For", "") if trusted else ""
            if forwarded:
                candidate = forwarded.split(",")[-1].strip()
                try:
                    return str(ipaddress.ip_address(candidate))
                except ValueError:
                    pass
        return peer

    # -- /api/simulate ---------------------------------------------------
    def _simulate_rate_limited(self, ip: str) -> bool:
        """Enkel per-IP-rate-limit for /api/simulate (i minnet, 1-times vindu)."""
        limit = self.app.config.simulate_rate_limit_per_hour
        if limit <= 0:
            return False
        now = time.time()
        self.app.prune_rate_state(now)
        with self.app.rate_lock:
            hits = [t for t in self.app.simulate_hits.get(ip, []) if now - t < 3600]
            self.app.simulate_hits[ip] = hits
            if len(hits) >= limit:
                return True
            hits.append(now)
            return False

    def _handle_simulate(self) -> None:
        if self.app.config.simulate_require_auth and not self._current_user():
            self._send_json(401, {"error": "auth_required"})
            return
        ip = self._client_ip()
        if self._simulate_rate_limited(ip):
            try:
                self.app.db.increment_counter("security_rate_limited")
            except Exception:
                pass
            self._send_json(
                429,
                {"error": "rate_limited", "retry_after_s": 3600},
                extra_headers={"Retry-After": "3600"},
            )
            return
        body = self._read_body(max_bytes=self.app.config.max_body_bytes)
        if body is None:
            return
        if not self._content_type_is("application/json"):
            self._send_json(415, {"error": "content_type_must_be_application_json"})
            return
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "invalid_json"})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "body_must_be_object"})
            return
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            self._send_json(400, {"error": "message_required"})
            return
        if len(message) > self.app.config.max_message_chars:
            self._send_json(400, {"error": "message_too_long"})
            return
        conversation_id = payload.get("conversation_id")
        if conversation_id is not None and (
            not isinstance(conversation_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", conversation_id)
        ):
            self._send_json(400, {"error": "invalid_conversation_id"})
            return
        # Klienten kan ikke velge en global kontekstnøkkel. Adminbrukeren (eller
        # anonym lokal testmodus) navnerommer conversation_id.
        user = self._current_user()
        conversation_key = None
        if conversation_id:
            conversation_key = f"api:{user or 'anonymous'}:{conversation_id}"
        trace = self.app.pipeline.run(
            message.strip(),
            channel="api",
            conversation_key=conversation_key,
        )
        self._send_json(200, trace)

    # -- admin -----------------------------------------------------------
    def _handle_admin_index(self) -> None:
        user = self._current_user()
        if user:
            self._redirect("/admin/health")
            return
        csrf = auth.sign_csrf(self.app.config.session_secret)
        self._set_cookie(
            self.app.config.csrf_cookie,
            csrf,
            max_age=3600,
            http_only=True,
            secure=self.app.config.cookie_secure,
        )
        self._send_html(200, templates.admin_login(csrf_token=csrf))

    def _login_post_rate_limited(self, ip: str) -> bool:
        """Begrens alle login-POSTs, også ugyldig/utløpt CSRF.

        Dette er en kortvarig ressursgrense, ikke en kontolås. Den skal ikke
        erstatte credential-lockout, og skal heller ikke gjøre utløpte skjemaer
        til en permanent utestengelse.
        """
        now = time.time()
        self.app.prune_rate_state(now)
        with self.app.rate_lock:
            hits = [t for t in self.app.login_posts.get(ip, [])
                    if now - t < LOGIN_POST_WINDOW_S]
            self.app.login_posts[ip] = hits
            if len(hits) >= LOGIN_POST_MAX:
                return True
            hits.append(now)
            return False

    def _handle_login(self) -> None:
        ip = self._client_ip()
        if self._login_post_rate_limited(ip):
            self._send_json(429, {"error": "login_rate_limited"})
            return
        if self._login_blocked(ip):
            self._send_json(429, {"error": "too_many_attempts"})
            return
        body = self._read_body(max_bytes=self.app.config.max_body_bytes)
        if body is None:
            return
        if not self._content_type_is("application/x-www-form-urlencoded"):
            self._send_json(415, {"error": "content_type_must_be_form"})
            return
        form = {key: values[0] for key, values in parse_qs(body.decode("utf-8", "replace")).items()}
        csrf_cookie = self._cookies().get(self.app.config.csrf_cookie, "")
        csrf_field = form.get("csrf", "")
        if not (
            csrf_cookie
            and csrf_field
            and auth.verify_csrf(self.app.config.session_secret, csrf_cookie)
            and auth.verify_csrf(self.app.config.session_secret, csrf_field)
            and csrf_cookie == csrf_field
        ):
            self._send_json(400, {"error": "invalid_csrf"})
            return
        username = (form.get("username") or "").strip()
        password = form.get("password") or ""
        password_ok = auth.verify_password(password, self.app.config.admin_password_hash)
        user_ok = username == self.app.config.admin_user
        if not (password_ok and user_ok):
            self._record_login_failure(ip)
            csrf = auth.sign_csrf(self.app.config.session_secret)
            self._set_cookie(self.app.config.csrf_cookie, csrf, max_age=3600,
                             http_only=True, secure=self.app.config.cookie_secure)
            self._send_html(401, templates.admin_login(csrf_token=csrf, error="Feil bruker eller passord."))
            return
        with self.app.rate_lock:
            self.app.login_attempts.pop(ip, None)
        token = auth.sign_session(
            self.app.config.session_secret,
            username,
            ttl_s=self.app.config.session_ttl_s,
        )
        self._set_cookie(
            self.app.config.session_cookie,
            token,
            max_age=self.app.config.session_ttl_s,
            http_only=True,
            secure=self.app.config.cookie_secure,
        )
        log("admin_login", ip=ip)
        self._redirect("/admin/health")

    def _handle_logout(self) -> None:
        user = self._current_user()
        if not user:
            self._send_html(
                401,
                templates.error_page(401, "Ikke autorisert", "Du må logge inn for å logge ut."),
            )
            return
        if not self._content_type_is("application/x-www-form-urlencoded"):
            self._send_json(415, {"error": "content_type_must_be_form"})
            return
        body = self._read_body(max_bytes=self.app.config.max_body_bytes)
        if body is None:
            return
        form = {key: values[0] for key, values in parse_qs(body.decode("utf-8", "replace")).items()}
        csrf_cookie = self._cookies().get(self.app.config.csrf_cookie, "")
        csrf_field = form.get("csrf", "")
        if not (
            csrf_cookie and csrf_field
            and auth.verify_csrf(self.app.config.session_secret, csrf_cookie)
            and auth.verify_csrf(self.app.config.session_secret, csrf_field)
            and csrf_cookie == csrf_field
        ):
            self._send_json(400, {"error": "invalid_csrf"})
            return
        self._set_cookie(self.app.config.session_cookie, "", max_age=0,
                         http_only=True, secure=self.app.config.cookie_secure)
        log("admin_logout", user=user)
        self._redirect("/admin")

    def _handle_error_review_update(self) -> None:
        user = self._require_admin()
        if not user:
            return
        body = self._read_body(max_bytes=self.app.config.max_body_bytes)
        if body is None:
            return
        if not self._content_type_is("application/x-www-form-urlencoded"):
            self._send_json(415, {"error": "content_type_must_be_form"})
            return
        form = {
            key: values[0] for key, values in parse_qs(
                body.decode("utf-8", "replace")
            ).items()
        }
        csrf_cookie = self._cookies().get(self.app.config.csrf_cookie, "")
        csrf_field = form.get("csrf", "")
        if not (
            csrf_cookie
            and csrf_field
            and auth.verify_csrf(self.app.config.session_secret, csrf_cookie)
            and auth.verify_csrf(self.app.config.session_secret, csrf_field)
            and csrf_cookie == csrf_field
        ):
            self._send_json(400, {"error": "invalid_csrf"})
            return
        try:
            review_id = int(form.get("id", "0"))
        except ValueError:
            self._send_json(400, {"error": "invalid_id"})
            return
        status = (form.get("status") or "").strip()
        note = (form.get("note") or "").strip()[:500]
        try:
            updated = self.app.db.update_error_review(review_id, status, note)
        except ValueError:
            self._send_json(400, {"error": "invalid_status"})
            return
        if not updated:
            self._send_json(404, {"error": "review_not_found"})
            return
        self._redirect("/admin/errors")

    def _handle_admin_page(self, path: str) -> None:
        user = self._require_admin()
        if not user:
            return
        ctx = self.app
        csrf = auth.sign_csrf(self.app.config.session_secret)
        self._set_cookie(
            self.app.config.csrf_cookie,
            csrf,
            max_age=3600,
            http_only=True,
            secure=self.app.config.cookie_secure,
        )
        if path == "/admin/health":
            self._send_html(
                200,
                templates.admin_health(
                    ctx.health.snapshot(),
                    counts=ctx.db.request_counts(),
                    obs=ctx.observability.snapshot(),
                    csrf_token=csrf,
                ),
            )
        elif path == "/admin/requests":
            self._send_html(200, templates.admin_requests(ctx.db.recent_requests(50), csrf_token=csrf))
        elif path == "/admin/errors":
            self._send_html(
                200,
                templates.admin_error_reviews(
                    ctx.db.recent_error_reviews(50),
                    counts=ctx.db.error_review_counts(),
                    csrf_token=csrf,
                ),
            )
        elif path == "/admin/deliveries":
            self._send_html(200, templates.admin_deliveries(ctx.db.recent_deliveries(50), csrf_token=csrf))
        elif path == "/admin/costs":
            day = datetime.now(timezone.utc).date().isoformat()
            counters = ctx.db.get_counters(day)
            self._send_html(
                200,
                templates.admin_costs(
                    counters,
                    day=day,
                    sms_rate=ctx.config.sms_unit_cost_nok,
                    llm_rate=ctx.config.llm_unit_cost_nok,
                    csrf_token=csrf,
                ),
            )
        else:
            self._send_html(
                404,
                templates.error_page(404, "Fant ikke admin-siden", "Siden finnes ikke."),
            )

    def _require_admin(self) -> str | None:
        user = self._current_user()
        if not user:
            self._send_html(
                401,
                templates.error_page(401, "Ikke autorisert", "Logg inn for å se admin-siden."),
            )
            return None
        return user

    # -- kontaktskjema --------------------------------------------------
    _CONTACT_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")

    def _contact_rate_limited(self, ip: str) -> bool:
        self.app.prune_rate_state()
        limit = self.app.config.contact_rate_limit_per_hour
        if limit <= 0:
            return False
        now = time.time()
        with self.app.rate_lock:
            hits = [t for t in self.app.contact_hits.get(ip, []) if now - t < 3600]
            self.app.contact_hits[ip] = hits
            if len(hits) >= limit:
                return True
            hits.append(now)
            return False

    def _handle_contact(self) -> None:
        if not self._content_type_is("application/x-www-form-urlencoded"):
            self._send_html(415, templates.contact(
                self._public_context(), error="Skjemaet må sendes som et vanlig skjema."))
            return
        body = self._read_body(max_bytes=16 * 1024)
        if body is None:
            return
        form = {key: values[0] for key, values in parse_qs(
            body.decode("utf-8", "replace"), keep_blank_values=True).items()}
        public = self._public_context()
        name = (form.get("name") or "").strip()
        email = (form.get("email") or "").strip()
        message = (form.get("message") or "").strip()
        consent = (form.get("consent") or "").strip()
        values = {"name": name[:100], "email": email[:200]}
        if form.get("website"):
            # Honningkrukke: lat som suksess uten å sende.
            self._redirect("/kontakt?sendt=1")
            return
        error = None
        if not email:
            error = "Du må oppgi en e-postadresse."
        elif len(email) > 200 or not self._CONTACT_EMAIL_RE.match(email):
            error = "E-postadressen ser ikke riktig ut."
        elif not message:
            error = "Du må skrive en melding."
        elif len(message) > 4000:
            error = "Meldingen er for lang (maks 4000 tegn)."
        elif len(name) > 100:
            error = "Navnet er for langt (maks 100 tegn)."
        elif consent not in {"1", "on", "true"}:
            error = "Du må bekrefte at du har lest personvernserklæringen."
        if error:
            self._send_html(400, templates.contact(public, error=error, values=values))
            return
        ip = self._client_ip()
        if self._contact_rate_limited(ip):
            self._send_html(429, templates.contact(
                public, error="For mange meldinger. Prøv igjen senere.", values=values))
            return
        if not self.app.config.contact_form_ready:
            self._send_html(503, templates.contact(
                public, error="Kontaktskjemaet er ikke aktivert ennå. Send e-post direkte.",
                values=values))
            return
        try:
            send_contact_email(self.app.config, name=name, email=email, message=message)
        except ContactNotConfigured:
            self._send_html(503, templates.contact(
                public, error="Kontaktskjemaet er ikke aktivert ennå. Send e-post direkte.",
                values=values))
            return
        except ContactSendError:
            self._send_html(502, templates.contact(
                public, error="Meldingen kunne ikke sendes akkurat nå. Prøv igjen senere.",
                values=values))
            return
        log("contact_form_submitted")
        self._redirect("/kontakt?sendt=1")

    # -- inMobile-webhook ------------------------------------------------
    def _handle_inmobile_webhook(self) -> None:
        config = self.app.config
        if not config.inmobile_webhook_enabled:
            self._send_json(503, {"error": "inmobile_webhook_not_enabled"})
            return
        body = self._read_body(max_bytes=INMOBILE_WEBHOOK_MAX_BODY)
        if body is None:
            return
        adapter = self.app.sms_adapter
        verification = adapter.verify_inbound(dict(self.headers.items()), body)
        if not verification.accepted or verification.inbound is None:
            # Adapteren logger den leverandørspesifikke årsaken.
            self._send_json(403, {"error": "invalid_signature"})
            return
        inbound = verification.inbound
        request_id = inbound.request_id
        if not adapter.claim_inbound(inbound):
            # Fullførte/pågående duplikater avvises med 409. Leverandørkontrakten
            # for duplicate/retry må dokumenteres før dette eventuelt endres.
            self._send_json(409, {"error": "duplicate_request"})
            return
        if not (inbound.message and inbound.sender):
            adapter.mark_inbound(inbound, "ignored")
            self._send_json(200, {"status": "ignored"})
            return
        message = inbound.message
        if len(message) > config.max_message_chars:
            message = message[: config.max_message_chars]
        pseudonym = pseudonymize(config.pseudonym_salt, inbound.sender)
        day = datetime.now(timezone.utc).date().isoformat()
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        accepted, reason = self.app.db.reserve_inbound(
            pseudonym=pseudonym,
            idempotency_key=f"inbound:{adapter.name}:{request_id}",
            daily_limit=config.inbound_daily_limit,
            rate_limit=config.inbound_rate_limit_per_hour,
            day=day, since_iso=since, allow_retry=True,
        )
        if not accepted:
            adapter.mark_inbound(
                inbound,
                "rate_limited" if reason == "rate_limit_reached" else "ignored",
            )
            self.app.db.increment_counter("inbound_rate_limited")
            log("webhook_inbound_rate_limited", reason=reason)
            self._send_json(200, {"status": "suppressed", "reason": reason})
            return
        try:
            trace = self.app.pipeline.run(
                message, pseudonym=pseudonym, channel="sms",
                conversation_key=pseudonym,
            )
            reply_text = (trace.get("sms") or {}).get("text") or ""
            log("inmobile_processed", request_id=request_id,
                result_type=trace.get("result_type"))
            if reply_text:
                result = adapter.send(
                    inbound.sender, reply_text, pseudonym=pseudonym,
                    idempotency_key=f"outbound:{adapter.name}:{request_id}",
                    request_id=trace.get("request_id"),
                )
                log("inmobile_reply", sent=result.sent, suppressed=result.suppressed,
                    reason=result.reason)
                if not result.sent and not result.suppressed:
                    if result.reason.startswith("http_4"):
                        adapter.mark_inbound(inbound, "failed")
                        self._send_json(502, {"error": "send_failed", "reason": result.reason})
                    else:
                        adapter.mark_inbound(inbound, "unknown")
                        self._send_json(200, {"status": "unknown_delivery"})
                    return
            adapter.mark_inbound(inbound, "completed")
            self._send_json(200, {"status": "received"})
        except Exception as exc:
            adapter.mark_inbound(inbound, "failed")
            log("inmobile_processing_failed", request_id=request_id,
                error=type(exc).__name__)
            self._send_json(500, {"error": "processing_failed"})

    # -- hjelpere --------------------------------------------------------
    def _current_user(self) -> str | None:
        token = self._cookies().get(self.app.config.session_cookie, "")
        return auth.verify_session(self.app.config.session_secret, token)

    def _cookies(self) -> dict[str, str]:
        cookies: dict[str, str] = {}
        header = self.headers.get("Cookie", "")
        for part in header.split(";"):
            if "=" in part:
                key, _, value = part.strip().partition("=")
                cookies[key] = value
        return cookies

    def _set_cookie(
        self,
        name: str,
        value: str,
        *,
        max_age: int,
        http_only: bool = True,
        secure: bool = False,
    ) -> None:
        parts = [f"{name}={value}", "Path=/", f"Max-Age={int(max_age)}", "SameSite=Lax"]
        if http_only:
            parts.append("HttpOnly")
        if secure:
            parts.append("Secure")
        self._set_cookies.append("; ".join(parts))

    def _login_blocked(self, ip: str) -> bool:
        now = time.time()
        self.app.prune_rate_state(now)
        with self.app.rate_lock:
            blocked_until = self.app.login_blocked.get(ip)
            if blocked_until is None:
                return False
            if blocked_until > now:
                return True
            self.app.login_blocked.pop(ip, None)
            return False

    def _record_login_failure(self, ip: str) -> None:
        now = time.time()
        self.app.prune_rate_state(now)
        with self.app.rate_lock:
            attempts = self.app.login_attempts.setdefault(ip, [])
            attempts.append(now)
            self.app.login_attempts[ip] = [t for t in attempts if now - t < LOGIN_WINDOW_S]
            if len(self.app.login_attempts[ip]) >= LOGIN_MAX_ATTEMPTS:
                self.app.login_blocked[ip] = now + LOGIN_BLOCK_S
                log("admin_login_blocked", ip=ip)

    def _content_type_is(self, expected: str) -> bool:
        raw = self.headers.get("Content-Type", "")
        return raw.split(";")[0].strip().lower() == expected

    def _read_body(self, *, max_bytes: int) -> bytes | None:
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            self._send_json(411, {"error": "content_length_required"})
            return None
        try:
            length = int(length_header)
        except ValueError:
            self._send_json(400, {"error": "invalid_content_length"})
            return None
        if length < 0:
            self._send_json(400, {"error": "invalid_content_length"})
            return None
        if length > max_bytes:
            self._send_json(413, {"error": "request_body_too_large"})
            return None
        try:
            return self.rfile.read(length)
        except (TimeoutError, OSError):
            self._send_json(408, {"error": "request_timeout"})
            return None

    # -- responshjelpere -------------------------------------------------
    def _send_json(
        self, status: int, payload: dict, *, extra_headers: dict | None = None
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self._send_raw(
            status,
            body,
            "application/json; charset=utf-8",
            no_store=True,
            extra_headers=extra_headers,
        )

    def _public_context(self) -> dict:
        config = self.app.config
        number = (config.public_sms_number or "").strip()
        digits = "".join(ch for ch in number if ch.isdigit())
        valid = len(digits) >= 6
        return {
            "sms_number": number,
            "sms_digits": digits,
            "sms_enabled": bool(config.public_sms_enabled and valid),
            "sms_configured": valid,
            "contact_email": (config.public_contact_email or "").strip(),
            "contact_form_ready": bool(config.contact_form_ready),
            "status_notice": (config.status_notice or "").strip(),
            "matomo_enabled": bool(config.public_matomo_enabled),
            "matomo_url": (config.public_matomo_url or "").strip(),
            "matomo_site_id": (config.public_matomo_site_id or "1").strip(),
        }

    def _send_html(self, status: int, html: str) -> None:
        self._send_raw(status, html.encode("utf-8"), "text/html; charset=utf-8", no_store=True)

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self._send_raw(status, body, content_type)

    def _send_raw(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        no_store: bool = False,
        extra_headers: dict | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.send_header("X-Request-Id", getattr(self, "_request_id", ""))
        self.send_header("X-Build-Sha", self.app.config.build_sha)
        if no_store:
            self.send_header("Cache-Control", "no-store")
        for cookie in getattr(self, "_set_cookies", []):
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        for cookie in getattr(self, "_set_cookies", []):
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _method_not_allowed(self) -> None:
        body = b'{"error":"method_not_allowed"}'
        self._send_raw(405, body, "application/json; charset=utf-8",
                       extra_headers={"Allow": "GET, POST"})
