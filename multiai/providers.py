from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any


DEFAULT_BASE_URL = "https://ollama.com/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
CLINE_BASE_URL = "https://api.cline.bot/api/v1"

# ClinePass (Annual $79.92/yr) — alle Open-Weights-Modelle inkludiert, 0 Credits pro Call.
# Model-IDs mit 'cline-pass/' Prefix routen durch die Flatrate, nicht durch usage-billing.
# Fallback (bare Ollama names): Ollama Cloud.
CLINE_PASS_MODELS = frozenset({
    "cline-pass/glm-5.2",
    "cline-pass/kimi-k2.7-code",
    "cline-pass/kimi-k2.6",
    "cline-pass/deepseek-v4-pro",
    "cline-pass/deepseek-v4-flash",
    "cline-pass/minimax-m3",
    "cline-pass/mimo-v2.5",
    "cline-pass/mimo-v2.5-pro",
    "cline-pass/qwen3.7-max",
    "cline-pass/qwen3.7-plus",
})

# ClinePass-Modelle sind Flatrate ($79.92/yr, 0 Credits pro Call).
# Non-ClinePass-Modelle (usage-billing) kosten Credits und werden NICHT mehr verwendet.
# Modelle, die Cline NICHT bedienen kann (model not found / inference failed).
# Diese gehen direkt an OpenRouter oder Ollama.
CLINE_BLOCKED_MODELS = frozenset({
    "anthropic/claude-sonnet-4-6",
    "anthropic/claude-sonnet-4-20250514",
    "anthropic/claude-opus-4-1",
    "anthropic/claude-opus-4-20250514",
    "anthropic/claude-3-7-sonnet",
    "anthropic/claude-3-5-sonnet-20241022",
    "x-ai/grok-3",
    "x-ai/grok-3-mini",
    "x-ai/grok-4",
    "google/gemini-2.0-flash",
    "qwen/qwen-2.5-coder-32b",
    "qwen/qwen3-coder-480b",
    "moonshot/kimi-k2",
})

# Fallback: cline-pass/* → OpenRouter-Modellname (nur wenn ClinePass UND Ollama beide down).
_CLINEPASS_TO_OPENROUTER = {
    "cline-pass/glm-5.2": "z-ai/glm-5.2",
    "cline-pass/kimi-k2.7-code": "moonshotai/kimi-k2.7-code",
    "cline-pass/kimi-k2.6": "moonshotai/kimi-k2.6",
    "cline-pass/deepseek-v4-pro": "deepseek/deepseek-v4-pro",
    "cline-pass/deepseek-v4-flash": "deepseek/deepseek-v4-flash",
    "cline-pass/minimax-m3": "minimax/minimax-m3",
    "cline-pass/qwen3.7-max": "qwen/qwen3.7-max",
    "cline-pass/qwen3.7-plus": "qwen/qwen3.7-plus",
}

# Transiente HTTP-Codes, bei denen ein Retry mit Backoff sinnvoll ist.
TRANSIENT_HTTP = frozenset({429, 502, 503, 504, 529})
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_S = 2.0
DEFAULT_BACKOFF_CAP_S = 30.0


class ProviderError(Exception):
    """Fehler bei der Kommunikation mit einem (OpenAI-kompatiblen) Cloud-Provider."""

    def __init__(self, model: str, detail: str, *, status: int | None = None, transient: bool = False):
        self.model = model
        self.detail = detail
        self.status = status
        self.transient = transient
        super().__init__(f"Provider-Fehler fuer Modell '{model}': {detail}")


class ThinkingModelBudgetError(ProviderError):
    """Thinking-Modell hat Token-Budget fuer Reasoning verbraucht, content ist leer.

    Tritt bei Modellen wie kimi-k2.7-code, glm-5.2 etc. auf, die ein 'reasoning'-Feld
    zurueckgeben. Das Reasoning verbraucht das max_tokens-Budget; bei zu niedrigem
    max_tokens bleibt content leer, obwohl finish_reason='stop' ist.
    """

    def __init__(self, model: str, reasoning_chars: int, max_tokens_used: int):
        self.reasoning_chars = reasoning_chars
        self.max_tokens_used = max_tokens_used
        super().__init__(
            model,
            f"Thinking-Modell: {reasoning_chars} chars Reasoning bei max_tokens={max_tokens_used}, content leer",
            transient=False,
        )


class OllamaCloudProvider:
    """OpenAI-kompatibler Provider fuer Ollama Cloud mit Retry/Backoff bei transienten Fehlern."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE_S,
        backoff_cap: float = DEFAULT_BACKOFF_CAP_S,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or _load_ollama_key()
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap

    # Zusaetzliche HTTP-Header (Subklassen koennen ueberschreiben, z.B. OpenRouter-Ranking).
    def _extra_headers(self) -> dict[str, str]:
        return {}

    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        timeout: float = 60,
        extra_body: dict[str, Any] | None = None,
        thinking_retry_cap: int = 65536,
    ) -> str:
        """Sendet einen Chat-Completion-Request und gibt den Content zurueck.

        Ollama Cloud ist Flatrate ($0/Call). max_tokens hochsetzen kostet nichts.
        Thinking-Modelle (kimi-k2.7-code, glm-5.2 etc.) verbrauchen max_tokens fuer
        internes Reasoning (10.000-30.000+ chars). Default 16384 reicht fuer die
        meisten Prompts. Falls Reasoning trotzdem das Budget sprengt, retryt
        complete() automatisch mit 4x max_tokens bis thinking_retry_cap.
        """
        url = f"{self.base_url}/chat/completions"
        current_max_tokens = max_tokens

        while True:
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "stream": False,
            }
            # max_tokens nur senden wenn > 0 (max_tokens=0 signalisiert:
            # ClineProvider hat max_completion_tokens im extra_body gesetzt,
            # NIE max_tokens UND max_completion_tokens gleichzeitig senden)
            if current_max_tokens > 0:
                payload["max_tokens"] = current_max_tokens
            if extra_body:
                payload.update(extra_body)

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            headers.update(self._extra_headers())

            try:
                return self._post_with_retry(url, payload, headers, timeout)
            except ThinkingModelBudgetError:
                # Retry mit 4x max_tokens, bis Cap erreicht
                # Bei max_tokens=0 (ClinePass mit max_completion_tokens im extra_body):
                # extra_body.max_completion_tokens hochsetzen, nicht current_max_tokens
                if current_max_tokens > 0:
                    if current_max_tokens >= thinking_retry_cap:
                        raise
                    current_max_tokens = min(current_max_tokens * 4, thinking_retry_cap)
                else:
                    # ClinePass-Pfad: max_completion_tokens im extra_body vergroessern
                    _mct = extra_body.get("max_completion_tokens", 0) if extra_body else 0
                    if _mct >= thinking_retry_cap:
                        raise
                    _mct = min(_mct * 4 if _mct > 0 else 16384, thinking_retry_cap)
                    if extra_body:
                        extra_body["max_completion_tokens"] = _mct
                continue
            except ProviderError as e:
                # 400 + extra_body -> einmal ohne extra_body wiederholen (z.B. reasoning_effort nicht unterstuetzt).
                if e.status == 400 and extra_body:
                    payload = {k: v for k, v in payload.items() if k not in extra_body}
                    return self._post_with_retry(url, payload, headers, timeout)
                raise

    def _post_with_retry(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> str:
        """Ruft _post auf und wiederholt bei transienten Fehlern (429/5xx/Timeout) mit exponentiellem Backoff."""
        attempt = 0
        while True:
            try:
                return self._post(url, payload, headers, timeout)
            except ProviderError as e:
                if e.transient and attempt < self.max_retries:
                    delay = min(self.backoff_cap, self.backoff_base * (2 ** attempt))
                    time.sleep(delay)
                    attempt += 1
                    continue
                raise

    def _post(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> str:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise ProviderError(
                payload["model"],
                f"HTTP {e.code}: {e.reason}",
                status=e.code,
                transient=e.code in TRANSIENT_HTTP,
            ) from e
        except urllib.error.URLError as e:
            # urllib wrappt Socket-Timeouts/Verbindungsfehler in URLError -> als transient behandeln.
            if isinstance(e.reason, TimeoutError):
                raise ProviderError(payload["model"], "Timeout", transient=True) from e
            raise ProviderError(payload["model"], f"URL-Fehler: {e.reason}", transient=True) from e
        except TimeoutError as e:
            raise ProviderError(payload["model"], "Timeout", transient=True) from e
        except json.JSONDecodeError as e:
            raise ProviderError(payload["model"], f"JSON-Fehler: {e}") from e

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(payload["model"], f"Unerwartetes Antwortformat: {e}") from e

        if not content:
            # Thinking-Modell? Reasoning-Field pruefen. Wenn Reasoning vorhanden ist,
            # hat das Modell das Token-Budget fuer Reasoning verbraucht, nicht content.
            # ThinkingModelBudgetError triggert automatischen Retry mit hoeherem max_tokens.
            message = body.get("choices", [{}])[0].get("message", {})
            reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
            if reasoning:
                raise ThinkingModelBudgetError(
                    payload["model"],
                    reasoning_chars=len(reasoning),
                    max_tokens_used=payload.get("max_tokens", 0),
                )
            raise ProviderError(payload["model"], "Leerer Content in Antwort")

        return content


class OpenRouterProvider(OllamaCloudProvider):
    """OpenAI-kompatibler Provider fuer OpenRouter (pay-per-token).

    Erbt Retry/Backoff + Antwort-Parsing von OllamaCloudProvider; nur Endpoint, Key und
    optionale Ranking-Header unterscheiden sich. Modellnamen im OpenRouter-Stil 'anbieter/modell'
    (z.B. 'google/gemini-3.1-pro-preview').

    max_tokens ist ein Deckel, kein Kontingent. OpenRouter rechnet nach tatsaechlich
    generierten Tokens. Ein hoeherer Deckel kostet nichts wenn das Modell frueher stoppt.
    Daher gleiche Defaults wie OllamaCloudProvider (16384 / 65536).
    """

    def __init__(self, base_url: str = OPENROUTER_BASE_URL, api_key: str | None = None, **kw):
        super().__init__(base_url=base_url, api_key=api_key or _load_openrouter_key(), **kw)

    def _extra_headers(self) -> dict[str, str]:
        # Optionale OpenRouter-Ranking-Header (schaden nie, helfen bei Attribution).
        return {
            "HTTP-Referer": "https://github.com/roman/skill-multiai",
            "X-Title": "multiai",
        }


class ClineProvider(OllamaCloudProvider):
    """ClinePass Flatrate Provider ($79.92/yr, 0 Credits pro Call).

    ClinePass ist ein separater Provider von Cline (usage-billing). Modell-IDs
    verwenden 'cline-pass/' Prefix (z.B. 'cline-pass/glm-5.2'). Der Endpoint ist
    derselbe (https://api.cline.bot/api/v1), aber das Routing bestimmt der model-Name.

    ClinePass-Quirks (aus GitHub Issue #3833):
    1. maxTokensField: 'max_completion_tokens' statt 'max_tokens' — sonst zaehlt
       reasoning gegen das Budget und content bleibt leer.
    2. reasoningContentField: 'reasoning' (nicht 'reasoning_content').
    3. reasoning_effort 'max' gibt HTTP 500 — muss 'xhigh' sein.
    4. Kein /models Endpoint — Modelle muessen hardcodiert werden (CLINE_PASS_MODELS).

    Erbt Retry/Backoff von OllamaCloudProvider; Antwort-Parsing wird ueberschrieben da Cline
    die OpenAI-Response in {'data': {'choices': [...]}} wrappt.
    """

    def __init__(self, base_url: str = CLINE_BASE_URL, api_key: str | None = None, **kw):
        super().__init__(base_url=base_url, api_key=api_key or _load_cline_key(), **kw)

    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        timeout: float = 60,
        extra_body: dict[str, Any] | None = None,
        thinking_retry_cap: int = 65536,
    ) -> str:
        """ClinePass verwendet max_completion_tokens statt max_tokens.

        Fuer cline-pass/* Modelle wird 'max_tokens' im Payload durch 'max_completion_tokens'
        ersetzt. Alles andere bleibt gleich (Retry/Backoff, Thinking-Model handling).
        """
        # ClinePass-Quirk: max_completion_tokens statt max_tokens
        # Pitfall #3: NIE max_tokens UND max_completion_tokens gleichzeitig senden.
        # Setze max_tokens=0 → OllamaCloudProvider.complete() lässt max_tokens weg.
        if model.startswith("cline-pass/"):
            extra_body = dict(extra_body or {})
            # Quirk #1: max_completion_tokens statt max_tokens (NICHT beides)
            extra_body.setdefault("max_completion_tokens", max_tokens)
            max_tokens = 0  # Signal: nicht als max_tokens senden
            # Quirk #3: reasoning_effort "max" gibt HTTP 500 — muss "xhigh" sein
            if "reasoning_effort" in extra_body and extra_body["reasoning_effort"] == "max":
                extra_body["reasoning_effort"] = "xhigh"

        return super().complete(
            model,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            extra_body=extra_body,
            thinking_retry_cap=thinking_retry_cap,
        )

    def _post(self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> str:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise ProviderError(
                payload["model"],
                f"HTTP {e.code}: {e.reason}",
                status=e.code,
                transient=e.code in TRANSIENT_HTTP,
            ) from e
        except urllib.error.URLError as e:
            if isinstance(e.reason, TimeoutError):
                raise ProviderError(payload["model"], "Timeout", transient=True) from e
            raise ProviderError(payload["model"], f"URL-Fehler: {e.reason}", transient=True) from e
        except TimeoutError as e:
            raise ProviderError(payload["model"], "Timeout", transient=True) from e
        except json.JSONDecodeError as e:
            raise ProviderError(payload["model"], f"JSON-Fehler: {e}") from e

        # Cline wrappt die OpenAI-Antwort in {"data": {...}}
        choices = body.get("data", {}).get("choices") if isinstance(body.get("data"), dict) else None
        if not choices:
            choices = body.get("choices", [])
        if not choices:
            raise ProviderError(payload["model"], f"Unerwartetes Antwortformat (keine choices): {list(body.keys())}")

        try:
            content = choices[0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(payload["model"], f"Unerwartetes Antwortformat: {e}") from e

        if not content:
            # Thinking-Modell? Gleiche Logik wie OllamaCloudProvider._post.
            # Cline proxied die gleichen Modelle, Reasoning-Field kann auftreten.
            message = choices[0].get("message", {})
            reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
            if reasoning:
                raise ThinkingModelBudgetError(
                    payload["model"],
                    reasoning_chars=len(reasoning),
                    max_tokens_used=payload.get("max_tokens", 0),
                )
            raise ProviderError(payload["model"], "Leerer Content in Antwort")

        return content


class RoutingProvider:
    """2-Tier Routing: ClinePass (Flatrate $0) → Ollama Cloud (Flatrate $0).

    Prioritaet (Roman 2026-07-02):
    1. ClinePass — alle cline-pass/* Modelle (Flatrate, $79.92/yr, 0 Credits pro Call).
       Inkludiert: GLM-5.2, Kimi K2.7 Code, DeepSeek V4 Pro, MiniMax M3, MiMo V2.5 Pro, Qwen3.7-Max.
    2. Ollama Cloud (Flatrate, $0) — fuer bare names ohne '/' oder ClinePass-Fallback.

    Routing-Logik:
    - 'cline-pass/' im Modellnamen + nicht blocked: ClinePass (immer, kein Cost-Check noetig)
    - Bare name: Ollama Cloud, bei Fallback cline-pass/<bare> (ClinePass) bzw. OpenRouter
    - CLINE_BLOCKED_MODELS (anthropic/*, x-ai/*): direkt Ollama/OpenRouter

    Gleiche complete()-Signatur wie OllamaCloudProvider -> fan_out/aggregate bleiben unveraendert.
    Provider werden lazy instanziiert (Keys nur noetig, wenn der Tier genutzt wird).
    """

    def __init__(
        self,
        ollama: OllamaCloudProvider | None = None,
        openrouter: OpenRouterProvider | None = None,
        cline: ClineProvider | None = None,
        ollama_base_url: str = DEFAULT_BASE_URL,
    ):
        self._ollama = ollama or OllamaCloudProvider(base_url=ollama_base_url)
        self._openrouter = openrouter
        self._cline = cline

    def _get_cline(self) -> ClineProvider:
        if self._cline is None:
            self._cline = ClineProvider()
        return self._cline

    def _get_openrouter(self) -> OpenRouterProvider:
        if self._openrouter is None:
            self._openrouter = OpenRouterProvider()
        return self._openrouter

    def complete(self, model: str, messages: list[dict[str, str]], **kwargs) -> str:
        """Try ClinePass → Ollama → OpenRouter. Erster Erfolg gewinnt."""
        # Tier 1: ClinePass — fuer cline-pass/* Modelle (Flatrate, 0 Credits)
        is_blocked = model in CLINE_BLOCKED_MODELS or model.removeprefix("cline-pass/") in CLINE_BLOCKED_MODELS
        if model.startswith("cline-pass/") and not is_blocked:
            try:
                return self._get_cline().complete(model, messages, **kwargs)
            except ProviderError:
                pass  # fallback zu Tier 2/3

        # Tier 2: Ollama Cloud (fuer bare names) mit Fallback auf ClinePass/OpenRouter
        if "/" not in model:
            try:
                return self._ollama.complete(model, messages, **kwargs)
            except ProviderError:
                pass
            # Fallback 1: cline-pass/<bare> falls in CLINE_PASS_MODELS
            cline_model = f"cline-pass/{model}"
            if cline_model in CLINE_PASS_MODELS:
                try:
                    return self._get_cline().complete(cline_model, messages, **kwargs)
                except ProviderError:
                    pass
            # Fallback 2: OpenRouter falls Mapping existiert
            or_model = _CLINEPASS_TO_OPENROUTER.get(cline_model)
            if or_model:
                return self._get_openrouter().complete(or_model, messages, **kwargs)
            raise ProviderError(model, "Alle Provider-Tiers fehlgeschlagen")

        # Tier 3: OpenRouter (fuer '/'-Modelle, fallback nach ClinePass-Fehler)
        if "/" in model and not model.startswith("cline-pass/"):
            return self._get_openrouter().complete(model, messages, **kwargs)

        # cline-pass/* Modelle: ClinePass durchgefallen → Ollama mit bare name
        if model.startswith("cline-pass/"):
            bare = model.removeprefix("cline-pass/")
            try:
                return self._ollama.complete(bare, messages, **kwargs)
            except ProviderError:
                pass
            # Letzter Ausweg: OpenRouter mit z-ai/ oder moonshotai/ Prefix
            or_model = _CLINEPASS_TO_OPENROUTER.get(model)
            if or_model:
                return self._get_openrouter().complete(or_model, messages, **kwargs)

        raise ProviderError(model, "Alle Provider-Tiers fehlgeschlagen")


def _load_ollama_key() -> str:
    """Laedt den Ollama-API-Key aus Umgebung oder Dotenv-Dateien."""
    return _load_key("OLLAMA_API_KEY")


def _load_openrouter_key() -> str:
    """Laedt den OpenRouter-API-Key aus Umgebung oder Dotenv-Dateien."""
    return _load_key("OPENROUTER_API_KEY")


def _load_cline_key() -> str:
    """Laedt den Cline-API-Key aus Umgebung oder Dotenv-Dateien."""
    return _load_key("CLINE_API_KEY")


def _load_key(key_name: str) -> str:
    env_key = os.environ.get(key_name)
    if env_key:
        return env_key

    candidates = [
        os.path.expanduser("~/.env"),
        os.path.expanduser("~/.hermes/.env"),
    ]
    for path in candidates:
        key = _parse_env_file(path, key_name)
        if key:
            return key

    raise ProviderError("", f"{key_name} nicht gefunden")


def _parse_env_file(path: str, key_name: str = "OLLAMA_API_KEY") -> str | None:
    """Parst eine .env-Datei nach key_name (mit/ohne export, mit/ohne Quotes)."""
    if not os.path.isfile(path):
        return None
    prefix = f"{key_name}="
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                line = re.sub(r"^export\s+", "", line)
                if line.startswith(prefix):
                    value = line[len(prefix):].strip()
                    if (value.startswith('"') and value.endswith('"')) or (
                        value.startswith("'") and value.endswith("'")
                    ):
                        value = value[1:-1]
                    return value
    except OSError:
        return None
    return None
