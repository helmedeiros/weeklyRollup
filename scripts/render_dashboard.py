"""Render the leadership dashboard as a static HTML page.

Reads every per-team snapshot under ``<snapshots-dir>/<team-id>/*.json``,
embeds the raw list into ``templates/dashboard.html``, and writes the
rendered HTML. The template computes the visible aggregate client-side
based on the current date-range picker + business-unit filter.

Default ``--snapshots-dir`` is ``demo-snapshots``; run with
``--snapshots-dir snapshots`` to render your local dataset.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError as exc:  # pragma: no cover - handled at runtime
    raise SystemExit("Jinja2 is required to render the dashboard") from exc


ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"


def load_snapshots(root: Path) -> list[dict[str, Any]]:
    """Return every per-team snapshot under ``root`` sorted by target_date."""
    snapshots: list[dict[str, Any]] = []
    for team_dir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
        for file in sorted(team_dir.glob("*.json")):
            snapshots.append(json.loads(file.read_text(encoding="utf-8")))
    snapshots.sort(key=lambda s: (s.get("week", {}).get("target_date", ""), s.get("team", {}).get("id", "")))
    return snapshots


def collect_business_units(snapshots: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for s in snapshots:
        bu = str(s.get("team", {}).get("business_unit") or "Unassigned")
        seen.setdefault(bu, None)
    return sorted(seen.keys())


def default_range(snapshots: list[dict[str, Any]]) -> tuple[str, str]:
    """Default range = calendar month of the latest snapshot's target_date (inclusive)."""
    if not snapshots:
        today = date.today()
        return today.replace(day=1).isoformat(), today.isoformat()
    latest = max(str(s.get("week", {}).get("target_date") or "") for s in snapshots)
    parsed = date.fromisoformat(latest)
    start = parsed.replace(day=1)
    if parsed.month == 12:
        end = date(parsed.year + 1, 1, 1)
    else:
        end = date(parsed.year, parsed.month + 1, 1)
    # last day inclusive
    last_day = date.fromordinal(end.toordinal() - 1)
    return start.isoformat(), last_day.isoformat()


def render(snapshots: list[dict[str, Any]]) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("dashboard.html")
    default_start, default_end = default_range(snapshots)
    return template.render(
        snapshots_json=json.dumps(snapshots, ensure_ascii=False),
        business_units=collect_business_units(snapshots),
        default_start=default_start,
        default_end=default_end,
        snapshot_count=len(snapshots),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots-dir", default="demo-snapshots")
    parser.add_argument("--output-path", help="Defaults to <snapshots-dir>/_dashboards/index.html")
    args = parser.parse_args(argv)

    root = Path(args.snapshots_dir)
    snapshots = load_snapshots(root)
    if not snapshots:
        print(f"No snapshots found under {root}/")
        return 1
    html = render(snapshots)
    output_path = Path(args.output_path) if args.output_path else (root / "_dashboards" / "index.html")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Wrote {output_path} — {len(snapshots)} snapshots across {len(collect_business_units(snapshots))} business units")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
