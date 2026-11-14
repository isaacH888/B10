"""Website packaging and the existing API Gateway 1.0 handler contract."""

import base64
import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest
import site_handler
from app.automation import runtime
from flask import Flask, request


def packager():
    script = Path(__file__).resolve().parents[2] / "scripts/build_site_lambda.py"
    spec = importlib.util.spec_from_file_location("build_site_lambda", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def package_inputs(tmp_path):
    root = tmp_path / "repo"
    sources = {
        "backend/site_handler.py": Path(site_handler.__file__).read_bytes(),
        "backend/app/__init__.py": b"# application\n",
        "backend/app/automation/runtime.py": b"# adapter\n",
        "backend/app/migrations.py": b"# migration checksums\n",
        "backend/app/data/locations.json": b"{}",
        "backend/app/pricing.config.json": b"{}",
        "backend/migrations/0001_auth.sql": b"-- migration\n",
        "frontend/dist/index.html": b'<div id="root"></div><script src="/assets/app.js"></script>',
        "frontend/dist/assets/app.js": b"console.log('synthetic build');",
        "frontend/dist/assets/logo.png": b"\x89PNG\x00\xff",
        "backend/app/.env.private": b"synthetic-private-value",
        "backend/app/__pycache__/app.pyc": b"synthetic-cache",
        "backend/tests/test_private.py": b"synthetic-test",
        "backend/.env": b"synthetic-private-value",
    }
    for name, body in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    dependencies = tmp_path / "dependencies"
    dependencies.mkdir()
    (dependencies / "flask.py").write_text("# installed dependency\n")
    return root, dependencies, tmp_path / "site.zip"


def test_package_has_exact_layout_manifest_and_reproducible_metadata(package_inputs):
    root, dependencies, output = package_inputs
    builder = packager()
    manifest = builder.build_package(root, dependencies, "a" * 40, output)
    first = output.read_bytes()
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            "site_handler.py",
            "app/__init__.py",
            "app/automation/runtime.py",
            "app/migrations.py",
            "app/data/locations.json",
            "app/pricing.config.json",
            "migrations/0001_auth.sql",
            "flask.py",
            "frontend/index.html",
            "frontend/assets/app.js",
            "frontend/assets/logo.png",
            "frontend/release.json",
        }
        assert json.loads(archive.read("frontend/release.json")) == manifest
        assert manifest["commit"] == "a" * 40
        for name, digest in manifest["files"].items():
            assert hashlib.sha256(archive.read("frontend" + name)).hexdigest() == digest
    builder.build_package(root, dependencies, "a" * 40, output)
    assert output.read_bytes() == first


def test_package_rejects_dependency_shadowing_and_oversize_inputs(package_inputs, monkeypatch):
    root, dependencies, output = package_inputs
    builder = packager()
    (dependencies / "site_handler.py").write_text("# dependency collision\n")
    with pytest.raises(ValueError, match="shadows"):
        builder.build_package(root, dependencies, "a" * 40, output)
    (dependencies / "site_handler.py").unlink()
    monkeypatch.setattr(builder, "MAX_UNCOMPRESSED_BYTES", 1)
    with pytest.raises(ValueError, match="250 MiB"):
        builder.build_package(root, dependencies, "a" * 40, output)
    monkeypatch.setattr(builder, "MAX_UNCOMPRESSED_BYTES", 100000)
    monkeypatch.setattr(builder, "MAX_COMPRESSED_BYTES", 1)
    with pytest.raises(ValueError, match="50 MiB"):
        builder.build_package(root, dependencies, "a" * 40, output)
    assert not output.exists()


def test_package_rejects_ambiguous_commit_and_symlinks(package_inputs):
    root, dependencies, output = package_inputs
    builder = packager()
    with pytest.raises(ValueError, match="complete 40-character"):
        builder.build_package(root, dependencies, "dev", output)
    (root / "frontend/dist/assets/private").symlink_to(root / "backend/.env")
    with pytest.raises(ValueError, match="Symlinks"):
        builder.build_package(root, dependencies, "a" * 40, output)


def test_existing_handler_serves_spa_binary_assets_and_404s(package_inputs, monkeypatch):
    root, _, _ = package_inputs
    frontend = root / "frontend/dist"
    monkeypatch.setattr(site_handler, "FRONTEND", frontend.resolve())
    index = (frontend / "index.html").read_bytes()
    for path in ("/", "/admin/orders/abc"):
        result = site_handler.handler({"path": path, "httpMethod": "GET"}, None)
        assert result["statusCode"] == 200
        assert base64.b64decode(result["body"]) == index
        assert result["headers"]["Content-Type"] == "text/html"
    asset = site_handler.handler({"path": "/assets/logo.png", "httpMethod": "GET"}, None)
    assert base64.b64decode(asset["body"]) == b"\x89PNG\x00\xff"
    assert "immutable" in asset["headers"]["Cache-Control"]
    head = site_handler.handler({"path": "/assets/logo.png", "httpMethod": "HEAD"}, None)
    assert head["statusCode"] == 200 and head["body"] == ""
    for path in ("/assets/missing.js", "/missing.png", "/%2e%2e/backend/.env"):
        assert site_handler.handler({"path": path}, None)["statusCode"] == 404
    assert site_handler.handler({"path": "/", "httpMethod": "POST"}, None)["statusCode"] == 405


def test_site_handler_dispatches_v1_queries_and_multiple_cookies(monkeypatch):
    app = Flask(__name__)

    @app.get("/api/v1/live")
    def edge():
        response = app.json.response(
            data={
                "status": "ok",
                "values": request.args.getlist("value"),
                "owner": request.cookies.get("owner"),
            }
        )
        response.set_cookie("one", "a", secure=True, httponly=True)
        response.set_cookie("two", "b", secure=True, httponly=True)
        return response

    monkeypatch.setattr(runtime, "_application", app)
    result = site_handler.handler(
        {
            "version": "1.0",
            "path": "/api/v1/live",
            "httpMethod": "GET",
            "headers": {"Host": "example.invalid"},
            "multiValueHeaders": {"Cookie": ["owner=synthetic", "other=second"]},
            "multiValueQueryStringParameters": {"value": ["a", "b"]},
        },
        None,
    )
    assert result["statusCode"] == 200
    assert len(result["multiValueHeaders"]["Set-Cookie"]) == 2
    assert json.loads(base64.b64decode(result["body"])) == {
        "data": {"status": "ok", "values": ["a", "b"], "owner": "synthetic"}
    }
