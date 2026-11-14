"""Verify the exact packaged frontend and read-only API probes over public HTTPS."""

import argparse
import hashlib
import json
import time
import uuid
import zipfile
from pathlib import PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


class VerificationError(RuntimeError):
    """The public website does not match the expected deployment."""


def frontend_files(package):
    with zipfile.ZipFile(package) as archive:
        return {
            "/" + name.removeprefix("frontend/"): archive.read(name)
            for name in archive.namelist()
            if name.startswith("frontend/") and not name.endswith("/")
        }


def fetch(url, path):
    request = Request(
        url.rstrip("/") + quote(path, safe="/") + "?b10_verify=" + uuid.uuid4().hex,
        headers={"Cache-Control": "no-cache", "Accept-Encoding": "identity"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            if (
                response.status != 200
                or urlsplit(response.url).scheme != "https"
                or urlsplit(response.url).netloc != urlsplit(url).netloc
            ):
                raise VerificationError(f"Unexpected status or redirect for {path}")
            return response.read(20 * 1024 * 1024), response.headers.get_content_type()
    except HTTPError as error:
        raise VerificationError(f"{path} returned HTTP {error.code}") from None
    except (URLError, TimeoutError, OSError):
        raise VerificationError(f"Could not reach {path}; check lab and AWS availability") from None


def verify_once(url, files, commit=None, deadline=None):
    def get(path):
        if deadline is not None and time.monotonic() >= deadline:
            raise VerificationError("Verification time budget exceeded; leave time for rollback")
        return fetch(url, path)

    if urlsplit(url).scheme != "https" or urlsplit(url).path not in {"", "/"}:
        raise VerificationError("Use the website's root HTTPS origin")
    if "/index.html" not in files:
        raise VerificationError("Package has no frontend/index.html")
    if commit:
        release = json.loads(files.get("/release.json", b"{}"))
        hashes = {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}
        hashes.pop("/release.json", None)
        if release.get("commit") != commit or release.get("files") != hashes:
            raise VerificationError("Local release manifest does not match packaged frontend")
    # Request / separately: a correct /index.html does not prove the actual landing page.
    for path, expected in {"/": files["/index.html"], **files}.items():
        actual, content_type = get(path)
        if hashlib.sha256(actual).digest() != hashlib.sha256(expected).digest():
            raise VerificationError(f"Live bytes differ from the package at {path}")
        suffix = PurePosixPath(path).suffix
        if suffix in {".js", ".mjs"} and content_type not in {
            "text/javascript",
            "application/javascript",
        }:
            raise VerificationError(f"JavaScript MIME type is incorrect at {path}")
        if (path == "/" or suffix == ".html") and content_type != "text/html":
            raise VerificationError(f"HTML MIME type is incorrect at {path}")
        if suffix == ".css" and content_type != "text/css":
            raise VerificationError(f"CSS MIME type is incorrect at {path}")
    for path in ("/api/v1/live", "/api/v1/health"):
        data, content_type = get(path)
        if content_type != "application/json":
            raise VerificationError(f"API did not return JSON at {path}")
        try:
            status = json.loads(data).get("data", {})
        except (ValueError, AttributeError):
            raise VerificationError(f"Invalid API response at {path}") from None
        if status.get("status") != "ok":
            raise VerificationError(f"API is not healthy at {path}")
        if path.endswith("/health") and status.get("database") != "ok":
            raise VerificationError("MySQL readiness failed")


def verify(url, files, commit=None, attempts=6, delay=10, timeout=180):
    deadline = time.monotonic() + timeout
    for attempt in range(attempts):
        try:
            verify_once(url, files, commit, deadline)
            print(f"Verified frontend bytes and API readiness: {commit or 'previous build'}")
            return
        except (VerificationError, ValueError) as error:
            if attempt + 1 == attempts or time.monotonic() >= deadline:
                raise VerificationError(str(error)) from None
            print(f"Verification attempt {attempt + 1} failed: {error}; retrying")
            time.sleep(min(delay, max(0, deadline - time.monotonic())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--url", default="https://n2fffdn5h9.execute-api.us-east-1.amazonaws.com/")
    parser.add_argument("--commit")
    parser.add_argument("--attempts", type=int, default=6)
    args = parser.parse_args()
    verify(args.url, frontend_files(args.package), args.commit, args.attempts)


if __name__ == "__main__":
    main()
