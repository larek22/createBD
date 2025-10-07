from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("httpx")

sys.path.append(str(Path(__file__).resolve().parents[2]))

from legal_rag_gui.utils.backend_launcher import BackendProcessManager
from legal_rag_gui.utils.config import SettingsStore


class DummyProcess:
    def __init__(self) -> None:
        self.started = False
        self._terminated = False

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        self._terminated = True

    def kill(self) -> None:  # pragma: no cover - safety net
        self._terminated = True

    def wait(self, timeout: float | None = None) -> None:  # pragma: no cover - not used in test
        return None


@pytest.fixture()
def settings(tmp_path):
    cfg = tmp_path / "config.yaml"
    store = SettingsStore(path=cfg)
    store.update(logs_dir=str(tmp_path / "logs"))
    return store


def test_manager_starts_backend_when_missing(monkeypatch, settings):
    call_state = {"count": 0}

    def fake_get(url: str, timeout: float = 0.5):  # noqa: ARG001
        call_state["count"] += 1
        if call_state["count"] < 3:
            raise OSError("connection refused")
        return SimpleNamespace(status_code=200)

    dummy = DummyProcess()

    def fake_popen(cmd, stdout=None, stderr=None, env=None, cwd=None):  # noqa: ARG001
        dummy.started = True
        return dummy

    monkeypatch.setattr("legal_rag_gui.utils.backend_launcher.httpx.get", fake_get)
    monkeypatch.setattr("legal_rag_gui.utils.backend_launcher.subprocess.Popen", fake_popen)
    monkeypatch.setattr("legal_rag_gui.utils.backend_launcher.time.sleep", lambda *_: None)

    manager = BackendProcessManager(settings)
    assert manager.ensure_running(timeout=0.1) is True
    assert dummy.started is True
    assert call_state["count"] >= 2
