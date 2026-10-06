import os
from types import SimpleNamespace

import pytest

from techbookocr.config import ModelSpec, ServerConfig
from techbookocr.models.server import ModelServer, ServerError


class FakeRun:
    def __init__(self, running: bool = True):
        self.calls: list[list[str]] = []
        self.running = running

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[:2] == ["docker", "inspect"]:
            return SimpleNamespace(returncode=0, stdout="true\n" if self.running else "false\n", stderr="")
        if cmd[:2] == ["docker", "logs"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="CUDA out of memory")
        return SimpleNamespace(returncode=0, stdout="abc\n", stderr="")


SPEC = ModelSpec(key="dots", adapter="dots", image="vllm/vllm-openai:v0.11.0", model="dots",
                 args=("--model", "rednote-hilab/dots.mocr", "--trust-remote-code"), env={"A": "1"})
CFG = ServerConfig(port=8011, startup_timeout_s=30, gpu_device="nvidia.com/gpu=all", hf_cache="~/.cache/huggingface")


def test_docker_cmd():
    cmd = ModelServer(SPEC, CFG, run=FakeRun()).docker_cmd()
    hf = os.path.expanduser("~/.cache/huggingface")
    assert cmd[:5] == ["docker", "run", "-d", "--name", "techbookocr-dots"]
    assert "--device" in cmd and cmd[cmd.index("--device") + 1] == "nvidia.com/gpu=all"
    assert "127.0.0.1:8011:8000" in cmd
    assert f"{hf}:/root/.cache/huggingface" in cmd
    assert "A=1" in cmd
    i = cmd.index("vllm/vllm-openai:v0.11.0")
    assert cmd[i + 1:] == ["--model", "rednote-hilab/dots.mocr", "--trust-remote-code"]


def test_wait_ready_success():
    probes = iter([False, False, True])
    s = ModelServer(SPEC, CFG, run=FakeRun(), probe=lambda url: next(probes), sleep=lambda s: None)
    s.wait_ready()


def test_wait_ready_fails_fast_when_container_died():
    t = iter(range(1000))
    s = ModelServer(SPEC, CFG, run=FakeRun(running=False), probe=lambda url: False,
                    sleep=lambda s: None, clock=lambda: next(t))
    with pytest.raises(ServerError, match="CUDA out of memory"):
        s.wait_ready()


def test_wait_ready_timeout():
    t = iter(range(0, 10000, 10))
    s = ModelServer(SPEC, CFG, run=FakeRun(), probe=lambda url: False, sleep=lambda s: None, clock=lambda: next(t))
    with pytest.raises(ServerError, match="timeout"):
        s.wait_ready()


def test_stop_removes_container():
    run = FakeRun()
    ModelServer(SPEC, CFG, run=run).stop()
    assert ["docker", "rm", "-f", "techbookocr-dots"] in run.calls


def test_stop_all_filter_is_anchored():
    from techbookocr.models.server import stop_all

    run = FakeRun()
    stop_all(run)
    assert ["docker", "ps", "-aq", "--filter", "name=^techbookocr-"] in run.calls


def test_enter_cleans_up_on_keyboard_interrupt():
    run = FakeRun()

    def probe(url):
        raise KeyboardInterrupt

    s = ModelServer(SPEC, CFG, run=run, probe=probe, sleep=lambda s: None)
    with pytest.raises(KeyboardInterrupt):
        s.__enter__()
    assert run.calls[-1] == ["docker", "rm", "-f", "techbookocr-dots"]
