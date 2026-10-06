"""VLM call through an OpenAI-compatible API, with loop protection."""
from __future__ import annotations

import base64
import io

import httpx
import openai
from PIL import Image

from techbookocr.models.errors import TransportError


def request_timeout(max_tokens: int) -> float:
    """Timeout of a single request: ~0.05 s per token (>=20 tok/s), from 120 to 1800 s."""
    return min(1800.0, max(120.0, max_tokens * 0.05))


def image_to_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def chat_image(client, model: str, image: Image.Image | None, prompt: str, *, system: str | None = None,
               max_tokens: int = 8192, temperature: float = 0.0, extra: dict | None = None) -> tuple[str, str]:
    """An "image + text" request; image=None means text only (endpoint without image support)."""
    messages: list[dict] = []
    if system is not None:
        messages.append({"role": "system", "content": system})
    if image is None:
        messages.append({"role": "user", "content": prompt})
    else:
        messages.append({"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": image_to_data_url(image)}},
            {"type": "text", "text": prompt},
        ]})
    try:
        resp = client.chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens, temperature=temperature, extra_body=extra or {},
            timeout=request_timeout(max_tokens),
        )
    except openai.BadRequestError as e:
        # 400: context length, invalid request → return error, don't raise
        return str(e), "bad_request"
    except (openai.RateLimitError, openai.AuthenticationError, openai.PermissionDeniedError) as e:
        # 429, 401, 403 → transport error (no key/message exposure)
        if isinstance(e, openai.AuthenticationError):
            msg = "auth failed (HTTP 401)"
        elif isinstance(e, openai.PermissionDeniedError):
            msg = "auth failed (HTTP 403)"
        else:  # RateLimitError
            msg = "rate limited"
        raise TransportError(msg) from e
    except openai.InternalServerError as e:
        # Ollama returns 500 when the model loops: that is its answer, not a server failure
        if "repeat limit" in str(e):
            return str(e), "repeat_limit"
        raise TransportError(f"{type(e).__name__}: {e}") from e
    except (openai.APIConnectionError, httpx.HTTPError) as e:
        raise TransportError(f"{type(e).__name__}: {e}") from e
    choice = resp.choices[0]
    return choice.message.content or "", choice.finish_reason or ""


def is_looping(text: str, tail: int = 600, max_period: int = 200) -> bool:
    """Whether the tail of length `tail` is an exact repetition of a fragment with period <= max_period."""
    if len(text) < tail:
        return False
    t = text[-tail:]
    for p in range(1, max_period + 1):
        if t[p:] == t[:-p]:
            return True
    return False
