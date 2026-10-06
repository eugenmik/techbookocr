import pytest

from techbookocr.config import Config, ConfigError
from techbookocr.tui.settings_io import load_values, save_settings

TOML = '''[render]
min_dpi = 300
max_dpi = 600   # верхний предел

[library]
dir = "out"
command_poll_s = 1.0   # как часто Control проверяет команды
idle_poll_s = 5.0

[pipeline]
layout_model = "dots_mocr"
arbiter_model = "qwen9b_arbiter"

[models.qwen9b_arbiter]
adapter = "qwen_arbiter"
model = "qwen"
image = "img"
'''


def write(tmp_path, text=TOML):
    p = tmp_path / "techbookocr.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_values(tmp_path):
    vals = load_values(write(tmp_path))
    assert vals[("pipeline", "mode")] == "fast"          # dataclass default (the key is not in the toml)
    assert vals[("library", "dir")] == "out"
    assert vals[("render", "min_dpi")] == 300
    assert vals[("library", "auto_summarize")] is True   # default
    assert vals[("library", "command_poll_s")] == 1.0


def test_save_replaces_preserving_comment(tmp_path):
    p = write(tmp_path)
    save_settings(p, {("library", "command_poll_s"): 2.5})
    text = p.read_text(encoding="utf-8")
    assert "command_poll_s = 2.5" in text
    assert "# как часто Control проверяет команды" in text  # the inline comment is not lost
    assert "max_dpi = 600   # верхний предел" in text        # other lines are untouched


def test_save_inserts_missing_key_into_section(tmp_path):
    """pipeline.mode is absent from the toml: it is inserted inside [pipeline], not at the end of the file."""
    p = write(tmp_path)
    save_settings(p, {("pipeline", "mode"): "cascade"})
    text = p.read_text(encoding="utf-8")
    pipe = text.split("[pipeline]")[1].split("[models")[0]
    assert 'mode = "cascade"' in pipe


def test_save_creates_missing_section(tmp_path):
    p = write(tmp_path, "[render]\nmin_dpi = 300\n")
    save_settings(p, {("library", "auto_summarize"): False})
    text = p.read_text(encoding="utf-8")
    assert "[library]" in text and "auto_summarize = false" in text


def test_save_bool_and_string_literals(tmp_path):
    p = write(tmp_path)
    save_settings(p, {("library", "auto_summarize"): False,
                      ("pipeline", "summarizer_model"): "qwen38_ud_arbiter"})
    text = p.read_text(encoding="utf-8")
    assert "auto_summarize = false" in text
    assert 'summarizer_model = "qwen38_ud_arbiter"' in text


def test_save_rejects_unknown_key_and_bad_value(tmp_path):
    p = write(tmp_path)
    with pytest.raises(ConfigError):
        save_settings(p, {("pipeline", "unknown_key"): 1})
    with pytest.raises(ConfigError):
        save_settings(p, {("render", "min_dpi"): "триста"})
    with pytest.raises(ConfigError):
        save_settings(p, {("pipeline", "mode"): "slow"})      # outside choices
    assert p.read_text(encoding="utf-8") == TOML               # the file is not damaged


def test_load_values_bad_toml_raises(tmp_path):
    p = write(tmp_path, "не toml [[[")
    with pytest.raises(ConfigError):
        load_values(p)


def test_model_choices_from_config(tmp_path):
    """choices() of summarizer_model: the models.* keys from the same toml."""
    vals = load_values(write(tmp_path), cfg=Config())
    assert vals[("pipeline", "summarizer_model")] == "qwen9b_arbiter"


def test_field_list_values_choices_comments(tmp_path):
    from techbookocr.tui.settings_io import field_list

    toml = tmp_path / "b.toml"
    toml.write_text('[pipeline]\nmode = "fast"  # быстрый режим\nwebp_quality = 70   # качество WebP\n'
                    '[models.m1]\nadapter = "dots"\nimage = "i"\nmodel = "m"\n', encoding="utf-8")
    fields = {(f["section"], f["key"]): f for f in field_list(toml)}
    assert fields[("pipeline", "mode")]["value"] == "fast"
    assert fields[("pipeline", "mode")]["comment"] == "быстрый режим"
    assert fields[("pipeline", "webp_quality")] == {"section": "pipeline", "key": "webp_quality", "kind": "int",
                                                    "choices": [], "value": 70, "comment": "качество WebP"}
    assert fields[("pipeline", "sketches_device")]["choices"] == ["cpu", "gpu"]
    assert fields[("pipeline", "text_layer")]["comment"] is None
    assert "m1" in fields[("pipeline", "summarizer_model")]["choices"]


def test_save_keeps_whitespace_before_inline_comment(tmp_path):
    """Spaces between the value and `#` are kept as they were: only the value changes."""
    p = write(tmp_path, '[pipeline]\nmode = "fast"      # быстрый режим\nwebp_quality = 70\t# q\n')
    save_settings(p, {("pipeline", "mode"): "cascade", ("pipeline", "webp_quality"): 55})
    assert p.read_text(encoding="utf-8") == '[pipeline]\nmode = "cascade"      # быстрый режим\nwebp_quality = 55\t# q\n'
