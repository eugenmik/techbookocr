from unittest.mock import MagicMock

from PIL import Image

from techbookocr.config import ModelSpec
from techbookocr.models.adapters.markdown_page import HunyuanAdapter, QwenPageAdapter, clean_markdown, fit_side


def test_clean_strips_fences_and_trailing_coords():
    """Trailing coordinates at end of line are stripped."""
    raw = "```markdown\n# Заголовок\n\nТекст (12,34),(56,78)\n```"
    assert clean_markdown(raw) == "# Заголовок\n\nТекст\n"


def test_clean_preserves_coords_in_formulas():
    """Coordinates inside formulas/text are preserved."""
    raw = "$f=(1,2),(3,4)$ x"
    assert clean_markdown(raw) == "$f=(1,2),(3,4)$ x\n"


def test_clean_preserves_coords_in_tables():
    """Coordinates inside table cells are preserved."""
    raw = "| a | (1,2),(3,4) |\n| --- | --- |"
    result = clean_markdown(raw)
    assert "(1,2),(3,4)" in result


def test_fit_side():
    assert fit_side(Image.new("RGB", (2000, 3000)), 2560).size == (1706, 2560)
    small = Image.new("RGB", (100, 100))
    assert fit_side(small, 2560) is small


def test_hunyuan_settings():
    a = HunyuanAdapter(ModelSpec(key="h", adapter="hunyuan", image="i", model="hunyuan"), None, "u")
    assert a.system == "" and a.prompt().startswith("提取文档图片中正文的所有信息用markdown格式表示")
    assert a.params["extra"]["repetition_penalty"] == 1.08


def test_hunyuan_sends_empty_system_message():
    """Empty system message is sent, not dropped by 'if system:' check."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="# Test"), finish_reason="stop")]
    mock_client.chat.completions.create.return_value = mock_response

    a = HunyuanAdapter(ModelSpec(key="h", adapter="hunyuan", image="i", model="hunyuan"), mock_client, "u")
    img = Image.new("RGB", (100, 100))
    a.chat(img, a.prompt())

    # Verify the system message was sent as empty string, not skipped
    call_args = mock_client.chat.completions.create.call_args
    messages = call_args.kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == ""


def test_qwen_disables_thinking():
    a = QwenPageAdapter(ModelSpec(key="q", adapter="qwen_page", image="i", model="qwen"), None, "u")
    assert a.params["extra"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "HTML" in a.prompt() and "LaTeX" in a.prompt()
