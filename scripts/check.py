"""Run the same local checks required by CI, without network access."""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="Skip the test/coverage run")
    parser.add_argument("--staged", action="store_true", help="Inspect staged repository contents")
    args = parser.parse_args()
    commands = [
        ["scripts/check_repo.py", *(["--staged"] if args.staged else [])],
        ["-m", "ruff", "check", "."],
        ["-m", "ruff", "format", "--check", "."],
        ["-m", "mypy"],
    ]
    if not args.quick:
        commands += [
            ["-m", "coverage", "run", "-m", "unittest", "discover", "-s", "tests", "-q"],
            ["-m", "coverage", "report"],
        ]
    for command in commands:
        print("Checking: " + " ".join(command), flush=True)
        result = subprocess.run([sys.executable, *command], cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
