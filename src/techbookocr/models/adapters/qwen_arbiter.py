"""Qwen as arbiter (llama.cpp or an external OpenAI-compatible endpoint): crop + prompt -> text.

The prompt is built by pipeline.arbiter; the adapter only sends the request (ChatAdapter.ask). params.vision = false means
an endpoint without image support: only the prompt text is sent."""
from __future__ import annotations

from techbookocr.models.adapters.base import ChatAdapter


class QwenArbiterAdapter(ChatAdapter):
    default_params = {"max_tokens": 8192, "temperature": 0.0, "retry_temperatures": [0.3],
                      "extra": {"chat_template_kwargs": {"enable_thinking": False}}}
