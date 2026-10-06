import base64
from types import SimpleNamespace

from PIL import Image

import httpx
import openai
import pytest

from techbookocr.models.errors import TransportError
from techbookocr.models.vlm import chat_image, image_to_data_url, is_looping, request_timeout


def test_data_url_roundtrip():
    url = image_to_data_url(Image.new("RGB", (10, 10), "white"))
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1])[:8] == b"\x89PNG\r\n\x1a\n"


def test_loop_detected():
    assert is_looping("Начало текста. " + "abc " * 400)
    assert is_looping("x" + "<td>12</td><td>13</td>" * 60)


def test_normal_text_not_loop():
    text = (
        "Одним из мероприятий, снижающих вероятность появления рассматриваемого дефекта, "
        "является удаление из металла вышеперечисленных составляющих. " * 3
        + "Это достигается повышением температуры металла и его выдержки в ковше."
    )
    assert not is_looping(text)


def test_legit_dash_column_not_loop():
    rows = "".join(f"<tr><td>{a}—{b}</td><td>—</td><td>—</td><td>—</td></tr>" for a, b in zip(range(100, 1300, 100), range(200, 1400, 100)))
    assert not is_looping(rows)


def test_chat_image_builds_request():
    captured = {}

    class FakeCompletions:
        def create(self, **kw):
            captured.update(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"), finish_reason="stop")])

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    text, reason = chat_image(client, "m", Image.new("RGB", (4, 4)), "Read", system="sys", max_tokens=100, extra={"top_p": 0.9})
    assert (text, reason) == ("ok", "stop")
    assert captured["model"] == "m" and captured["max_tokens"] == 100 and captured["temperature"] == 0.0
    assert captured["messages"][0] == {"role": "system", "content": "sys"}
    user = captured["messages"][1]["content"]
    assert user[0]["type"] == "image_url" and user[1] == {"type": "text", "text": "Read"}
    assert captured["extra_body"] == {"top_p": 0.9}


def test_request_timeout_scales_and_caps():
    assert request_timeout(100) == 120
    assert request_timeout(24000) == 1200
    assert request_timeout(10**6) == 1800


def test_chat_image_passes_timeout():
    captured = {}

    class C:
        def create(self, **kw):
            captured.update(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"), finish_reason="stop")])

    chat_image(SimpleNamespace(chat=SimpleNamespace(completions=C())), "m", Image.new("RGB", (4, 4)), "p", max_tokens=24000)
    assert captured["timeout"] == 1200


@pytest.mark.parametrize("make", [
    lambda req: openai.APIConnectionError(request=req),
    lambda req: openai.APITimeoutError(request=req),
    lambda req: httpx.ReadError("x"),
    lambda req: openai.InternalServerError("boom", response=httpx.Response(500, request=req), body=None),
])
def test_transport_failures_wrapped(make):
    req = httpx.Request("POST", "http://x/v1/chat/completions")

    class C:
        def create(self, **kw):
            raise make(req)

    with pytest.raises(TransportError):
        chat_image(SimpleNamespace(chat=SimpleNamespace(completions=C())), "m", Image.new("RGB", (4, 4)), "p")


def test_rate_limit_error_wrapped():
    """429 RateLimitError → TransportError (no key leaked)."""
    req = httpx.Request("POST", "http://x/v1/chat/completions")
    resp = httpx.Response(429, request=req, text="Rate limited")

    class C:
        def create(self, **kw):
            raise openai.RateLimitError("Rate limited", response=resp, body=None)

    with pytest.raises(TransportError, match="rate limited"):
        chat_image(SimpleNamespace(chat=SimpleNamespace(completions=C())), "m", Image.new("RGB", (4, 4)), "p")


def test_auth_error_wrapped():
    """401/403 AuthenticationError/PermissionDeniedError → TransportError (no key leaked)."""
    req = httpx.Request("POST", "http://x/v1/chat/completions")
    resp = httpx.Response(401, request=req, text="Unauthorized")

    class C:
        def create(self, **kw):
            raise openai.AuthenticationError("Invalid key", response=resp, body=None)

    with pytest.raises(TransportError, match="auth failed"):
        chat_image(SimpleNamespace(chat=SimpleNamespace(completions=C())), "m", Image.new("RGB", (4, 4)), "p")


def test_bad_request_error_returns_content_error():
    """400 BadRequestError → return "bad_request: <msg>" instead of raising."""
    req = httpx.Request("POST", "http://x/v1/chat/completions")
    resp = httpx.Response(400, request=req, text="Context length exceeded")

    class C:
        def create(self, **kw):
            raise openai.BadRequestError("Context too long", response=resp, body=None)

    text, reason = chat_image(SimpleNamespace(chat=SimpleNamespace(completions=C())), "m", Image.new("RGB", (4, 4)), "p")
    assert reason == "bad_request"
    assert "too long" in text.lower() or "context" in text.lower()


def test_ollama_repeat_limit_is_looping_not_transport():
    """Ollama returns 500 "token repeat limit reached" when the model loops: this is a reply, not a transport failure."""
    req = httpx.Request("POST", "http://x/v1/chat/completions")

    class C:
        def create(self, **kw):
            raise openai.InternalServerError(
                "prediction aborted, token repeat limit reached",
                response=httpx.Response(500, request=req), body=None)

    text, reason = chat_image(SimpleNamespace(chat=SimpleNamespace(completions=C())), "m",
                              Image.new("RGB", (4, 4)), "p")
    assert reason == "repeat_limit" and "repeat limit" in text
