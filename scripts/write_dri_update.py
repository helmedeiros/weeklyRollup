"""Interactive helper to write a template-valid DRI weekly mission update and
post it as a Jira comment via the bundled Jira MCP.

Usage:
    python3 scripts/write_dri_update.py --config config/<team>-local.yaml \
        --expect-team-id <team-id> --date YYYY-MM-DD

The flow is:
1. Load + validate the team config.
2. Query the Jira MCP for Epics carrying this month's mission label.
3. Show a menu with each Epic's current weekly-update state
   (missing / malformed / valid <status emoji>) plus DRI name.
4. Prompt the user to pick one.
5. Open $EDITOR per section (Status, Done this week, Target for next week,
   Blockers / Risks). Status accepts an emoji or word.
6. Render the template, validate with the same parse_update the rollup uses,
   refuse to post until it is template-valid.
7. Build the ADF body (status emoji as an ADF emoji node, prose as paragraphs)
   and post via JiraMcpAdapter.add_comment after y/n confirmation.

The posted comment is authored by whichever user is authenticated in the
bundled jira-mcp. When that user is not the Epic assignee, the rollup's
cover_authors flag tags the update as a cover-author comment.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from mission_rollup import (  # noqa: E402
    STATUS_EMOJI,
    STATUS_GREEN,
    STATUS_RED,
    STATUS_YELLOW,
    compute_week_window,
    display_dri,
    find_latest_valid_dri_comment,
    get_path,
    load_config,
    month_label,
    normalize_status,
    parse_update,
    validate_expected_team,
    validate_team_config,
)
from run_rollup import parse_update_options  # noqa: E402

STATUS_TO_EMOJI = {
    STATUS_GREEN: "\U0001F7E2",
    STATUS_YELLOW: "\U0001F7E1",
    STATUS_RED: "\U0001F534",
}

STATUS_SHORTNAME = {
    STATUS_GREEN: ":green_circle:",
    STATUS_YELLOW: ":yellow_circle:",
    STATUS_RED: ":red_circle:",
}

STATUS_HELP = {
    STATUS_GREEN: "On track to ship the agreed scope by the due date. Evidence this week: PRs merged, demos posted, metrics moved.",
    STATUS_YELLOW: "At risk. One named blocker, scope/quality concern, or unclear date/requirements. Resolution path stated for next week.",
    STATUS_RED: "Off track. Severely delayed (>2 weeks). Will not ship without scope cut, more capacity, or replan.",
}


@dataclass
class EpicState:
    key: str
    summary: str
    url: str
    dri_name: str
    update_status: str
    update_summary: str


@dataclass
class CollectedSections:
    status: str
    done_this_week: str
    target_next_week: str
    blockers_risks: str


def render_menu(epics: list[EpicState]) -> str:
    """Render the epic-picker menu as a string. Pure function for testability."""
    width_key = max((len(e.key) for e in epics), default=10)
    width_status = max((len(e.update_status) for e in epics), default=10)
    lines = []
    for idx, epic in enumerate(epics, start=1):
        lines.append(
            f"{idx:>2}. [{epic.update_status:<{width_status}}] {epic.key:<{width_key}}  {epic.summary}"
            f"\n      DRI: {epic.dri_name} | {epic.url}"
        )
    return "\n".join(lines)


def update_state_for_epic(
    comments: list[dict],
    dri: dict | None,
    window_start: datetime,
    window_end: datetime,
    parse_opts: dict,
    cover_emails: list[str],
) -> tuple[str, str]:
    """Return (status_label, summary) for the epic menu badge."""
    selection = find_latest_valid_dri_comment(
        comments,
        dri,
        window_start,
        window_end,
        parse_options=parse_opts,
        cover_emails=cover_emails or None,
    )
    if selection.selected_comment is not None and selection.parsed_update is not None:
        emoji = STATUS_TO_EMOJI.get(selection.parsed_update.status, "")
        cover = " (cover)" if selection.cover_author else ""
        return f"valid {emoji}{cover}".strip(), f"Latest valid update by {_author_name(selection.selected_comment)}"
    if selection.malformed_update_seen:
        return "malformed", "Latest comment did not match the template"
    return "missing", "No DRI weekly update in this week's window"


def _author_name(comment: dict) -> str:
    author = comment.get("author", {}) or {}
    return str(author.get("displayName") or author.get("emailAddress") or "unknown")


def parse_status_input(raw: str) -> str | None:
    """Accept emoji, word, or shortname. Returns canonical Green/Yellow/Red or None."""
    if not raw:
        return None
    return normalize_status(raw.strip())


def build_template_text(sections: CollectedSections) -> str:
    """Render the template a DRI weekly update needs to match. Pure function."""
    emoji = STATUS_TO_EMOJI[sections.status]
    body = [
        f"Status: {emoji}",
        "",
        f"Done this week: {sections.done_this_week}",
        "",
        f"Target for next week: {sections.target_next_week}",
    ]
    if sections.blockers_risks.strip():
        body.append("")
        body.append(f"Blockers / Risks: {sections.blockers_risks}")
    return "\n".join(body)


def build_adf_body(sections: CollectedSections) -> dict:
    """Build the ADF document the Jira MCP will POST to /issue/{key}/comment.

    Status is wrapped in an emoji node so the comment shows the same green/
    yellow/red circle in Jira UI that the rollup parser recognises.
    """
    shortname = STATUS_SHORTNAME[sections.status]
    emoji_text = STATUS_TO_EMOJI[sections.status]
    emoji_id = {"\U0001F7E2": "1f7e2", "\U0001F7E1": "1f7e1", "\U0001F534": "1f534"}[emoji_text]

    def text_paragraph(text: str) -> dict:
        return {"type": "paragraph", "content": [{"type": "text", "text": text}]}

    content: list[dict] = [
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Status: "},
                {
                    "type": "emoji",
                    "attrs": {"shortName": shortname, "id": emoji_id, "text": emoji_text},
                },
            ],
        },
        text_paragraph(f"Done this week: {sections.done_this_week}"),
        text_paragraph(f"Target for next week: {sections.target_next_week}"),
    ]
    if sections.blockers_risks.strip():
        content.append(text_paragraph(f"Blockers / Risks: {sections.blockers_risks}"))
    return {"type": "doc", "version": 1, "content": content}


def collect_section_via_editor(label: str, hint: str, initial: str = "") -> str:
    """Open $EDITOR with a stub for one section. Strip lines starting with '#'."""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as tmp:
        tmp.write(f"# {label}\n# {hint}\n# Lines beginning with '#' are ignored.\n")
        if initial:
            tmp.write(initial)
        tmp.flush()
        path = tmp.name
    try:
        subprocess.run([editor, path], check=True)
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    finally:
        os.unlink(path)
    return "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("#")).strip()


def prompt_status(stdin=sys.stdin, stdout=sys.stdout) -> str:
    """Ask the DRI for a status. Loops until a valid value is given."""
    while True:
        stdout.write("\nStatus options:\n")
        for status, emoji in STATUS_TO_EMOJI.items():
            stdout.write(f"  {emoji} {status} — {STATUS_HELP[status]}\n")
        stdout.write("Enter status (Green/Yellow/Red or paste the emoji): ")
        stdout.flush()
        raw = stdin.readline()
        status = parse_status_input(raw)
        if status:
            return status
        stdout.write("Could not recognise that. Please enter Green, Yellow, or Red.\n")


def collect_sections(prompt_status_fn=prompt_status, editor_fn=collect_section_via_editor) -> CollectedSections:
    status = prompt_status_fn()
    done = editor_fn(
        "Done this week",
        "What did you actually ship this week? PRs merged, demos posted, behaviours shipped, metrics moved.",
    )
    plan = editor_fn(
        "Target for next week",
        "What do you expect to ship or validate next week?",
    )
    blockers = editor_fn(
        "Blockers / Risks (leave empty if none)",
        "Named blockers, scope concerns, timeline shifts. Tag owners for unblocking.",
    )
    return CollectedSections(status=status, done_this_week=done, target_next_week=plan, blockers_risks=blockers)


def validate_sections(sections: CollectedSections, parse_opts: dict) -> tuple[bool, list[str]]:
    """Return (is_valid, errors). Mirrors the rollup parser exactly."""
    text = build_template_text(sections)
    parsed = parse_update(text, **parse_opts)
    return parsed.template_valid, parsed.errors


def label_for(config: dict, target_date: date) -> str:
    pattern = str(get_path(config, "jira.mission_label_pattern"))
    return month_label(target_date.month, target_date.year, pattern)


def load_epics(config: dict, target_date: date, adapter) -> tuple[list[dict], str]:
    """Search the bundled Jira MCP for the team's epics carrying this month's label."""
    label = label_for(config, target_date)
    return adapter.search_mission_epics(config, label), label


def build_epic_states(
    config: dict,
    target_date: date,
    epics: list[dict],
    adapter,
) -> list[EpicState]:
    """Decorate the epics list with their current weekly-update state for the menu."""
    window_start, window_end, _ = compute_week_window(
        target_date,
        str(get_path(config, "team.timezone")),
        get_path(config, "weekly_update.window"),
    )
    parse_opts = parse_update_options(get_path(config, "weekly_update.validation", {}))
    cover_emails = [
        str(addr).strip()
        for addr in get_path(config, "weekly_update.cover_authors", []) or []
        if str(addr).strip()
    ]
    states: list[EpicState] = []
    for mission in epics:
        try:
            comments = adapter.get_comments(mission, window_start, window_end)
        except Exception:  # noqa: BLE001
            comments = []
        status_label, summary = update_state_for_epic(
            comments,
            mission.get("dri"),
            window_start,
            window_end,
            parse_opts,
            cover_emails,
        )
        states.append(
            EpicState(
                key=str(mission.get("key", "")),
                summary=str(mission.get("name") or mission.get("summary") or "")[:80],
                url=str(mission.get("url", "")),
                dri_name=display_dri(mission.get("dri")),
                update_status=status_label,
                update_summary=summary,
            )
        )
    return states


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True, help="Team config YAML")
    parser.add_argument("--expect-team-id", required=True, help="Team id the config must declare")
    parser.add_argument(
        "--date",
        default=datetime.now(timezone.utc).date().isoformat(),
        help="Target date (defaults to today UTC); selects the mission label and weekly window",
    )
    parser.add_argument("--jira-mcp-dir", help="Override the bundled jira-mcp path")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    errors = validate_team_config(config)
    errors.extend(validate_expected_team(config, expected_team_id=args.expect_team_id))
    if errors:
        for err in errors:
            print(f"config error: {err}", file=sys.stderr)
        return 2

    target_date = date.fromisoformat(args.date)

    # Lazy import so unit tests can stub the adapter without spawning Node.
    from run_rollup import JiraMcpAdapter

    adapter = JiraMcpAdapter(args.jira_mcp_dir)
    epics, label = load_epics(config, target_date, adapter)
    if not epics:
        print(f"No epics found with label {label}.")
        return 0

    states = build_epic_states(config, target_date, epics, adapter)
    print(f"\nEpics in {config['team']['name']} for label {label}:\n")
    print(render_menu(states))

    while True:
        choice = input("\nPick an epic number (or 'q' to quit): ").strip().lower()
        if choice in {"q", "quit", "exit"}:
            return 0
        if choice.isdigit() and 1 <= int(choice) <= len(states):
            picked = states[int(choice) - 1]
            picked_mission = epics[int(choice) - 1]
            break
        print("Invalid choice.")

    print(f"\nWriting weekly update for {picked.key} — {picked.summary}")
    print(f"DRI: {picked.dri_name} | {picked.url}\n")

    parse_opts = parse_update_options(get_path(config, "weekly_update.validation", {}))
    while True:
        sections = collect_sections()
        ok, errors = validate_sections(sections, parse_opts)
        text_preview = build_template_text(sections)
        print("\n--- Preview ---")
        print(text_preview)
        print("---------------")
        if ok:
            break
        print("\nTemplate invalid:")
        for err in errors:
            print(f"  - {err}")
        print("Re-opening the editors for another pass...\n")

    confirm = input(f"\nPost this update to {picked.key}? [y/N] ").strip().lower()
    if confirm not in {"y", "yes"}:
        print("Aborted. Nothing posted.")
        return 0

    adf = build_adf_body(sections)
    result = adapter.add_comment(picked.key, adf)
    print(f"\nPosted. Comment id={result.get('id')} created={result.get('created')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
