"""Replace only Lambda code, validate the public build, and restore the saved ZIP on failure."""

import argparse
import base64
import hashlib
import io
import json
import os
import re
import sys
import time
import zipfile
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from verify_site_lambda import frontend_files, verify

FUNCTION = "b10-lab-api"
REGION = "us-east-1"
API_ID = "n2fffdn5h9"
SITE_URL = f"https://{API_ID}.execute-api.{REGION}.amazonaws.com/"
CONFIG_KEYS = (
    "Runtime",
    "Handler",
    "Architectures",
    "PackageType",
    "Role",
    "Environment",
    "MemorySize",
    "Timeout",
    "VpcConfig",
    "Layers",
    "DeadLetterConfig",
    "TracingConfig",
    "FileSystemConfigs",
    "KMSKeyArn",
    "EphemeralStorage",
    "LoggingConfig",
    "SnapStart",
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


def summary(message):
    print(message)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
            output.write(message + "\n\n")


def configuration(config):
    # Never print this mapping: Environment can contain runtime secrets.
    return {key: config.get(key) for key in CONFIG_KEYS}


def validate_configuration(config):
    require(config.get("Runtime") == "python3.12", "Expected Python 3.12; configuration unchanged")
    require(config.get("Handler") == "site_handler.handler", "Unexpected handler; no update")
    require(config.get("Architectures") == ["x86_64"], "Expected x86_64; no update")
    require(config.get("PackageType") == "Zip", "Expected a ZIP Lambda; no update")
    require(not config.get("Layers"), "Layers require a separate size/dependency review; no update")
    require(config.get("State") == "Active", "Lambda is not active; start/check the lab")
    require(
        config.get("LastUpdateStatus") == "Successful", "Lambda already has a pending/failed update"
    )


def validate_gateway(gateway, function_arn):
    integrations = {}
    for page in gateway.get_paginator("get_integrations").paginate(ApiId=API_ID):
        for integration in page.get("Items", []):
            uri = integration.get("IntegrationUri", "")
            # Qualified versions/aliases do not serve the $LATEST code being updated here.
            if uri == function_arn or uri.endswith(f"/functions/{function_arn}/invocations"):
                require(
                    integration.get("PayloadFormatVersion") == "1.0", "API payload must remain 1.0"
                )
                require(integration.get("IntegrationType") == "AWS_PROXY", "Expected Lambda proxy")
                integrations["integrations/" + integration["IntegrationId"]] = True
    routes = {}
    for page in gateway.get_paginator("get_routes").paginate(ApiId=API_ID):
        routes.update({item["RouteKey"]: item.get("Target") for item in page.get("Items", [])})
    default = routes.get("$default") in integrations
    require(default, "Expected the existing $default route to invoke this unqualified Lambda")
    # More-specific routes override $default. Reject any alternate integration or auth change.
    for route, target in routes.items():
        require(
            target in integrations,
            f"Route {route} points elsewhere; review mapping before deploying",
        )
    gateway.get_stage(ApiId=API_ID, StageName="$default")


def read_zip(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate archive paths")
        require(
            sum(info.file_size for info in archive.infolist()) < 250 * 1024**2,
            "ZIP exceeds Lambda size",
        )
        require(
            all(not name.startswith("/") and ".." not in Path(name).parts for name in names),
            "Unsafe ZIP path",
        )
        return {name: archive.read(name) for name in names if not name.endswith("/")}


def distributions(files):
    result = {}
    for name, data in files.items():
        if name.endswith(".dist-info/METADATA"):
            metadata = BytesParser().parsebytes(data)
            key = re.sub(r"[-_.]+", "-", metadata["Name"].lower())
            result[key] = metadata["Version"]
    return result


def assemble(old_data, new_data, commit, reviewed_sha):
    old, new = read_zip(old_data), read_zip(new_data)
    require(
        old.get("site_handler.py") == new.get("site_handler.py") is not None,
        "Deployed site_handler.py differs from reviewed source; stop and reconcile",
    )
    require(
        "app/__init__.py" in old and "frontend/index.html" in old,
        "Existing Lambda layout differs; no update",
    )
    old_migrations = {name: data for name, data in old.items() if name.startswith("migrations/")}
    new_migrations = {name: data for name, data in new.items() if name.startswith("migrations/")}
    changed = sorted(
        name
        for name in old_migrations.keys() | new_migrations.keys()
        if old_migrations.get(name) != new_migrations.get(name)
    )
    if changed:
        summary("Database review required for: " + ", ".join(changed))
        require(
            reviewed_sha == commit,
            "Database files changed. Reconcile live schema/history, then set "
            "B10_MIGRATIONS_REVIEWED_SHA to this exact commit. No migration was run.",
        )
    old_deps, new_deps = distributions(old), distributions(new)
    changed_deps = sorted(
        name
        for name in old_deps.keys() | new_deps.keys()
        if old_deps.get(name) != new_deps.get(name)
    )
    summary(
        "Dependency package rebuilt from pinned requirements. Changed distributions: "
        + (", ".join(changed_deps) or "none")
    )
    # Keep the existing database CA, but never copy unknown code, .env, or local files.
    for name, data in old.items():
        if name.startswith("certs/"):
            require(
                name.endswith(".pem") and b"PRIVATE KEY" not in data,
                "Unexpected certificate material; review separately",
            )
            require(b"-----BEGIN CERTIFICATE-----" in data, "Invalid CA certificate")
            new[name] = data
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(new.items()):
            archive.writestr(name, data)
    result = output.getvalue()
    require(len(result) < 50 * 1024**2, "ZIP exceeds direct-upload limit; review an S3 deployment")
    read_zip(result)
    return result


def wait_settled(client):
    for _ in range(90):
        current = client.get_function_configuration(FunctionName=FUNCTION)
        if current.get("LastUpdateStatus") in {"Successful", "Failed"}:
            return current
        time.sleep(2)
    raise RuntimeError("Lambda update did not finish within three minutes")


def wait_ready(client):
    current = wait_settled(client)
    require(
        current.get("LastUpdateStatus") == "Successful" and current.get("State") == "Active",
        "Lambda code update failed",
    )
    return current


def download_backup(location, expected_digest):
    parsed = urlsplit(location)
    require(
        parsed.scheme == "https" and parsed.hostname.endswith(".amazonaws.com"),
        "Unexpected Lambda download URL",
    )
    # The signed URL is a credential; never log it or pass it as a command argument.
    with urlopen(location, timeout=60) as response:
        data = response.read(50 * 1024**2 + 1)
    require(digest(data) == expected_digest, "Downloaded backup does not match Lambda CodeSha256")
    return data


def deploy(client, gateway, package, commit, reviewed_sha=""):
    require(re.fullmatch(r"[0-9a-f]{40}", commit), "Expected the exact full commit SHA")
    initial = client.get_function(FunctionName=FUNCTION)
    original_config = initial["Configuration"]
    validate_configuration(original_config)
    validate_gateway(gateway, original_config["FunctionArn"])
    old_data = download_backup(initial["Code"]["Location"], original_config["CodeSha256"])
    new_data = assemble(old_data, Path(package).read_bytes(), commit, reviewed_sha)
    old_files, new_files = (
        frontend_files(io.BytesIO(old_data)),
        frontend_files(io.BytesIO(new_data)),
    )
    # A preexisting outage must not be mistaken for a release regression.
    verify(SITE_URL, old_files, attempts=2, delay=5)
    require(json.loads(new_files["/release.json"])["commit"] == commit, "Wrong package commit")
    expected_digest = digest(new_data)
    attempted = False
    try:
        attempted = True
        client.update_function_code(
            FunctionName=FUNCTION,
            ZipFile=new_data,
            RevisionId=original_config["RevisionId"],
            Publish=False,
        )
        current = wait_ready(client)
        require(current["CodeSha256"] == expected_digest, "Live Lambda code hash is incorrect")
        require(
            configuration(current) == configuration(original_config), "AWS configuration drifted"
        )
        verify(SITE_URL, new_files, commit)
        summary(
            f"Deployed and verified `{commit}` at {SITE_URL}; Lambda CodeSha256 `{expected_digest}`."
        )
    except Exception:
        if attempted:
            try:
                current = wait_settled(client)
            except Exception:
                summary(
                    "ROLLBACK STATE UNKNOWN: AWS could not confirm a settled update. "
                    "The candidate may be live; an operator must inspect Lambda when AWS returns."
                )
                raise
            if current["CodeSha256"] == original_config["CodeSha256"]:
                summary(
                    "Deployment failed before code changed; the previous ZIP remains installed."
                )
            elif current["CodeSha256"] == expected_digest:
                summary("Deployment/verification failed; restoring the saved previous ZIP.")
                try:
                    require(
                        configuration(current) == configuration(original_config),
                        "Concurrent configuration change; refusing to overwrite it",
                    )
                    require(
                        current["CodeSha256"] == expected_digest,
                        "Concurrent code change; no rollback",
                    )
                    client.update_function_code(
                        FunctionName=FUNCTION,
                        ZipFile=old_data,
                        RevisionId=current["RevisionId"],
                        Publish=False,
                    )
                    restored = wait_ready(client)
                    require(
                        restored["CodeSha256"] == original_config["CodeSha256"],
                        "Rollback hash differs",
                    )
                    require(
                        configuration(restored) == configuration(original_config),
                        "Rollback config differs",
                    )
                    verify(SITE_URL, old_files)
                    summary(
                        "Rollback verified: the previous frontend and API are healthy. This deployment failed."
                    )
                except Exception:
                    summary(
                        "ROLLBACK FAILED: an operator must inspect Lambda and restore the previous code. "
                        "No database or AWS configuration was changed by this job."
                    )
                    raise
            else:
                summary(
                    "Concurrent code change detected; rollback refused to avoid overwriting another release."
                )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    import boto3

    try:
        deploy(
            boto3.client("lambda", region_name=REGION),
            boto3.client("apigatewayv2", region_name=REGION),
            args.package,
            args.commit,
            os.environ.get("B10_MIGRATIONS_REVIEWED_SHA", ""),
        )
    except Exception as error:
        # AWS SDK responses can contain private details. Log only deliberate local errors.
        message = str(error) if type(error) is RuntimeError else type(error).__name__
        summary(
            f"Deployment FAILED for `{args.commit}`: {message}. "
            "Foundation checks remain independent. Check AWS/lab availability and rerun this run's failed jobs."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
