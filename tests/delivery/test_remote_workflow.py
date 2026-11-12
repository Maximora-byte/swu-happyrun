"""Regression for GitHub's job-level env expression context restrictions."""

from pathlib import Path


def test_remote_private_directory_is_initialized_in_runner_step():
    workflow = Path(".github/workflows/android-remote-https.yml").read_text()
    assert "${{ runner.temp }}" not in workflow
    assert (
        'echo "HAPPYRUN_REMOTE_PRIVATE_DIR=$RUNNER_TEMP/happyrun-remote-api'
        '$HAPPYRUN_ANDROID_API" >> "$GITHUB_ENV"' in workflow
    )
    assert workflow.index('echo "HAPPYRUN_REMOTE_PRIVATE_DIR=') < workflow.index(
        "Generate temporary QA-only certificate"
    )
    assert "path.parent == pathlib.Path(os.environ['RUNNER_TEMP']).resolve()" in workflow
