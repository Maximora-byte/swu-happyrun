"""Static delivery guards; these do not substitute for a container build."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_container_is_nonroot_single_process_and_uses_frozen_server_dependencies():
    dockerfile = (ROOT / "deploy/Dockerfile").read_text()
    assert "USER 10001:10001" in dockerfile
    assert "--frozen --extra server --no-dev" in dockerfile
    assert '"server"' in dockerfile
    assert "--workers" not in dockerfile
    assert "COPY . " not in dockerfile


def test_compose_is_loopback_persistent_and_requires_distinct_credentials():
    compose = (ROOT / "deploy/compose.yaml").read_text()
    assert '"127.0.0.1:8080:8080"' in compose
    assert "happyrun-data:/data" in compose
    assert "restart: unless-stopped" in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "privileged:" not in compose


def test_build_context_allowlist_excludes_local_secrets():
    ignore = (ROOT / "deploy/Dockerfile.dockerignore").read_text().splitlines()
    assert ignore[0] == "**"
    assert "!src/**" in ignore
    assert "!uv.lock" in ignore
    assert not any(line.startswith("!local") for line in ignore)
    assert not any(line.startswith("!.env") for line in ignore)


def test_smoke_fixture_has_valid_local_profiles_and_is_simulation_only(tmp_path):
    import importlib.util
    from datetime import UTC, datetime

    from swu_happyrun.core.canonical import profile_revision
    from swu_happyrun.core.models import RouteProfile, SchoolProfile

    spec = importlib.util.spec_from_file_location("smoke", ROOT / "deploy/smoke_fake.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    job = module.create_fixture(tmp_path, "00000000-0000-4000-8000-000000000001")
    assert job.mode == "simulation"
    assert job.not_before <= datetime.now(UTC) < job.deadline
    school = SchoolProfile.model_validate_json(
        next((tmp_path / "profiles/schools").rglob("*.json")).read_text()
    )
    route = RouteProfile.model_validate_json(
        next((tmp_path / "profiles/routes").rglob("*.json")).read_text()
    )
    assert profile_revision(school) == job.profile_revision
    assert profile_revision(route) == job.route_revision
    assert school.campus == "synthetic-only"
    assert route.source_ref == "synthetic-only"


def test_environment_template_contains_no_working_credentials():
    lines = (ROOT / "deploy/.env.example").read_text().splitlines()
    settings = [line for line in lines if line and not line.startswith("#")]
    assert settings == ["HAPPYRUN_ADMIN_TOKEN=", "HAPPYRUN_AGENT_TOKENS="]


def test_ci_distribution_upload_is_narrow_and_after_install_verification():
    workflow = (ROOT / ".github/workflows/checks.yml").read_text()
    assert workflow.index("scripts/check_install.py") < workflow.index("sha256sum")
    assert workflow.count("if: matrix.os == 'ubuntu-latest' && matrix.python == '3.11'") == 2
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in workflow
    assert "name: candidate-${{ github.sha }}" in workflow
    assert "if-no-files-found: error" in workflow
    assert "retention-days: 7" in workflow
    paths = workflow.split("          path: |\n")[1].split("          if-no-files-found:")[0]
    assert paths.split() == ["dist/*.whl", "dist/*.tar.gz", "dist/SHA256SUMS"]


def test_container_probe_checks_readiness_not_only_liveness():
    dockerfile = (ROOT / "deploy/Dockerfile").read_text()
    probe = dockerfile.split("HEALTHCHECK", 1)[1].split("CMD [", 1)[0]
    assert "/api/v1/ready" in probe
    assert "/api/v1/health" not in probe
