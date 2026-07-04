"""Backfill one weekly rollup for a past Friday.

Fetches the same Jira data the live runner would fetch, then walks each
Epic's changelog to rewind the mutable fields (status, due date, labels,
assignee) to the state they were in at the end of the target Friday. Emits
a snapshot the deterministic runner can consume with
`--jira-source snapshot`.

Progress percentage is not reconstructed — the current child-issue mix is
kept for simplicity, so backfill runs may show slightly higher progress than
the epic actually had on that Friday. Every other visible field on the
rollup is date-accurate.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from mission_rollup import (  # noqa: E402
    compute_week_window,
    get_path,
    load_config,
    month_label,
    validate_team_config,
    validate_expected_team,
)
from run_rollup import (  # noqa: E402
    JiraMcpAdapter,
    collect_jira_snapshot_mission,
    normalize_jira_issue,
)


def parse_jira_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    # Jira emits ISO-8601 with milliseconds and offset like "2026-06-05T16:54:32.328+0200"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            return None


def apply_history(current: Any, histories: list[dict[str, Any]], field_name: str, cutoff: datetime) -> Any:
    """Walk the changelog backwards and undo any change made after `cutoff`.

    Jira changelog entries are strictly per-field; each entry carries
    fromString / toString for the value transition. Iterating from most
    recent to oldest, we revert `toString -> fromString` for changes that
    happened after cutoff, so the returned value reflects the field state
    at cutoff.
    """
    value = current
    changes = []
    for history in histories:
        stamp = parse_jira_datetime(history.get("created"))
        if stamp is None:
            continue
        for item in history.get("items") or []:
            if item.get("field") == field_name:
                changes.append((stamp, item))
    changes.sort(key=lambda entry: entry[0], reverse=True)
    for stamp, item in changes:
        if stamp > cutoff:
            value = item.get("fromString")
        else:
            break
    return value


def apply_history_status(status: dict[str, Any] | None, histories: list[dict[str, Any]], cutoff: datetime) -> dict[str, Any] | None:
    if not isinstance(status, dict):
        return status
    reverted = apply_history(status.get("name"), histories, "status", cutoff)
    if reverted == status.get("name"):
        return status
    new_status = dict(status)
    new_status["name"] = reverted
    # Category lookup is best-effort — map back to the canonical category
    # when the historical name is a known state.
    category_map = {
        "To Do": {"key": "new", "name": "To Do"},
        "In Progress": {"key": "indeterminate", "name": "In Progress"},
        "To Refine": {"key": "new", "name": "To Do"},
        "Done": {"key": "done", "name": "Done"},
    }
    category = category_map.get(str(reverted), None)
    if category:
        new_status["statusCategory"] = category
    return new_status


def apply_history_labels(current: list[str] | None, histories: list[dict[str, Any]], cutoff: datetime) -> list[str]:
    """Labels changelog stores the full label string on both sides."""
    text = " ".join(current or [])
    reverted = apply_history(text, histories, "labels", cutoff)
    return [label for label in (reverted or "").split() if label]


def apply_history_assignee(current: dict[str, Any] | None, histories: list[dict[str, Any]], cutoff: datetime) -> dict[str, Any] | None:
    reverted_name = apply_history(
        (current or {}).get("displayName") if isinstance(current, dict) else None,
        histories,
        "assignee",
        cutoff,
    )
    if reverted_name is None:
        return None
    if isinstance(current, dict) and current.get("displayName") == reverted_name:
        return current
    return {"displayName": reverted_name}


def apply_history_duedate(current: str | None, histories: list[dict[str, Any]], cutoff: datetime) -> str | None:
    reverted = apply_history(current, histories, "duedate", cutoff)
    if not reverted:
        return None
    text = str(reverted)
    # Trim trailing time when Jira stores "2026-06-30 00:00:00.0".
    if " " in text:
        text = text.split(" ", 1)[0]
    return text[:10] if len(text) >= 10 else text


def fetch_issue_with_changelog(adapter: JiraMcpAdapter, issue_key: str) -> dict[str, Any]:
    payload = adapter._call({
        "operation": "issueWithChangelog",
        "issueKey": issue_key,
    })
    return payload


def rewind_mission(
    mission: dict[str, Any],
    raw_issue: dict[str, Any],
    cutoff: datetime,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """Return a mission dict with historical field values, or None if the
    mission did not exist as a labelled June mission at cutoff."""
    fields = raw_issue.get("fields") or {}
    histories = (raw_issue.get("changelog") or {}).get("histories") or []

    # Filter: did the issue exist yet?
    created = parse_jira_datetime(fields.get("created"))
    if created and created > cutoff:
        return None

    # Filter: was the mission-june-2026 label on the issue at cutoff?
    historical_labels = apply_history_labels(fields.get("labels"), histories, cutoff)
    label_pattern = str(get_path(config, "jira.mission_label_pattern", "mission-{month}-{year}"))
    required_label = month_label(cutoff.month, cutoff.year, label_pattern)
    if required_label not in historical_labels:
        return None

    historical_status = apply_history_status(fields.get("status"), histories, cutoff)
    historical_duedate = apply_history_duedate(fields.get("duedate"), histories, cutoff)
    historical_assignee = apply_history_assignee(fields.get("assignee"), histories, cutoff)

    rewound_fields = dict(fields)
    rewound_fields["status"] = historical_status
    rewound_fields["duedate"] = historical_duedate
    rewound_fields["assignee"] = historical_assignee
    rewound_fields["labels"] = historical_labels

    rewound_issue = dict(raw_issue)
    rewound_issue["fields"] = rewound_fields
    return normalize_jira_issue(rewound_issue, config)


def rewind_children(
    children: list[dict[str, Any]],
    adapter: JiraMcpAdapter,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    """Best-effort child rewind: keep only children that already existed and
    revert their status. Progress computation upstream will use these."""
    reverted = []
    for child in children:
        key = child.get("key")
        if not key:
            continue
        try:
            detail = fetch_issue_with_changelog(adapter, str(key))
        except Exception:  # noqa: BLE001
            continue
        cfields = detail.get("fields") or {}
        created = parse_jira_datetime(cfields.get("created"))
        if created and created > cutoff:
            continue
        histories = (detail.get("changelog") or {}).get("histories") or []
        cfields = dict(cfields)
        cfields["status"] = apply_history_status(cfields.get("status"), histories, cutoff)
        rebuilt = dict(child)
        rebuilt["fields"] = cfields
        reverted.append(rebuilt)
    return reverted


def build_snapshot(
    config: dict[str, Any],
    target_date: date,
    adapter: JiraMcpAdapter,
) -> dict[str, Any]:
    tz_name = str(get_path(config, "team.timezone"))
    tz = ZoneInfo(tz_name)
    cutoff = datetime.combine(target_date, time.max, tzinfo=tz)

    window_start, window_end, iso_week = compute_week_window(
        target_date, tz_name, get_path(config, "weekly_update.window")
    )
    label_pattern = str(get_path(config, "jira.mission_label_pattern"))
    label = month_label(target_date.month, target_date.year, label_pattern)

    live_missions = adapter.search_mission_epics(config, label)

    snapshot_missions: list[dict[str, Any]] = []
    for mission in live_missions:
        key = mission.get("key")
        if not key:
            continue
        try:
            detail = fetch_issue_with_changelog(adapter, str(key))
        except Exception as exc:  # noqa: BLE001
            print(f"  skipped {key}: changelog fetch failed ({exc})", file=sys.stderr)
            continue
        rewound = rewind_mission(mission, detail, cutoff, config)
        if rewound is None:
            print(f"  filtered {key}: not a labelled June mission at {target_date}", file=sys.stderr)
            continue
        # Collect properties + comments (comments are filtered to the target
        # week's window by collect_jira_snapshot_mission), plus current
        # children so progress renders. Then rewind the children's status.
        base = collect_jira_snapshot_mission(
            rewound, config, adapter, window_start=window_start, window_end=window_end
        )
        base["children"] = rewind_children(base.get("children") or [], adapter, cutoff)
        snapshot_missions.append(base)

    return {
        "schema_version": 1,
        "source": "jira-mcp-backfill",
        "team": get_path(config, "team.name"),
        "target_date": target_date.isoformat(),
        "month_label": label,
        "iso_week": iso_week,
        "window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "timezone": tz_name,
        },
        "missions": snapshot_missions,
        "errors": [],
        "current_mission_count": len(snapshot_missions),
        "spillover_mission_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--expect-team-id", required=True)
    parser.add_argument("--date", required=True, help="Target Friday, YYYY-MM-DD")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    errors = validate_team_config(config)
    errors.extend(validate_expected_team(config, expected_team_id=args.expect_team_id))
    if errors:
        for err in errors:
            print(f"config error: {err}", file=sys.stderr)
        return 2

    target = date.fromisoformat(args.date)
    adapter = JiraMcpAdapter()
    print(f"Building backfill snapshot for {args.expect_team_id} @ {target}...", file=sys.stderr)
    snapshot = build_snapshot(config, target, adapter)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = output_dir / f"data-snapshot-{target.isoformat()}.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {snapshot_path} with {len(snapshot['missions'])} missions", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
