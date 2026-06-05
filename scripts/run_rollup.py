#!/usr/bin/env python3
"""Run the weekly Engineer-Owned Mission rollup.

This is the orchestration layer for Codex invocation. It keeps the weekly run
deterministic while allowing the external systems to stay behind adapters:

- Jira adapter: find mission Epics and fetch comments.
- Sheet adapter: read previous weekly rows and prepare/write this week's tab.
- Email adapter: prepare a connector-compatible draft request.
- Core logic: parse comments, evaluate hygiene, build rows, render email.

For live Codex runs, use any capable Jira source that can produce the normalized
snapshot shape, the `mcp-plan` sheet adapter, and rendered copy-pastable email
artifacts. No shared workflow stores passwords or sends email directly.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from email import policy
from email.message import EmailMessage
import base64
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from mission_rollup import (
    Blocker,
    ConfigError,
    ParsedUpdate,
    STATUS_DONE,
    STATUS_GREEN,
    STATUS_MISSING,
    STATUS_NOT_STARTED,
    STATUS_RED,
    STATUS_YELLOW,
    assert_valid_config,
    blocker_fingerprint,
    blocker_items,
    comment_body_to_text,
    compute_week_window,
    display_dri,
    due_date_overdue_days,
    evaluate_hygiene,
    extract_blockers,
    format_day_count,
    find_latest_valid_dri_comment,
    get_path,
    load_config,
    mission_email_row,
    mission_effective_due_date,
    mission_to_sheet_row,
    month_label,
    render_email_draft,
    sheet_file_name,
    sheet_values,
    stringify_percent,
    summarize_missions,
    validate_expected_team,
    week_tab_name,
)

MISSION_TYPE_CURRENT = "current"
MISSION_TYPE_SPILLOVER = "spillover"
RUN_HISTORY_DEFAULT_TAB_NAME = "_Run History"
RUN_HISTORY_SCHEMA_VERSION = "1"
RUN_HISTORY_COLUMNS = [
    "History version",
    "Run ID",
    "Team ID",
    "Team name",
    "Target date",
    "ISO week",
    "Mission key",
    "Mission name",
    "Mission URL",
    "Mission label",
    "Mission type",
    "DRI",
    "Jira status",
    "Rollup status",
    "Is done",
    "Original due date",
    "Current due date",
    "Effective due date",
    "Due date movement",
    "Due date delta days",
    "Overdue days",
    "Missing update?",
    "Missing update weeks",
    "Latest valid comment timestamp",
    "Blockers / risks",
    "Hygiene severity",
    "Hygiene issues",
    "First observed date",
    "Done date",
    "Cycle time days",
]


@dataclass
class SheetWriteResult:
    status: str
    spreadsheet_id: str
    tab_name: str
    row_count: int
    tab_gid: str = ""
    message: str = ""
    request: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class EmailCreateResult:
    status: str
    to: str
    cc: str
    subject: str
    message: str = ""
    request: dict[str, Any] | None = None
    draft_id: str | None = None
    message_id: str | None = None
    thread_id: str | None = None
    error: str | None = None


class RollupAdapterError(RuntimeError):
    """Raised when an external adapter fails."""


class JiraAdapter:
    def search_mission_epics(self, config: dict[str, Any], label: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_child_issues(self, mission: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_issue_property(self, mission: dict[str, Any], property_key: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def get_comments(
        self,
        mission: dict[str, Any],
        window_start: datetime,
        window_end: datetime,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError


class FixtureJiraAdapter(JiraAdapter):
    """Jira adapter backed by a local JSON file for deterministic tests."""

    def __init__(self, fixture_path: str | Path | None = None, *, data: dict[str, Any] | None = None):
        self.fixture_path = Path(fixture_path) if fixture_path else None
        if data is not None:
            self.data = data
        elif self.fixture_path:
            self.data = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        else:
            raise ConfigError("FixtureJiraAdapter requires fixture_path or data")

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "FixtureJiraAdapter":
        return cls(data=data)

    def search_mission_epics(self, config: dict[str, Any], label: str) -> list[dict[str, Any]]:
        missions = list(self.data.get("missions", []))
        return [
            normalize_fixture_mission(mission, config)
            for mission in missions
            if mission_matches_config(mission, config, label)
        ]

    def get_child_issues(self, mission: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
        del config
        if mission.get("_children_error"):
            raise RollupAdapterError(str(mission["_children_error"]))
        return list(mission.get("children", []))

    def get_issue_property(self, mission: dict[str, Any], property_key: str) -> dict[str, Any] | None:
        property_errors = mission.get("_property_errors", {}) or {}
        if property_errors.get(property_key):
            raise RollupAdapterError(str(property_errors[property_key]))
        return (mission.get("properties", {}) or {}).get(property_key)

    def get_comments(
        self,
        mission: dict[str, Any],
        window_start: datetime,
        window_end: datetime,
    ) -> list[dict[str, Any]]:
        del window_start, window_end
        if mission.get("_comments_error"):
            raise RollupAdapterError(str(mission["_comments_error"]))
        return list(mission.get("comments", []))


class JiraMcpAdapter(JiraAdapter):
    """Jira adapter backed by the bundled Jira MCP server credentials."""

    def __init__(self, mcp_dir: str | Path | None = None):
        self.mcp_dir = Path(
            mcp_dir
            or os.environ.get("JIRA_MCP_DIR")
            or Path(__file__).resolve().parent.parent / "jira-mcp"
        )
        self.client_script = Path(__file__).resolve().parent / "jira_mcp_client.js"
        if not self.client_script.exists():
            raise RollupAdapterError(f"Missing Jira MCP client helper: {self.client_script}")

    def search_mission_epics(self, config: dict[str, Any], label: str) -> list[dict[str, Any]]:
        jql = build_mission_jql(config, label)
        fields = sorted(jira_fields_to_request(config))
        issues: list[dict[str, Any]] = []
        next_page_token: str | None = None
        while True:
            payload = self._call(
                {
                    "operation": "search",
                    "jql": jql,
                    "fields": fields,
                    "maxResults": 100,
                    "nextPageToken": next_page_token,
                }
            )
            batch = payload.get("issues", [])
            issues.extend(batch)
            next_page_token = payload.get("nextPageToken")
            if not next_page_token or not batch:
                break
        return [normalize_jira_issue(issue, config) for issue in issues]

    def get_child_issues(self, mission: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
        del config
        issue_key = str(mission["key"])
        children: list[dict[str, Any]] = []
        next_page_token: str | None = None
        while True:
            payload = self._call(
                {
                    "operation": "search",
                    "jql": build_child_issue_jql(issue_key),
                    "fields": sorted(child_issue_fields_to_request()),
                    "maxResults": 100,
                    "nextPageToken": next_page_token,
                }
            )
            batch = payload.get("issues", [])
            children.extend(batch)
            next_page_token = payload.get("nextPageToken")
            if not next_page_token or not batch:
                break
        return children

    def get_issue_property(self, mission: dict[str, Any], property_key: str) -> dict[str, Any] | None:
        payload = self._call(
            {
                "operation": "issueProperty",
                "issueKey": str(mission["key"]),
                "propertyKey": property_key,
            }
        )
        if payload.get("missing"):
            return None
        return payload

    def get_comments(
        self,
        mission: dict[str, Any],
        window_start: datetime,
        window_end: datetime,
    ) -> list[dict[str, Any]]:
        del window_start, window_end
        base_url = str(mission["base_url"]).rstrip("/")
        issue_key = str(mission["key"])
        comments: list[dict[str, Any]] = []
        start_at = 0
        while True:
            payload = self._call(
                {
                    "operation": "comments",
                    "issueKey": issue_key,
                    "startAt": start_at,
                    "maxResults": 100,
                }
            )
            batch = payload.get("comments", [])
            comments.extend([normalize_jira_comment(comment, base_url, issue_key) for comment in batch])
            start_at += len(batch)
            total = int(payload.get("total", start_at))
            if start_at >= total or not batch:
                break
        return comments

    def _call(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = {**payload, "mcpDir": str(self.mcp_dir)}
        try:
            completed = subprocess.run(
                ["node", str(self.client_script)],
                input=json.dumps(request_payload),
                capture_output=True,
                check=False,
                encoding="utf-8",
                timeout=90,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RollupAdapterError(f"Jira MCP helper failed: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RollupAdapterError(f"Jira MCP helper failed: {detail}")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RollupAdapterError(
                f"Jira MCP helper returned non-JSON output: {completed.stdout.strip()}"
            ) from exc


def collect_jira_snapshot(
    config: dict[str, Any],
    target_date: date,
    jira_adapter: JiraAdapter,
    *,
    source: str = "jira-mcp",
) -> dict[str, Any]:
    """Collect all Jira data needed by the deterministic rollup phase."""

    assert_valid_config(config)
    window_start, window_end, iso_week = compute_week_window(
        target_date,
        str(get_path(config, "team.timezone")),
        get_path(config, "weekly_update.window"),
    )
    label = month_label(
        target_date.month,
        target_date.year,
        str(get_path(config, "jira.mission_label_pattern")),
    )
    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "source": source,
        "team": get_path(config, "team.name"),
        "target_date": target_date.isoformat(),
        "month_label": label,
        "iso_week": iso_week,
        "window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "timezone": get_path(config, "team.timezone"),
        },
        "missions": [],
        "errors": [],
    }
    missions, current_mission_count, spillover_mission_count = collect_rollup_missions(
        config,
        target_date,
        jira_adapter,
        current_label=label,
        errors=snapshot["errors"],
    )
    snapshot["current_mission_count"] = current_mission_count
    snapshot["spillover_mission_count"] = spillover_mission_count
    for mission in sorted(missions, key=lambda item: str(item.get("key", ""))):
        snapshot["missions"].append(
            collect_jira_snapshot_mission(
                mission,
                config,
                jira_adapter,
                window_start=window_start,
                window_end=window_end,
            )
        )
    return snapshot


def collect_jira_snapshot_mission(
    mission: dict[str, Any],
    config: dict[str, Any],
    jira_adapter: JiraAdapter,
    *,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    """Collect child issues, issue properties, and comments for one mission."""

    snapshot_mission = json_safe(mission)
    snapshot_mission.setdefault("properties", {})
    try:
        snapshot_mission["children"] = json_safe(jira_adapter.get_child_issues(mission, config))
    except Exception as exc:  # noqa: BLE001 - preserve partial snapshots
        snapshot_mission["children"] = []
        snapshot_mission["_children_error"] = str(exc)

    property_errors: dict[str, str] = {}
    for property_key in issue_property_keys_to_request(config):
        try:
            property_payload = jira_adapter.get_issue_property(mission, property_key)
        except Exception as exc:  # noqa: BLE001
            property_errors[property_key] = str(exc)
            continue
        if property_payload:
            snapshot_mission["properties"][property_key] = json_safe(property_payload)
    if property_errors:
        snapshot_mission["_property_errors"] = property_errors

    try:
        snapshot_mission["comments"] = json_safe(jira_adapter.get_comments(mission, window_start, window_end))
    except Exception as exc:  # noqa: BLE001
        snapshot_mission["comments"] = []
        snapshot_mission["_comments_error"] = str(exc)
    return snapshot_mission


def issue_property_keys_to_request(config: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    linked_okr_config = get_path(config, "jira.fields.linked_okr", {}) or {}
    if linked_okr_config.get("source") == "issue_property" and linked_okr_config.get("property_key"):
        keys.add(str(linked_okr_config["property_key"]))
    return keys


def json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def jira_snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    mission_errors = 0
    for mission in snapshot.get("missions", []) or []:
        if mission.get("_children_error") or mission.get("_comments_error") or mission.get("_property_errors"):
            mission_errors += 1
    return {
        "schema_version": snapshot.get("schema_version"),
        "source": snapshot.get("source"),
        "target_date": snapshot.get("target_date"),
        "month_label": snapshot.get("month_label"),
        "iso_week": snapshot.get("iso_week"),
        "mission_count": len(snapshot.get("missions", []) or []),
        "error_count": len(snapshot.get("errors", []) or []) + mission_errors,
    }


class SheetAdapter:
    def read_history(self, config: dict[str, Any], current_tab_name: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def read_run_history(self, config: dict[str, Any]) -> list[list[Any]]:
        raise NotImplementedError

    def replace_week_tab(
        self,
        config: dict[str, Any],
        tab_name: str,
        values: list[list[str]],
    ) -> SheetWriteResult:
        raise NotImplementedError

    def replace_run_history(
        self,
        config: dict[str, Any],
        tab_name: str,
        values: list[list[str]],
        *,
        run_id: str,
    ) -> SheetWriteResult:
        raise NotImplementedError


class FixtureSheetAdapter(SheetAdapter):
    """Sheet adapter backed by local JSON history and optional write failure."""

    def __init__(self, fixture_path: str | Path | None = None, *, fail_write: bool = False):
        self.history_available = True
        self.run_history_available = True
        self.data: dict[str, Any] = {}
        self.run_history_values: list[list[str]] = []
        if fixture_path:
            self.data = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        self.run_history_values = self._initial_run_history_values()
        self.fail_write = fail_write or bool(self.data.get("sheet_write", {}).get("fail"))

    def read_history(self, config: dict[str, Any], current_tab_name: str) -> list[dict[str, Any]]:
        del config, current_tab_name
        return list(self.data.get("history_tabs", []))

    def read_run_history(self, config: dict[str, Any]) -> list[list[Any]]:
        del config
        return [list(row) for row in self.run_history_values]

    def replace_week_tab(
        self,
        config: dict[str, Any],
        tab_name: str,
        values: list[list[str]],
    ) -> SheetWriteResult:
        del config
        if self.fail_write:
            raise RollupAdapterError("Fixture sheet write failed")
        return SheetWriteResult(
            status="written",
            spreadsheet_id="",
            tab_name=tab_name,
            row_count=max(len(values) - 1, 0),
            message="Fixture sheet write succeeded",
        )

    def replace_run_history(
        self,
        config: dict[str, Any],
        tab_name: str,
        values: list[list[str]],
        *,
        run_id: str,
    ) -> SheetWriteResult:
        del config
        if self.fail_write:
            raise RollupAdapterError("Fixture run history write failed")
        self.run_history_values = merge_run_history_values(
            self.run_history_values,
            values,
            run_id=run_id,
        )
        return SheetWriteResult(
            status="written",
            spreadsheet_id="",
            tab_name=tab_name,
            row_count=max(len(values) - 1, 0),
            message="Fixture run history write succeeded",
        )

    def _initial_run_history_values(self) -> list[list[str]]:
        return run_history_values_from_fixture_data(self.data)


class McpPlanSheetAdapter(SheetAdapter):
    """Prepare a Google Drive MCP write request without calling MCP from Python."""

    def __init__(self, history_fixture_path: str | Path | None = None):
        self.history_available = bool(history_fixture_path)
        self.run_history_available = bool(history_fixture_path)
        self.history_fixture_path = Path(history_fixture_path) if history_fixture_path else None
        self.history_data: dict[str, Any] = {}
        self.run_history_values: list[list[str]] = []
        if self.history_fixture_path:
            self.history_data = json.loads(self.history_fixture_path.read_text(encoding="utf-8"))
        self.run_history_values = run_history_values_from_fixture_data(self.history_data)

    def read_history(self, config: dict[str, Any], current_tab_name: str) -> list[dict[str, Any]]:
        del config, current_tab_name
        return list(self.history_data.get("history_tabs", []))

    def read_run_history(self, config: dict[str, Any]) -> list[list[Any]]:
        del config
        return [list(row) for row in self.run_history_values]

    def replace_week_tab(
        self,
        config: dict[str, Any],
        tab_name: str,
        values: list[list[str]],
    ) -> SheetWriteResult:
        folder_id = str(get_path(config, "sheet.folder_id", ""))
        file_name = sheet_file_name(config)
        request_payload = {
            "spreadsheet_id": "",
            "folder_id": folder_id,
            "file_name": file_name,
            "tab_name": tab_name,
            "mode": get_path(config, "sheet.mode", "replace_week_tab"),
            "create_tab_if_missing": bool(get_path(config, "sheet.create_tab_if_missing", True)),
            "values": values,
            "email_link": {
                "target": "current_week_tab",
                "tab_name": tab_name,
                "gid_source": "sheetId for tab_name from sheet_list_sheets after the weekly tab exists",
                "url_format": "https://docs.google.com/spreadsheets/d/<spreadsheet_id>/edit#gid=<weekly_tab_sheetId>",
            },
            "spreadsheet_resolution": {
                "strategy": "folder_file_name_then_create",
                "folder_id": folder_id,
                "file_name": file_name,
                "mime_type": "application/vnd.google-apps.spreadsheet",
                "matching_rule": "exact_file_name_in_folder",
                "create_if_missing": True,
                "reuse_existing": True,
            },
            "mcp_steps": [
                "list files in folder_id for an exact spreadsheet file_name match",
                "if matching spreadsheet exists: use its file id as spreadsheet_id",
                "else: create_google_sheet(title=file_name), then move_file(file_id, folder_id)",
                "sheet_list_sheets(spreadsheet_id)",
                "if tab is missing: sheet_add_sheet(spreadsheet_id, tab_name)",
                "capture the sheetId/gid for tab_name from sheet_list_sheets or sheet_add_sheet",
                "if tab exists: sheet_clear_values(spreadsheet_id, f'{tab_name}!A:Z')",
                "sheet_update_values(spreadsheet_id, f'{tab_name}!A1', values)",
                "sheet_clear_basic_filter(spreadsheet_id, tab_name)",
                "sheet_set_basic_filter(spreadsheet_id, tab_name)",
                "sheet_freeze_rows(spreadsheet_id, tab_name, 1)",
                "sheet_auto_resize_columns(spreadsheet_id, tab_name, 0, len(values[0]))",
                "build the final email sheet URL with #gid=<weekly tab sheetId>",
            ],
        }
        return SheetWriteResult(
            status="mcp_plan",
            spreadsheet_id="",
            tab_name=tab_name,
            row_count=max(len(values) - 1, 0),
            message="Prepared Google Drive MCP sheet write request; Codex must execute it.",
            request=request_payload,
        )

    def replace_run_history(
        self,
        config: dict[str, Any],
        tab_name: str,
        values: list[list[str]],
        *,
        run_id: str,
    ) -> SheetWriteResult:
        folder_id = str(get_path(config, "sheet.folder_id", ""))
        file_name = sheet_file_name(config)
        merged_values = merge_run_history_values(
            self.run_history_values,
            values,
            run_id=run_id,
        )
        request_payload = {
            "spreadsheet_id": "",
            "folder_id": folder_id,
            "file_name": file_name,
            "tab_name": tab_name,
            "mode": "merge_run_history_by_run_id",
            "run_id": run_id,
            "values": merged_values,
            "current_run_values": values,
            "spreadsheet_resolution": {
                "strategy": "folder_file_name_then_create",
                "folder_id": folder_id,
                "file_name": file_name,
                "mime_type": "application/vnd.google-apps.spreadsheet",
                "matching_rule": "exact_file_name_in_folder",
                "create_if_missing": True,
                "reuse_existing": True,
            },
            "mcp_steps": [
                "list files in folder_id for an exact spreadsheet file_name match",
                "if matching spreadsheet exists: use its file id as spreadsheet_id",
                "else: create_google_sheet(title=file_name), then move_file(file_id, folder_id)",
                "sheet_list_sheets(spreadsheet_id)",
                f"if tab {tab_name} is missing: sheet_add_sheet(spreadsheet_id, tab_name)",
                f"read existing values from {tab_name}!A:AD if the tab exists",
                "drop existing rows where Run ID equals run_id",
                "append current_run_values rows below the preserved rows",
                f"sheet_clear_values(spreadsheet_id, '{tab_name}!A:AD')",
                f"sheet_update_values(spreadsheet_id, '{tab_name}!A1', merged values)",
                "sheet_clear_basic_filter(spreadsheet_id, tab_name)",
                "sheet_set_basic_filter(spreadsheet_id, tab_name)",
                "sheet_freeze_rows(spreadsheet_id, tab_name, 1)",
                "sheet_auto_resize_columns(spreadsheet_id, tab_name, 0, len(values[0]))",
            ],
        }
        return SheetWriteResult(
            status="mcp_plan",
            spreadsheet_id="",
            tab_name=tab_name,
            row_count=max(len(values) - 1, 0),
            message="Prepared Google Drive MCP run-history write request; Codex must execute it.",
            request=request_payload,
        )


class EmailAdapter:
    def create_draft(self, config: dict[str, Any], draft_email: dict[str, Any]) -> EmailCreateResult:
        raise NotImplementedError


class RawMimePlanEmailAdapter(EmailAdapter):
    """Prepare a raw-MIME Gmail API draft request for an HTML-capable client."""

    def create_draft(self, config: dict[str, Any], draft_email: dict[str, Any]) -> EmailCreateResult:
        del config
        to = comma_join(draft_email.get("to", []))
        cc = comma_join(draft_email.get("cc", []))
        subject = str(draft_email.get("subject", ""))
        request_payload = gmail_raw_draft_request_for_email(draft_email)
        return EmailCreateResult(
            status="raw_mime_plan",
            to=to,
            cc=cc,
            subject=subject,
            message="Prepared Gmail API raw MIME draft request; execute with users.drafts.create.",
            request=request_payload,
        )


def run_rollup(
    config: dict[str, Any],
    target_date: date,
    jira_adapter: JiraAdapter,
    sheet_adapter: SheetAdapter,
    *,
    email_adapter: EmailAdapter | None = None,
    jira_snapshot: dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
    sheet_url_override: str = "",
    sheet_tab_gid: str = "",
) -> dict[str, Any]:
    """Run the weekly rollup and return a deterministic result object."""

    assert_valid_config(config)
    window_start, window_end, iso_week = compute_week_window(
        target_date,
        str(get_path(config, "team.timezone")),
        get_path(config, "weekly_update.window"),
    )
    label = month_label(
        target_date.month,
        target_date.year,
        str(get_path(config, "jira.mission_label_pattern")),
    )
    tab_name = week_tab_name(iso_week, str(get_path(config, "sheet.tab_name_pattern")))
    run_id = run_id_for_run(config, target_date, iso_week)
    run_history_tab = run_history_tab_name(config)

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    missions, current_mission_count, spillover_mission_count = collect_rollup_missions(
        config,
        target_date,
        jira_adapter,
        current_label=label,
        errors=errors,
    )
    if current_mission_count == 0 and not any(error.get("source") == "jira" for error in errors):
        warnings.append(
            {
                "severity": "yellow",
                "source": "jira",
                "message": (
                    f"No epics found with mission label {label}; "
                    f"expected label format is {get_path(config, 'jira.mission_label_pattern')}"
                ),
                "mission_label": label,
            }
        )

    history, history_meta = resolve_history(
        config,
        sheet_adapter,
        current_tab_name=tab_name,
        current_week=iso_week,
        current_run_id=run_id,
        target_date=target_date,
        errors=errors,
    )
    history_available = bool(history_meta["available"])
    if not history_available:
        warnings.append(
            {
                "severity": "yellow",
                "source": "sheet_history",
                "message": (
                    "Sheet history was not loaded; due-date movement and no-update streaks "
                    "cannot be computed. For mcp-plan runs, pass --sheet-fixture with "
                    f"existing {run_history_tab} or weekly sheet tabs."
                ),
            }
        )

    sheet_rows: list[list[str]] = []
    email_rows: list[dict[str, Any]] = []
    mission_summaries: list[dict[str, Any]] = []
    hygiene_issues: list[dict[str, str]] = []

    parse_options = parse_update_options(get_path(config, "weekly_update.validation", {}))
    for mission in sorted(missions, key=lambda item: str(item.get("key", ""))):
        try:
            apply_issue_property_fields(mission, config, jira_adapter)
        except Exception as exc:  # noqa: BLE001
            errors.append({"source": "jira_issue_property", "mission_key": mission.get("key", ""), "message": str(exc)})

        try:
            apply_derived_progress(mission, config, jira_adapter)
        except Exception as exc:  # noqa: BLE001
            errors.append({"source": "jira_progress", "mission_key": mission.get("key", ""), "message": str(exc)})

        try:
            comments = mission.get("comments")
            if comments is None:
                comments = jira_adapter.get_comments(mission, window_start, window_end)
        except Exception as exc:  # noqa: BLE001
            comments = []
            errors.append({"source": "jira_comments", "mission_key": mission.get("key", ""), "message": str(exc)})

        selection = find_latest_valid_dri_comment(
            comments,
            mission.get("dri"),
            window_start,
            window_end,
            parse_options=parse_options,
        )
        parsed = selection.parsed_update
        mission_key = str(mission.get("key", ""))
        mission_done = mission_is_done(mission, config)
        mission_not_started = mission_is_not_started(mission)
        start_signal_seen = mission_start_signal_seen(
            mission,
            parsed,
            malformed_update_seen=selection.malformed_update_seen,
        )
        effective_due_date = mission_effective_due_date(mission)
        days_overdue = 0 if mission_done else due_date_overdue_days(effective_due_date, target_date)
        not_started_without_signal = (
            mission_not_started
            and not mission_done
            and not start_signal_seen
            and days_overdue == 0
        )
        missing_update = selection.missing_update and not mission_done and not not_started_without_signal
        previous_due_date = history.previous_due_dates.get(mission_key)
        original_due_date = original_due_date_for_mission(
            history,
            mission_key=mission_key,
            current_due_date=mission.get("due_date"),
        )
        prior_missing_streak = history.missing_update_streaks.get(mission_key, 0)
        stale_weeks = 0
        if missing_update:
            stale_weeks = (prior_missing_streak if history_available else 0) + 1
        due_date_history_baseline = history.original_due_dates.get(mission_key) or previous_due_date
        due_date_status = due_date_change_status(
            mission.get("due_date"),
            due_date_history_baseline,
            observed_before=mission_key in history.observed_mission_keys,
            history_available=history_available,
        )
        due_date_movement = due_date_movement_label(
            mission.get("due_date"),
            due_date_history_baseline,
            observed_before=mission_key in history.observed_mission_keys,
            history_available=history_available,
            target_date=None if mission_done else target_date,
        )
        history_fields = mission_history_fields(
            history,
            mission_key=mission_key,
            target_date=target_date,
            is_done=mission_done,
        )
        due_date_delta = due_date_delta_days(
            original_due_date,
            str(mission.get("due_date", "") or ""),
        )
        stale_threshold = int(get_path(config, "weekly_update.validation.no_update_red_after_weeks", 2))
        if mission_done:
            effective_status = STATUS_DONE
        elif not_started_without_signal:
            effective_status = STATUS_NOT_STARTED
        else:
            effective_status = rollup_status(parsed, days_overdue)
        if parsed:
            display_parsed = (
                replace(parsed, status=effective_status)
                if effective_status != (parsed.status or STATUS_MISSING)
                else parsed
            )
        elif mission_done:
            display_parsed = ParsedUpdate(
                status=STATUS_DONE,
                done_this_week="Jira epic is Done.",
                plan_for_next_week="",
                blockers_risks="",
                template_valid=True,
                score=0,
            )
        elif not_started_without_signal:
            display_parsed = ParsedUpdate(
                status=STATUS_NOT_STARTED,
                done_this_week="Not started yet.",
                plan_for_next_week="",
                blockers_risks="",
                template_valid=True,
                score=0,
            )
        else:
            display_parsed = None
        issues = evaluate_hygiene(
            mission,
            config,
            parsed,
            missing_update=missing_update,
            malformed_update_seen=selection.malformed_update_seen,
            previous_due_date=previous_due_date,
            stale_weeks=stale_weeks,
            history_available=history_available,
            target_date=target_date,
            is_done=mission_done,
            is_not_started=mission_not_started,
            start_signal_seen=start_signal_seen,
        )
        blockers = (
            apply_blocker_history(
                extract_blockers(
                    parsed.blockers_risks,
                    mission=str(mission.get("name") or mission.get("summary") or mission.get("key") or ""),
                    dri=display_dri(mission.get("dri")),
                    status=effective_status,
                ),
                history,
                mission_key=mission_key,
                current_week=iso_week,
            )
            if parsed
            else []
        )
        sheet_rows.append(
            mission_to_sheet_row(
                mission,
                config,
                display_parsed,
                issues,
                blockers,
                dri_comment=(
                    comment_body_to_text(selection.selected_comment.get("body"))
                    if selection.selected_comment
                    else ""
                ),
                missing_update=missing_update,
                missing_update_weeks=stale_weeks,
                due_date_movement=due_date_movement,
            )
        )
        email_row = mission_email_row(
            mission,
            display_parsed,
            issues,
            blockers,
            missing_update=missing_update,
            missing_update_weeks=stale_weeks,
            due_date_movement=due_date_movement,
            due_date_overdue_days=days_overdue,
            original_due_date=original_due_date,
        )
        email_rows.append(email_row)
        hygiene_issues.extend(
            {
                "mission_key": str(mission.get("key", "")),
                "mission": str(mission.get("name") or mission.get("summary") or mission.get("key") or ""),
                **issue,
            }
            for issue in issues
        )
        mission_summaries.append(
            {
                "key": mission.get("key", ""),
                "mission": mission.get("name") or mission.get("summary") or "",
                "mission_url": str(mission.get("url", "")),
                "mission_type": mission.get("mission_type", MISSION_TYPE_CURRENT),
                "original_month_label": mission.get("original_month_label", label),
                "dri": display_dri(mission.get("dri")),
                "jira_status": str(mission.get("status", "") or ""),
                "status": effective_status,
                "is_done": mission_done,
                "current_due_date": str(mission.get("due_date", "") or ""),
                "effective_due_date": effective_due_date,
                "previous_due_date": previous_due_date or "",
                "original_due_date": original_due_date or "",
                "due_date_change_status": due_date_status,
                "due_date_movement": due_date_movement,
                "due_date_delta_days": due_date_delta if due_date_delta is not None else "",
                "due_date_overdue_days": days_overdue,
                "missing_update": missing_update,
                "missing_update_weeks": stale_weeks,
                "recurring_missing_update": bool(history_available and stale_weeks >= stale_threshold and stale_weeks > 0),
                "template_valid": bool(parsed and parsed.template_valid),
                "hygiene": issues,
                "hygiene_severity": highest_hygiene_severity(issues),
                "blockers": [asdict(blocker) for blocker in blockers],
                "latest_valid_comment_timestamp": (
                    selection.selected_comment.get("created") if selection.selected_comment else ""
                ),
                **history_fields,
            }
        )

    values = sheet_values(sheet_rows)
    try:
        sheet_write = sheet_adapter.replace_week_tab(config, tab_name, values)
    except Exception as exc:  # noqa: BLE001
        sheet_write = SheetWriteResult(
            status="failed",
            spreadsheet_id="",
            tab_name=tab_name,
            row_count=max(len(values) - 1, 0),
            error=str(exc),
            message="Sheet write failed; draft email was still generated.",
        )
        errors.append({"source": "sheet_write", "message": str(exc)})

    current_run_history_values = build_run_history_values(
        config,
        mission_summaries,
        run_id=run_id,
        target_date=target_date,
        iso_week=iso_week,
    )
    if run_history_enabled(config):
        try:
            run_history_write = sheet_adapter.replace_run_history(
                config,
                run_history_tab,
                current_run_history_values,
                run_id=run_id,
            )
        except Exception as exc:  # noqa: BLE001
            run_history_write = SheetWriteResult(
                status="failed",
                spreadsheet_id="",
                tab_name=run_history_tab,
                row_count=max(len(current_run_history_values) - 1, 0),
                error=str(exc),
                message="Run history write failed; weekly sheet and draft email were still generated.",
            )
            errors.append({"source": "run_history_write", "message": str(exc)})
    else:
        run_history_write = SheetWriteResult(
            status="disabled",
            spreadsheet_id="",
            tab_name=run_history_tab,
            row_count=0,
            message="Run history is disabled by config.",
        )

    sheet_url = sheet_url_override or sheet_link_url(config, sheet_write)
    sheet_url = sheet_url_with_gid(sheet_url, sheet_tab_gid or sheet_write.tab_gid)
    draft_email = render_email_draft(config, email_rows, iso_week=iso_week, sheet_url=sheet_url)
    email_create = EmailCreateResult(
        status="not_requested",
        to=comma_join(draft_email.get("to", [])),
        cc=comma_join(draft_email.get("cc", [])),
        subject=str(draft_email.get("subject", "")),
        message="Email draft creation was not requested.",
    )
    if email_adapter:
        try:
            email_create = email_adapter.create_draft(config, draft_email)
        except Exception as exc:  # noqa: BLE001
            email_create = EmailCreateResult(
                status="failed",
                to=comma_join(draft_email.get("to", [])),
                cc=comma_join(draft_email.get("cc", [])),
                subject=str(draft_email.get("subject", "")),
                message="Email draft creation failed; rendered draft files are still available.",
                error=str(exc),
            )
            errors.append({"source": "email_create", "message": str(exc)})

    counts = summarize_missions(email_rows)
    stale_update_count = sum(
        1
        for mission in mission_summaries
        if any(str(issue.get("message", "")).startswith("No update in ") for issue in mission["hygiene"])
    )
    metrics = compute_run_metrics(mission_summaries)
    due_date_changed_count = sum(
        1 for mission in mission_summaries if mission["due_date_change_status"] == "changed"
    )
    due_date_moved_later_count = metrics["due_date_moved_later_count"]
    due_date_moved_earlier_count = metrics["due_date_moved_earlier_count"]
    overdue_mission_count = metrics["overdue_mission_count"]
    hygiene_issue_counts = count_hygiene_issues_by_severity(hygiene_issues)
    preview_status = "rendered" if draft_email.get("html_body") or draft_email.get("text_body") else "missing"
    run_summary = {
        "current_month_mission_count": current_mission_count,
        "spillover_mission_count": spillover_mission_count,
        "mission_count": metrics["mission_count"],
        "completed_mission_count": metrics["completed_mission_count"],
        "active_mission_count": metrics["active_mission_count"],
        "completion_rate": metrics["completion_rate"],
        "average_cycle_time_days": metrics["average_cycle_time_days"],
        "active_mission_average_age_days": metrics["active_mission_average_age_days"],
        "status_counts": {
            "green": counts["green"],
            "yellow": counts["yellow"],
            "red": counts["red"],
            "missing": sum(1 for row in email_rows if row.get("status") == STATUS_MISSING),
            "done": counts["done"],
            "not_started": counts["not_started"],
        },
        "missing_update_count": counts["missing_updates"],
        "stale_update_count": stale_update_count,
        "due_date_changed_count": due_date_changed_count,
        "due_date_moved_later_count": due_date_moved_later_count,
        "due_date_moved_earlier_count": due_date_moved_earlier_count,
        "overdue_mission_count": overdue_mission_count,
        "recurring_missing_update_count": metrics["recurring_missing_update_count"],
        "hygiene_issue_counts": hygiene_issue_counts,
        "sheet_write_status": sheet_write.status,
        "run_history_read_status": history_meta["read_status"],
        "run_history_write_status": run_history_write.status,
        "draft_status": email_create.status,
        "preview_status": preview_status,
    }
    result = {
        "team": get_path(config, "team.name"),
        "target_date": target_date.isoformat(),
        "month_label": label,
        "iso_week": iso_week,
        "window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "timezone": get_path(config, "team.timezone"),
        },
        "mission_count": counts["total"],
        "current_mission_count": current_mission_count,
        "spillover_mission_count": spillover_mission_count,
        "status_counts": {
            "green": counts["green"],
            "yellow": counts["yellow"],
            "red": counts["red"],
            "missing": sum(1 for row in email_rows if row.get("status") == STATUS_MISSING),
            "done": counts["done"],
            "not_started": counts["not_started"],
        },
        "missing_update_count": counts["missing_updates"],
        "stale_update_count": stale_update_count,
        "due_date_changed_count": due_date_changed_count,
        "due_date_moved_later_count": due_date_moved_later_count,
        "due_date_moved_earlier_count": due_date_moved_earlier_count,
        "overdue_mission_count": overdue_mission_count,
        "blocker_count": counts["blockers"],
        "hygiene_issue_counts": hygiene_issue_counts,
        "metrics": metrics,
        "run_summary": run_summary,
        "hygiene_issues": hygiene_issues,
        "warnings": warnings,
        "sheet_url": sheet_url,
        "sheet_write": asdict(sheet_write),
        "run_history": {
            "enabled": run_history_enabled(config),
            "tab_name": run_history_tab,
            "run_id": run_id,
            "source": history_meta["source"],
            "read_status": history_meta["read_status"],
            "available": history_available,
            "current_run_values": current_run_history_values,
        },
        "run_history_write": asdict(run_history_write),
        "sheet_values": values,
        "draft_email": draft_email,
        "email_create": asdict(email_create),
        "missions": mission_summaries,
        "errors": errors,
    }
    if jira_snapshot:
        result["jira_snapshot"] = jira_snapshot_summary(jira_snapshot)
    if output_dir:
        result["output_files"] = write_output_files(result, output_dir, jira_snapshot=jira_snapshot)
    return result


def collect_rollup_missions(
    config: dict[str, Any],
    target_date: date,
    jira_adapter: JiraAdapter,
    *,
    current_label: str,
    errors: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], int, int]:
    try:
        current_missions = jira_adapter.search_mission_epics(config, current_label)
    except Exception as exc:  # noqa: BLE001 - keep draft generation resilient
        current_missions = []
        errors.append({"source": "jira", "message": str(exc)})

    current_missions = [
        mission_with_report_type(mission, MISSION_TYPE_CURRENT, current_label)
        for mission in current_missions
    ]
    current_keys = {str(mission.get("key", "")) for mission in current_missions}

    spillover_missions: list[dict[str, Any]] = []
    continuing_missions: list[dict[str, Any]] = []
    if previous_month_spillover_enabled(config):
        previous_year, previous_month = previous_month_for_date(target_date)
        previous_label = month_label(
            previous_month,
            previous_year,
            str(get_path(config, "jira.mission_label_pattern")),
        )
        try:
            previous_missions = jira_adapter.search_mission_epics(config, previous_label)
        except Exception as exc:  # noqa: BLE001
            previous_missions = []
            errors.append({"source": "jira_spillover", "message": str(exc)})
        for mission in previous_missions:
            key = str(mission.get("key", ""))
            if key in current_keys:
                continue
            if spillover_requires_open_status(config) and mission_is_done(mission, config):
                continue
            if mission_has_reached_spillover_due_point(
                mission,
                target_date,
                label_year=previous_year,
                label_month=previous_month,
            ):
                spillover_missions.append(
                    mission_with_report_type(mission, MISSION_TYPE_SPILLOVER, previous_label)
                )
            else:
                continuing_missions.append(
                    mission_with_report_type(mission, MISSION_TYPE_CURRENT, previous_label)
                )

    return (
        current_missions + continuing_missions + spillover_missions,
        len(current_missions) + len(continuing_missions),
        len(spillover_missions),
    )


def mission_with_report_type(mission: dict[str, Any], mission_type: str, original_month_label: str) -> dict[str, Any]:
    typed = dict(mission)
    typed["mission_type"] = mission_type
    typed["original_month_label"] = original_month_label
    return typed


def previous_month_spillover_enabled(config: dict[str, Any]) -> bool:
    return bool(get_path(config, "previous_month_spillover.enabled", True))


def spillover_requires_open_status(config: dict[str, Any]) -> bool:
    return bool(
        get_path(
            config,
            "previous_month_spillover.include_if_status_not_in_done_statuses",
            True,
        )
    )


def previous_month_for_date(target_date: date) -> tuple[int, int]:
    year = target_date.year
    month = target_date.month - 1
    if month == 0:
        month = 12
        year -= 1
    return year, month


def previous_month_label_for_date(target_date: date, pattern: str) -> str:
    year, month = previous_month_for_date(target_date)
    return month_label(month, year, pattern)


def mission_has_reached_spillover_due_point(
    mission: dict[str, Any],
    target_date: date,
    *,
    label_year: int,
    label_month: int,
) -> bool:
    due_point = parse_due_date(mission.get("due_date")) or end_of_month(label_year, label_month)
    return target_date > due_point


def end_of_month(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def mission_is_done(mission: dict[str, Any], config: dict[str, Any]) -> bool:
    done_statuses = {
        normalize_status_name(status)
        for status in (get_path(config, "jira.done_statuses", []) or [])
    }
    return status_is_done(mission.get("status"), done_statuses)


def mission_is_not_started(mission: dict[str, Any]) -> bool:
    status = mission.get("status")
    if isinstance(status, dict):
        status_name = normalize_status_name(status.get("name"))
        category_key = normalize_status_name(get_path(status, "statusCategory.key"))
        category_name = normalize_status_name(get_path(status, "statusCategory.name"))
        return status_name in {"to do", "todo"} or category_key == "new" or category_name == "to do"
    return normalize_status_name(status) in {"to do", "todo"}


def mission_start_signal_seen(
    mission: dict[str, Any],
    parsed_update: ParsedUpdate | None,
    *,
    malformed_update_seen: bool = False,
) -> bool:
    if parsed_update is not None or malformed_update_seen:
        return True
    return mission_progress_started(mission.get("progress"))


def mission_progress_started(progress: Any) -> bool:
    text = stringify_percent(progress).strip()
    if not text:
        return False
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return False
    return float(match.group(0)) > 0


def sheet_link_url(config: dict[str, Any], sheet_write: SheetWriteResult | None = None) -> str:
    configured_url = str(
        get_path(config, "sheet.url", "")
        or get_path(config, "sheet.spreadsheet_url", "")
        or ""
    ).strip()
    if configured_url:
        return configured_url
    spreadsheet_id = str(
        (sheet_write.spreadsheet_id if sheet_write else "")
        or get_path(config, "sheet.resolved_spreadsheet_id", "")
        or ""
    ).strip()
    if spreadsheet_id:
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    return ""


def sheet_url_with_gid(url: str, tab_gid: Any) -> str:
    """Return a Google Sheets URL that opens a specific tab when a gid is known."""

    base_url = str(url or "").strip()
    gid = str(tab_gid or "").strip()
    if not base_url or not gid:
        return base_url
    parts = urlsplit(base_url)
    if "docs.google.com" not in parts.netloc or "/spreadsheets/" not in parts.path:
        return base_url
    fragment_pairs = dict(parse_qsl(parts.fragment, keep_blank_values=True))
    fragment_pairs["gid"] = gid
    fragment = urlencode(fragment_pairs)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, fragment))


def comma_join(values: Any) -> str:
    if not values:
        return ""
    if isinstance(values, str):
        return values
    if isinstance(values, list):
        return ", ".join(str(value) for value in values if value)
    return str(values)


def rollup_status(parsed_update: Any, days_overdue: int) -> str:
    if parsed_update is None:
        return STATUS_MISSING
    if days_overdue > 0:
        return STATUS_RED
    return parsed_update.status or STATUS_MISSING


def count_hygiene_issues_by_severity(issues: list[dict[str, str]]) -> dict[str, int]:
    counts = {"red": 0, "yellow": 0, "info": 0}
    for issue in issues:
        severity = str(issue.get("severity", "")).lower()
        if not severity:
            continue
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def compute_run_metrics(mission_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    mission_count = len(mission_summaries)
    completed = [mission for mission in mission_summaries if bool(mission.get("is_done"))]
    active = [mission for mission in mission_summaries if not bool(mission.get("is_done"))]
    cycle_time_values = [
        value
        for value in (metric_int(mission.get("cycle_time_days")) for mission in completed)
        if value is not None
    ]
    active_age_values = [
        value
        for value in (metric_int(mission.get("active_age_days")) for mission in active)
        if value is not None
    ]
    due_date_deltas = [
        value
        for value in (metric_int(mission.get("due_date_delta_days")) for mission in mission_summaries)
        if value is not None
    ]
    return {
        "mission_count": mission_count,
        "completed_mission_count": len(completed),
        "active_mission_count": len(active),
        "completion_rate": round(len(completed) / mission_count, 3) if mission_count else 0.0,
        "average_cycle_time_days": average_metric(cycle_time_values),
        "active_mission_average_age_days": average_metric(active_age_values),
        "overdue_mission_count": count_overdue_active_missions(active),
        "recurring_missing_update_count": sum(1 for mission in mission_summaries if mission.get("recurring_missing_update")),
        "due_date_moved_later_count": sum(1 for delta in due_date_deltas if delta > 0),
        "due_date_moved_earlier_count": sum(1 for delta in due_date_deltas if delta < 0),
    }


def metric_int(value: Any) -> int | None:
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def count_overdue_active_missions(missions: list[dict[str, Any]]) -> int:
    count = 0
    for mission in missions:
        overdue_days = metric_int(mission.get("due_date_overdue_days"))
        if overdue_days is not None and overdue_days > 0:
            count += 1
    return count


def average_metric(values: list[int]) -> int | float | None:
    if not values:
        return None
    average = round(sum(values) / len(values), 1)
    return int(average) if average.is_integer() else average


def highest_hygiene_severity(issues: list[dict[str, str]]) -> str:
    order = {"red": 0, "yellow": 1, "info": 2}
    severities = [str(issue.get("severity", "")).lower() for issue in issues if issue.get("severity")]
    if not severities:
        return ""
    return min(severities, key=lambda severity: order.get(severity, 9))


def run_history_enabled(config: dict[str, Any]) -> bool:
    return bool(get_path(config, "run_history.enabled", True))


def run_history_tab_name(config: dict[str, Any]) -> str:
    return str(get_path(config, "run_history.tab_name", RUN_HISTORY_DEFAULT_TAB_NAME) or RUN_HISTORY_DEFAULT_TAB_NAME)


def run_id_for_run(config: dict[str, Any], target_date: date, iso_week: int) -> str:
    team_id = str(get_path(config, "team.id", "") or get_path(config, "team.name", "") or "team")
    iso_year = target_date.isocalendar().year
    return f"{team_id}:{iso_year}-W{iso_week:02d}:{target_date.isoformat()}"


def resolve_history(
    config: dict[str, Any],
    sheet_adapter: SheetAdapter,
    *,
    current_tab_name: str,
    current_week: int,
    current_run_id: str,
    target_date: date,
    errors: list[dict[str, str]],
) -> tuple["SheetHistory", dict[str, Any]]:
    if run_history_enabled(config):
        try:
            run_history_values = sheet_adapter.read_run_history(config)
        except Exception as exc:  # noqa: BLE001
            run_history_values = []
            errors.append({"source": "run_history_read", "message": str(exc)})
            if hasattr(sheet_adapter, "run_history_available"):
                sheet_adapter.run_history_available = False
        run_history_available = bool(getattr(sheet_adapter, "run_history_available", True))
        if run_history_has_rows(run_history_values):
            return (
                parse_run_history(
                    run_history_values,
                    current_run_id=current_run_id,
                    target_date=target_date,
                ),
                {"source": "run_history", "read_status": "loaded", "available": True},
            )
        run_history_status = "empty" if run_history_available else "unavailable"
    else:
        run_history_status = "disabled"

    try:
        history_tabs = sheet_adapter.read_history(config, current_tab_name)
    except Exception as exc:  # noqa: BLE001
        history_tabs = []
        errors.append({"source": "sheet_history", "message": str(exc)})
        if hasattr(sheet_adapter, "history_available"):
            sheet_adapter.history_available = False
    weekly_history_available = bool(getattr(sheet_adapter, "history_available", True))
    if history_tabs:
        return (
            parse_sheet_history(history_tabs, current_week=current_week),
            {
                "source": "weekly_sheet",
                "read_status": "fallback_weekly_sheet",
                "available": weekly_history_available,
            },
        )
    return (
        empty_sheet_history(),
        {
            "source": "none" if not weekly_history_available else "empty",
            "read_status": "unavailable" if not weekly_history_available else run_history_status,
            "available": weekly_history_available,
        },
    )


def run_history_values_from_fixture_data(data: dict[str, Any]) -> list[list[str]]:
    if "run_history_values" in data:
        return [list(row) for row in data.get("run_history_values", [])]
    run_history = data.get("run_history", {}) or {}
    if isinstance(run_history, dict) and run_history.get("values"):
        return [list(row) for row in run_history.get("values", [])]
    return []


def run_history_has_rows(values: list[list[Any]]) -> bool:
    return len(values) > 1 and any(any(str(cell or "").strip() for cell in row) for row in values[1:])


def build_run_history_values(
    config: dict[str, Any],
    mission_summaries: list[dict[str, Any]],
    *,
    run_id: str,
    target_date: date,
    iso_week: int,
) -> list[list[str]]:
    return [
        RUN_HISTORY_COLUMNS,
        *[
            build_run_history_row(
                config,
                mission,
                run_id=run_id,
                target_date=target_date,
                iso_week=iso_week,
            )
            for mission in mission_summaries
        ],
    ]


def build_run_history_row(
    config: dict[str, Any],
    mission: dict[str, Any],
    *,
    run_id: str,
    target_date: date,
    iso_week: int,
) -> list[str]:
    hygiene_messages = "; ".join(str(issue.get("message", "")) for issue in mission.get("hygiene", []))
    blocker_text = "\n".join(str(blocker.get("text", "")) for blocker in mission.get("blockers", []))
    return [
        RUN_HISTORY_SCHEMA_VERSION,
        run_id,
        str(get_path(config, "team.id", "")),
        str(get_path(config, "team.name", "")),
        target_date.isoformat(),
        str(iso_week),
        str(mission.get("key", "")),
        str(mission.get("mission", "")),
        str(mission.get("mission_url", "")),
        str(mission.get("original_month_label", "")),
        str(mission.get("mission_type", "")),
        str(mission.get("dri", "")),
        str(mission.get("jira_status", "")),
        str(mission.get("status", "")),
        "yes" if mission.get("is_done") else "no",
        str(mission.get("original_due_date", "")),
        str(mission.get("current_due_date", "")),
        str(mission.get("effective_due_date", "")),
        str(mission.get("due_date_movement", "")),
        str(mission.get("due_date_delta_days", "")),
        str(mission.get("due_date_overdue_days", "")),
        "yes" if mission.get("missing_update") else "no",
        str(mission.get("missing_update_weeks", "")),
        str(mission.get("latest_valid_comment_timestamp", "")),
        blocker_text,
        str(mission.get("hygiene_severity", "")),
        hygiene_messages,
        str(mission.get("first_observed_date", "")),
        str(mission.get("done_date", "")),
        str(mission.get("cycle_time_days", "")),
    ]


def merge_run_history_values(
    existing_values: list[list[Any]],
    current_run_values: list[list[Any]],
    *,
    run_id: str,
) -> list[list[str]]:
    current_rows = [list(map(str, row)) for row in current_run_values[1:]]
    if not existing_values:
        return [RUN_HISTORY_COLUMNS, *current_rows]
    headers = [str(header) for header in existing_values[0]]
    run_id_index = header_index(headers, "Run ID")
    preserved_rows: list[list[str]] = []
    if run_id_index is not None:
        for row in existing_values[1:]:
            existing_run_id = str(row[run_id_index]) if run_id_index < len(row) else ""
            if existing_run_id != run_id:
                preserved_rows.append(normalize_run_history_row(headers, row))
    else:
        preserved_rows = [normalize_run_history_row(headers, row) for row in existing_values[1:]]
    return [RUN_HISTORY_COLUMNS, *preserved_rows, *current_rows]


def normalize_run_history_row(headers: list[str], row: list[Any]) -> list[str]:
    row_dict = row_to_dict(headers, row)
    return [str(row_dict.get(column, "") or "") for column in RUN_HISTORY_COLUMNS]


def due_date_movement_delta(movement: Any) -> int:
    match = re.search(r"\(([+-]\d+)d\)", str(movement or ""))
    return int(match.group(1)) if match else 0


@dataclass
class SheetHistory:
    previous_due_dates: dict[str, str]
    original_due_dates: dict[str, str]
    observed_mission_keys: set[str]
    missing_update_streaks: dict[str, int]
    blocker_first_seen_weeks: dict[str, int]
    first_observed_dates: dict[str, str]
    done_dates: dict[str, str]


def empty_sheet_history() -> SheetHistory:
    return SheetHistory(
        previous_due_dates={},
        original_due_dates={},
        observed_mission_keys=set(),
        missing_update_streaks={},
        blocker_first_seen_weeks={},
        first_observed_dates={},
        done_dates={},
    )


def parse_sheet_history(history_tabs: list[dict[str, Any]], *, current_week: int) -> SheetHistory:
    """Parse previous weekly sheet rows into due-date and missing-update history."""

    rows_by_key: dict[str, list[dict[str, str]]] = {}
    for tab in history_tabs:
        values = tab.get("values") or []
        if not values:
            continue
        headers = [str(header) for header in values[0]]
        tab_week = parse_week_number(str(tab.get("name", "")))
        for raw_row in values[1:]:
            row = row_to_dict(headers, raw_row)
            key = row.get("Mission key", "")
            if not key:
                continue
            week = parse_int(row.get("Week")) or tab_week
            if week is None or week >= current_week:
                continue
            row["_week"] = str(week)
            rows_by_key.setdefault(key, []).append(row)

    previous_due_dates: dict[str, str] = {}
    original_due_dates: dict[str, str] = {}
    observed_mission_keys: set[str] = set()
    missing_update_streaks: dict[str, int] = {}
    blocker_first_seen_weeks: dict[str, int] = {}
    for key, rows in rows_by_key.items():
        observed_mission_keys.add(key)
        rows.sort(key=lambda row: int(row["_week"]), reverse=True)
        previous_due_dates[key] = next(
            (
                previous_due_date_from_row(row)
                for row in rows
                if previous_due_date_from_row(row)
            ),
            "",
        )
        original_due_dates[key] = earliest_due_date_from_rows(rows)
        streak = 0
        for row in rows:
            if str(row.get("Missing update?", "")).strip().lower() == "yes":
                streak += 1
            else:
                break
        missing_update_streaks[key] = streak
        for row in rows:
            week = int(row["_week"])
            for item in blocker_items(row.get("Blockers / risks", "")):
                fingerprint = blocker_fingerprint(item)
                if not fingerprint:
                    continue
                history_key = blocker_history_key(key, fingerprint)
                if history_key not in blocker_first_seen_weeks or week < blocker_first_seen_weeks[history_key]:
                    blocker_first_seen_weeks[history_key] = week
    return SheetHistory(
        previous_due_dates={key: value for key, value in previous_due_dates.items() if value},
        original_due_dates={key: value for key, value in original_due_dates.items() if value},
        observed_mission_keys=observed_mission_keys,
        missing_update_streaks=missing_update_streaks,
        blocker_first_seen_weeks=blocker_first_seen_weeks,
        first_observed_dates={},
        done_dates={},
    )


def parse_run_history(
    values: list[list[Any]],
    *,
    current_run_id: str,
    target_date: date,
) -> SheetHistory:
    """Parse the V3 run-history tab into history used by the current run."""

    if not values:
        return empty_sheet_history()
    headers = [str(header) for header in values[0]]
    rows_by_key: dict[str, list[dict[str, str]]] = {}
    for raw_row in values[1:]:
        row = row_to_dict(headers, raw_row)
        key = first_non_empty(row, "Mission key", "mission_key")
        if not key:
            continue
        if first_non_empty(row, "Run ID", "run_id") == current_run_id:
            continue
        row_target = parse_due_date(first_non_empty(row, "Target date", "target_date"))
        if row_target and row_target >= target_date:
            continue
        row["_target_date"] = row_target.isoformat() if row_target else ""
        row["_week"] = first_non_empty(row, "ISO week", "Week", "week") or "0"
        rows_by_key.setdefault(key, []).append(row)

    previous_due_dates: dict[str, str] = {}
    original_due_dates: dict[str, str] = {}
    observed_mission_keys: set[str] = set()
    missing_update_streaks: dict[str, int] = {}
    blocker_first_seen_weeks: dict[str, int] = {}
    first_observed_dates: dict[str, str] = {}
    done_dates: dict[str, str] = {}

    for key, rows in rows_by_key.items():
        observed_mission_keys.add(key)
        rows.sort(key=history_row_sort_key, reverse=True)
        previous_due_dates[key] = next(
            (
                previous_due_date_from_row(row)
                for row in rows
                if previous_due_date_from_row(row)
            ),
            "",
        )
        original_due_dates[key] = earliest_run_history_due_date(rows)
        first_observed_dates[key] = earliest_first_observed_date(rows)
        done_dates[key] = earliest_done_date(rows)
        streak = 0
        for row in rows:
            if yes_no_value(first_non_empty(row, "Missing update?", "missing_update")):
                streak += 1
            else:
                break
        missing_update_streaks[key] = streak
        for row in rows:
            week = parse_int(first_non_empty(row, "ISO week", "Week", "week")) or 0
            for item in blocker_items(row.get("Blockers / risks", "")):
                fingerprint = blocker_fingerprint(item)
                if not fingerprint:
                    continue
                history_key = blocker_history_key(key, fingerprint)
                if history_key not in blocker_first_seen_weeks or week < blocker_first_seen_weeks[history_key]:
                    blocker_first_seen_weeks[history_key] = week
    return SheetHistory(
        previous_due_dates={key: value for key, value in previous_due_dates.items() if value},
        original_due_dates={key: value for key, value in original_due_dates.items() if value},
        observed_mission_keys=observed_mission_keys,
        missing_update_streaks=missing_update_streaks,
        blocker_first_seen_weeks=blocker_first_seen_weeks,
        first_observed_dates={key: value for key, value in first_observed_dates.items() if value},
        done_dates={key: value for key, value in done_dates.items() if value},
    )


def previous_due_date_from_row(row: dict[str, str]) -> str:
    return first_non_empty(row, "current_due_date", "Current due date", "Due date")


def earliest_due_date_from_rows(rows: list[dict[str, str]]) -> str:
    for row in sorted(rows, key=lambda item: int(item["_week"])):
        movement_original = original_due_date_from_movement(row.get("Due date movement", ""))
        if movement_original:
            return movement_original
        due_date = previous_due_date_from_row(row)
        if due_date:
            return due_date
    return ""


def earliest_run_history_due_date(rows: list[dict[str, str]]) -> str:
    for row in sorted(rows, key=history_row_sort_key):
        original_due_date = first_non_empty(row, "Original due date", "original_due_date")
        if original_due_date:
            return original_due_date
        movement_original = original_due_date_from_movement(row.get("Due date movement", ""))
        if movement_original:
            return movement_original
        due_date = first_non_empty(row, "Current due date", "Due date", "Effective due date")
        if due_date:
            return due_date
    return ""


def earliest_first_observed_date(rows: list[dict[str, str]]) -> str:
    candidates = []
    for row in rows:
        first_observed = first_non_empty(row, "First observed date", "first_observed_date")
        target = first_non_empty(row, "Target date", "target_date")
        for value in (first_observed, target):
            parsed = parse_due_date(value)
            if parsed:
                candidates.append(parsed)
    return min(candidates).isoformat() if candidates else ""


def earliest_done_date(rows: list[dict[str, str]]) -> str:
    candidates = []
    for row in rows:
        done_date = parse_due_date(first_non_empty(row, "Done date", "done_date"))
        if done_date:
            candidates.append(done_date)
            continue
        if yes_no_value(first_non_empty(row, "Is done", "is_done")):
            target = parse_due_date(first_non_empty(row, "Target date", "target_date"))
            if target:
                candidates.append(target)
    return min(candidates).isoformat() if candidates else ""


def history_row_sort_key(row: dict[str, str]) -> tuple[date, int]:
    target = parse_due_date(first_non_empty(row, "_target_date", "Target date", "target_date")) or date.min
    week = parse_int(first_non_empty(row, "_week", "ISO week", "Week", "week")) or 0
    return target, week


def yes_no_value(value: Any) -> bool:
    return str(value or "").strip().lower() in {"yes", "true", "1", "y"}


def original_due_date_from_movement(value: Any) -> str:
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\s*->\s*\d{4}-\d{2}-\d{2}\b", str(value or ""))
    return match.group(1) if match else ""


def original_due_date_for_mission(
    history: SheetHistory,
    *,
    mission_key: str,
    current_due_date: Any,
) -> str:
    original = history.original_due_dates.get(mission_key, "")
    if original:
        return original
    current = str(current_due_date or "").strip()
    if current:
        return current
    return ""


def first_non_empty(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key, "") or "").strip()
        if value:
            return value
    return ""


def mission_history_fields(
    history: SheetHistory,
    *,
    mission_key: str,
    target_date: date,
    is_done: bool,
) -> dict[str, Any]:
    first_observed_date = history.first_observed_dates.get(mission_key) or target_date.isoformat()
    done_date = history.done_dates.get(mission_key) or (target_date.isoformat() if is_done else "")
    cycle_time_days = days_between(first_observed_date, done_date) if done_date else ""
    active_age_days = "" if done_date else days_between(first_observed_date, target_date.isoformat())
    return {
        "first_observed_date": first_observed_date,
        "done_date": done_date,
        "cycle_time_days": cycle_time_days if cycle_time_days is not None else "",
        "active_age_days": active_age_days if active_age_days is not None else "",
    }


def days_between(start: Any, end: Any) -> int | None:
    start_date = parse_due_date(start)
    end_date = parse_due_date(end)
    if start_date is None or end_date is None:
        return None
    return max((end_date - start_date).days, 0)


def header_index(headers: list[str], header_name: str) -> int | None:
    for index, header in enumerate(headers):
        if header == header_name:
            return index
    return None


def apply_blocker_history(
    blockers: list[Blocker],
    history: SheetHistory,
    *,
    mission_key: str,
    current_week: int,
) -> list[Blocker]:
    resolved: list[Blocker] = []
    for blocker in blockers:
        fingerprint = blocker_fingerprint(blocker.text)
        first_seen_week = history.blocker_first_seen_weeks.get(blocker_history_key(mission_key, fingerprint))
        if first_seen_week is None:
            first_seen_week = current_week
        days_open = blocker_days_open_label(current_week, first_seen_week)
        resolved.append(
            replace(
                blocker,
                days_open=days_open,
                first_seen_week=str(first_seen_week),
            )
        )
    return resolved


def blocker_days_open_label(current_week: int, first_seen_week: int) -> str:
    days_open = max((current_week - first_seen_week) * 7, 0)
    return "new risk" if days_open == 0 else str(days_open)


def blocker_history_key(mission_key: str, fingerprint: str) -> str:
    return f"{mission_key}\0{fingerprint}"


def parse_update_options(validation_config: dict[str, Any]) -> dict[str, Any]:
    """Keep parser options separate from hygiene-only validation settings."""

    allowed = {
        "require_template_match",
        "minimum_score",
        "optional_sections",
        "allow_section_aliases",
        "allow_unstructured_if_confident",
    }
    return {key: value for key, value in (validation_config or {}).items() if key in allowed}


def row_to_dict(headers: list[str], row: list[Any]) -> dict[str, str]:
    return {header: str(row[index]) if index < len(row) else "" for index, header in enumerate(headers)}


def parse_week_number(name: str) -> int | None:
    match = re.search(r"\bWeek\s+(\d+)\b", name, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def parse_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def due_date_change_status(
    current_due_date: Any,
    previous_due_date: str | None,
    *,
    observed_before: bool,
    history_available: bool = True,
) -> str:
    current = str(current_due_date or "")
    if not current:
        return "missing"
    if not history_available:
        return "history_unavailable"
    if not observed_before or not previous_due_date:
        return "first_observed"
    return "changed" if current != previous_due_date else "unchanged"


def due_date_movement_label(
    current_due_date: Any,
    previous_due_date: str | None,
    *,
    observed_before: bool,
    history_available: bool = True,
    target_date: date | None = None,
) -> str:
    current = str(current_due_date or "").strip()
    previous = str(previous_due_date or "").strip()
    overdue_suffix = due_date_overdue_suffix(current, target_date)
    status = due_date_change_status(
        current,
        previous,
        observed_before=observed_before,
        history_available=history_available,
    )
    if status == "missing":
        return ""
    if status == "history_unavailable":
        return append_due_date_suffix(f"history unavailable: {current}", overdue_suffix)
    if status == "first_observed":
        return overdue_suffix
    if status == "unchanged":
        return overdue_suffix

    delta = due_date_delta_days(previous, current)
    if delta is None:
        return append_due_date_suffix(f"{previous} -> {current}", overdue_suffix)
    return append_due_date_suffix(f"{previous} -> {current} ({delta:+d}d)", overdue_suffix)


def due_date_overdue_suffix(current_due_date: Any, target_date: date | None) -> str:
    days_overdue = due_date_overdue_days(current_due_date, target_date)
    return f"overdue by {format_day_count(days_overdue)}" if days_overdue > 0 else ""


def append_due_date_suffix(label: str, suffix: str) -> str:
    return f"{label}; {suffix}" if suffix else label


def due_date_delta_days(previous_due_date: str, current_due_date: str) -> int | None:
    previous = parse_due_date(previous_due_date)
    current = parse_due_date(current_due_date)
    if previous is None or current is None:
        return None
    return (current - previous).days


def parse_due_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text.split("T", 1)[0])
    except ValueError:
        return None


def mission_matches_config(mission: dict[str, Any], config: dict[str, Any], label: str) -> bool:
    labels = mission.get("labels", []) or []
    if label not in labels:
        return False
    issue_type = mission.get("issue_type") or mission.get("issuetype") or get_path(mission, "fields.issuetype.name")
    expected_type = get_path(config, "jira.epic_issue_type")
    if issue_type and expected_type and str(issue_type).lower() != str(expected_type).lower():
        return False
    project_key = mission.get("project_key") or get_path(mission, "fields.project.key")
    expected_project = get_path(config, "jira.project_key")
    if expected_project and project_key and str(project_key) != str(expected_project):
        return False
    board_id = str(mission.get("board_id", ""))
    expected_board = str(get_path(config, "jira.board_id", ""))
    if expected_board and board_id and board_id != expected_board:
        return False
    return True


def normalize_fixture_mission(mission: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    base_url = str(get_path(config, "jira.base_url", "")).rstrip("/")
    key = str(mission.get("key", ""))
    normalized = dict(mission)
    normalized.setdefault("name", mission.get("summary", ""))
    normalized.setdefault("url", f"{base_url}/browse/{key}" if base_url and key else "")
    normalized.setdefault("base_url", base_url)
    return normalized


def build_mission_jql(config: dict[str, Any], label: str) -> str:
    clauses = [
        f'issuetype = "{get_path(config, "jira.epic_issue_type", "Epic")}"',
        f'labels = "{label}"',
    ]
    project_key = get_path(config, "jira.project_key")
    if project_key:
        clauses.insert(0, f"project = {project_key}")
    return " AND ".join(clauses) + " ORDER BY status DESC, key ASC"


def build_child_issue_jql(issue_key: str) -> str:
    return f"parent = {issue_key} ORDER BY key ASC"


def jira_fields_to_request(config: dict[str, Any]) -> set[str]:
    fields = {"summary", "status", "assignee", "labels", "duedate", "issuetype", "project"}
    for field_config in (get_path(config, "jira.fields", {}) or {}).values():
        field_id = field_config.get("field_id")
        if field_id:
            fields.add(field_id)
    fields.add("progress")
    fields.add("aggregateprogress")
    return fields


def child_issue_fields_to_request() -> set[str]:
    return {"summary", "status", "issuetype", "parent"}


def apply_derived_progress(
    mission: dict[str, Any],
    config: dict[str, Any],
    jira_adapter: JiraAdapter,
) -> None:
    progress_config = get_path(config, "jira.fields.progress", {}) or {}
    if progress_config.get("field_id"):
        return
    source = progress_config.get("source")
    if source != "child_issue_progress":
        return
    mission["progress"] = child_issue_progress(
        jira_adapter.get_child_issues(mission, config),
        config,
    )


def apply_issue_property_fields(
    mission: dict[str, Any],
    config: dict[str, Any],
    jira_adapter: JiraAdapter,
) -> None:
    linked_okr_config = get_path(config, "jira.fields.linked_okr", {}) or {}
    if linked_okr_config.get("source") != "issue_property":
        return
    property_key = str(linked_okr_config.get("property_key") or "")
    if not property_key:
        return
    property_payload = jira_adapter.get_issue_property(mission, property_key)
    if not property_payload:
        mission["linked_okr"] = ""
        return
    mission["linked_okr"] = stringify_field_value(
        get_path(property_payload, str(linked_okr_config.get("path") or "value"))
    )


def child_issue_progress(children: list[dict[str, Any]], config: dict[str, Any]) -> str:
    total = 0
    done = 0
    done_statuses = {
        normalize_status_name(status)
        for status in (get_path(config, "jira.done_statuses", []) or [])
    }
    for child in children:
        fields = child.get("fields", child)
        if get_path(fields, "issuetype.subtask") is True:
            continue
        total += 1
        status = fields.get("status") if isinstance(fields, dict) else None
        if status_is_done(status, done_statuses):
            done += 1
    if total == 0:
        return ""
    return stringify_percent(round((done / total) * 100))


def status_is_done(status: Any, done_statuses: set[str]) -> bool:
    if isinstance(status, dict):
        category_key = normalize_status_name(get_path(status, "statusCategory.key"))
        category_name = normalize_status_name(get_path(status, "statusCategory.name"))
        status_name = normalize_status_name(status.get("name"))
        return (
            category_key == "done"
            or category_name == "done"
            or status_name in done_statuses
        )
    return normalize_status_name(status) in done_statuses


def normalize_status_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def normalize_jira_issue(issue: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields", {})
    base_url = str(get_path(config, "jira.base_url", "")).rstrip("/")
    key = issue.get("key", "")
    linked_okr_field = get_path(config, "jira.fields.linked_okr.field_id", "")
    linked_okr_source = get_path(config, "jira.fields.linked_okr.source", "")
    progress_field = get_path(config, "jira.fields.progress.field_id", "")
    progress_source = get_path(config, "jira.fields.progress.source", "")
    due_date_field = get_path(config, "jira.fields.due_date.field_id", "duedate")
    status_value = field_value(fields, get_path(config, "jira.fields.status.field_id", "status"))
    if progress_field:
        progress = field_value(fields, progress_field)
    elif progress_source == "child_issue_progress":
        progress = ""
    else:
        progress = fields.get("progress") or fields.get("aggregateprogress")
    return {
        "key": key,
        "name": fields.get("summary", ""),
        "summary": fields.get("summary", ""),
        "url": f"{base_url}/browse/{key}" if base_url and key else "",
        "base_url": base_url,
        "project_key": get_path(fields, "project.key", ""),
        "issue_type": get_path(fields, "issuetype.name", ""),
        "labels": fields.get("labels", []) or [],
        "dri": normalize_jira_user(field_value(fields, get_path(config, "jira.fields.dri.field_id", "assignee"))),
        "due_date": field_value(fields, due_date_field),
        "progress": normalize_jira_progress(progress),
        "linked_okr": ""
        if linked_okr_source == "issue_property"
        else stringify_field_value(field_value(fields, linked_okr_field)) if linked_okr_field else "",
        "status": normalize_jira_status(status_value),
    }


def field_value(fields: dict[str, Any], field_id: str | None) -> Any:
    if not field_id:
        return ""
    value = fields.get(field_id, "")
    return "" if value is None else value


def normalize_jira_user(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "accountId": value.get("accountId", ""),
        "displayName": value.get("displayName", ""),
        "emailAddress": value.get("emailAddress", ""),
    }


def normalize_jira_status(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name", ""))
    return str(value or "")


def normalize_jira_progress(value: Any) -> str:
    if isinstance(value, dict):
        if "percent" in value:
            return stringify_percent(value["percent"])
        progress = value.get("progress")
        total = value.get("total")
        if isinstance(progress, (int, float)) and isinstance(total, (int, float)) and total:
            return stringify_percent(round((progress / total) * 100))
        if isinstance(progress, (int, float)) and total == 0:
            return ""
    return stringify_percent(value)


def stringify_field_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("value", "name", "displayName", "key", "id"):
            if value.get(key):
                return str(value[key])
        return json.dumps(value, sort_keys=True)
    if isinstance(value, list):
        return ", ".join(stringify_field_value(item) for item in value if stringify_field_value(item))
    return str(value)


def normalize_jira_comment(comment: dict[str, Any], base_url: str, issue_key: str) -> dict[str, Any]:
    comment_id = str(comment.get("id", ""))
    url = (
        f"{base_url}/browse/{issue_key}?focusedCommentId={comment_id}"
        "&page=com.atlassian.jira.plugin.system.issuetabpanels:comment-tabpanel"
        f"#comment-{comment_id}"
        if comment_id
        else ""
    )
    normalized = dict(comment)
    normalized["url"] = url
    return normalized


def write_output_files(
    result: dict[str, Any],
    output_dir: str | Path,
    *,
    jira_snapshot: dict[str, Any] | None = None,
) -> dict[str, str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    files = {
        "result_json": output_path / "rollup-result.json",
        "email_html": output_path / "draft-email.html",
        "email_mime": output_path / "draft-email.eml",
        "email_text": output_path / "draft-email.txt",
        "sheet_values": output_path / "sheet-values.json",
        "sheet_csv": output_path / "sheet-preview.csv",
        "run_history_values": output_path / "run-history-values.json",
    }
    serializable = dict(result)
    serializable.pop("output_files", None)
    files["result_json"].write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
    files["email_html"].write_text(result["draft_email"]["html_body"], encoding="utf-8")
    files["email_text"].write_text(result["draft_email"]["text_body"], encoding="utf-8")
    mime_bytes = build_email_mime(result["draft_email"])
    files["email_mime"].write_bytes(mime_bytes)
    files["sheet_values"].write_text(json.dumps(result["sheet_values"], indent=2, ensure_ascii=False), encoding="utf-8")
    files["run_history_values"].write_text(
        json.dumps(result["run_history"]["current_run_values"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    with files["sheet_csv"].open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerows(result["sheet_values"])
    if result["sheet_write"].get("request"):
        request_path = output_path / "sheet-mcp-request.json"
        request_path.write_text(json.dumps(result["sheet_write"]["request"], indent=2, ensure_ascii=False), encoding="utf-8")
        files["sheet_mcp_request"] = request_path
    if result.get("run_history_write", {}).get("request"):
        request_path = output_path / "run-history-mcp-request.json"
        request_path.write_text(
            json.dumps(result["run_history_write"]["request"], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        files["run_history_mcp_request"] = request_path
    if result.get("email_create", {}).get("request"):
        request_path = output_path / "email-mcp-request.json"
        request_path.write_text(json.dumps(result["email_create"]["request"], indent=2, ensure_ascii=False), encoding="utf-8")
        files["email_mcp_request"] = request_path
    raw_request_path = output_path / "gmail-raw-draft-request.json"
    raw_request_path.write_text(
        json.dumps(gmail_raw_draft_request_for_email(result["draft_email"]), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    files["gmail_raw_draft_request"] = raw_request_path
    if jira_snapshot:
        snapshot_date = str(jira_snapshot.get("target_date") or result.get("target_date") or "run")
        snapshot_path = output_path / f"data-snapshot-{snapshot_date}.json"
        snapshot_path.write_text(json.dumps(jira_snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
        files["data_snapshot"] = snapshot_path
    return {name: str(path) for name, path in files.items()}


def build_email_mime(draft_email: dict[str, Any]) -> bytes:
    message = EmailMessage()
    if draft_email.get("subject"):
        message["Subject"] = str(draft_email.get("subject", ""))
    from_address = str(draft_email.get("from_address") or draft_email.get("from") or "")
    to = comma_join(draft_email.get("to", []))
    cc = comma_join(draft_email.get("cc", []))
    bcc = comma_join(draft_email.get("bcc", []))
    if from_address:
        message["From"] = from_address
    if to:
        message["To"] = to
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc
    plain_text_body = str(draft_email.get("plainTextBody") or draft_email.get("text_body", ""))
    html_body = str(draft_email.get("htmlBody") or draft_email.get("html_body", ""))
    message.set_content(plain_text_body, subtype="plain", charset="utf-8")
    message.add_alternative(html_body, subtype="html", charset="utf-8")
    return message.as_bytes(policy=policy.default)


def gmail_raw_draft_request_for_email(draft_email: dict[str, Any]) -> dict[str, Any]:
    raw = base64.urlsafe_b64encode(build_email_mime(draft_email)).decode().rstrip("=")
    plain_text_body = str(draft_email.get("plainTextBody") or draft_email.get("text_body", ""))
    html_body = str(draft_email.get("htmlBody") or draft_email.get("html_body", ""))
    request_payload = gmail_raw_draft_request(raw)
    request_payload.update(
        {
            "operation": "create_html_draft",
            "to": comma_join(draft_email.get("to", [])),
            "cc": comma_join(draft_email.get("cc", [])),
            "bcc": comma_join(draft_email.get("bcc", [])),
            "subject": str(draft_email.get("subject", "")),
            "plainTextBody": plain_text_body,
            "htmlBody": html_body,
            "body_source": "raw_mime.multipart_alternative",
        }
    )
    return request_payload


def gmail_raw_draft_request(raw: str) -> dict[str, Any]:
    return {
        "api": "gmail.users.drafts.create",
        "method": "POST",
        "path": "/gmail/v1/users/me/drafts",
        "body": {"message": {"raw": raw}},
        "mime_type": "multipart/alternative",
        "html_capable": True,
        "mcp_tool_compatible": False,
        "note": "Requires a Gmail API/raw-MIME capable client. Do not pass this through a body-only Gmail draft helper.",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Team YAML/JSON config")
    parser.add_argument("--expect-team-id", help="Fail before adapters run if config team.id does not match this team")
    parser.add_argument("--expect-team-name", help="Fail before adapters run if config team.name does not match this team")
    parser.add_argument("--date", help="Target run date in YYYY-MM-DD. Defaults to today.")
    parser.add_argument(
        "--jira-source",
        choices=["fixture", "mcp", "snapshot"],
        default="fixture",
        help="Where to read Jira mission Epics/comments from",
    )
    parser.add_argument("--jira-fixture", help="Fixture JSON for --jira-source fixture")
    parser.add_argument("--jira-snapshot", help="Data snapshot JSON for --jira-source snapshot")
    parser.add_argument("--jira-mcp-dir", help="Path to a local jira-mcp checkout for --jira-source mcp (defaults to the in-tree jira-mcp/)")
    parser.add_argument(
        "--collect-jira-snapshot-only",
        action="store_true",
        help="Collect data-snapshot-<date>.json through the Jira MCP and exit before rollup rendering",
    )
    parser.add_argument(
        "--sheet-source",
        choices=["fixture", "mcp-plan"],
        default="mcp-plan",
        help="How to handle sheet history and writes",
    )
    parser.add_argument("--sheet-fixture", help="Fixture JSON with history_tabs and optional sheet_write.fail")
    parser.add_argument(
        "--sheet-url",
        default="",
        help="Resolved Google Sheet URL to include in the email draft",
    )
    parser.add_argument(
        "--sheet-tab-gid",
        default="",
        help="Google Sheets gid/sheetId for the current week tab; appended to --sheet-url for the email draft",
    )
    parser.add_argument(
        "--email-source",
        choices=["none", "raw-mime-plan"],
        default="raw-mime-plan",
        help="How to handle email draft output",
    )
    parser.add_argument("--output-dir", help="Directory for result/email/sheet artifacts")
    parser.add_argument("--json", action="store_true", help="Print full JSON result")
    return parser.parse_args()


def jira_adapter_from_args(
    args: argparse.Namespace,
    config: dict[str, Any],
    target: date,
) -> tuple[JiraAdapter, dict[str, Any] | None]:
    if args.jira_source == "fixture":
        if not args.jira_fixture:
            raise ConfigError("--jira-fixture is required with --jira-source fixture")
        return FixtureJiraAdapter(args.jira_fixture), None
    if args.jira_source == "snapshot":
        if not args.jira_snapshot:
            raise ConfigError("--jira-snapshot is required with --jira-source snapshot")
        snapshot = json.loads(Path(args.jira_snapshot).read_text(encoding="utf-8"))
        return FixtureJiraAdapter.from_data(snapshot), snapshot

    live_adapter = JiraMcpAdapter(args.jira_mcp_dir)
    snapshot = collect_jira_snapshot(config, target, live_adapter, source="jira-mcp")
    return FixtureJiraAdapter.from_data(snapshot), snapshot


def non_jira_adapters_from_args(args: argparse.Namespace) -> tuple[SheetAdapter, EmailAdapter | None]:
    if args.sheet_source == "fixture":
        sheet_adapter: SheetAdapter = FixtureSheetAdapter(args.sheet_fixture)
    else:
        sheet_adapter = McpPlanSheetAdapter(args.sheet_fixture)

    email_adapter: EmailAdapter | None
    if args.email_source == "none":
        email_adapter = None
    elif args.email_source == "raw-mime-plan":
        email_adapter = RawMimePlanEmailAdapter()
    return sheet_adapter, email_adapter


def write_jira_snapshot_file(snapshot: dict[str, Any], output_dir: str | Path) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    snapshot_date = str(snapshot.get("target_date") or "run")
    snapshot_path = output_path / f"data-snapshot-{snapshot_date}.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    return snapshot_path


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    identity_errors = validate_expected_team(
        config,
        expected_team_id=args.expect_team_id,
        expected_team_name=args.expect_team_name,
    )
    if identity_errors:
        raise ConfigError("; ".join(identity_errors))
    target = date.fromisoformat(args.date) if args.date else date.today()
    jira_adapter, jira_snapshot = jira_adapter_from_args(args, config, target)
    if args.collect_jira_snapshot_only:
        if args.jira_source != "mcp":
            raise ConfigError("--collect-jira-snapshot-only requires --jira-source mcp")
        if not args.output_dir:
            raise ConfigError("--collect-jira-snapshot-only requires --output-dir")
        snapshot_path = write_jira_snapshot_file(jira_snapshot or {}, args.output_dir)
        summary = jira_snapshot_summary(jira_snapshot or {})
        print(f"Wrote Jira snapshot: {snapshot_path}")
        print(
            "Summary: "
            f"{summary['mission_count']} missions, "
            f"{summary['error_count']} retrieval errors, "
            f"label {summary['month_label']}, "
            f"week {summary['iso_week']}"
        )
        return 1 if summary["error_count"] else 0

    sheet_adapter, email_adapter = non_jira_adapters_from_args(args)
    result = run_rollup(
        config,
        target,
        jira_adapter,
        sheet_adapter,
        email_adapter=email_adapter,
        jira_snapshot=jira_snapshot,
        output_dir=args.output_dir,
        sheet_url_override=args.sheet_url,
        sheet_tab_gid=args.sheet_tab_gid,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_human_summary(result)
    return 1 if result["errors"] else 0


def print_human_summary(result: dict[str, Any]) -> None:
    subject = result["draft_email"]["subject"]
    print(subject)
    print()
    print(f"Mission label: {result['month_label']}")
    print(f"Window: {result['window']['start']} → {result['window']['end']}")
    print(
        "Summary: "
        f"{result['mission_count']} missions, "
        f"{result['status_counts']['green']} green, "
        f"{result['status_counts']['yellow']} yellow, "
        f"{result['status_counts']['red']} red, "
        f"{result['status_counts'].get('not_started', 0)} not started, "
        f"{result['status_counts'].get('done', 0)} done, "
        f"{result['missing_update_count']} missing updates, "
        f"{result['stale_update_count']} stale updates, "
        f"{result['due_date_changed_count']} due date changes, "
        f"{result['due_date_moved_later_count']} moved later, "
        f"{result['due_date_moved_earlier_count']} moved earlier, "
        f"{result['overdue_mission_count']} overdue, "
        f"{result['blocker_count']} blockers/risks"
    )
    hygiene_counts = result.get("hygiene_issue_counts", {})
    print(
        "Hygiene: "
        f"{hygiene_counts.get('red', 0)} red, "
        f"{hygiene_counts.get('yellow', 0)} yellow, "
        f"{hygiene_counts.get('info', 0)} info"
    )
    metrics = result.get("metrics", {})
    print(
        "Metrics: "
        f"{metrics.get('completed_mission_count', 0)}/{metrics.get('mission_count', 0)} completed "
        f"({format_completion_rate(metrics.get('completion_rate'))}), "
        f"{metrics.get('active_mission_count', 0)} active, "
        f"avg cycle {format_metric_days(metrics.get('average_cycle_time_days'))}, "
        f"avg active age {format_metric_days(metrics.get('active_mission_average_age_days'))}, "
        f"{metrics.get('recurring_missing_update_count', 0)} recurring misses"
    )
    print(
        f"Sheet: {result['sheet_write']['status']} "
        f"({result['sheet_write']['tab_name']}, {result['sheet_write']['row_count']} rows)"
    )
    run_history = result.get("run_history", {})
    run_history_write = result.get("run_history_write", {})
    print(
        f"Run history: {run_history.get('read_status', 'unknown')} read from "
        f"{run_history.get('source', 'unknown')}, {run_history_write.get('status', 'unknown')} write "
        f"({run_history.get('tab_name', '')}, {run_history_write.get('row_count', 0)} rows)"
    )
    print(
        f"Email: {result['email_create']['status']} "
        f"({result['email_create']['to']}, {result['email_create']['subject']})"
    )
    if result.get("output_files"):
        print("Output files:")
        for name, path in result["output_files"].items():
            print(f"- {name}: {path}")
    if result["hygiene_issues"]:
        print()
        print("Data hygiene:")
        for issue in result["hygiene_issues"]:
            print(
                f"- {issue['severity'].upper()} {issue['mission_key']} "
                f"{issue['mission']}: {issue['message']}"
            )
    if result.get("warnings"):
        print()
        print("Warnings:")
        for warning in result["warnings"]:
            print(f"- {warning.get('source')}: {warning.get('message')}")
    if result["errors"]:
        print()
        print("Errors:")
        for error in result["errors"]:
            print(f"- {error.get('source')}: {error.get('message')}")


def format_completion_rate(value: Any) -> str:
    try:
        return f"{round(float(value) * 100)}%"
    except (TypeError, ValueError):
        return "n/a"


def format_metric_days(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    return f"{value} day" if str(value) == "1" else f"{value} days"


if __name__ == "__main__":
    raise SystemExit(main())
