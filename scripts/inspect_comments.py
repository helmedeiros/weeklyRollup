#!/usr/bin/env python3
"""Inspect Jira comments against the weekly DRI update parser."""

from __future__ import annotations

import argparse
from datetime import date
from textwrap import indent
from typing import Any

from mission_rollup import (
    assert_valid_config,
    author_matches,
    comment_body_to_text,
    compute_week_window,
    display_dri,
    find_latest_valid_dri_comment,
    get_path,
    is_deleted_or_internal,
    is_reply_comment,
    load_config,
    month_label,
    parse_jira_datetime,
    parse_update,
)
from run_rollup import FixtureJiraAdapter, JiraMcpAdapter, parse_update_options


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to the team YAML/JSON config")
    parser.add_argument("--date", required=True, help="Run date in YYYY-MM-DD format")
    parser.add_argument(
        "--jira-source",
        choices=("fixture", "mcp", "snapshot"),
        default="mcp",
        help="Where to read Jira mission Epics/comments from",
    )
    parser.add_argument("--jira-fixture", help="Fixture JSON path when --jira-source=fixture")
    parser.add_argument("--jira-snapshot", help="Data snapshot JSON path when --jira-source=snapshot")
    args = parser.parse_args()

    config = load_config(args.config)
    assert_valid_config(config)
    target_date = date.fromisoformat(args.date)
    window_start, window_end, _iso_week = compute_week_window(
        target_date,
        str(get_path(config, "team.timezone")),
        get_path(config, "weekly_update.window"),
    )
    label = month_label(
        target_date.month,
        target_date.year,
        str(get_path(config, "jira.mission_label_pattern")),
    )
    parse_options = parse_update_options(get_path(config, "weekly_update.validation", {}))
    if args.jira_source == "fixture":
        adapter = FixtureJiraAdapter(args.jira_fixture)
    elif args.jira_source == "snapshot":
        adapter = FixtureJiraAdapter(args.jira_snapshot)
    else:
        adapter = JiraMcpAdapter()

    missions = sorted(adapter.search_mission_epics(config, label), key=lambda item: str(item.get("key", "")))
    print(f"Mission label: {label}")
    print(f"Window: {window_start.isoformat()} -> {window_end.isoformat()}")
    print(f"Mission Epics: {len(missions)}")
    print()

    for mission in missions:
        comments = adapter.get_comments(mission, window_start, window_end)
        selection = find_latest_valid_dri_comment(
            comments,
            mission.get("dri"),
            window_start,
            window_end,
            parse_options=parse_options,
        )
        selected_id = str(selection.selected_comment.get("id")) if selection.selected_comment else ""
        mission_name = mission.get("name") or mission.get("summary") or ""
        print(f"{mission['key']} - {mission_name}")
        print(f"DRI: {display_dri(mission.get('dri'))}")
        print(f"Comments returned: {len(comments)}")
        if not comments:
            print("No comments returned by Jira for this Epic.")
            print()
            continue

        for comment in comments:
            diagnostic = diagnose_comment(comment, mission.get("dri"), window_start, window_end, parse_options)
            marker = "PASS"
            if not diagnostic["passes"]:
                marker = "FAIL"
            elif str(comment.get("id", "")) == selected_id:
                marker = "PASS selected"
            else:
                marker = "PASS older valid"

            print(f"- Comment {comment.get('id', '<unknown>')} [{marker}]")
            print(f"  Author: {diagnostic['author']}")
            print(f"  Created: {diagnostic['created']}")
            print(f"  Reason: {diagnostic['reason']}")
            if diagnostic.get("parsed"):
                parsed = diagnostic["parsed"]
                print(
                    "  Parsed: "
                    f"status={parsed['status'] or ''}, "
                    f"score={parsed['score']}/4, "
                    f"template_valid={'yes' if parsed['template_valid'] else 'no'}"
                )
                if parsed["missing_sections"]:
                    print(f"  Missing sections: {', '.join(parsed['missing_sections'])}")
                if parsed["errors"]:
                    print(f"  Parser errors: {'; '.join(parsed['errors'])}")
            print("  Body:")
            print(indent(diagnostic["body"] or "<empty>", "    "))
        print()

    return 0


def diagnose_comment(
    comment: dict[str, Any],
    dri: dict[str, Any] | None,
    window_start,
    window_end,
    parse_options: dict[str, Any],
) -> dict[str, Any]:
    author = comment.get("author", {}) or {}
    body = comment_body_to_text(comment.get("body"))
    created = parse_jira_datetime(comment.get("created") or comment.get("updated"))
    created_label = str(comment.get("created") or comment.get("updated") or "")
    if created:
        created_label = created.astimezone(window_start.tzinfo).isoformat()

    base = {
        "author": author.get("displayName") or author.get("emailAddress") or author.get("accountId") or "",
        "created": created_label,
        "body": body.strip(),
        "passes": False,
        "reason": "",
        "parsed": None,
    }

    if is_deleted_or_internal(comment):
        return {**base, "reason": "deleted or internal comment"}
    if is_reply_comment(comment):
        return {**base, "reason": "reply comment"}
    if not body.strip():
        return {**base, "reason": "empty body"}
    if not author_matches(author, dri):
        return {**base, "reason": "author is not the mission DRI"}
    if created is None:
        return {**base, "reason": "missing or unparsable timestamp"}
    local_created = created.astimezone(window_start.tzinfo)
    if not (window_start <= local_created <= window_end):
        return {**base, "reason": "outside weekly window"}

    parsed = parse_update(body, **parse_options)
    parsed_summary = {
        "status": parsed.status,
        "score": parsed.score,
        "template_valid": parsed.template_valid,
        "missing_sections": parsed.missing_sections,
        "errors": parsed.errors,
    }
    if not parsed.template_valid:
        reason = "malformed weekly update"
        if parsed.errors:
            reason += ": " + "; ".join(parsed.errors)
        return {**base, "reason": reason, "parsed": parsed_summary}

    return {**base, "passes": True, "reason": "valid weekly DRI update", "parsed": parsed_summary}


if __name__ == "__main__":
    raise SystemExit(main())
