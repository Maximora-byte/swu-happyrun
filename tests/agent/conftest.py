import pytest


@pytest.fixture(autouse=True)
def isolated_host_identity(tmp_path, monkeypatch):
    # Tests never create or reuse the user's real host namespace file.
    monkeypatch.setenv("SWU_HAPPYRUN_HOST_ID_FILE", str(tmp_path / "host-id"))


@pytest.fixture
def stub_command_process(monkeypatch):
    """Adapt parser fixtures to binary Popen pipes; real capture has separate tests."""
    import io
    import subprocess

    def install(response):
        def popen(args, **kwargs):
            result = response(args, **kwargs)

            class CompletedChild:
                stdout = io.BytesIO(result.stdout.encode("utf-8"))
                stderr = io.BytesIO(getattr(result, "stderr", "").encode("utf-8"))
                returncode = result.returncode

                def poll(self):
                    return self.returncode

                def wait(self, timeout=None):
                    return self.returncode

                def kill(self):
                    raise AssertionError("completed fixture must not be killed")

            return CompletedChild()

        monkeypatch.setattr(subprocess, "Popen", popen)

    return install
