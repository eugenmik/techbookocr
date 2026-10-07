"""Editable fields of techbookocr.toml: reading values and line-by-line writing.

Writing goes through the lines of the source file: known `key = value` lines are replaced
(the line's inline comment is kept), missing ones are inserted at the end of their
section, a nonexistent section is created at the end of the file. tomllib is read-only,
there is no full serializer among the dependencies, and editing is limited to a whitelist
of Settings-panel fields.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from techbookocr.config import Config, ConfigError, load_config

_SECTION = re.compile(r"\s*\[([^\]]+)\]")
_KEYVAL = re.compile(r"^(\s*)([A-Za-z0-9_]+)\s*=\s*(.*)$")


@dataclass(frozen=True)
class Field:
    """An editable field: section, key, type and allowed values (for choice)."""
    section: str
    key: str
    kind: str                       # choice | path | int | float | bool | model
    choices: tuple[str, ...] = ()   # for kind="choice"; model: keys of [models.*]
    help: str = ""                  # help text shown in the panel (the panel does not show toml comments)


FIELDS: tuple[Field, ...] = (
    Field("pipeline", "mode", "choice", ("fast", "cascade"),
          "fast: layout model plus arbiter on tables; cascade: a second draft for every block, about 2.5x slower"),
    Field("library", "dir", "path", help="library root: library.sqlite and the book folders"),
    Field("render", "min_dpi", "int", help="lowest resolution a scan page is rendered at"),
    Field("render", "max_dpi", "int", help="highest resolution a scan page is rendered at"),
    Field("render", "split_spreads", "choice", ("auto", "always", "never"),
          "split two-page spreads into separate pages"),
    Field("library", "auto_summarize", "bool", help="the daemon writes a book summary after each assembled book"),
    Field("pipeline", "summarizer_model", "model", help="model that writes book summaries (techbookocr summarize)"),
    Field("library", "command_poll_s", "float", help="how often a running book checks for panel commands, s"),
    Field("library", "idle_poll_s", "float", help="daemon pause between queue checks when the queue is empty, s"),
    Field("pipeline", "sketches_device", "choice", ("cpu", "gpu"),
          "where the detector of drawings in table cells runs"),
    Field("pipeline", "webp_quality", "int", help="WebP quality of cropped figures and scan fragments (1-100)"),
    Field("pipeline", "text_layer", "choice", ("auto", "force", "off"),
          "use the text layer of born-digital PDFs: auto, force or off"),
)

_FIELD_MAP = {(f.section, f.key): f for f in FIELDS}


def _section_values(cfg: Config, section: str):
    """Config section dataclass or the models dict: the source of defaults/values."""
    if section == "models":
        return cfg.models
    return getattr(cfg, section, None)


def load_values(path: Path, cfg: Config | None = None) -> dict[tuple[str, str], object]:
    """Current values of editable fields: toml (path), defaults are the Config dataclasses."""
    if cfg is None:
        try:
            cfg = load_config(path)
        except ConfigError:
            raise
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise ConfigError(f"{path}: {e}") from e
    return {(f.section, f.key): getattr(_section_values(cfg, f.section), f.key, None)
            for f in FIELDS}


def field_list(path: Path, cfg: Config | None = None) -> list[dict]:
    """Fields for the panel: value, allowed values and the field's help text (JSON-compatible).
    The help text comes from the code, so the panel stays the same whatever the toml comments say."""
    if cfg is None:
        cfg = load_config(path)
    values = load_values(path, cfg)
    out = []
    for f in FIELDS:
        choices = sorted(cfg.models) if f.kind == "model" else list(f.choices)
        v = values[(f.section, f.key)]
        out.append({"section": f.section, "key": f.key, "kind": f.kind, "choices": choices,
                    "value": str(v) if isinstance(v, Path) else v,
                    "comment": f.help or None})
    return out


def toml_literal(v) -> str:
    """Value literal in toml: bool/int/float bare, strings quoted."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _coerce(f: Field, v):
    """Coerce a value to the field type; incompatible/outside choices -> ConfigError."""
    try:
        if f.kind == "bool":
            if not isinstance(v, bool):
                raise ValueError
            return v
        if f.kind == "int":
            return int(v)
        if f.kind == "float":
            return float(v)
        v = str(v)
        if f.kind == "choice" and v not in f.choices:
            raise ValueError
        return v
    except (TypeError, ValueError):
        raise ConfigError(f"{f.section}.{f.key}: bad value {v!r}") from None


def _comment_at(line_tail: str) -> int | None:
    """Position of `#` outside quotes in the tail of a `key = ...` line: the start of an inline comment."""
    quote = ""
    esc = False
    for i, ch in enumerate(line_tail):
        if esc:
            esc = False
            continue
        if ch == "\\" and quote == '"':
            esc = True
        elif ch in "\"'":
            if not quote:
                quote = ch
            elif ch == quote:
                quote = ""
        elif ch == "#" and not quote:
            return i
    return None


def save_settings(path: Path, updates: dict[tuple[str, str], object]) -> None:
    """Line-by-line toml edit. updates {(section, key): value}; an unknown key
    or an uncoercible value -> ConfigError, the file is not touched."""
    for k in updates:
        if k not in _FIELD_MAP:
            raise ConfigError(f"{k[0]}.{k[1]}: not an editable setting")
    pending = {k: _coerce(_FIELD_MAP[k], v) for k, v in updates.items()}

    lines = (path.read_text(encoding="utf-8").splitlines(keepends=True)
             if path.exists() else [])
    out: list[str] = []
    cur: str | None = None

    def flush_section() -> None:
        """Insert not yet written keys of the section being left."""
        if cur is None:
            return
        for (sec, key) in [k for k in pending if k[0] == cur]:
            out.append(f"{key} = {toml_literal(pending.pop((sec, key)))}\n")

    for line in lines:
        m = _SECTION.match(line)
        if m:
            flush_section()
            cur = m.group(1).strip()
            out.append(line)
            continue
        kv = _KEYVAL.match(line)
        if cur is not None and kv and (cur, kv.group(2)) in pending:
            value = toml_literal(pending.pop((cur, kv.group(2))))
            tail = kv.group(3)
            pos = _comment_at(tail)
            if pos is None:
                comment = ""
            else:  # spaces between the value and `#` as in the source line
                head = tail[:pos]
                comment = head[len(head.rstrip()):] + tail[pos:].rstrip("\n")
            out.append(f"{kv.group(1)}{kv.group(2)} = {value}{comment}\n")
        else:
            out.append(line)
    flush_section()

    # the section was not in the file: create it at the end
    for (sec, key), value in pending.items():
        if not any(l.strip() == f"[{sec}]" for l in out):
            if out and out[-1].strip():
                out.append("\n")
            out.append(f"[{sec}]\n")
        out.append(f"{key} = {toml_literal(value)}\n")
    path.write_text("".join(out), encoding="utf-8")
