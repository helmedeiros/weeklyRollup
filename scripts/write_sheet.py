#!/usr/bin/env python3
"""Prepare or write the weekly mission sheet tab.

The script keeps the Google Sheets integration behind a seam. In Codex, the
skill should use the Google Drive MCP sheet tools to create/replace the tab and
write the values returned by --dry-run. A direct API adapter can be added later
without changing the business logic.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mission_rollup import get_path, load_config, sheet_file_name, sheet_values, week_tab_name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="Path to team YAML/JSON config")
    parser.add_argument("rows", help="JSON file containing sheet rows without header")
    parser.add_argument("--week", type=int, required=True, help="ISO week number")
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()

    config = load_config(args.config)
    rows = json.loads(Path(args.rows).read_text(encoding="utf-8"))
    tab_name = week_tab_name(args.week, config["sheet"]["tab_name_pattern"])
    values = sheet_values(rows)
    folder_id = str(get_path(config, "sheet.folder_id", ""))
    result = {
        "spreadsheet_id": "",
        "folder_id": folder_id,
        "file_name": sheet_file_name(config),
        "tab_name": tab_name,
        "mode": config["sheet"]["mode"],
        "values": values,
        "spreadsheet_resolution": {
            "strategy": "folder_file_name_then_create",
            "matching_rule": "exact_file_name_in_folder",
            "create_if_missing": True,
            "reuse_existing": True,
        },
    }
    if not args.dry_run:
        result["write_status"] = "not_written"
        result["message"] = (
            "Use the Google Drive MCP sheet tools to create/replace the tab and "
            "write these values, or add a concrete Google Sheets adapter."
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
