"""Enforce feat/* -> dev -> main using pull-request metadata, without shell interpolation."""

import json
import os
from pathlib import Path


def main() -> int:
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        print("Branch policy applies to pull requests.")
        return 0
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    pr = event["pull_request"]
    base, head = pr["base"]["ref"], pr["head"]["ref"]
    if base == "main":
        valid = head == "dev" and pr["head"]["repo"]["full_name"] == pr["base"]["repo"]["full_name"]
    elif base == "dev":
        valid = (head.startswith("feat/") and len(head) > 5) or head.startswith("dependabot/")
    else:
        valid = False
    print(f"Branch policy: {head} -> {base}: {'accepted' if valid else 'rejected'}")
    return int(not valid)


if __name__ == "__main__":
    raise SystemExit(main())
