from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from techbookocr.config import ModelSpec
from techbookocr.models.adapters.chandra import OCR_PROMPT, ChandraAdapter, table_html
from techbookocr.models.adapters.markdown_page import (HUNYUAN_DOC_PARSE, HUNYUAN_FORMULA, HUNYUAN_STRUCTURED,
                                                   HUNYUAN_TABLE, HunyuanAdapter)
from techbookocr.models.adapters.qwen_arbiter import QwenArbiterAdapter
from techbookocr.models.errors import TransportError
from tests.models.test_adapter_base import fake_client

IMG = Image.new("RGB", (300, 60), "white")
HUN = ModelSpec(key="hunyuan", adapter="hunyuan", image="i", model="hunyuan", params={"max_tokens": 16000})
CHA = ModelSpec(key="chandra2", adapter="chandra", image="i", model="chandra")
QWE = ModelSpec(key="qwen9b_arbiter", adapter="qwen_arbiter", image="i", model="qwen")


def _prompt(call) -> str:
    content = call["messages"][-1]["content"]
    return content if isinstance(content, str) else content[1]["text"]


@pytest.mark.parametrize("kind,prompt,max_tokens", [
    ("text", HUNYUAN_STRUCTURED, 4096), ("caption", HUNYUAN_STRUCTURED, 4096), ("formula", HUNYUAN_FORMULA, 4096),
    ("table", HUNYUAN_TABLE, 4096), ("page", HUNYUAN_DOC_PARSE, 16000)])
def test_hunyuan_block_prompts(kind, prompt, max_tokens):
    client, comp = fake_client([("```markdown\nЧугун марки СЧ20\n```", "stop")])
    res = HunyuanAdapter(HUN, client, "http://x").ocr_block(IMG, kind)
    assert res.text == "Чугун марки СЧ20" and res.error is None
    assert _prompt(comp.calls[0]) == prompt and comp.calls[0]["max_tokens"] == max_tokens
    assert comp.calls[0]["messages"][0] == {"role": "system", "content": ""}


def test_hunyuan_block_looping_reported():
    client, _ = fake_client([("ab" * 400, "length")])
    assert HunyuanAdapter(HUN, client, "http://x").ocr_block(IMG, "text").error == "looping"


def test_unknown_kind_rejected():
    client, _ = fake_client([])
    with pytest.raises(ValueError, match="unknown block kind"):
        HunyuanAdapter(HUN, client, "http://x").ocr_block(IMG, "picture")


def test_chandra_table_block():
    raw = ('<div data-label="Table"><table><tr><td><img alt="a hook welded to a frame"/></td>'
           '<td><math>l_в</math></td><td>15—20</td></tr></table></div>')
    client, comp = fake_client([(raw, "stop")])
    res = ChandraAdapter(CHA, client, "http://x").ocr_block(IMG, "table")
    assert res.error is None and res.text.startswith("<table>")
    assert "<img>" in res.text and "alt" not in res.text and "$l_в$" in res.text and "15—20" in res.text
    assert _prompt(comp.calls[0]) == OCR_PROMPT and comp.calls[0]["max_tokens"] == 8192
    assert table_html(raw) == res.text


def test_chandra_table_without_table_is_parse_error():
    client, _ = fake_client([("<p>Просто текст</p>", "stop"), ("<p>И снова</p>", "stop")])  # the second is an ocr_layout retry
    res = ChandraAdapter(CHA, client, "http://x").ocr_block(IMG, "table")
    assert res.text == "" and res.error.startswith("parse_error")


def test_chandra_text_block_to_markdown():
    client, _ = fake_client([("<p>Доля графита <math>W_г</math> равна 2,2.</p>", "stop")])
    res = ChandraAdapter(CHA, client, "http://x").ocr_block(IMG, "text")
    assert res.text == "Доля графита $W_г$ равна 2,2."


def test_transport_error_propagates():
    class Boom:
        def create(self, **kw):
            raise httpx.ConnectError("refused")

    client = SimpleNamespace(chat=SimpleNamespace(completions=Boom()))
    with pytest.raises(TransportError):
        HunyuanAdapter(HUN, client, "http://x").ocr_block(IMG, "text")


def test_arbiter_ask_with_and_without_image():
    client, comp = fake_client([("Ответ\nFIXES: []", "stop"), ("Ответ", "stop")])
    a = QwenArbiterAdapter(QWE, client, "http://x")
    res = a.ask(IMG, "Проверь", max_tokens=777)
    assert res.text == "Ответ\nFIXES: []" and res.error is None and a.vision
    call = comp.calls[0]
    assert call["max_tokens"] == 777 and call["temperature"] == 0.0
    assert call["extra_body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert call["messages"][-1]["content"][0]["type"] == "image_url"
    blind = QwenArbiterAdapter(ModelSpec(key="r", adapter="qwen_arbiter", image="", model="q",
                                         base_url="http://r/v1", params={"vision": False}), client, "http://r/v1")
    assert blind.vision is False
    blind.ask(IMG, "Проверь")
    assert comp.calls[1]["messages"][-1]["content"] == "Проверь" and comp.calls[1]["max_tokens"] == 8192


def test_chandra_table_hint_option_changes_prompt():
    from techbookocr.models.adapters.chandra import TABLE_HINT, TABLE_PROMPT
    raw = '<table><tr><td>1</td></tr></table>'
    client, comp = fake_client([(raw, "stop")])
    spec = ModelSpec(key="chandra2", adapter="chandra", image="i", model="chandra", params={"table_hint": True})
    ChandraAdapter(spec, client, "http://x").ocr_block(IMG, "table")
    assert _prompt(comp.calls[0]) == TABLE_PROMPT and TABLE_HINT in TABLE_PROMPT and TABLE_PROMPT.startswith(OCR_PROMPT)
    client, comp = fake_client([(raw, "stop")])
    ChandraAdapter(spec, client, "http://x").ocr_block(IMG, "text")
    assert _prompt(comp.calls[0]) == OCR_PROMPT  # the hint is for tables only


def test_chandra_table_retry_with_layout_prompt():
    from techbookocr.models.adapters.chandra import OCR_LAYOUT_PROMPT
    layout = ('<div data-bbox="0 0 1000 100" data-label="Text"><p>x</p></div>'
              '<div data-bbox="0 100 1000 900" data-label="Table"><table><tr><td>5</td></tr></table></div>')
    client, comp = fake_client([("<div><p>нет таблицы</p></div>", "stop"), (layout, "stop")])
    res = ChandraAdapter(CHA, client, "http://x").ocr_block(IMG, "table")
    assert res.error is None and res.text == "<table><tr><td>5</td></tr></table>"
    assert _prompt(comp.calls[1]) == OCR_LAYOUT_PROMPT and len(comp.calls) == 2
    assert "нет таблицы" in res.raw and "retry: ocr_layout" in res.raw and 'data-label="Table"' in res.raw


def test_chandra_table_retry_also_fails_keeps_raw_and_error():
    client, comp = fake_client([("<p>один</p>", "stop"), ("<p>два</p>", "stop")])
    res = ChandraAdapter(CHA, client, "http://x").ocr_block(IMG, "table")
    assert res.text == "" and res.error.startswith("parse_error") and "retry:" in res.error
    assert "один" in res.raw and "два" in res.raw and len(comp.calls) == 2


def test_chandra_no_retry_for_text_or_truncation():
    client, comp = fake_client([("<p>текст</p>", "stop")])
    assert ChandraAdapter(CHA, client, "http://x").ocr_block(IMG, "text").text == "текст" and len(comp.calls) == 1
