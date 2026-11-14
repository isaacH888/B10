"""Run inside the Lambda Python 3.12 image against the extracted candidate ZIP."""

import argparse
import base64
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    import _cffi_backend  # noqa: F401
    import cryptography.hazmat.bindings._rust  # noqa: F401
    import rpds  # noqa: F401
    import site_handler

    root = Path(site_handler.__file__).resolve().parent
    release = json.loads((root / "frontend/release.json").read_bytes())
    assert release["commit"] == args.commit
    for path, expected in release["files"].items():
        response = site_handler.handler({"path": path, "httpMethod": "GET"}, None)
        assert response["statusCode"] == 200, path
        assert hashlib.sha256(base64.b64decode(response["body"])).hexdigest() == expected, path
    for path in ("/", "/admin/dashboard"):
        response = site_handler.handler({"path": path, "httpMethod": "GET"}, None)
        assert base64.b64decode(response["body"]) == (root / "frontend/index.html").read_bytes()
    assert (
        site_handler.handler({"path": "/assets/not-present.js", "httpMethod": "GET"}, None)[
            "statusCode"
        ]
        == 404
    )
    response = site_handler.handler(
        {
            "path": "/api/v1/live",
            "httpMethod": "GET",
            "headers": {"Host": "localhost"},
            "requestContext": {"identity": {"sourceIp": "127.0.0.1"}},
        },
        None,
    )
    assert response["statusCode"] == 200
    body = (
        base64.b64decode(response["body"]) if response.get("isBase64Encoded") else response["body"]
    )
    assert json.loads(body)["data"]["status"] == "ok"
    print("Lambda runtime, native imports, frontend manifest and payload 1.0 API passed")


if __name__ == "__main__":
    main()
