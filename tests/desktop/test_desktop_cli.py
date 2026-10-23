from unittest.mock import Mock

from swu_happyrun.cli import main


def test_desktop_cli_dispatches_without_real_browser(tmp_path, monkeypatch):
    from swu_happyrun.desktop import launcher

    run = Mock(return_value=0)
    monkeypatch.setattr(launcher, "run", run)
    assert (
        main(["desktop", "--data-dir", str(tmp_path / "desktop"), "--port", "8766", "--no-browser"])
        == 0
    )
    assert run.call_args.kwargs == {
        "root": tmp_path / "desktop",
        "port": 8766,
        "open_browser": False,
    }


def test_invalid_desktop_port_creates_no_state(tmp_path):
    path = tmp_path / "desktop"
    assert main(["desktop", "--data-dir", str(path), "--port", "0"]) == 2
    assert not path.exists()
