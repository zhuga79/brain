"""Validate Brain wiki/raw/task references."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path



try:
    import brain_wiki
except ImportError as exc:
    print(f"ERROR: cannot import brain_wiki: {exc}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Brain wiki/raw contracts.")
    parser.add_argument("--brain", default=os.environ.get("BRAIN_PATH", str(Path.home() / "brain")))
    parser.add_argument("--warnings-as-errors", action="store_true")
    args = parser.parse_args()

    issues = brain_wiki.validate_all(args.brain)
    for issue in issues:
        print(issue.format())

    has_error = any(issue.severity == "ERROR" for issue in issues)
    has_warn = any(issue.severity == "WARN" for issue in issues)
    if has_error or (args.warnings_as_errors and has_warn):
        return 1

    print("OK: Brain validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
