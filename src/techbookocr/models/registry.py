"""Adapter name -> class; create an adapter with an OpenAI client."""
from __future__ import annotations

from openai import OpenAI

from techbookocr.config import ModelSpec
from techbookocr.models.adapters.chandra import ChandraAdapter
from techbookocr.models.adapters.deepseek import DeepseekAdapter
from techbookocr.models.adapters.dots import DotsAdapter
from techbookocr.models.adapters.markdown_page import HunyuanAdapter, QwenPageAdapter
from techbookocr.models.adapters.paddle_vl import PaddleVLAdapter
from techbookocr.models.adapters.qwen_arbiter import QwenArbiterAdapter
from techbookocr.models.server import api_key
from techbookocr.models.types import PageOCR

ADAPTERS: dict[str, type] = {
    "dots": DotsAdapter,
    "chandra": ChandraAdapter,
    "deepseek": DeepseekAdapter,
    "hunyuan": HunyuanAdapter,
    "qwen_page": QwenPageAdapter,
    "paddle_vl": PaddleVLAdapter,
    "qwen_arbiter": QwenArbiterAdapter,
}


def make_adapter(spec: ModelSpec, base_url: str) -> PageOCR:
    if spec.adapter not in ADAPTERS:
        raise KeyError(f"unknown adapter {spec.adapter!r} for model {spec.key!r}")
    client = OpenAI(base_url=base_url, api_key=api_key(spec), max_retries=0)
    return ADAPTERS[spec.adapter](spec, client, base_url)
