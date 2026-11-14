"""Serve the built React site alongside the existing Flask API."""

import base64
import mimetypes
from pathlib import Path
from urllib.parse import unquote

FRONTEND = Path(__file__).resolve().parent / "frontend"


def handler(event, context):
    request_path = unquote(event.get("path") or "/")
    if request_path == "/api" or request_path.startswith("/api/"):
        from app.automation.runtime import api_handler

        return api_handler(event, context)

    method = event.get("httpMethod", "GET")
    if method not in {"GET", "HEAD"}:
        return {"statusCode": 405, "headers": {"Allow": "GET, HEAD"}, "body": ""}
    if "\x00" in request_path:
        return {"statusCode": 400, "body": ""}

    asset = (FRONTEND / request_path.lstrip("/")).resolve()
    if not asset.is_relative_to(FRONTEND):
        return {"statusCode": 404, "body": ""}
    if not asset.is_file():
        if request_path.startswith("/assets/") or asset.suffix:
            return {"statusCode": 404, "body": ""}
        asset = FRONTEND / "index.html"

    media_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
    cache_control = (
        "public, max-age=31536000, immutable" if asset.parent == FRONTEND / "assets" else "no-cache"
    )
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": media_type,
            "Cache-Control": cache_control,
            "X-Content-Type-Options": "nosniff",
        },
        "body": "" if method == "HEAD" else base64.b64encode(asset.read_bytes()).decode("ascii"),
        "isBase64Encoded": method != "HEAD",
    }
