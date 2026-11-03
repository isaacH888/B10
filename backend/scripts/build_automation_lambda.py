"""Copy the Lambda source allowlist, never local secrets or virtual environments."""

import shutil
import sys
from pathlib import Path


def copy_sources(source, target):
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    for name in ("app", "certs"):
        if (source / name).is_dir():
            shutil.copytree(
                source / name,
                target / name,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env", ".env.*"),
            )


if __name__ == "__main__":
    copy_sources(Path(__file__).resolve().parents[1], sys.argv[1])
