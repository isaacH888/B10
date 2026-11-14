"""Deployment failure recovery and public frontend/API verification without AWS writes."""

import copy
import hashlib
import importlib
import io
import json
import zipfile
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest

COMMIT = "a" * 40
URL = "https://n2fffdn5h9.execute-api.us-east-1.amazonaws.com/"


@pytest.fixture
def deployment_modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("deploy_site_lambda"), importlib.import_module(
        "verify_site_lambda"
    )


def archive_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return stream.getvalue()


def site_files(label, *, release=False, migration=b"-- unchanged schema\n"):
    files = {
        "site_handler.py": b"# same reviewed handler\n",
        "app/__init__.py": b"# application\n",
        "migrations/0001_auth.sql": migration,
        "flask-3.1.3.dist-info/METADATA": b"Name: Flask\nVersion: 3.1.3\n",
        "frontend/index.html": f'<script src="/assets/{label}.js"></script>'.encode(),
        f"frontend/assets/{label}.js": f"console.log('{label}');".encode(),
        "frontend/assets/site.css": b"body{margin:0}",
        "frontend/assets/logo.png": b"\x89PNG\x00\xff",
    }
    if release:
        manifest = {
            "commit": COMMIT,
            "files": {
                "/" + name.removeprefix("frontend/"): hashlib.sha256(body).hexdigest()
                for name, body in files.items()
                if name.startswith("frontend/")
            },
        }
        files["frontend/release.json"] = json.dumps(manifest).encode()
    return files


class FakeLambda:
    """A code-only Lambda API with optimistic revision checks and immediate completion."""

    def __init__(self, module, old_data):
        self.module = module
        self.code = old_data
        self.updates = []
        self.fail_update_number = None
        self.config = {
            "FunctionArn": "arn:aws:lambda:us-east-1:123456789012:function:b10-lab-api",
            "Runtime": "python3.12",
            "Handler": "site_handler.handler",
            "Architectures": ["x86_64"],
            "PackageType": "Zip",
            "State": "Active",
            "LastUpdateStatus": "Successful",
            "CodeSha256": module.digest(old_data),
            "RevisionId": "revision-0",
            "Role": "arn:aws:iam::123456789012:role/existing-runtime-role",
            "Environment": {"Variables": {"DB_PASSWORD": "synthetic-secret-must-not-print"}},
            "MemorySize": 512,
            "Timeout": 30,
            "VpcConfig": {"SubnetIds": ["subnet-original"], "SecurityGroupIds": ["sg-original"]},
            "Layers": [],
        }

    def get_function(self, **kwargs):
        assert kwargs == {"FunctionName": self.module.FUNCTION}
        return {
            "Configuration": copy.deepcopy(self.config),
            "Code": {"Location": "https://snapshot.s3.amazonaws.com/private-signed-url"},
        }

    def get_function_configuration(self, **kwargs):
        assert kwargs == {"FunctionName": self.module.FUNCTION}
        return copy.deepcopy(self.config)

    def update_function_code(self, **kwargs):
        self.updates.append(kwargs)
        if self.fail_update_number == len(self.updates):
            raise RuntimeError("synthetic rollback update failed")
        assert set(kwargs) == {"FunctionName", "ZipFile", "RevisionId", "Publish"}
        assert kwargs["FunctionName"] == self.module.FUNCTION
        assert kwargs["RevisionId"] == self.config["RevisionId"]
        assert kwargs["Publish"] is False
        self.code = kwargs["ZipFile"]
        self.config["CodeSha256"] = self.module.digest(self.code)
        self.config["RevisionId"] = f"revision-{len(self.updates)}"
        return copy.deepcopy(self.config)


class FakeGateway:
    def __init__(self, function_arn, payload_version="1.0"):
        self.pages = {
            "get_integrations": [
                {
                    "Items": [
                        {
                            "IntegrationId": "existing",
                            "IntegrationUri": function_arn,
                            "PayloadFormatVersion": payload_version,
                            "IntegrationType": "AWS_PROXY",
                        }
                    ]
                }
            ],
            "get_routes": [
                {"Items": [{"RouteKey": "$default", "Target": "integrations/existing"}]}
            ],
        }

    def get_paginator(self, name):
        return Mock(paginate=Mock(return_value=self.pages[name]))

    def get_stage(self, **kwargs):
        assert kwargs == {"ApiId": "n2fffdn5h9", "StageName": "$default"}
        return {"StageName": "$default", "AutoDeploy": True}


@pytest.fixture
def deployment_case(deployment_modules, tmp_path, monkeypatch):
    deploy, verifier = deployment_modules
    old_files = site_files("old")
    old_files["certs/rds-ca.pem"] = b"-----BEGIN CERTIFICATE-----\npublic-ca\n"
    old_data = archive_bytes(old_files)
    package = tmp_path / "new.zip"
    package.write_bytes(archive_bytes(site_files("new", release=True)))
    client = FakeLambda(deploy, old_data)
    gateway = FakeGateway(client.config["FunctionArn"])
    monkeypatch.setattr(deploy, "download_backup", Mock(return_value=old_data))
    monkeypatch.setattr(deploy, "verify", Mock())
    return deploy, verifier, client, gateway, package, old_data


def test_deploys_exact_commit_and_preserves_all_existing_configuration(deployment_case, capsys):
    deploy, verifier, client, gateway, package, old_data = deployment_case
    original = deploy.configuration(copy.deepcopy(client.config))
    deploy.deploy(client, gateway, package, COMMIT)
    assert len(client.updates) == 1
    assert deploy.configuration(client.config) == original
    installed = deploy.read_zip(client.code)
    assert installed["certs/rds-ca.pem"] == deploy.read_zip(old_data)["certs/rds-ca.pem"]
    assert json.loads(installed["frontend/release.json"])["commit"] == COMMIT
    assert deploy.verify.call_args_list[0].args[:2] == (
        URL,
        verifier.frontend_files(io.BytesIO(old_data)),
    )
    assert deploy.verify.call_args_list[1].args == (
        URL,
        verifier.frontend_files(io.BytesIO(client.code)),
        COMMIT,
    )
    assert "synthetic-secret-must-not-print" not in capsys.readouterr().out


def test_migration_review_gate_rejects_before_any_update(deployment_case):
    deploy, _, client, gateway, package, _ = deployment_case
    package.write_bytes(
        archive_bytes(site_files("new", release=True, migration=b"-- changed schema\n"))
    )
    with pytest.raises(RuntimeError, match="B10_MIGRATIONS_REVIEWED_SHA"):
        deploy.deploy(client, gateway, package, COMMIT)
    assert client.updates == []
    deploy.verify.assert_not_called()


def test_failed_new_build_verification_restores_saved_zip_and_still_fails(deployment_case, capsys):
    deploy, verifier, client, gateway, package, old_data = deployment_case
    deploy.verify.side_effect = [None, verifier.VerificationError("new assets stale"), None]
    with pytest.raises(verifier.VerificationError, match="new assets stale"):
        deploy.deploy(client, gateway, package, COMMIT)
    assert len(client.updates) == 2
    assert client.updates[1]["ZipFile"] == old_data
    assert client.code == old_data
    assert deploy.verify.call_count == 3
    assert "Rollback verified" in capsys.readouterr().out


def test_rollback_failure_is_reported_and_propagated(deployment_case, capsys):
    deploy, verifier, client, gateway, package, _ = deployment_case
    client.fail_update_number = 2
    deploy.verify.side_effect = [None, verifier.VerificationError("API readiness failed")]
    with pytest.raises(RuntimeError, match="synthetic rollback update failed"):
        deploy.deploy(client, gateway, package, COMMIT)
    assert len(client.updates) == 2
    assert "ROLLBACK FAILED" in capsys.readouterr().out


def test_concurrent_code_change_is_never_overwritten_by_rollback(deployment_case, capsys):
    deploy, verifier, client, gateway, package, _ = deployment_case

    def verify_live(*args, **kwargs):
        if len(args) == 3:
            client.code = b"another operator's deployment"
            client.config["CodeSha256"] = deploy.digest(client.code)
            client.config["RevisionId"] = "other-operator-revision"
            raise verifier.VerificationError("concurrent live build")

    deploy.verify.side_effect = verify_live
    with pytest.raises(verifier.VerificationError, match="concurrent live build"):
        deploy.deploy(client, gateway, package, COMMIT)
    assert len(client.updates) == 1
    assert client.code == b"another operator's deployment"
    assert "Concurrent code change detected; rollback refused" in capsys.readouterr().out


def test_gateway_payload_v2_is_rejected_before_any_update(deployment_case):
    deploy, _, client, _, package, _ = deployment_case
    gateway = FakeGateway(client.config["FunctionArn"], payload_version="2.0")
    with pytest.raises(RuntimeError, match="payload must remain 1.0"):
        deploy.deploy(client, gateway, package, COMMIT)
    assert client.updates == []
    deploy.download_backup.assert_not_called()


def test_uncertain_update_waits_past_old_hash_then_restores_accepted_candidate(
    deployment_case, monkeypatch, capsys
):
    deploy, _, client, gateway, package, old_data = deployment_case
    original_config = copy.deepcopy(client.config)
    original_update = client.update_function_code
    reads = []

    def uncertain_update(**kwargs):
        result = original_update(**kwargs)
        if len(client.updates) == 1:
            raise TimeoutError("AWS accepted the update but the response was lost")
        return result

    def eventually_settled(**kwargs):
        reads.append(kwargs)
        if len(reads) == 1:
            return dict(original_config, LastUpdateStatus="InProgress")
        return copy.deepcopy(client.config)

    monkeypatch.setattr(client, "update_function_code", uncertain_update)
    monkeypatch.setattr(client, "get_function_configuration", eventually_settled)
    monkeypatch.setattr(deploy.time, "sleep", Mock())
    with pytest.raises(TimeoutError, match="response was lost"):
        deploy.deploy(client, gateway, package, COMMIT)
    assert len(client.updates) == 2
    assert len(reads) == 3
    assert client.code == old_data
    assert client.updates[1]["ZipFile"] == old_data
    output = capsys.readouterr().out
    assert "Rollback verified" in output
    assert "failed before code changed" not in output


def test_terminal_failed_update_restores_previous_zip_after_in_progress(
    deployment_case, monkeypatch, capsys
):
    deploy, _, client, gateway, package, old_data = deployment_case
    reads = []

    def failed_then_restored(**kwargs):
        reads.append(kwargs)
        current = copy.deepcopy(client.config)
        if len(reads) == 1:
            current["LastUpdateStatus"] = "InProgress"
        elif len(reads) in {2, 3}:
            current["LastUpdateStatus"] = "Failed"
        return current

    monkeypatch.setattr(client, "get_function_configuration", failed_then_restored)
    monkeypatch.setattr(deploy.time, "sleep", Mock())
    with pytest.raises(RuntimeError, match="Lambda code update failed"):
        deploy.deploy(client, gateway, package, COMMIT)
    assert len(client.updates) == 2
    assert len(reads) == 4
    assert client.code == old_data
    assert "Rollback verified" in capsys.readouterr().out


def test_aws_loss_during_update_recovery_reports_unknown_live_state(
    deployment_case, monkeypatch, capsys
):
    deploy, _, client, gateway, package, old_data = deployment_case
    original_update = client.update_function_code

    def response_lost(**kwargs):
        original_update(**kwargs)
        raise TimeoutError("initial update response lost")

    pending = dict(client.config, LastUpdateStatus="InProgress")
    monkeypatch.setattr(client, "update_function_code", response_lost)
    monkeypatch.setattr(
        client,
        "get_function_configuration",
        Mock(side_effect=[pending, ConnectionError("AWS is now unavailable")]),
    )
    monkeypatch.setattr(deploy.time, "sleep", Mock())
    with pytest.raises(ConnectionError, match="AWS is now unavailable"):
        deploy.deploy(client, gateway, package, COMMIT)
    assert len(client.updates) == 1
    assert client.code != old_data
    output = capsys.readouterr().out
    assert "ROLLBACK STATE UNKNOWN" in output
    assert "candidate may be live" in output
    assert "Rollback verified" not in output


@pytest.fixture
def candidate_module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("check_deploy_candidate")


def newer_run(event="push", attempt=1):
    return {
        "id": 200,
        "run_number": 20,
        "run_attempt": attempt,
        "head_sha": "b" * 40,
        "event": event,
        "html_url": "https://github.com/isaacH888/B10/actions/runs/200",
    }


def test_candidate_gate_rejects_older_commit_when_newer_commit_passed_all_checks(
    candidate_module, monkeypatch
):
    run = newer_run()
    jobs = [{"name": name, "conclusion": "success"} for name in candidate_module.REQUIRED_JOBS]
    api = Mock(side_effect=[{"workflow_runs": [run]}, {"jobs": jobs}])
    monkeypatch.setattr(candidate_module, "api", api)
    with pytest.raises(RuntimeError, match="A newer DEV commit " + "b" * 40):
        candidate_module.check_candidate(COMMIT, 10)
    assert api.call_args_list[1].args[0] == ("actions/runs/200/attempts/1/jobs?per_page=100&page=1")


def test_candidate_gate_allows_latest_passing_commit_when_newer_commit_failed_a_check(
    candidate_module, monkeypatch
):
    jobs = [
        {
            "name": name,
            "conclusion": "failure" if name == "Contract and backend integration" else "success",
        }
        for name in candidate_module.REQUIRED_JOBS
    ]
    api = Mock(side_effect=[{"workflow_runs": [newer_run()]}, {"jobs": jobs}])
    monkeypatch.setattr(candidate_module, "api", api)
    candidate_module.check_candidate(COMMIT, 10)
    assert api.call_count == 2


def test_candidate_gate_excludes_newer_pull_request_checks(candidate_module, monkeypatch):
    api = Mock(return_value={"workflow_runs": [newer_run(event="pull_request")]})
    monkeypatch.setattr(candidate_module, "api", api)
    candidate_module.check_candidate(COMMIT, 10)
    assert api.call_count == 1


def test_candidate_gate_inherits_passing_checks_from_before_deployment_only_rerun(
    candidate_module, monkeypatch
):
    successful_checks = [
        {"name": name, "conclusion": "success"} for name in candidate_module.REQUIRED_JOBS
    ]
    api = Mock(
        side_effect=[
            {"workflow_runs": [newer_run(attempt=2)]},
            {"jobs": [{"name": "Deploy existing website", "conclusion": "failure"}]},
            {"jobs": successful_checks},
        ]
    )
    monkeypatch.setattr(candidate_module, "api", api)
    with pytest.raises(RuntimeError, match="A newer DEV commit " + "b" * 40):
        candidate_module.check_candidate(COMMIT, 10)
    assert [call.args[0] for call in api.call_args_list[1:]] == [
        "actions/runs/200/attempts/2/jobs?per_page=100&page=1",
        "actions/runs/200/attempts/1/jobs?per_page=100&page=1",
    ]


def test_candidate_gate_latest_attempt_failure_overrides_earlier_passing_check(
    candidate_module, monkeypatch
):
    successful_checks = [
        {"name": name, "conclusion": "success"} for name in candidate_module.REQUIRED_JOBS
    ]
    api = Mock(
        side_effect=[
            {"workflow_runs": [newer_run(attempt=2)]},
            {"jobs": [{"name": "Contract and backend integration", "conclusion": "failure"}]},
            {"jobs": successful_checks},
        ]
    )
    monkeypatch.setattr(candidate_module, "api", api)
    candidate_module.check_candidate(COMMIT, 10)
    assert api.call_count == 3


def frontend_manifest(verifier):
    return verifier.frontend_files(io.BytesIO(archive_bytes(site_files("new", release=True))))


def public_fetch(files):
    def fetch(url, path):
        assert url == URL
        if path in {"/api/v1/live", "/api/v1/health"}:
            return b'{"data":{"status":"ok","database":"ok"}}', "application/json"
        body = files["/index.html" if path == "/" else path]
        suffix = Path(path).suffix
        return body, {
            ".js": "application/javascript",
            ".css": "text/css",
            ".png": "image/png",
            ".json": "application/json",
        }.get(suffix, "text/html")

    return fetch


def test_verifier_checks_every_manifest_file_root_and_both_api_probes(
    deployment_modules, monkeypatch
):
    _, verifier = deployment_modules
    files = frontend_manifest(verifier)
    fetch = Mock(side_effect=public_fetch(files))
    monkeypatch.setattr(verifier, "fetch", fetch)
    verifier.verify_once(URL, files, COMMIT)
    assert {call.args[1] for call in fetch.call_args_list} == {
        "/",
        *files,
        "/api/v1/live",
        "/api/v1/health",
    }


def test_verifier_detects_stale_binary_asset_even_with_current_commit(
    deployment_modules, monkeypatch
):
    _, verifier = deployment_modules
    files = frontend_manifest(verifier)
    live = dict(files, **{"/assets/logo.png": b"old logo bytes"})
    monkeypatch.setattr(verifier, "fetch", public_fetch(live))
    with pytest.raises(verifier.VerificationError, match="/assets/logo.png"):
        verifier.verify_once(URL, files, COMMIT)


def test_verifier_rejects_manifest_tampering_before_network_requests(
    deployment_modules, monkeypatch
):
    _, verifier = deployment_modules
    files = frontend_manifest(verifier)
    files["/assets/new.js"] = b"changed after manifest was built"
    fetch = Mock()
    monkeypatch.setattr(verifier, "fetch", fetch)
    with pytest.raises(verifier.VerificationError, match="Local release manifest"):
        verifier.verify_once(URL, files, COMMIT)
    fetch.assert_not_called()


def test_verifier_health_503_is_a_failed_deployment(deployment_modules, monkeypatch):
    _, verifier = deployment_modules
    files = frontend_manifest(verifier)
    fetch = public_fetch(files)

    def unavailable_health(url, path):
        if path == "/api/v1/health":
            raise verifier.VerificationError("/api/v1/health returned HTTP 503")
        return fetch(url, path)

    monkeypatch.setattr(verifier, "fetch", unavailable_health)
    with pytest.raises(verifier.VerificationError, match="HTTP 503"):
        verifier.verify(URL, files, COMMIT, attempts=1, delay=0)


def test_fetch_converts_real_http_503_to_safe_error(deployment_modules, monkeypatch):
    _, verifier = deployment_modules
    monkeypatch.setattr(
        verifier,
        "urlopen",
        Mock(side_effect=HTTPError(URL, 503, "private backend response", {}, None)),
    )
    with pytest.raises(verifier.VerificationError, match="/api/v1/health returned HTTP 503"):
        verifier.fetch(URL, "/api/v1/health")


def test_verification_time_budget_leaves_time_for_rollback(deployment_modules, monkeypatch):
    _, verifier = deployment_modules
    fetch = Mock()
    monkeypatch.setattr(verifier, "fetch", fetch)
    with pytest.raises(verifier.VerificationError, match="time budget exceeded"):
        verifier.verify(URL, frontend_manifest(verifier), COMMIT, timeout=0)
    fetch.assert_not_called()
