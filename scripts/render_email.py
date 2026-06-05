#!/usr/bin/env python3
"""Render a draft weekly mission email from normalized mission rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mission_rollup import load_config, render_email_draft


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="Path to team YAML/JSON config")
    parser.add_argument("rows", help="JSON file containing normalized mission rows")
    parser.add_argument("--week", type=int, required=True, help="ISO week number")
    parser.add_argument("--sheet-url", default="")
    parser.add_argument(
        "--body",
        choices=["payload", "html", "text"],
        default="payload",
        help="Which part of the draft to print",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    rows = json.loads(Path(args.rows).read_text(encoding="utf-8"))
    draft = render_email_draft(config, rows, iso_week=args.week, sheet_url=args.sheet_url)
    if args.body == "html":
        print(draft["html_body"])
    elif args.body == "text":
        print(draft["text_body"])
    else:
        print(json.dumps(draft, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
