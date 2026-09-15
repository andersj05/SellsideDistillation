"""Check tracked source contracts and guard against publishing local research data."""

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_ROOTS = {"data", "private_eval", "runs", "exports", ".venv", ".uv-cache"}
ALLOWED_PRIVATE_FILES = {"data/incoming/.gitkeep"}
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
)


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()
    paths = git("ls-files", "-z").decode("utf-8").split("\0")
    errors = []
    for name in filter(None, paths):
        path = PurePosixPath(name)
        if (
            (path.parts[0] in PRIVATE_ROOTS and name not in ALLOWED_PRIVATE_FILES)
            or (path.name.startswith(".env") and path.name != ".env.example")
            or path.suffix.lower() in {".sqlite3", ".db", ".pem", ".key"}
        ):
            errors.append(f"Private data or credential path is tracked: {name}")
            continue
        payload = git("show", ":" + name) if args.staged else (ROOT / name).read_bytes()
        if len(payload) > 2 * 1024 * 1024:
            errors.append(f"Review large files before tracking them: {name}")
        if any(pattern.search(payload) for pattern in SECRET_PATTERNS):
            errors.append(f"Possible credential found in {name}; remove it and rotate it if real")
        try:
            if path.suffix == ".json":
                json.loads(payload)
            elif path.suffix == ".toml" or name == "uv.lock":
                tomllib.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            errors.append(f"Invalid source configuration {name}: {exc}")
    for error in errors:
        print(error, file=sys.stderr)
    print(
        f"Repository content checks: {len(list(filter(None, paths)))} tracked files; {len(errors)} errors."
    )
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
