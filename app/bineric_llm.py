"""Bineric Qwen 235B-adapter for Østfoldbussen.

Aktiveres kun med BINERIC_ENABLED=true. Ved feil faller pipelinen tilbake til
regler – aldri automatisk til en annen leverandør. Adapteren har:
- begrenset samtidighet
- maks antall kall per minutt
- 429/5xx-backoff med Retry-After
- timeout
- daglig budsjettkontroll i databasen (mikro-USD)
"""
from __future__ import annotations

import json
import math
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone

from .llm import SYSTEM_PROMPT, LlmResult, LlmInterpreter
from .logging_setup import log
from .http_util import open_no_redirect


class BinericLlm:
    def __init__(self, config, db, http_post=None, clock=None, sleep=None):
        self.config = config
        self.db = db
        self.http_post = http_post or self._http_post
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or time.sleep
        self._semaphore = threading.Semaphore(max(1, config.bineric_max_concurrency))
        self._rate_lock = threading.Lock()
        self._calls = deque()
        self._validator = LlmInterpreter(config)

    @property
    def enabled(self) -> bool:
        return bool(
            self.config.bineric_enabled
            and self.config.bineric_api_key
            and self.config.bineric_base_url
            and self.config.bineric_model
        )

    def _rate_wait(self) -> None:
        limit = max(1, self.config.bineric_requests_per_minute)
        while True:
            with self._rate_lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] > 60:
                    self._calls.popleft()
                if len(self._calls) < limit:
                    self._calls.append(now)
                    return
                wait = max(0.05, 60 - (now - self._calls[0]) + 0.05)
            self._sleep(wait)

    def _estimate_micro(self, message: str) -> int:
        # Konservativ: 1 token per 2 tegn + maks output.
        input_tokens = math.ceil((len(SYSTEM_PROMPT) + len(message)) / 2) + 40
        return int(input_tokens * 0.22 + self.config.bineric_max_output_tokens * 0.88)

    def _reserve_budget(self, estimate_micro: int) -> bool:
        """DB-atomisk reservasjon; virker også med flere appprosesser."""
        if self.config.bineric_daily_budget_usd <= 0:
            return True
        return self.db.reserve_daily_counter(
            "bineric_cost_micro_usd",
            estimate_micro,
            int(self.config.bineric_daily_budget_usd * 1_000_000),
            day=self.clock().date().isoformat(),
        )

    def _release_budget(self, estimate_micro: int) -> None:
        self.db.adjust_daily_counter(
            "bineric_cost_micro_usd", -estimate_micro,
            day=self.clock().date().isoformat(),
        )

    def _record_cost(self, micro: int) -> None:
        if micro:
            self.db.adjust_daily_counter(
                "bineric_cost_micro_usd", micro,
                day=self.clock().date().isoformat(),
            )

    def _count(self, kind: str, amount: int = 1) -> None:
        try:
            self.db.increment_counter(kind, amount)
        except Exception:
            pass

    def interpret(self, message: str) -> LlmResult:
        if not self.enabled:
            return LlmResult(ok=False, data=None, error="bineric_disabled")
        if not isinstance(message, str) or not message.strip():
            return LlmResult(ok=False, data=None, error="empty_input")
        if len(message) > self.config.llm_max_input_chars:
            self._count("llm_failures")
            return LlmResult(ok=False, data=None, error="input_too_long")
        estimate = self._estimate_micro(message)
        if not self._reserve_budget(estimate):
            log("bineric_budget_exhausted")
            return LlmResult(ok=False, data=None, error="budget_exhausted")
        with self._semaphore:
            self._rate_wait()
            payload = {
                "model": self.config.bineric_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ],
                "temperature": 0,
                "max_completion_tokens": self.config.bineric_max_output_tokens,
                "reasoning_effort": "none",
            }
            attempts = max(0, self.config.bineric_max_retries)
            last_error = "request_failed"
            reserved_current = True
            for attempt in range(attempts + 1):
                self._count("llm_attempts")
                if attempt:
                    self._count("llm_retries")
                try:
                    data = self.http_post(payload)
                    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
                    parsed = self._parse(content)
                    usage = data.get("usage") or {}
                    input_tokens = int(usage.get("prompt_tokens", 0) or 0)
                    output_tokens = int(usage.get("completion_tokens", 0) or 0)
                    actual_micro = int(input_tokens * 0.22 + output_tokens * 0.88)
                    # Uten usage er estimatet fortsatt konservativt.
                    self._record_cost((actual_micro or estimate) - estimate)
                    self._count("llm_input_tokens", input_tokens)
                    self._count("llm_output_tokens", output_tokens)
                    self._count("llm_success")
                    return LlmResult(ok=True, data=parsed, error=None)
                except urllib.error.HTTPError as exc:
                    last_error = f"http_{exc.code}"
                    if 400 <= exc.code < 500:
                        # Definitiv avvisning (inkl. 429) er ikke fakturert;
                        # frigjør denne reservasjonen.
                        self._release_budget(estimate)
                        reserved_current = False
                        if exc.code == 429 and attempt < attempts:
                            retry_after = exc.headers.get("Retry-After") if exc.headers else None
                            try:
                                delay = float(retry_after) if retry_after else min(2 ** attempt, 8)
                            except ValueError:
                                delay = min(2 ** attempt, 8)
                            log("bineric_retry", status=exc.code, delay_s=delay)
                            self._sleep(delay)
                            if not self._reserve_budget(estimate):
                                last_error = "budget_exhausted"
                                break
                            reserved_current = True
                            continue
                    break
                except Exception as exc:
                    # Timeout/transport er tvetydig: behold reservasjonen.
                    last_error = type(exc).__name__
                    if attempt < attempts:
                        self._sleep(min(2 ** attempt, 8))
                        if not self._reserve_budget(estimate):
                            last_error = "budget_exhausted"
                            break
                        reserved_current = True
                        continue
                    break
            # 5xx/timeout/ukjent kan være fakturert og beholder reservasjonen.
            # Definitiv 4xx/429 er frigjort i grenen over.
        self._count("llm_failures")
        log("bineric_failed", reason=last_error)
        return LlmResult(ok=False, data=None, error=last_error)

    def _parse(self, content: str):
        text = (content or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        parsed = json.loads(text)
        return self._validator._validate({"choices": [{"message": {"content": json.dumps(parsed)}}]})

    def _http_post(self, payload: dict) -> dict:
        request = urllib.request.Request(
            self.config.bineric_base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.config.bineric_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "ostfoldbussen/1.0",
            },
            method="POST",
        )
        with open_no_redirect(request, timeout=self.config.bineric_timeout_s) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
