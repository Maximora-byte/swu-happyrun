from swu_happyrun.desktop.worker import DesktopWorker
from swu_happyrun.desktop.workspace import Workspace


def test_corrupt_persisted_fake_state_reports_failure_instead_of_connecting(tmp_path):
    workspace = Workspace.open(tmp_path / "desktop")
    path = workspace.root / "fake-state.json"
    path.write_text("{", encoding="utf-8")
    worker = DesktopWorker(workspace, 8765, "synthetic-worker-test-only")
    worker.start()
    worker.thread.join(3)
    assert not worker.thread.is_alive()
    assert worker.status == "needs_attention"
    assert path.read_text(encoding="utf-8") == "{"
