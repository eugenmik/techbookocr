"""Subprocess with a JSON-lines protocol: the first line is {"ready": true}, then one line per "request -> response".

Never hangs: timeouts on startup and on each request; on failure the process (whole group) is killed and the next
request starts it again. Process failures are TransportError; the process stderr is written to stderr_path."""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path

from techbookocr.models.errors import TransportError


class WorkerTimeout(TransportError):
    pass


class JsonLineWorker:
    label = "worker"

    def __init__(self, worker_cmd: list[str], startup_timeout: float, page_timeout: float, stderr_path: Path):
        self.worker_cmd = worker_cmd
        self.startup_timeout, self.page_timeout = startup_timeout, page_timeout
        self.stderr_path = Path(stderr_path)
        self._proc: subprocess.Popen | None = None
        self._q: queue.Queue | None = None
        self._reader: threading.Thread | None = None

    @staticmethod
    def _pump(stream, q: queue.Queue) -> None:
        try:
            for line in stream:
                q.put(line)
        except (OSError, ValueError):
            pass
        finally:
            q.put(None)

    def _read_json(self, timeout: float) -> dict:
        """Next JSON object line from the process. TransportError if the process exited; WorkerTimeout on timeout."""
        assert self._proc and self._q
        deadline = time.monotonic() + timeout
        while True:
            try:
                line = self._q.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                raise WorkerTimeout(f"{self.label} timeout") from None
            if line is None:
                raise TransportError(f"{self.label} exited with code {self._proc.poll()}")
            line = line.strip()
            if line.startswith("{"):
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, dict):
                    return msg

    def _reset(self) -> None:
        """Kill the process (whole group), wait for it, close the pipes, forget it."""
        proc, reader = self._proc, self._reader
        self._proc = self._q = self._reader = None
        if proc is None:
            return
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        if reader is not None:
            reader.join(timeout=5)
        for f in (proc.stdin, proc.stdout):
            try:
                if f:
                    f.close()
            except (OSError, ValueError):
                pass

    def _ensure_worker(self) -> None:
        """Start the process if it is not running and wait for {"ready": true}."""
        if self._proc and self._proc.poll() is None:
            return
        self._reset()
        self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.stderr_path, "ab") as log:
            self._proc = subprocess.Popen(self.worker_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                          text=True, bufsize=1, start_new_session=True)
        self._q = queue.Queue()
        self._reader = threading.Thread(target=self._pump, args=(self._proc.stdout, self._q), daemon=True)
        self._reader.start()
        if not self._read_json(self.startup_timeout).get("ready"):
            raise TransportError(f"{self.label} did not report ready")

    def request(self, msg: dict, timeout: float | None = None) -> dict:
        """Send a request and wait for the reply. Any process failure is a TransportError and the process is reset."""
        try:
            self._ensure_worker()
            self._proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
            return self._read_json(timeout or self.page_timeout)
        except TransportError:
            self._reset()
            raise
        except (RuntimeError, OSError, ValueError) as e:
            self._reset()
            raise TransportError(f"{self.label} exited: {type(e).__name__}: {e}") from e

    def close(self) -> None:
        """Close: politely first (EOF on stdin), then kill the process group."""
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.stdin.close()
            except (OSError, ValueError):
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        self._reset()
