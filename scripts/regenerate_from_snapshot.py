"""Regenerate a specific format from a stored team snapshot.

Reads a snapshot JSON (as produced by ``run_rollup.py --team-snapshot-dir``
or the demo generator), rebuilds the requested output format, and writes
it to stdout — or, with ``--in-place``, updates ``outputs.email`` inside
the snapshot itself.

Supported formats:

- ``email-html`` (default): the HTML draft used in the dashboard modal
- ``email-text``: plain-text fallback
- ``markdown``:   Confluence-friendly summary

Enrichment mode:

  ``--in-place``
      Also rewrites the snapshot file with fresh ``outputs.email.html``
      and ``outputs.email.text`` bodies, so future dashboard renders pick
      them up automatically.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from email_from_snapshot import (
    build_email_html,
    build_email_text,
    build_markdown,
    synth_leader_engineer_update,
)


def _ensure_updates(snapshot: dict) -> None:
    """Fill in ``objectives[i].update`` if missing, so email rendering works."""
    team_name = snapshot.get("team", {}).get("name", "")
    week = snapshot.get("week", {})
    iso_year = int(week.get("iso_year") or 0)
    iso_week = int(week.get("iso_week") or 0)
    for obj in snapshot.get("objectives", []):
        if not obj.get("update"):
            obj["update"] = synth_leader_engineer_update(obj, team_name, iso_year, iso_week)


def _subject(snapshot: dict) -> str:
    return f"Objectives Rollup — {snapshot.get('team', {}).get('name', '')} — Week {snapshot.get('week', {}).get('iso_week', '')}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--format", choices=["email-html", "email-text", "markdown"], default="email-html")
    parser.add_argument("--output-path", type=Path, help="Write to this file instead of stdout")
    parser.add_argument("--in-place", action="store_true", help="Also write outputs.email back into the snapshot JSON")
    parser.add_argument("--synthesize-updates", action="store_true", help="Fill in any missing per-objective LE updates via the deterministic synthesizer")
    args = parser.parse_args(argv)

    payload = json.loads(args.snapshot.read_text(encoding="utf-8"))
    if args.synthesize_updates:
        _ensure_updates(payload)

    if args.format == "email-html":
        rendered = build_email_html(payload)
    elif args.format == "email-text":
        rendered = build_email_text(payload)
    else:
        rendered = build_markdown(payload)

    if args.output_path:
        args.output_path.parent.mkdir(parents=True, exist_ok=True)
        args.output_path.write_text(rendered, encoding="utf-8")
        print(f"Wrote {args.output_path}")
    else:
        print(rendered)

    if args.in_place:
        outputs = payload.setdefault("outputs", {})
        email = outputs.setdefault("email", {})
        email["subject"] = _subject(payload)
        email["html"] = build_email_html(payload)
        email["text"] = build_email_text(payload)
        args.snapshot.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Updated {args.snapshot} in place with fresh outputs.email")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
