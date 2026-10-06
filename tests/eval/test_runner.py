import json

from PIL import Image

from techbookocr.eval.golden import GoldenPage
from techbookocr.eval.runner import run_model
from techbookocr.models.types import Block, PageResult


class FakeOCR:
    name = "fake"

    def __init__(self, fail_on=()):
        self.seen = []
        self.fail_on = fail_on

    def close(self):
        pass

    def ocr_page(self, image):
        self.seen.append(image.size)
        if image.size[0] in self.fail_on:
            raise RuntimeError("boom")
        return PageResult(markdown="Текст\n", blocks=[Block("Text", "Текст", (0, 0, 1, 1))], raw="{}", seconds=0.5)


def _pages(tmp_path, n):
    out = []
    for i in range(n):
        png = tmp_path / f"p{i}.png"
        Image.new("RGB", (100 + i, 100)).save(png)
        md = tmp_path / f"p{i}.md"
        md.write_text("Текст\n", encoding="utf-8")
        out.append((GoldenPage(id=f"p{i}", book="b", scan=i, side="", categories=("text",)), png, md))
    return out


def test_run_model_writes_and_resumes(tmp_path):
    pages = _pages(tmp_path, 3)
    out = tmp_path / "run"
    ocr = FakeOCR()
    run_model(ocr, pages[:2], out)
    assert len(ocr.seen) == 2
    run_model(ocr, pages, out)  # rerun: compute only p2
    assert len(ocr.seen) == 3
    assert (out / "p2.md").read_text(encoding="utf-8") == "Текст\n"
    meta = json.loads((out / "p0.json").read_text(encoding="utf-8"))
    assert meta["seconds"] == 0.5 and meta["blocks"][0]["category"] == "Text"


def test_exception_recorded_not_raised(tmp_path):
    pages = _pages(tmp_path, 2)
    recs = run_model(FakeOCR(fail_on=(100,)), pages, tmp_path / "run")
    assert recs[0]["error"].startswith("RuntimeError: boom")
    assert (tmp_path / "run" / "p0.md").read_text(encoding="utf-8") == ""
    assert recs[1]["error"] is None


def test_run_candidates_closes_adapter(tmp_path, monkeypatch):
    """Test that run_candidates calls close() on adapters that have it and writes _meta.json."""
    from techbookocr.config import Config, ModelSpec, ServerConfig
    from techbookocr.eval.runner import run_candidates

    # Set up golden pages
    golden = tmp_path / "golden"
    golden.mkdir()
    pages = _pages(golden, 1)
    (golden / "manifest.toml").write_text(
        '[[page]]\nid="p0"\nbook="b"\nscan=0\ncategories=["text"]\n', encoding="utf-8"
    )

    # Track if close was called
    close_called = []

    class FakeAdapterWithClose(FakeOCR):
        def close(self):
            close_called.append(True)

    # Mock make_adapter
    def fake_make_adapter(spec, base_url):
        return FakeAdapterWithClose()

    monkeypatch.setattr("techbookocr.models.registry.make_adapter", fake_make_adapter)

    # Mock gpu_memory_used_mib to avoid actual GPU calls
    monkeypatch.setattr("techbookocr.eval.runner.gpu_memory_used_mib", lambda: 1024)

    # Mock ModelServer context manager
    class FakeServer:
        base_url = "http://fake"
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            pass

    def fake_server_factory(spec, cfg):
        return FakeServer()

    # Run candidates
    cfg = Config(
        server=ServerConfig(),
        models={"fake": ModelSpec(key="fake", adapter="fake", image="fake", model="fake")}
    )
    runs_dir = tmp_path / "runs"
    failed = run_candidates(cfg, ["fake"], golden, runs_dir, server_factory=fake_server_factory)

    # Verify close was called
    assert len(close_called) == 1
    # Verify _meta.json was written
    assert (runs_dir / "fake" / "_meta.json").exists()
    # Verify no failures
    assert failed == []


def test_one_failing_model_doesnt_abort(tmp_path, monkeypatch):
    """Test that one model failure records _failed.txt and continues with next model."""
    from techbookocr.config import Config, ModelSpec, ServerConfig
    from techbookocr.eval.runner import run_candidates

    # Set up golden pages
    golden = tmp_path / "golden"
    golden.mkdir()
    pages = _pages(golden, 1)
    (golden / "manifest.toml").write_text(
        '[[page]]\nid="p0"\nbook="b"\nscan=0\ncategories=["text"]\n', encoding="utf-8"
    )

    # Mock make_adapter
    call_count = [0]
    def fake_make_adapter(spec, base_url):
        call_count[0] += 1
        if spec.key == "fails":
            raise RuntimeError("model server error")
        return FakeOCR()

    monkeypatch.setattr("techbookocr.models.registry.make_adapter", fake_make_adapter)
    monkeypatch.setattr("techbookocr.eval.runner.gpu_memory_used_mib", lambda: 1024)

    class FakeServer:
        base_url = "http://fake"
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            pass

    def fake_server_factory(spec, cfg):
        return FakeServer()

    cfg = Config(
        server=ServerConfig(),
        models={
            "fails": ModelSpec(key="fails", adapter="fake", image="fake", model="fake"),
            "works": ModelSpec(key="works", adapter="fake", image="fake", model="fake"),
        }
    )
    runs_dir = tmp_path / "runs"
    failed = run_candidates(cfg, ["fails", "works"], golden, runs_dir, server_factory=fake_server_factory)

    # Verify failure recorded
    assert failed == ["fails"]
    assert (runs_dir / "fails" / "_failed.txt").exists()
    # Verify second model still ran
    assert (runs_dir / "works" / "p0.md").exists()
    assert (runs_dir / "works" / "p0.json").exists()
    # Verify make_adapter was called for both
    assert call_count[0] == 2


def test_truncated_json_recomputes_page(tmp_path):
    """Test that a truncated .json causes the page to be recomputed."""
    pages = _pages(tmp_path, 2)
    out = tmp_path / "run"

    # First run
    ocr = FakeOCR()
    run_model(ocr, pages, out)
    assert len(ocr.seen) == 2

    # Truncate one JSON file
    json_p0 = out / "p0.json"
    json_p0.write_text("{", encoding="utf-8")  # Invalid JSON

    # Second run with same OCR object but reset seen count
    ocr = FakeOCR()
    run_model(ocr, pages, out)

    # Should recompute p0 (corrupted JSON) but skip p1
    assert len(ocr.seen) == 1
    # Both files should exist and be valid
    assert (out / "p0.md").exists()
    assert (out / "p1.md").exists()
    meta0 = json.loads((out / "p0.json").read_text(encoding="utf-8"))
    assert meta0["seconds"] == 0.5


def test_failed_txt_cleared_on_success(tmp_path, monkeypatch):
    """Test that _failed.txt is removed after a successful run."""
    from techbookocr.config import Config, ModelSpec, ServerConfig
    from techbookocr.eval.runner import run_candidates

    # Set up golden pages
    golden = tmp_path / "golden"
    golden.mkdir()
    pages = _pages(golden, 1)
    (golden / "manifest.toml").write_text(
        '[[page]]\nid="p0"\nbook="b"\nscan=0\ncategories=["text"]\n', encoding="utf-8"
    )

    def fake_make_adapter(spec, base_url):
        return FakeOCR()

    monkeypatch.setattr("techbookocr.models.registry.make_adapter", fake_make_adapter)
    monkeypatch.setattr("techbookocr.eval.runner.gpu_memory_used_mib", lambda: 1024)

    class FakeServer:
        base_url = "http://fake"
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            pass

    def fake_server_factory(spec, cfg):
        return FakeServer()

    cfg = Config(
        server=ServerConfig(),
        models={"test": ModelSpec(key="test", adapter="fake", image="fake", model="fake")}
    )
    runs_dir = tmp_path / "runs"

    # Create a _failed.txt file to simulate previous failure
    (runs_dir / "test").mkdir(parents=True)
    (runs_dir / "test" / "_failed.txt").write_text("previous error", encoding="utf-8")

    # Run should succeed and clear _failed.txt
    failed = run_candidates(cfg, ["test"], golden, runs_dir, server_factory=fake_server_factory)

    assert failed == []
    assert not (runs_dir / "test" / "_failed.txt").exists(), "_failed.txt should be removed after successful run"


class _Flaky(FakeOCR):
    def __init__(self, exc, fail_first=10**9):
        super().__init__()
        self.exc, self.fail_first, self.n = exc, fail_first, 0

    def ocr_page(self, image):
        self.n += 1
        if self.n <= self.fail_first:
            raise self.exc
        return super().ocr_page(image)


def test_transport_error_not_cached_and_retried(tmp_path):
    pages = _pages(tmp_path, 2)
    out = tmp_path / "run"
    ocr = _Flaky(ConnectionError("down"), fail_first=1)
    recs = run_model(ocr, pages, out)
    assert recs[0]["error"].startswith("transport:")
    assert not (out / "p0.json").exists() and not (out / "p0.md").exists()
    assert (out / "p1.json").exists()
    ocr2 = FakeOCR()
    run_model(ocr2, pages, out)  # p0 is recomputed, p1 comes from the cache
    assert len(ocr2.seen) == 1 and (out / "p0.json").exists()


def test_three_consecutive_transport_errors_abort(tmp_path):
    import pytest

    from techbookocr.models.errors import TransportError

    pages = _pages(tmp_path, 5)
    ocr = _Flaky(TransportError("worker dead"))
    with pytest.raises(TransportError, match="3 consecutive"):
        run_model(ocr, pages, tmp_path / "run")
    assert ocr.n == 3
    assert not list((tmp_path / "run").glob("*.json"))


def test_success_resets_transport_streak(tmp_path):
    pages = _pages(tmp_path, 5)

    class Alt(FakeOCR):
        n = 0

        def ocr_page(self, image):
            self.n += 1
            if self.n % 3:
                raise TimeoutError("slow")
            return super().ocr_page(image)

    # fails, fails, ok, fails, fails -> never 3 in a row
    run_model(Alt(), pages, tmp_path / "run")


def test_aborted_model_recorded_as_failed_and_next_continues(tmp_path, monkeypatch):
    from techbookocr.config import Config, ModelSpec, ServerConfig
    from techbookocr.eval.runner import run_candidates
    from techbookocr.models.errors import TransportError

    golden = tmp_path / "golden"
    golden.mkdir()
    _pages(golden, 3)
    (golden / "manifest.toml").write_text(
        "".join(f'[[page]]\nid="p{i}"\nbook="b"\nscan={i}\ncategories=["text"]\n' for i in range(3)), encoding="utf-8")
    monkeypatch.setattr("techbookocr.models.registry.make_adapter",
                        lambda spec, url: _Flaky(TransportError("x")) if spec.key == "bad" else FakeOCR())
    monkeypatch.setattr("techbookocr.eval.runner.gpu_memory_used_mib", lambda: 1)

    class S:
        base_url = "http://f"

        def __enter__(self):
            return self

        def __exit__(self, *e):
            pass

    cfg = Config(server=ServerConfig(), models={k: ModelSpec(key=k, adapter="f", image="i", model="m") for k in ("bad", "good")})
    failed = run_candidates(cfg, ["bad", "good"], golden, tmp_path / "runs", server_factory=lambda s, c: S())
    assert failed == ["bad"] and (tmp_path / "runs" / "good" / "p0.json").exists()
