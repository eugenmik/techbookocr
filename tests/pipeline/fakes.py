"""Model stubs and helpers for pipeline tests (no GPU)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from techbookocr.models.types import Block, BlockResult, PageResult
from techbookocr.pipeline.state import BookState, PageEntry


def NO_SLEEP(seconds: float) -> None:
    pass


def page_png(path: Path, size: tuple[int, int] = (1000, 1400), lines: int = 10) -> Path:
    """White page with black bars ("lines") 20 px high, 60 px apart, starting at y=100."""
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    for i in range(lines):
        y = 100 + i * 60
        d.rectangle([100, y, size[0] - 100, y + 19], fill="black")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def new_state(tmp_path: Path, names=("0001", "0002"), size=(1000, 1400)) -> BookState:
    """state.sqlite in tmp_path/work and page images work/pages/<name>.png."""
    work = tmp_path / "work"
    entries = []
    for i, name in enumerate(names):
        page_png(work / "pages" / f"{name}.png", size)
        entries.append(PageEntry(name=name, idx=i, scan=i, side="", file=f"pages/{name}.png",
                                 width=size[0], height=size[1]))
    st = BookState(work / "state.sqlite")
    st.add_pages(entries)
    return st


class FakePageOCR:
    """ocr_page returns replies in turn (the last one repeats); an exception in the list is raised."""

    def __init__(self, replies: list, name: str = "fake-layout"):
        self.name, self.replies, self.calls, self.closed = name, list(replies), 0, False

    def ocr_page(self, image) -> PageResult:
        self.calls += 1
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(r, BaseException):
            raise r
        return r

    def close(self) -> None:
        self.closed = True


class FakeBlockOCR:
    """ocr_block(image, kind) -> reply(image, kind): BlockResult or an exception."""

    def __init__(self, reply=None, name: str = "fake-drafts"):
        self.name, self.calls, self.closed = name, [], False
        self.reply = reply or (lambda image, kind: BlockResult(text=f"B:{kind}"))

    def ocr_block(self, image, kind) -> BlockResult:
        self.calls.append((image.size, kind))
        r = self.reply(image, kind)
        if isinstance(r, BaseException):
            raise r
        return r

    def close(self) -> None:
        self.closed = True


class FakeVLM:
    """ask(image, prompt) -> reply(prompt): BlockResult or an exception."""

    vision = True

    def __init__(self, reply, name: str = "fake-arbiter"):
        self.name, self.reply, self.calls, self.closed = name, reply, [], False

    def ask(self, image, prompt, *, max_tokens=None) -> BlockResult:
        self.calls.append((image.size, prompt, max_tokens))
        r = self.reply(prompt)
        if isinstance(r, BaseException):
            raise r
        return r

    def close(self) -> None:
        self.closed = True


class FakeDetector:
    """detect(image) -> reply(image): (regions, error) or an exception."""

    def __init__(self, reply, name: str = "fake-detector"):
        self.name, self.reply, self.calls, self.closed = name, reply, [], False

    def detect(self, image):
        self.calls.append(image.size)
        r = self.reply(image)
        if isinstance(r, BaseException):
            raise r
        return r

    def close(self) -> None:
        self.closed = True


# --- whole run without GPU, docker, network and paddle ---

TEXT = "Чугун марки СЧ20 содержит углерод."
TABLE_A = "<table><tr><td>15—25</td></tr></table>"
TABLE_B = "<table><tr><td><img></td><td>15—25</td></tr></table>"
LAYOUT = PageResult(markdown="", seconds=1.0, blocks=[
    Block("Text", TEXT, (100, 100, 900, 120)), Block("Table", TABLE_A, (100, 220, 900, 400)),
    Block("Formula", "$$x^2$$", (100, 460, 900, 480)), Block("Page-footer", "12", (450, 1300, 550, 1350))])


class Servers:
    """server_factory: records which models were started, launches nothing."""

    def __init__(self):
        self.started: list[str] = []

    def __call__(self, spec, server_cfg):
        started = self.started

        class _Ctx:
            base_url = f"http://fake/{spec.key}/v1"

            def __enter__(self):
                started.append(spec.key)
                return self

            def __exit__(self, *exc):
                pass

        return _Ctx()


def fake_adapters(layout=LAYOUT, arbiter=None):
    """adapter_factory: dots_mocr -> layout, hunyuan -> text/formula, chandra2 -> table, otherwise the arbiter."""
    def make(spec, base_url):
        if spec.key == "dots_mocr":
            return FakePageOCR([layout])
        if spec.key == "hunyuan":
            return FakeBlockOCR(lambda img, kind: BlockResult("x^{2}" if kind == "formula" else TEXT, seconds=0.5))
        if spec.key == "chandra2":
            return FakeBlockOCR(lambda img, kind: BlockResult(TABLE_B, seconds=0.5))
        return arbiter or FakeVLM(lambda prompt: BlockResult(
            (TABLE_B if "one table block" in prompt else TEXT) + "\nFIXES: []", seconds=1.0))
    return make


def fake_deps(servers, adapters) -> dict:
    """Dependencies of run_pages/run_book: a sketch (32,32)-(132,132) in the crop coordinates of every table."""
    from techbookocr.models.doclayout import Region

    return dict(server_factory=servers, adapter_factory=adapters,
                detector_factory=lambda **kw: FakeDetector(lambda img: ([Region("image", 0.9, (32, 32, 132, 132))], None)),
                speller_factory=lambda langs, cache_dir, log: None, sleep=NO_SLEEP, echo=None)
