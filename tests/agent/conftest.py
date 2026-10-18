import pytest


@pytest.fixture(autouse=True)
def isolated_host_identity(tmp_path, monkeypatch):
    # Tests never create or reuse the user's real host namespace file.
    monkeypatch.setenv("SWU_HAPPYRUN_HOST_ID_FILE", str(tmp_path / "host-id"))
