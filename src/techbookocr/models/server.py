"""Start an OCR model in a docker container with an OpenAI-compatible API."""
from __future__ import annotations

import os
import subprocess
import time
from typing import Callable

import httpx

from techbookocr.config import ConfigError, ModelSpec, ServerConfig

PREFIX = "techbookocr-"


class ServerError(RuntimeError):
    pass


def _http_ok(url: str, headers: dict | None = None) -> bool:
    try:
        return httpx.get(url, timeout=5, headers=headers or {}).status_code == 200
    except httpx.HTTPError:
        return False


def stop_all(run=subprocess.run) -> None:
    ids = run(["docker", "ps", "-aq", "--filter", f"name=^{PREFIX}"], capture_output=True, text=True).stdout.split()
    if ids:
        run(["docker", "rm", "-f", *ids], capture_output=True, text=True)


def gpu_memory_used_mib(run=subprocess.run) -> int:
    out = run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
              capture_output=True, text=True).stdout
    return int(out.split()[0])


class ModelServer:
    def __init__(self, spec: ModelSpec, cfg: ServerConfig, run=subprocess.run,
                 probe: Callable[[str], bool] | None = None, sleep=time.sleep, clock=time.monotonic):
        self.spec, self.cfg = spec, cfg
        self._run, self._probe, self._sleep, self._clock = run, probe or _http_ok, sleep, clock
        self.container = f"{PREFIX}{spec.key}"
        self.base_url = f"http://127.0.0.1:{cfg.port}/v1"

    def docker_cmd(self) -> list[str]:
        hf = os.path.expanduser(self.cfg.hf_cache)
        cmd = ["docker", "run", "-d", "--name", self.container,
               "--device", self.cfg.gpu_device, "--ipc=host",
               "-p", f"127.0.0.1:{self.cfg.port}:8000", "-v", f"{hf}:/root/.cache/huggingface"]
        for k, v in self.spec.env.items():
            cmd += ["-e", f"{k}={v}"]
        return cmd + [self.spec.image, *self.spec.args]

    def start(self) -> None:
        r = self._run(self.docker_cmd(), capture_output=True, text=True)
        if r.returncode != 0:
            raise ServerError(f"docker run failed: {r.stderr.strip()}")

    def _running(self) -> bool:
        r = self._run(["docker", "inspect", "-f", "{{.State.Running}}", self.container], capture_output=True, text=True)
        return r.returncode == 0 and r.stdout.strip() == "true"

    def _logs(self) -> str:
        r = self._run(["docker", "logs", "--tail", "50", self.container], capture_output=True, text=True)
        return (r.stdout + r.stderr).strip()

    def wait_ready(self) -> None:
        deadline = self._clock() + self.cfg.startup_timeout_s
        while self._clock() < deadline:
            if self._probe(f"{self.base_url}/models"):
                return
            if not self._running():
                raise ServerError(f"container {self.container} exited:\n{self._logs()}")
            self._sleep(5)
        logs = self._logs()
        self.stop()
        raise ServerError(f"timeout waiting for {self.container}:\n{logs}")

    def stop(self) -> None:
        self._run(["docker", "rm", "-f", self.container], capture_output=True, text=True)

    def __enter__(self) -> "ModelServer":
        stop_all(self._run)
        try:
            self.start()
            self.wait_ready()
        except BaseException:
            self.stop()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


def api_key(spec: ModelSpec) -> str:
    """API key: the value of the env variable spec.api_key_env (external model) or "EMPTY" (local server)."""
    if not spec.api_key_env:
        return "EMPTY"
    key = os.environ.get(spec.api_key_env)
    if not key:
        raise ServerError(f"{spec.key}: environment variable {spec.api_key_env} is not set")
    return key


class ExternalServer:
    """External model (OpenAI-compatible endpoint): starts and stops nothing, only checks
    {base_url}/models on entry. Used for benchmark comparison; the production pipeline is local."""

    def __init__(self, spec: ModelSpec, cfg: ServerConfig | None = None, probe: Callable[[str], bool] | None = None):
        if not spec.base_url:
            raise ConfigError(f"{spec.key}: external model needs base_url")
        self.spec = spec
        self.base_url = spec.base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {api_key(spec)}"}
        self._probe = probe or (lambda url: _http_ok(url, headers))

    def __enter__(self) -> "ExternalServer":
        if not self._probe(f"{self.base_url}/models"):
            raise ServerError(f"external model {self.spec.key} is not reachable at {self.base_url}")
        return self

    def __exit__(self, *exc) -> None:
        pass


def server_for(spec: ModelSpec, cfg: ServerConfig):
    """Model context: docker container (ModelServer) or external endpoint (ExternalServer)."""
    return ExternalServer(spec, cfg) if spec.base_url else ModelServer(spec, cfg)
