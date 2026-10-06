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


FIELDS: tuple[Field, ...] = (
    Field("pipeline", "mode", "choice", ("fast", "cascade")),
    Field("library", "dir", "path"),
    Field("render", "min_dpi", "int"),
    Field("render", "max_dpi", "int"),
    Field("render", "split_spreads", "choice", ("auto", "always", "never")),
    Field("library", "auto_summarize", "bool"),
    Field("pipeline", "summarizer_model", "model"),
    Field("library", "command_poll_s", "float"),
    Field("library", "idle_poll_s", "float"),
    Field("pipeline", "sketches_device", "choice", ("cpu", "gpu")),
    Field("pipeline", "webp_quality", "int"),
    Field("pipeline", "text_layer", "choice", ("auto", "force", "off")),
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


def _comments(path: Path) -> dict[tuple[str, str], str]:
    """Inline comments of `key = value  # ...` lines by (section, key); no file -> {}."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    out: dict[tuple[str, str], str] = {}
    cur = None
    for line in lines:
        m = _SECTION.match(line)
        if m:
            cur = m.group(1).strip()
            continue
        kv = _KEYVAL.match(line)
        if cur is not None and kv:
            pos = _comment_at(kv.group(3))
            if pos is not None:
                out[(cur, kv.group(2))] = kv.group(3)[pos + 1:].strip()
    return out


def field_list(path: Path, cfg: Config | None = None) -> list[dict]:
    """Fields for the panel: value, allowed values and the toml line's comment (JSON-compatible)."""
    if cfg is None:
        cfg = load_config(path)
    values = load_values(path, cfg)
    comments = _comments(Path(path))
    out = []
    for f in FIELDS:
        choices = sorted(cfg.models) if f.kind == "model" else list(f.choices)
        v = values[(f.section, f.key)]
        out.append({"section": f.section, "key": f.key, "kind": f.kind, "choices": choices,
                    "value": str(v) if isinstance(v, Path) else v,
                    "comment": comments.get((f.section, f.key))})
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
