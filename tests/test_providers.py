from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from multiai.providers import OllamaCloudProvider, ProviderError, RoutingProvider


def _make_response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def test_provider_construct_with_base_url():
    # Regression: run_multiai konstruiert OllamaCloudProvider(base_url=...).
    p = OllamaCloudProvider(base_url="https://ollama.com/v1", api_key="k")
    assert p.base_url == "https://ollama.com/v1"
    assert p.api_key == "k"


def test_provider_base_url_trailing_slash_stripped():
    p = OllamaCloudProvider(base_url="https://example.test/v1/", api_key="k")
    assert p.base_url == "https://example.test/v1"


def test_complete_parses_content():
    provider = OllamaCloudProvider(api_key="test-key")
    with patch("urllib.request.urlopen") as mock_urlopen:
        resp = MagicMock()
        resp.read.return_value = json.dumps(_make_response("Hallo Welt")).encode()
        mock_urlopen.return_value.__enter__.return_value = resp

        result = provider.complete("glm-5.2", [{"role": "user", "content": "Hi"}])

        assert result == "Hallo Welt"
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "https://ollama.com/v1/chat/completions"
        assert req.headers["Authorization"] == "Bearer test-key"
        assert req.headers["Content-type"] == "application/json"
        body = json.loads(req.data)
        assert body["model"] == "glm-5.2"
        assert body["stream"] is False


def test_complete_provider_error_on_http_error():
    provider = OllamaCloudProvider(api_key="test-key")
    with patch("urllib.request.urlopen") as mock_urlopen:
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            url="https://ollama.com/v1/chat/completions",
            code=500, msg="Internal Server Error", hdrs=None, fp=None,
        )
        with pytest.raises(ProviderError) as exc_info:
            provider.complete("glm-5.2", [{"role": "user", "content": "Hi"}])
        assert "500" in str(exc_info.value)


def test_complete_retries_without_extra_body_on_400():
    provider = OllamaCloudProvider(api_key="test-key")
    with patch("urllib.request.urlopen") as mock_urlopen:
        from urllib.error import HTTPError

        def side_effect(req, **kwargs):
            body = json.loads(req.data)
            if "reasoning_effort" in body:
                raise HTTPError(
                    url=req.full_url, code=400, msg="Bad Request", hdrs=None, fp=None,
                )
            resp = MagicMock()
            resp.read.return_value = json.dumps(_make_response("OK ohne extra")).encode()
            cm = MagicMock()
            cm.__enter__.return_value = resp
            return cm

        mock_urlopen.side_effect = side_effect
        result = provider.complete(
            "glm-5.2", [{"role": "user", "content": "Hi"}],
            extra_body={"reasoning_effort": "xhigh"},
        )
        assert result == "OK ohne extra"
        assert mock_urlopen.call_count == 2


def _cm(content: str):
    resp = MagicMock()
    resp.read.return_value = json.dumps(_make_response(content)).encode()
    cm = MagicMock()
    cm.__enter__.return_value = resp
    return cm


def test_retry_on_429_then_success():
    from urllib.error import HTTPError

    provider = OllamaCloudProvider(api_key="test-key", max_retries=3, backoff_base=0.0)
    calls = {"n": 0}

    def side_effect(req, **kwargs):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise HTTPError(url=req.full_url, code=429, msg="Too Many Requests", hdrs=None, fp=None)
        return _cm("nach Retry")

    with patch("urllib.request.urlopen", side_effect=side_effect), \
            patch("multiai.providers.time.sleep") as mock_sleep:
        result = provider.complete("glm-5.2", [{"role": "user", "content": "Hi"}])

    assert result == "nach Retry"
    assert calls["n"] == 3          # 2x 429, dann Erfolg
    assert mock_sleep.call_count == 2


def test_retry_exhausted_on_429_raises():
    from urllib.error import HTTPError

    provider = OllamaCloudProvider(api_key="test-key", max_retries=2, backoff_base=0.0)

    def side_effect(req, **kwargs):
        raise HTTPError(url=req.full_url, code=429, msg="Too Many Requests", hdrs=None, fp=None)

    with patch("urllib.request.urlopen", side_effect=side_effect), \
            patch("multiai.providers.time.sleep") as mock_sleep:
        with pytest.raises(ProviderError) as ei:
            provider.complete("glm-5.2", [{"role": "user", "content": "Hi"}])

    assert ei.value.status == 429
    assert ei.value.transient is True
    assert mock_sleep.call_count == 2  # max_retries Sleeps, dann raise


def test_non_transient_500_not_retried():
    from urllib.error import HTTPError

    provider = OllamaCloudProvider(api_key="test-key", max_retries=3, backoff_base=0.0)
    calls = {"n": 0}

    def side_effect(req, **kwargs):
        calls["n"] += 1
        raise HTTPError(url=req.full_url, code=500, msg="Server Error", hdrs=None, fp=None)

    with patch("urllib.request.urlopen", side_effect=side_effect), \
            patch("multiai.providers.time.sleep") as mock_sleep:
        with pytest.raises(ProviderError):
            provider.complete("glm-5.2", [{"role": "user", "content": "Hi"}])

    assert calls["n"] == 1             # 500 nicht transient -> kein Retry
    assert mock_sleep.call_count == 0


class _FakeProvider:
    def __init__(self, fail=False, resp="OK"):
        self.fail = fail
        self.resp = resp
        self.calls = []

    def complete(self, model, messages, **kwargs):
        self.calls.append(model)
        if self.fail:
            raise ProviderError(model, "down")
        return self.resp


def test_routing_provider_delegates_to_ollama():
    """RoutingProvider leitet direkt an Ollama Cloud weiter."""
    ollama = _FakeProvider(fail=False, resp="Ollama OK")
    router = RoutingProvider(ollama=ollama)
    result = router.complete("glm-5.2", [{"role": "user", "content": "Hi"}])
    assert result == "Ollama OK"
    assert ollama.calls == ["glm-5.2"]


def test_routing_provider_raises_on_ollama_error():
    """RoutingProvider wirft ProviderError wenn Ollama scheitert (kein Fallback)."""
    ollama = _FakeProvider(fail=True)
    router = RoutingProvider(ollama=ollama)
    with pytest.raises(ProviderError):
        router.complete("glm-5.2", [{"role": "user", "content": "Hi"}])


def test_routing_provider_ignores_extra_kwargs():
    """RoutingProvider akzeptiert unbekannte kwargs (Rueckwaertskompatibilitaet)."""
    ollama = _FakeProvider(fail=False, resp="OK")
    # openrouter= und cline= aus altem Code werden per **_ignored ignoriert
    router = RoutingProvider(ollama=ollama, openrouter=None, cline=None)
    result = router.complete("deepseek-v4-pro", [{"role": "user", "content": "Hi"}])
    assert result == "OK"



# ── Key wird faul geladen ──────────────────────────────────────────────────

def test_missing_key_does_not_break_construction(monkeypatch):
    """Ein fehlender Key darf erst beim Call auffallen, nicht schon im Konstruktor.

    Sonst stirbt der ganze Lauf, statt dass die Sitze einzeln ausfallen und die
    Pipeline in den Degradationsmodus gehen kann.
    """
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.setattr(
        "multiai.providers._load_ollama_key",
        lambda: (_ for _ in ()).throw(ProviderError("", "OLLAMA_API_KEY nicht gefunden")),
    )
    provider = OllamaCloudProvider()          # darf nicht werfen
    with pytest.raises(ProviderError, match="OLLAMA_API_KEY nicht gefunden"):
        _ = provider.api_key


def test_explicit_key_is_used_without_lookup(monkeypatch):
    def boom():
        raise AssertionError("Key-Lookup haette nicht laufen duerfen")

    monkeypatch.setattr("multiai.providers._load_ollama_key", boom)
    assert OllamaCloudProvider(api_key="direkt").api_key == "direkt"


def test_provider_error_without_model_reads_cleanly():
    assert str(ProviderError("", "kein Key")) == "Provider-Fehler: kein Key"
    assert "Modell 'x'" in str(ProviderError("x", "kaputt"))
