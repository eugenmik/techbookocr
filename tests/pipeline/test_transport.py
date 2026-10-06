import pytest

from techbookocr.models.errors import TransportError
from techbookocr.pipeline.transport import StageAborted, TransportFailed, TransportGuard


def _down():
    raise TransportError("down")


def test_guard_retries_then_succeeds():
    sleeps, calls = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise TransportError("down")
        return "ok"

    assert TransportGuard(retries=2, sleep=sleeps.append).call(flaky) == "ok"
    assert len(calls) == 3 and sleeps == [5.0, 5.0]


def test_guard_gives_up_after_retries():
    with pytest.raises(TransportFailed, match="TransportError: down"):
        TransportGuard(retries=1, sleep=lambda s: None).call(_down)


def test_guard_does_not_swallow_other_errors():
    def bad():
        raise ValueError("bug")

    with pytest.raises(ValueError):
        TransportGuard(sleep=lambda s: None).call(bad)


def test_guard_aborts_after_consecutive_failures():
    g = TransportGuard(max_consecutive=3)
    g.failure("a")
    g.success()
    g.failure("b")
    g.failure("c")
    with pytest.raises(StageAborted) as e:
        g.failure("d")
    assert e.value.items == ["b", "c", "d"]
