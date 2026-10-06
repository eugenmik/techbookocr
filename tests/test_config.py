from pathlib import Path

import pytest

from techbookocr.config import ConfigError, load_config


def test_defaults_when_no_file(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.render.min_dpi == 300
    assert cfg.render.split_spreads == "auto"
    assert cfg.server.port == 8000
    assert cfg.models == {}


def test_models_parsed(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text(
        """
[render]
max_dpi = 400

[models.dots]
adapter = "dots"
image = "vllm/vllm-openai:latest"
model = "rednote-hilab/dots.mocr"
args = ["--trust-remote-code"]
env = { VLLM_USE_V1 = "1" }
params = { max_tokens = 16000 }
""",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.render.max_dpi == 400
    assert cfg.render.min_dpi == 300
    m = cfg.models["dots"]
    assert m.key == "dots"
    assert m.args == ("--trust-remote-code",)
    assert m.env == {"VLLM_USE_V1": "1"}
    assert m.params["max_tokens"] == 16000


def test_unknown_split_mode_rejected(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text('[render]\nsplit_spreads = "maybe"\n', encoding="utf-8")
    import pytest

    with pytest.raises(ValueError, match="split_spreads"):
        load_config(p)


def _load(tmp_path, text):
    p = tmp_path / "c.toml"
    p.write_text(text, encoding="utf-8")
    return load_config(p)


def test_missing_required_model_field(tmp_path):
    import pytest

    with pytest.raises(ValueError, match=r"\[models.dots\] missing 'image'"):
        _load(tmp_path, '[models.dots]\nadapter="dots"\nmodel="m"\n')


def test_unknown_keys_name_section(tmp_path):
    import pytest

    with pytest.raises(ValueError, match=r"\[render\] unknown key 'foo'"):
        _load(tmp_path, "[render]\nfoo = 1\n")
    with pytest.raises(ValueError, match=r"\[server\] unknown key 'bar'"):
        _load(tmp_path, "[server]\nbar = 1\n")
    with pytest.raises(ValueError, match=r"\[models.x\] unknown key 'imge'"):
        _load(tmp_path, '[models.x]\nadapter="a"\nimage="i"\nmodel="m"\nimge="typo"\n')


def test_pipeline_defaults_and_override(tmp_path):
    cfg = load_config(tmp_path / "missing.toml")
    p = cfg.pipeline
    assert (p.layout_model, p.text_model, p.table_model, p.arbiter_model) == (
        "dots_mocr", "hunyuan", "chandra2", "qwen9b_arbiter")
    assert p.tau_text == 0.01 and p.tau_halluc == 0.15 and p.min_line_px == 32 and p.figure_pad == 8
    cfg = _load(tmp_path, '[pipeline]\ntau_text = 0.02\narbiter_model = "remote_arbiter"\n')
    assert cfg.pipeline.tau_text == 0.02 and cfg.pipeline.arbiter_model == "remote_arbiter"
    assert cfg.pipeline.tau_halluc == 0.15


def test_pipeline_unknown_key(tmp_path):
    import pytest

    with pytest.raises(ValueError, match=r"\[pipeline\] unknown key 'tau'"):
        _load(tmp_path, "[pipeline]\ntau = 1\n")


def test_sketches_device_config(tmp_path):
    import pytest

    assert load_config(tmp_path / "missing.toml").pipeline.sketches_device == "cpu"
    cfg = _load(tmp_path, '[pipeline]\nsketches_device = "gpu"\n')
    assert cfg.pipeline.sketches_device == "gpu"
    with pytest.raises(ValueError, match="sketches_device"):
        _load(tmp_path, '[pipeline]\nsketches_device = "tpu"\n')


def test_external_model_spec(tmp_path):
    import pytest

    cfg = _load(tmp_path, '[models.remote]\nadapter = "qwen_arbiter"\nmodel = "qwen3.8-27b"\n'
                          'base_url = "http://10.0.0.5:8000/v1"\napi_key_env = "REMOTE_KEY"\n')
    m = cfg.models["remote"]
    assert m.base_url == "http://10.0.0.5:8000/v1" and m.api_key_env == "REMOTE_KEY" and m.image == ""
    assert load_config(tmp_path / "missing.toml").models == {}
    with pytest.raises(ValueError, match=r"\[models.both\] image and base_url are mutually exclusive"):
        _load(tmp_path, '[models.both]\nadapter="a"\nmodel="m"\nimage="i"\nbase_url="http://x/v1"\n')
    with pytest.raises(ValueError, match=r"\[models.none\] missing 'image'"):
        _load(tmp_path, '[models.none]\nadapter="a"\nmodel="m"\n')
    with pytest.raises(ValueError, match=r"\[models.empty_image\] image must be non-empty"):
        _load(tmp_path, '[models.empty_image]\nadapter="a"\nmodel="m"\nimage=""\n')
    with pytest.raises(ValueError, match=r"\[models.empty_base_url\] base_url must be non-empty"):
        _load(tmp_path, '[models.empty_base_url]\nadapter="a"\nmodel="m"\nbase_url=""\n')
    with pytest.raises(ValueError, match=r"\[models.api_key_no_url\] api_key_env requires base_url"):
        _load(tmp_path, '[models.api_key_no_url]\nadapter="a"\nmodel="m"\nimage="i"\napi_key_env="KEY"\n')


def test_pipeline_mode_default_and_validation(tmp_path):
    assert load_config(None).pipeline.mode == "fast"
    p = tmp_path / "c.toml"
    p.write_text('[pipeline]\nmode = "turbo"\n')
    with pytest.raises(ConfigError, match="mode must be"):
        load_config(p)


def test_webp_quality_config(tmp_path):
    import pytest

    assert load_config(tmp_path / "missing.toml").pipeline.webp_quality == 70
    cfg = _load(tmp_path, "[pipeline]\nwebp_quality = 85\n")
    assert cfg.pipeline.webp_quality == 85
    with pytest.raises(ValueError, match="webp_quality"):
        _load(tmp_path, "[pipeline]\nwebp_quality = 0\n")
