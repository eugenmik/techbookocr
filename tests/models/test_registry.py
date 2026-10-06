from pathlib import Path

import pytest

from techbookocr.config import ModelSpec, load_config
from techbookocr.models.registry import ADAPTERS, make_adapter


def test_unknown_adapter():
    with pytest.raises(KeyError, match="nope"):
        make_adapter(ModelSpec(key="k", adapter="nope", image="i", model="m"), "http://127.0.0.1:8000/v1")


def test_all_configured_models_have_adapters():
    cfg = load_config(Path(__file__).resolve().parents[2] / "techbookocr.toml")
    assert cfg.models, "techbookocr.toml has no models"
    for spec in cfg.models.values():
        assert spec.adapter in ADAPTERS, spec.key


def test_pipeline_models_configured():
    cfg = load_config(Path(__file__).resolve().parents[2] / "techbookocr.toml")
    p = cfg.pipeline
    for key in (p.layout_model, p.text_model, p.table_model, p.arbiter_model):
        assert key in cfg.models, key
    assert cfg.models["qwen9b_arbiter"].adapter == "qwen_arbiter"
