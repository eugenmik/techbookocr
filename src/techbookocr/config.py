"""Load techbookocr.toml into immutable dataclasses."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

DEFAULT_CONFIG = Path("techbookocr.toml")
SPLIT_MODES = ("auto", "always", "never")


class ConfigError(ValueError):
    """Configuration or book-state error: the user fixes it themselves (CLI: exit code 2)."""


@dataclass(frozen=True)
class RenderConfig:
    min_dpi: int = 300
    max_dpi: int = 600
    split_spreads: str = "auto"
    deskew: bool = True
    crop_borders: bool = True


@dataclass(frozen=True)
class ServerConfig:
    port: int = 8000
    startup_timeout_s: int = 1200
    gpu_device: str = "nvidia.com/gpu=all"
    hf_cache: str = "~/.cache/huggingface"


@dataclass(frozen=True)
class ModelSpec:
    key: str
    adapter: str
    image: str  # docker image; "" for an external model
    model: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    base_url: str | None = None      # external model: OpenAI-compatible endpoint, no docker is started
    api_key_env: str | None = None   # name of the env variable holding the external model's API key


@dataclass(frozen=True)
class PipelineConfig:
    layout_model: str = "dots_mocr"        # layout + draft A
    text_model: str = "hunyuan"            # draft B: text, headings, captions, footnotes, lists, formulas
    table_model: str = "chandra2"          # draft B: tables
    arbiter_model: str = "qwen9b_arbiter"  # arbiter of disputed blocks
    summarizer_model: str = "qwen9b_arbiter"  # book summary (techbookocr summarize): a text request to the same server
    mode: str = "fast"                     # default mode for `techbookocr run`: fast | cascade
    tau_text: float = 0.01                 # CER(A, B) up to which a text block is accepted without the arbiter
    tau_halluc: float = 0.15               # CER(result, nearest draft); above it the arbiter's answer is rejected
    halluc_abs_chars: int = 3              # allowed edit in characters regardless of block length
    crop_pad: int = 12                     # block crop padding, px
    figure_pad: int = 8                    # figure and sketch crop padding, px
    min_line_px: int = 32                  # minimum line height on a crop
    max_upscale: float = 4.0               # crop upscale limit
    sketch_threshold: float = 0.3          # PP-DocLayoutV3 confidence threshold for sketches
    sketches_device: str = "cpu"           # sketch detector device: cpu | gpu (paddlepaddle-gpu)
    text_layer: str = "auto"               # born-digital PDF text layer: auto | force | off
    textlayer_table_conf: float = 0.7      # confidence threshold of table geometry from the layer; below it goes to the arbiter
    textlayer_probe_pages: int = 40        # born-digital probe pages for text_layer=auto
    webp_quality: int = 70                 # lossy WebP quality for the book's images/ (1-100)
    fix_page_crop_max: int = 1600          # long side of a whole-page scan crop for the v key, px
    transport_retries: int = 2             # request retries on a transport failure
    max_consecutive_failures: int = 3      # consecutive failures after which the stage is aborted
    lang_sample_pages: int = 10            # pages used for language detection
    dict_dir: str = "~/.cache/techbookocr/hunspell"
    span_single_value: bool = False        # row with a single value -> colspan (measured 12/15 < 13/15, eval/table-spans.md)
    span_geometry: bool = False            # colspan/dashes from ruling-line geometry on the crop (measurement: eval/table-spans.md)
    column_rule_min_ink: float = 0.6       # share of crop height/width covered by ink for a line to count as a rule
    fix_reject_dictionary_words: bool = True  # an arbiter fix that replaces a dictionary word with another word is reverted
    fix_dictionary_min_len: int = 4        # shorter words are outside this rule (unit abbreviations: pcs, mm, kg)


@dataclass(frozen=True)
class LibraryConfig:
    dir: str = "out"               # library root: library.sqlite and book folders
    command_poll_s: float = 1.0    # how often Control checks for commands between model requests
    idle_poll_s: float = 5.0       # daemon loop pause when the queue is empty
    auto_summarize: bool = True    # after done the daemon generates the book summary (failure: warn, status untouched)


@dataclass(frozen=True)
class Config:
    render: RenderConfig = field(default_factory=RenderConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    models: dict[str, ModelSpec] = field(default_factory=dict)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    library: LibraryConfig = field(default_factory=LibraryConfig)


def _build(cls, section: str, data: dict):
    """cls(**data) with a clear error for unknown keys."""
    known = {f.name for f in fields(cls)}
    for k in data:
        if k not in known:
            raise ConfigError(f"[{section}] unknown key {k!r}")
    return cls(**data)


_MODEL_REQUIRED = ("adapter", "model")
_MODEL_OPTIONAL = ("image", "args", "env", "params", "base_url", "api_key_env")


def _model(key: str, m: dict) -> ModelSpec:
    section = f"models.{key}"
    for req in _MODEL_REQUIRED:
        if req not in m:
            raise ConfigError(f"[{section}] missing {req!r}")
    for k in m:
        if k not in _MODEL_REQUIRED + _MODEL_OPTIONAL:
            raise ConfigError(f"[{section}] unknown key {k!r}")
    if "image" in m and "base_url" in m:
        raise ConfigError(f"[{section}] image and base_url are mutually exclusive")
    if "image" not in m and "base_url" not in m:
        raise ConfigError(f"[{section}] missing 'image'")
    if "image" in m and not m["image"]:
        raise ConfigError(f"[{section}] image must be non-empty")
    if "base_url" in m and not m["base_url"]:
        raise ConfigError(f"[{section}] base_url must be non-empty")
    if "api_key_env" in m and "base_url" not in m:
        raise ConfigError(f"[{section}] api_key_env requires base_url")
    return ModelSpec(key=key, adapter=m["adapter"], image=m.get("image", ""), model=m["model"],
                     args=tuple(m.get("args", ())), env=dict(m.get("env", {})), params=dict(m.get("params", {})),
                     base_url=m.get("base_url"), api_key_env=m.get("api_key_env"))


def load_config(path: Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG
    raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    render = _build(RenderConfig, "render", raw.get("render", {}))
    if render.split_spreads not in SPLIT_MODES:
        raise ConfigError(f"render.split_spreads must be one of {SPLIT_MODES}, got {render.split_spreads!r}")
    server = _build(ServerConfig, "server", raw.get("server", {}))
    models = {key: _model(key, m) for key, m in raw.get("models", {}).items()}
    pipeline = _build(PipelineConfig, "pipeline", raw.get("pipeline", {}))
    if pipeline.mode not in ("fast", "cascade"):
        raise ConfigError(f"[pipeline] mode must be 'fast' or 'cascade', got {pipeline.mode!r}")
    if pipeline.sketches_device not in ("cpu", "gpu"):
        raise ConfigError(f"[pipeline] sketches_device must be 'cpu' or 'gpu', "
                          f"got {pipeline.sketches_device!r}")
    if pipeline.text_layer not in ("auto", "force", "off"):
        raise ConfigError(f"[pipeline] text_layer must be 'auto', 'force' or 'off', "
                          f"got {pipeline.text_layer!r}")
    if not 1 <= pipeline.webp_quality <= 100:
        raise ConfigError(f"[pipeline] webp_quality must be 1..100, got {pipeline.webp_quality!r}")
    library = _build(LibraryConfig, "library", raw.get("library", {}))
    return Config(render=render, server=server, models=models, pipeline=pipeline, library=library)
