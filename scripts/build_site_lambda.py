"""Build the website's Python 3.12/x86_64 Lambda ZIP from reviewed source inputs."""

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

MAX_COMPRESSED_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
EXCLUDED_DIRECTORIES = {
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
}


def source_files(directory):
    """Reject symlinks and omit private environment files and generated caches."""
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError(f"Required input is not a directory: {directory}")
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if any(part in EXCLUDED_DIRECTORIES for part in relative.parts):
            continue
        if path.name == ".env" or path.name.startswith(".env."):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink():
            raise ValueError(f"Symlinks are not deployment inputs: {relative}")
        if path.is_file():
            yield relative.as_posix(), path.read_bytes()


def build_package(repository_root, dependencies, commit, output, certificates=None):
    """Return release manifest and write a deterministic ZIP, never running migrations."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("--commit must be the complete 40-character lowercase Git commit SHA")
    repository_root, output = Path(repository_root), Path(output)
    files = {}

    def add(name, body):
        if name in files:
            raise ValueError(f"Deployment input collision: {name}")
        files[name] = body

    reserved = {"app", "migrations", "frontend", "certs", "site_handler.py"}
    for name, body in source_files(dependencies):
        if name.split("/", 1)[0] in reserved:
            raise ValueError(f"A dependency shadows application source: {name}")
        add(name, body)
    for directory, suffixes in (("app", {".py", ".json"}), ("migrations", {".sql"})):
        for name, body in source_files(repository_root / "backend" / directory):
            if Path(name).suffix in suffixes:
                add(f"{directory}/{name}", body)
    for required in ("app/__init__.py", "app/automation/runtime.py", "app/migrations.py"):
        if required not in files:
            raise ValueError(f"Missing required application source: {required}")
    if not any(name.startswith("migrations/") for name in files):
        raise ValueError("The Lambda package must contain the migration checksum inputs")
    handler = repository_root / "backend/site_handler.py"
    if handler.is_symlink():
        raise ValueError("The Lambda handler cannot be a symlink")
    add("site_handler.py", handler.read_bytes())
    if certificates is not None:
        for name, body in source_files(certificates):
            if Path(name).suffix not in {".pem", ".crt"} or b"PRIVATE KEY" in body:
                raise ValueError("--certificates accepts public PEM/CRT certificates only")
            add(f"certs/{name}", body)

    manifest = {"commit": commit, "files": {}}
    for name, body in source_files(repository_root / "frontend/dist"):
        if name == "release.json":
            raise ValueError("frontend/dist/release.json is reserved for deployment provenance")
        add(f"frontend/{name}", body)
        manifest["files"]["/" + name] = hashlib.sha256(body).hexdigest()
    if "/index.html" not in manifest["files"]:
        raise ValueError("Build frontend/dist/index.html before packaging")
    add("frontend/release.json", (json.dumps(manifest, sort_keys=True) + "\n").encode())
    total = sum(map(len, files.values()))
    if total > MAX_UNCOMPRESSED_BYTES:
        raise ValueError("The uncompressed ZIP exceeds Lambda's 250 MiB limit")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(
            output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for name, body in sorted(files.items()):
                entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, body, compresslevel=9)
        if output.stat().st_size > MAX_COMPRESSED_BYTES:
            raise ValueError("The ZIP exceeds Lambda's 50 MiB direct-upload limit")
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dependencies", type=Path, required=True)
    parser.add_argument("--certificates", type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_package(
        args.repository_root, args.dependencies, args.commit, args.output, args.certificates
    )
    print(
        json.dumps(
            {
                "commit": manifest["commit"],
                "frontend_files": len(manifest["files"]),
                "zip_bytes": args.output.stat().st_size,
                "zip_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    main()
