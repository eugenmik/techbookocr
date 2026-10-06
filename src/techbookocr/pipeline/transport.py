"""Model transport failures: request retry, counting consecutive failures, aborting the stage."""
from __future__ import annotations

import time
from typing import Callable, TypeVar

from techbookocr.models.errors import TransportError

TRANSPORT_ERRORS = (TransportError, ConnectionError, TimeoutError)
T = TypeVar("T")


class TransportFailed(RuntimeError):
    """The request failed after all retries."""


class StageAborted(RuntimeError):
    """N consecutive failures: the server has probably died. items are the series elements, they must be returned to pending."""

    stage: str | None = None  # filled in by runner

    def __init__(self, message: str, items: list):
        super().__init__(message)
        self.items = list(items)


class TransportGuard:
    def __init__(self, retries: int = 2, max_consecutive: int = 3, backoff_s: float = 5.0,
                 sleep: Callable[[float], None] = time.sleep,
                 control: Callable[[], None] | None = None):
        self.retries, self.max_consecutive, self.backoff_s, self._sleep = retries, max_consecutive, backoff_s, sleep
        self._control = control  # daemon command polling; called before each model request
        self._streak: list = []
        self.failed: list = []  # items with a transport failure: stay pending

    def call(self, fn: Callable[..., T], *args, **kwargs) -> T:
        """fn(*args, **kwargs) with retries on transport failure; TransportFailed if the retries did not help."""
        if self._control:
            self._control()  # pause/stop/skip; non-transport exceptions (RunStopped) propagate outward
        last: BaseException | None = None
        for attempt in range(self.retries + 1):
            try:
                return fn(*args, **kwargs)
            except TRANSPORT_ERRORS as e:
                last = e
                if attempt < self.retries:
                    self._sleep(self.backoff_s)
        raise TransportFailed(f"{type(last).__name__}: {last}") from last

    def success(self) -> None:
        self._streak.clear()


    def failure(self, item) -> None:
        """Record an item failure; after max_consecutive in a row, StageAborted with the whole series."""
        self._streak.append(item)
        self.failed.append(item)
        if len(self._streak) >= self.max_consecutive:
            items, self._streak = self._streak, []
            raise StageAborted(f"{len(items)} consecutive transport failures", items)

    def finish(self) -> None:
        """End of stage: if items with a transport failure remain, the stage is not complete (StageAborted)."""
        if self.failed:
            raise StageAborted(f"{len(self.failed)} items left pending after transport failures", self.failed)
