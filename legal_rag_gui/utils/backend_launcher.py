"""Helper to ensure the FastAPI backend is running for the GUI."""
from __future__ import annotations

import atexit
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import httpx

from .config import SettingsStore

LOGGER = logging.getLogger(__name__)


class BackendProcessManager:
    """Start and stop the bundled FastAPI backend on demand."""

    def __init__(self, settings: SettingsStore) -> None:
        self._settings = settings
        self._process: Optional[subprocess.Popen[bytes]] = None
        self._lock = threading.Lock()
        self._log_handle: Optional[object] = None
        atexit.register(self.shutdown)

    # ------------------------------------------------------------------
    @property
    def port(self) -> int:
        return int(self._settings.data.last_backend_port)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    # ------------------------------------------------------------------
    def ensure_running(self, timeout: float = 10.0) -> bool:
        """Spin up the backend if it is not already reachable."""
        if self._is_alive():
            LOGGER.debug("Backend already reachable at %s", self.base_url)
            return True

        with self._lock:
            if self._is_alive():
                return True
            LOGGER.info("Starting bundled backend server on %s", self.base_url)
            self._spawn_process()

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._is_alive():
                LOGGER.info("Backend server is ready at %s", self.base_url)
                return True
            time.sleep(0.3)

        LOGGER.error("Backend did not become ready within %.1f seconds", timeout)
        self.shutdown()
        return False

    def shutdown(self) -> None:
        with self._lock:
            if self._process and self._process.poll() is None:
                LOGGER.info("Stopping backend server")
                try:
                    self._process.terminate()
                except Exception:
                    self._process.kill()
                try:
                    self._process.wait(timeout=5.0)
                except Exception:
                    self._process.kill()
            if self._log_handle:
                try:
                    self._log_handle.close()  # type: ignore[attr-defined]
                except Exception:
                    pass
            self._process = None
            self._log_handle = None

    # ------------------------------------------------------------------
    def _spawn_process(self) -> None:
        logs_dir = Path(self._settings.data.logs_dir)
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / "backend.log"
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")

        self._log_handle = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "legal_rag_gui.backend.server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
        ]
        project_root = Path(__file__).resolve().parents[2]
        self._process = subprocess.Popen(  # noqa: S603
            cmd,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(project_root),
        )

    def _is_alive(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/health", timeout=0.5)
            return response.status_code == 200
        except Exception:
            return False


__all__ = ["BackendProcessManager"]
