#!/usr/bin/env python3
"""Parse a weekly DRI update comment from stdin or a file."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from mission_rollup import parse_update


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", help="Text file to parse. Defaults to stdin.")
    parser.add_argument("--minimum-score", type=int, default=4)
    args = parser.parse_args()

    if args.path:
        body = Path(args.path).read_text(encoding="utf-8")
    else:
        body = sys.stdin.read()

    parsed = parse_update(body, minimum_score=args.minimum_score)
    print(json.dumps(asdict(parsed), indent=2, ensure_ascii=False))
    return 0 if parsed.template_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
