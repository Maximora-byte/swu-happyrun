import pytest


@pytest.fixture(autouse=True)
def isolated_host_identity(tmp_path, monkeypatch):
    # Tests never create or reuse the user's real host namespace file.
    monkeypatch.setenv("SWU_HAPPYRUN_HOST_ID_FILE", str(tmp_path / "host-id"))


@pytest.fixture
def symlink_or_skip():
    """Skip only unavailable fixture creation, never product rejection assertions."""
    import errno

    def create(link, target):
        try:
            link.symlink_to(target)
        except NotImplementedError:
            pytest.skip("symlink fixture unavailable: OS operation not implemented")
        except OSError as error:
            if getattr(error, "winerror", None) == 1314:
                pytest.skip("symlink fixture unavailable: Windows privilege WinError 1314")
            if error.errno in {errno.ENOSYS, errno.EOPNOTSUPP, errno.ENOTSUP}:
                pytest.skip("symlink fixture unavailable: OS operation explicitly unsupported")
            raise

    return create
