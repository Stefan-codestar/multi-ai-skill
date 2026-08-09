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
        # Nicht jeder Provider-Fehler haengt an einem Modell — ein fehlender
        # API-Key etwa trifft alle gleichermassen.
        if model:
            super().__init__(f"Provider-Fehler fuer Modell '{model}': {detail}")
        else:
            super().__init__(f"Provider-Fehler: {detail}")


class ThinkingModelBudgetError(ProviderError):
    """Thinking-Modell hat Token-Budget fuer Reasoning verbraucht, content ist leer.

    Tritt bei Modellen wie glm-5.2, deepseek-v4-pro etc. auf, die ein 'reasoning'-Feld
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
        self._api_key = api_key
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap

    @property
    def api_key(self) -> str:
        """Laedt den Key beim ersten Zugriff, nicht schon im Konstruktor.

        Dadurch schlaegt ein fehlender Key als Fehler des einzelnen Sitzes durch
        und nicht als Absturz des ganzen Laufs — die Pipeline kann darauf
        reagieren (Degradationsmodus, Hinweis auf den Solo-Modus).
        """
        if self._api_key is None:
            self._api_key = self._load_key()
        return self._api_key

    def _load_key(self) -> str:
        return _load_ollama_key()

    def _extra_headers(self) -> dict[str, str]:
        return {}

    def stream_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        timeout: float = 120,
        extra_body: dict[str, Any] | None = None,
        thinking_retry_cap: int = 65536,
    ):
        """Streamt einen Chat-Completion-Request via SSE und yieldt Content-Deltas.

        Yieldt str-Chunks mit den jeweiligen Content-Deltas.
        Bei HTTP 400 mit extra_body wird automatisch ohne extra_body erneut versucht
        (z.B. reasoning_effort wird beim Streaming-Endpoint nicht unterstuetzt).

        Thinking-Model-Retry: Wenn die ersten chunks nur reasoning aber keinen
        content enthalten und der Stream mit finish_reason='stop' endet ohne
        jemals content geliefert zu haben, wird mit 4x max_tokens erneut versucht
        (analog zu complete()).
        """
        current_max_tokens = max_tokens

        while True:
            content_chunks: list[str] = []
            had_reasoning = False
            got_content = False

            for chunk in self._raw_stream(
                model, messages,
                temperature=temperature,
                max_tokens=current_max_tokens,
                timeout=timeout,
                extra_body=extra_body,
            ):
                delta_content = chunk.get("content")
                delta_reasoning = chunk.get("reasoning") or chunk.get("reasoning_content")
                if delta_reasoning:
                    had_reasoning = True
                if delta_content:
                    got_content = True
                    content_chunks.append(delta_content)
                    yield delta_content

            if got_content:
                return

            # Kein Content, aber Reasoning vorhanden -> Thinking-Model Budget-Problem
            if had_reasoning and current_max_tokens < thinking_retry_cap:
                current_max_tokens = min(current_max_tokens * 4, thinking_retry_cap)
                continue

            # Weder Content noch Reasoning -> leerer Stream, nichts zu tun
            return

    def _raw_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        timeout: float = 120,
        extra_body: dict[str, Any] | None = None,
    ):
        """Low-Level SSE-Stream. Yieldt rohe delta-dicts (nicht nur content).

        Behandelt HTTP 400 mit extra_body Fallback (wie complete()).
        """
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if extra_body:
            payload.update(extra_body)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        headers.update(self._extra_headers())

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 400 and extra_body:
                # Retry ohne extra_body (reasoning_effort etc. nicht unterstuetzt)
                payload = {k: v for k, v in payload.items() if k not in extra_body}
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                try:
                    resp = urllib.request.urlopen(req, timeout=timeout)
                except urllib.error.HTTPError as e2:
                    raise ProviderError(
                        model,
                        f"HTTP {e2.code}: {e2.reason}",
                        status=e2.code,
                        transient=e2.code in TRANSIENT_HTTP,
                    ) from e2
            else:
                raise ProviderError(
                    model,
                    f"HTTP {e.code}: {e.reason}",
                    status=e.code,
                    transient=e.code in TRANSIENT_HTTP,
                ) from e
        except urllib.error.URLError as e:
            raise ProviderError(model, f"URL-Fehler: {e.reason}", transient=True) from e
        except TimeoutError as e:
            raise ProviderError(model, "Timeout", transient=True) from e

        try:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                data_str = line[len("data:"):].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                try:
                    delta = chunk["choices"][0]["delta"]
                    yield delta
                except (KeyError, IndexError, TypeError):
                    continue
        finally:
            resp.close()

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

        Falls Reasoning das Token-Budget sprengt, retryt complete() automatisch
        mit 4x max_tokens bis thinking_retry_cap.
        """
        url = f"{self.base_url}/chat/completions"
        current_max_tokens = max_tokens

        while True:
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": current_max_tokens,
                "stream": False,
            }
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
                if current_max_tokens >= thinking_retry_cap:
                    raise
                current_max_tokens = min(current_max_tokens * 4, thinking_retry_cap)
                continue
            except ProviderError as e:
                # 400 + extra_body -> einmal ohne extra_body wiederholen
                # (z.B. reasoning_effort nicht unterstuetzt)
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
        """Ruft _post auf und wiederholt bei transienten Fehlern mit exponentiellem Backoff."""
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
    """OpenAI-kompatibler Provider fuer OpenRouter (pay-per-token, optionaler Fallback)."""

    def __init__(self, base_url: str = OPENROUTER_BASE_URL, api_key: str | None = None, **kw):
        super().__init__(base_url=base_url, api_key=api_key, **kw)

    def _load_key(self) -> str:
        return _load_openrouter_key()

    def _extra_headers(self) -> dict[str, str]:
        return {
            "HTTP-Referer": "https://github.com/skill-multiai",
            "X-Title": "multiai",
        }


class RoutingProvider:
    """Einfaches 1-Tier Routing: nur Ollama Cloud.

    Fuer Ollama Cloud Pro — kein ClinePass, kein OpenRouter-Fallback benoetigt.
    Bei Fehler eines Workers ueberspringt pipeline.py den Worker und macht weiter.
    """

    def __init__(
        self,
        ollama: OllamaCloudProvider | None = None,
        ollama_base_url: str = DEFAULT_BASE_URL,
        **_ignored,
    ):
        self._ollama = ollama or OllamaCloudProvider(base_url=ollama_base_url)

    def complete(self, model: str, messages: list[dict[str, str]], **kwargs) -> str:
        return self._ollama.complete(model, messages, **kwargs)

    def stream_complete(self, model: str, messages: list[dict[str, str]], **kwargs):
        """Streamt Content-Deltas vom underlying Ollama-Provider."""
        yield from self._ollama.stream_complete(model, messages, **kwargs)


def _load_ollama_key() -> str:
    """Laedt den Ollama-API-Key aus Umgebung oder Dotenv-Dateien."""
    return _load_key("OLLAMA_API_KEY")


def _load_openrouter_key() -> str:
    """Laedt den OpenRouter-API-Key aus Umgebung oder Dotenv-Dateien (optionaler Fallback)."""
    return _load_key("OPENROUTER_API_KEY")


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
