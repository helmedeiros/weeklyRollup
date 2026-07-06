"""Aggregate per-team snapshots into an org-level roll-up.

Walks the configured snapshots directory (default: demo-snapshots/) for a
given ISO week, reads every team's <YYYY>-Www.json, and emits a single
aggregate at <root>/_aggregates/<YYYY>-Www.json with:

- top-level totals across every team
- per-BU totals
- one row per team, sorted deterministically so the dashboard is stable

The aggregate is the single source of truth the dashboard renderer reads;
no dashboard should re-derive team classifications from raw snapshots.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any


BUCKETS = ("done", "spillover_on_track", "spillover_at_risk", "spillover_blocked", "missing")


def _empty_bucket_counts() -> dict[str, int]:
    return {bucket: 0 for bucket in BUCKETS}


def _add_buckets(target: dict[str, int], source: dict[str, int]) -> None:
    for bucket in BUCKETS:
        target[bucket] += int(source.get(bucket, 0) or 0)


def _delivery_rate(totals: dict[str, int]) -> float:
    total_missions = sum(totals.get(bucket, 0) or 0 for bucket in BUCKETS)
    if total_missions <= 0:
        return 0.0
    return round(totals["done"] / total_missions, 4)


def _load_team_snapshots(root: Path, iso_year: int, iso_week: int) -> list[dict[str, Any]]:
    """Return every team's snapshot for the requested week."""
    filename = f"{iso_year}-W{iso_week:02d}.json"
    snapshots: list[dict[str, Any]] = []
    for team_dir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
        candidate = team_dir / filename
        if not candidate.exists():
            continue
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        snapshots.append(payload)
    return snapshots


def build_aggregate(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure function: assembles the aggregate structure from raw team snapshots."""
    org_totals = _empty_bucket_counts()
    bu_totals: dict[str, dict[str, int]] = {}
    team_rows: list[dict[str, Any]] = []
    iso_year = 0
    iso_week = 0
    target_date = ""
    month_label = ""

    for snapshot in snapshots:
        team = snapshot.get("team", {}) or {}
        week = snapshot.get("week", {}) or {}
        totals = snapshot.get("totals", {}) or {}
        business_unit = str(team.get("business_unit") or "Unassigned")
        iso_year = iso_year or int(week.get("iso_year") or 0)
        iso_week = iso_week or int(week.get("iso_week") or 0)
        target_date = target_date or str(week.get("target_date") or "")
        month_label = month_label or str(week.get("month_label") or "")

        team_bucket_counts = {bucket: int(totals.get(bucket, 0) or 0) for bucket in BUCKETS}
        team_row_total = sum(team_bucket_counts.values())
        team_delivery_rate = _delivery_rate(team_bucket_counts)

        team_rows.append({
            "team_id": team.get("id", ""),
            "team_name": team.get("name", ""),
            "business_unit": business_unit,
            "total_missions": team_row_total,
            "delivery_rate": team_delivery_rate,
            **team_bucket_counts,
        })

        _add_buckets(org_totals, team_bucket_counts)
        _add_buckets(bu_totals.setdefault(business_unit, _empty_bucket_counts()), team_bucket_counts)

    org_row_total = sum(org_totals.values())
    org_delivery_rate = _delivery_rate(org_totals)

    # Deterministic sort: highest delivery rate first, then largest mission
    # base, then team name — matches how humans read the screenshot layout.
    team_rows.sort(key=lambda row: (-row["delivery_rate"], -row["total_missions"], row["team_name"]))

    return {
        "schema_version": 1,
        "week": {
            "iso_year": iso_year,
            "iso_week": iso_week,
            "target_date": target_date,
            "month_label": month_label,
        },
        "totals": {
            "teams": len(team_rows),
            "missions": org_row_total,
            "delivery_rate": org_delivery_rate,
            **org_totals,
        },
        "business_units": [
            {
                "business_unit": name,
                "team_count": sum(1 for row in team_rows if row["business_unit"] == name),
                "total_missions": sum(counts.values()),
                "delivery_rate": _delivery_rate(counts),
                **counts,
            }
            for name, counts in sorted(bu_totals.items())
        ],
        "teams": team_rows,
    }


def resolve_week(args: argparse.Namespace) -> tuple[int, int]:
    """Support --week YYYY-Www OR --target-date YYYY-MM-DD."""
    if args.week:
        year_part, week_part = args.week.split("-W")
        return int(year_part), int(week_part)
    if args.target_date:
        parsed = date.fromisoformat(args.target_date)
        year, week, _ = parsed.isocalendar()
        return year, week
    raise SystemExit("Provide --week YYYY-Www or --target-date YYYY-MM-DD")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots-dir", default="demo-snapshots", help="Root directory of per-team snapshots")
    parser.add_argument("--week", help="ISO week label, e.g. 2026-W27")
    parser.add_argument("--target-date", help="Any date inside the target week, e.g. 2026-06-30")
    parser.add_argument("--output-path", help="Override output path; defaults to <root>/_aggregates/<YYYY>-Www.json")
    args = parser.parse_args(argv)

    iso_year, iso_week = resolve_week(args)
    root = Path(args.snapshots_dir)
    snapshots = _load_team_snapshots(root, iso_year, iso_week)
    if not snapshots:
        print(f"No team snapshots found under {root}/ for {iso_year}-W{iso_week:02d}")
        return 1

    aggregate = build_aggregate(snapshots)
    output_path = Path(args.output_path) if args.output_path else (root / "_aggregates" / f"{iso_year}-W{iso_week:02d}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(aggregate, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {output_path} — {aggregate['totals']['teams']} teams, {aggregate['totals']['missions']} missions, delivery rate {aggregate['totals']['delivery_rate'] * 100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
