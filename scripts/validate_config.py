#!/usr/bin/env python3
"""Validate a objective weekly rollup team config."""

from __future__ import annotations

import argparse
import json

from objective_rollup import load_config, validate_expected_team, validate_team_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="Path to the team YAML/JSON config")
    parser.add_argument("--expect-team-id", help="Fail if config team.id does not match this team")
    parser.add_argument("--expect-team-name", help="Fail if config team.name does not match this team")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    args = parser.parse_args()

    config = load_config(args.config)
    errors = validate_team_config(config)
    errors.extend(
        validate_expected_team(
            config,
            expected_team_id=args.expect_team_id,
            expected_team_name=args.expect_team_name,
        )
    )
    if args.json:
        print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    elif errors:
        print("Config is invalid:")
        for error in errors:
            print(f"- {error}")
    else:
        print("Config is valid.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
