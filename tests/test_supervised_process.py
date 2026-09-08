from app.supervised_process import FailureWindow
import subprocess
import sys
from types import SimpleNamespace
from app import supervised_process


def test_sustained_failure_exits_but_transient_failure_recovers():
    window = FailureWindow(180)
    assert not window.expired(False, 0)
    assert not window.expired(False, 179)
    assert not window.expired(True, 180)
    assert not window.expired(False, 181)
    assert not window.expired(False, 360)
    assert window.expired(False, 361)


def test_unhealthy_child_is_terminated_and_parent_returns_failure(monkeypatch, tmp_path):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        monkeypatch.setattr(sys, "argv", ["supervisor", "domain"])
        monkeypatch.setenv("WORKER_HEALTH_FILE", str(tmp_path / "health.json"))
        monkeypatch.setattr(supervised_process.subprocess, "Popen", lambda *a, **k: child)
        monkeypatch.setattr(supervised_process.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
        monkeypatch.setattr(supervised_process, "FailureWindow", lambda _: FailureWindow(0))
        monkeypatch.setattr(supervised_process.signal, "signal", lambda *a: None)
        assert supervised_process.main() == 1
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
