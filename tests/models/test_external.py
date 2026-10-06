import pytest

from techbookocr.config import ModelSpec, ServerConfig
from techbookocr.models.registry import make_adapter
from techbookocr.models.server import ExternalServer, ModelServer, ServerError, api_key, server_for

REMOTE = ModelSpec(key="remote", adapter="qwen_arbiter", image="", model="qwen3.8-27b",
                   base_url="http://10.0.0.5:8000/v1/")
LOCAL = ModelSpec(key="dots", adapter="dots", image="vllm/vllm-openai:v0.30.0", model="dots")


def test_server_for_picks_kind():
    assert isinstance(server_for(REMOTE, ServerConfig()), ExternalServer)
    assert isinstance(server_for(LOCAL, ServerConfig()), ModelServer)


def test_external_probe_and_no_docker():
    urls = []
    with ExternalServer(REMOTE, probe=lambda u: urls.append(u) or True) as s:
        assert s.base_url == "http://10.0.0.5:8000/v1"
    assert urls == ["http://10.0.0.5:8000/v1/models"]
    with pytest.raises(ServerError, match="not reachable"):
        with ExternalServer(REMOTE, probe=lambda u: False):
            pass


def test_api_key_from_env(monkeypatch):
    spec = ModelSpec(key="r", adapter="qwen_arbiter", image="", model="m", base_url="http://x/v1",
                     api_key_env="TECHBOOKOCR_TEST_KEY")
    monkeypatch.delenv("TECHBOOKOCR_TEST_KEY", raising=False)
    with pytest.raises(ServerError, match="TECHBOOKOCR_TEST_KEY"):
        api_key(spec)
    monkeypatch.setenv("TECHBOOKOCR_TEST_KEY", "secret")
    assert api_key(spec) == "secret" and api_key(LOCAL) == "EMPTY"
    assert make_adapter(spec, "http://x/v1").client.api_key == "secret"


def test_server_for_external_never_calls_subprocess(monkeypatch):
    """External spec: server_for returns ExternalServer without calling subprocess."""
    import subprocess
    from techbookocr.models import server as server_module

    called = []
    original_run = subprocess.run
    def track_run(*args, **kwargs):
        called.append(args[0] if args else None)
        return original_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", track_run)

    # Monkeypatch _http_ok to simulate endpoint availability
    monkeypatch.setattr(server_module, "_http_ok", lambda url, headers=None: True)

    with server_for(REMOTE, ServerConfig()) as s:
        assert isinstance(s, ExternalServer)
        assert s.base_url == "http://10.0.0.5:8000/v1"

    assert not called, f"subprocess.run was called: {called}"
