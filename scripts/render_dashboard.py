"""Render a leadership dashboard HTML page from a weekly aggregate JSON.

Reads the aggregate at ``<snapshots-dir>/_aggregates/<YYYY>-Www.json``,
plugs it into ``templates/dashboard.html``, and writes the rendered
static page to ``<snapshots-dir>/_dashboards/<YYYY>-Www.html``.

Default `--snapshots-dir` is ``demo-snapshots``; run with
``--snapshots-dir snapshots`` to render your local dataset.

The output is a fully self-contained HTML file with inline CSS + a
small vanilla-JS BU filter, so it can be published as-is (e.g. via
GitHub Pages) without a build step or JS bundler.
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


def _month_display(month_label: str, target_date: str) -> str:
    """Return a friendly month label like 'June 2026' for the H1."""
    if month_label:
        parts = month_label.replace("objective-", "").split("-")
        if len(parts) == 2:
            month, year = parts
            return f"{month.capitalize()} {year}"
    if target_date:
        try:
            return date.fromisoformat(target_date).strftime("%B %Y")
        except ValueError:
            pass
    return "Weekly"


def render(aggregate: dict[str, Any]) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("dashboard.html")
    aggregate_json = json.dumps(aggregate, ensure_ascii=False)
    return template.render(
        aggregate=aggregate,
        aggregate_json=aggregate_json,
        month_display=_month_display(
            str(aggregate.get("week", {}).get("month_label") or ""),
            str(aggregate.get("week", {}).get("target_date") or ""),
        ),
    )


def resolve_week(args: argparse.Namespace) -> tuple[int, int]:
    if args.week:
        year_part, week_part = args.week.split("-W")
        return int(year_part), int(week_part)
    if args.target_date:
        parsed = date.fromisoformat(args.target_date)
        y, w, _ = parsed.isocalendar()
        return y, w
    raise SystemExit("Provide --week YYYY-Www or --target-date YYYY-MM-DD")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots-dir", default="demo-snapshots")
    parser.add_argument("--week", help="ISO week label, e.g. 2026-W27")
    parser.add_argument("--target-date")
    parser.add_argument("--output-path")
    args = parser.parse_args(argv)

    iso_year, iso_week = resolve_week(args)
    root = Path(args.snapshots_dir)
    aggregate_path = root / "_aggregates" / f"{iso_year}-W{iso_week:02d}.json"
    if not aggregate_path.exists():
        print(f"Aggregate not found: {aggregate_path}. Run aggregate_snapshots.py first.")
        return 1
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))

    html = render(aggregate)
    output_path = Path(args.output_path) if args.output_path else (root / "_dashboards" / f"{iso_year}-W{iso_week:02d}.html")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
