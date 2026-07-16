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


def test_bare_name_fallback_to_clinepass():
    """Bare name: Ollama scheitert -> ClinePass wird versucht."""
    ollama = _FakeProvider(fail=True)
    cline = _FakeProvider(fail=False, resp="ClinePass OK")

    router = RoutingProvider(ollama=ollama, cline=cline)
    result = router.complete("glm-5.2", [{"role": "user", "content": "Hi"}])

    assert result == "ClinePass OK"
    assert ollama.calls == ["glm-5.2"]
    assert cline.calls == ["cline-pass/glm-5.2"]


def test_bare_name_fallback_to_openrouter():
    """Bare name: Ollama und ClinePass scheitern -> OpenRouter falls Mapping."""
    ollama = _FakeProvider(fail=True)
    cline = _FakeProvider(fail=True)
    openrouter = _FakeProvider(fail=False, resp="OpenRouter OK")

    router = RoutingProvider(ollama=ollama, cline=cline, openrouter=openrouter)
    result = router.complete("glm-5.2", [{"role": "user", "content": "Hi"}])

    assert result == "OpenRouter OK"
    assert ollama.calls == ["glm-5.2"]
    assert cline.calls == ["cline-pass/glm-5.2"]
    assert openrouter.calls == ["z-ai/glm-5.2"]


def test_bare_name_no_fallback_available():
    """Bare name: Ollama scheitert, kein ClinePass/OpenRouter-Mapping -> ProviderError."""
    ollama = _FakeProvider(fail=True)
    cline = _FakeProvider(fail=False, resp="ClinePass OK")
    openrouter = _FakeProvider(fail=False, resp="OpenRouter OK")

    router = RoutingProvider(ollama=ollama, cline=cline, openrouter=openrouter)
    with pytest.raises(ProviderError) as ei:
        router.complete("nemotron-3-ultra", [{"role": "user", "content": "Hi"}])
    assert "fehlgeschlagen" in str(ei.value)
    assert ollama.calls == ["nemotron-3-ultra"]
    assert cline.calls == []
    assert openrouter.calls == []
