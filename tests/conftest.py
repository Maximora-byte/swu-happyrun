import pytest


@pytest.fixture
def symlink_or_skip():
    """Skip only unavailable fixture creation, never product rejection assertions."""
    import errno

    def create(link, target, *, target_is_directory=False):
        try:
            link.symlink_to(target, target_is_directory=target_is_directory)
        except NotImplementedError:
            pytest.skip("symlink fixture unavailable: OS operation not implemented")
        except OSError as error:
            if getattr(error, "winerror", None) == 1314:
                pytest.skip("symlink fixture unavailable: Windows privilege WinError 1314")
            if error.errno in {errno.ENOSYS, errno.EOPNOTSUPP, errno.ENOTSUP}:
                pytest.skip("symlink fixture unavailable: OS operation explicitly unsupported")
            raise

    return create
