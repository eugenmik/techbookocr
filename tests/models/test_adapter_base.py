from types import SimpleNamespace

import pytest
from PIL import Image

from techbookocr.config import ConfigError, ModelSpec
from techbookocr.models.adapters.base import ChatAdapter
from techbookocr.models.types import Block


class FakeCompletions:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def create(self, **kw):
        self.calls.append(kw)
        text, reason = self.replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=reason)])


def fake_client(replies):
    comp = FakeCompletions(replies)
    return SimpleNamespace(chat=SimpleNamespace(completions=comp)), comp


class Echo(ChatAdapter):
    default_params = {"max_tokens": 100, "extra": {"top_p": 0.1}, "retry_extra": {"top_p": 0.95}}

    def prompt(self):
        return "P"

    def parse(self, raw, orig_size, sent_size):
        return [Block("Text", raw)], raw + "\n"


SPEC = ModelSpec(key="echo", adapter="echo", image="i", model="m")


def test_retry_on_loop_uses_retry_params():
    client, comp = fake_client([("ab" * 400, "length"), ("Хороший текст", "stop")])
    res = Echo(SPEC, client, "http://x").ocr_page(Image.new("RGB", (8, 8)))
    assert res.markdown == "Хороший текст\n" and res.error is None
    assert [c["temperature"] for c in comp.calls] == [0.0, 0.3]
    assert comp.calls[0]["extra_body"] == {"top_p": 0.1}
    assert comp.calls[1]["extra_body"] == {"top_p": 0.95}


def test_loop_after_all_retries_flagged():
    client, _ = fake_client([("ab" * 400, "length"), ("ab" * 400, "length")])
    res = Echo(SPEC, client, "http://x").ocr_page(Image.new("RGB", (8, 8)))
    assert res.error == "looping"


def test_truncated_flagged():
    client, _ = fake_client([("Обрезанный текст", "length")])
    res = Echo(SPEC, client, "http://x").ocr_page(Image.new("RGB", (8, 8)))
    assert res.error == "truncated" and res.markdown == "Обрезанный текст\n"


def test_max_tokens_must_be_int():
    """params.max_tokens is not an int: ConfigError when the adapter is created, not TypeError on the first request."""
    spec = ModelSpec(key="e", adapter="echo", image="i", model="m", params={"max_tokens": "много"})
    with pytest.raises(ConfigError):
        Echo(spec, fake_client([])[0], "http://x")


def test_spec_params_override_defaults():
    spec = ModelSpec(key="e", adapter="echo", image="i", model="m", params={"max_tokens": 7})
    client, comp = fake_client([("ok", "stop")])
    Echo(spec, client, "http://x").ocr_page(Image.new("RGB", (8, 8)))
    assert comp.calls[0]["max_tokens"] == 7 and comp.calls[0]["model"] == "m"


def test_periodic_text_with_stop_is_accepted():
    """Controller ruling: a periodic text with finish_reason 'stop' is accepted on the first call with error None (one call only)."""
    client, comp = fake_client([("ab" * 400, "stop")])
    res = Echo(SPEC, client, "http://x").ocr_page(Image.new("RGB", (8, 8)))
    assert res.error is None
    assert len(comp.calls) == 1


class Crasher(ChatAdapter):
    """Adapter that raises exception during parsing."""
    default_params = {"max_tokens": 100}

    def prompt(self):
        return "P"

    def parse(self, raw, orig_size, sent_size):
        raise ValueError("Parse failed")


def test_parse_exception_preserved_with_raw():
    """Fix: parser exception caught, raw preserved, error has 'parse_error' prefix."""
    client, _ = fake_client([("some output", "stop")])
    res = Crasher(SPEC, client, "http://x").ocr_page(Image.new("RGB", (8, 8)))
    assert res.error.startswith("parse_error:")
    assert "ValueError" in res.error
    assert "Parse failed" in res.error
    assert res.raw == "some output"
    assert res.markdown == ""
    assert res.blocks == []


def test_extra_params_deep_merged():
    """Spec extra merges (not replaces) default extra; nested dicts merged."""
    class Arbiter(ChatAdapter):
        default_params = {
            "max_tokens": 8192,
            "extra": {"chat_template_kwargs": {"enable_thinking": False}, "top_p": 0.1}
        }
        def prompt(self):
            return "P"
        def parse(self, raw, orig_size, sent_size):
            return [], ""

    spec = ModelSpec(key="a", adapter="a", image="i", model="m",
                     params={"extra": {"top_p": 0.9}})  # Override top_p, keep enable_thinking
    client, comp = fake_client([("ok", "stop")])
    Arbiter(spec, client, "http://x").ocr_page(Image.new("RGB", (8, 8)))

    # Should have both: enable_thinking from default (nested) and top_p from spec (overridden)
    extra = comp.calls[0]["extra_body"]
    assert extra.get("chat_template_kwargs") == {"enable_thinking": False}, f"nested dict lost: {extra}"
    assert extra.get("top_p") == 0.9, f"override lost: {extra}"


def test_bad_request_propagates_empty_text_and_error():
    """400 BadRequestError: ocr_page returns empty markdown, error startswith 'bad_request'."""
    client, _ = fake_client([("context too long", "bad_request")])
    res = Echo(SPEC, client, "http://x").ocr_page(Image.new("RGB", (8, 8)))
    assert res.markdown == "", f"expected empty markdown, got {res.markdown!r}"
    assert res.error.startswith("bad_request"), f"expected error to start with 'bad_request', got {res.error!r}"
    assert res.blocks == []


def test_repeat_limit_retries_then_reports_looping(monkeypatch):
    """Ollama cut off a loop (500 "token repeat limit"): retry with another temperature, then "looping"."""
    import techbookocr.models.adapters.base as base
    temps = []

    def fake(client, model, image, prompt, *, system=None, max_tokens=8192, temperature=0.0, extra=None):
        temps.append(temperature)
        return "prediction aborted, token repeat limit reached", "repeat_limit"

    monkeypatch.setattr(base, "chat_image", fake)
    res = Echo(SPEC, None, "http://x").ocr_page(Image.new("RGB", (8, 8)))
    assert res.error == "looping" and temps == [0.0, 0.3]
