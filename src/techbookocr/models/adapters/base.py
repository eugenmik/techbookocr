"""Base adapter: a single "image + prompt" request to an OpenAI-compatible server."""
from __future__ import annotations

import time

from PIL import Image

from techbookocr.config import ConfigError, ModelSpec
from techbookocr.models.errors import ERR_LOOPING, ERR_PARSE, ERR_TRUNCATED
from techbookocr.models.types import BLOCK_KINDS, Block, BlockResult, PageResult
from techbookocr.models.vlm import chat_image, is_looping


def _deep_merge(default: dict, spec: dict) -> dict:
    """Deep dict merge: spec values override defaults, nested dicts are merged."""
    merged = default.copy()
    for k, v in spec.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


class ChatAdapter:
    default_params: dict = {}
    system: str | None = None

    def __init__(self, spec: ModelSpec, client, base_url: str):
        self.spec, self.client, self.base_url = spec, client, base_url
        self.name = spec.key
        self.params = _deep_merge(self.default_params, spec.params)
        mt = self.params.get("max_tokens")
        if not isinstance(mt, int) or isinstance(mt, bool) or mt <= 0:
            raise ConfigError(f"{self.name}: params.max_tokens must be a positive int, got {mt!r}")

    @property
    def vision(self) -> bool:
        """Whether the model sees the image; False means a text-only endpoint and the image is not sent."""
        return bool(self.params.get("vision", True))

    def close(self) -> None:
        pass

    def prepare(self, image: Image.Image) -> Image.Image:
        return image

    def prompt(self) -> str:
        raise NotImplementedError

    def parse(self, raw: str, orig_size: tuple[int, int], sent_size: tuple[int, int]) -> tuple[list[Block], str]:
        raise NotImplementedError

    def chat(self, image: Image.Image | None, prompt: str, max_tokens: int | None = None) -> tuple[str, str | None]:
        p = self.params
        attempts = [(p.get("temperature", 0.0), p.get("extra", {}))]
        attempts += [(t, {**p.get("extra", {}), **p.get("retry_extra", {})}) for t in p.get("retry_temperatures", [0.3])]
        text = ""
        for temperature, extra in attempts:
            text, reason = chat_image(self.client, self.spec.model, image, prompt, system=self.system,
                                      max_tokens=max_tokens or p["max_tokens"], temperature=temperature, extra=extra)
            if reason == "bad_request":
                # 400 error: content error, not retriable; return empty with error immediately
                return "", f"bad_request: {text}"
            if reason == "repeat_limit":  # the server itself cut off a loop: retry with a different temperature
                continue
            if reason == "length" and is_looping(text):
                continue
            return text, ERR_TRUNCATED if reason == "length" else None
        return text, ERR_LOOPING

    def ocr_page(self, image: Image.Image) -> PageResult:
        t0 = time.monotonic()
        sent = self.prepare(image)
        raw, error = self.chat(sent, self.prompt())
        # Bad request (400): content error, don't parse, return empty result
        if error and error.startswith("bad_request"):
            return PageResult(markdown="", blocks=[], raw=raw, seconds=time.monotonic() - t0, error=error)
        try:
            blocks, markdown = self.parse(raw, image.size, sent.size)
        except Exception as e:
            return PageResult(markdown="", blocks=[], raw=raw, seconds=time.monotonic() - t0,
                              error=f"{ERR_PARSE}: {type(e).__name__}: {e}")
        return PageResult(markdown=markdown, blocks=blocks, raw=raw, seconds=time.monotonic() - t0, error=error)

    # --- block crops and arbitrary requests ---

    def ask(self, image: Image.Image, prompt: str, *, max_tokens: int | None = None) -> BlockResult:
        """Image (if the model sees it) + prompt -> raw reply; errors follow the common convention."""
        t0 = time.monotonic()
        raw, error = self.chat(self.prepare(image) if self.vision else None, prompt, max_tokens)
        return BlockResult(text=raw, raw=raw, seconds=time.monotonic() - t0, error=error)

    def block_prompt(self, kind: str) -> str:
        raise NotImplementedError(f"{self.name}: block OCR is not supported")

    def block_max_tokens(self, kind: str) -> int:
        return self.params.get("block_max_tokens", self.params["max_tokens"])

    def parse_block(self, raw: str, kind: str) -> str:
        return raw.strip()

    def ocr_block(self, image: Image.Image, kind: str) -> BlockResult:
        if kind not in BLOCK_KINDS:
            raise ValueError(f"unknown block kind {kind!r}")
        res = self.ask(image, self.block_prompt(kind), max_tokens=self.block_max_tokens(kind))
        try:
            text = self.parse_block(res.raw, kind)
        except Exception as e:
            parse_error = f"{ERR_PARSE}: {type(e).__name__}: {e}"
            # Keep first error code when parse also fails (e.g. "truncated; parse_error")
            error = f"{res.error}; {parse_error}" if res.error else parse_error
            return BlockResult("", res.raw, res.seconds, error)
        return BlockResult(text, res.raw, res.seconds, res.error)
