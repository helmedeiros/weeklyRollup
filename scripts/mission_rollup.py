"""Core logic for the Engineer-Owned Mission weekly rollup skill.

The module intentionally keeps product logic local and deterministic. Jira,
Google Sheets, and email clients should call these functions through thin
adapters instead of embedding parsing or hygiene rules in connector code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from html import escape
import json
import os
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only on minimal systems
    yaml = None

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from markupsafe import Markup, escape as markup_escape
except ImportError:  # pragma: no cover - exercised only on minimal systems
    Environment = None
    FileSystemLoader = None
    Markup = None
    markup_escape = None
    select_autoescape = None


STATUS_GREEN = "Green"
STATUS_YELLOW = "Yellow"
STATUS_RED = "Red"
STATUS_MISSING = "Missing"
STATUS_DONE = "Done"
STATUS_NOT_STARTED = "Not Started"
# When set, every team config must pin sheet.folder_id to this exact value.
# Left blank in the tracked source so no organisation-specific folder id
# lives in git; deployments that want the enforcement export the id via
# WEEKLY_ROLLUP_REQUIRED_FOLDER_ID (typically alongside GOOGLE_SHEETS_MCP_URL).
REQUIRED_SHEET_FOLDER_ID = os.environ.get("WEEKLY_ROLLUP_REQUIRED_FOLDER_ID", "")
EMAIL_TEMPLATE_NAME = "mission-email.html"

STATUS_WORDS = {
    "green": STATUS_GREEN,
    "yellow": STATUS_YELLOW,
    "red": STATUS_RED,
}

STATUS_PHRASES = (
    (
        STATUS_RED,
        (
            r"\boff track\b",
            r"\bseverely delayed\b",
            r"\bdelayed\b",
            r"\bwill not ship\b",
            r"\b(?:won t|wont|cannot|can t|cant) ship\b",
            r"\bscope cut\b",
            r"\bmore capacity\b",
            r"\breplan\b",
        ),
    ),
    (
        STATUS_YELLOW,
        (
            r"\bat risk\b",
            r"\brisk of\b",
            r"\bscope concern\b",
            r"\bquality concern\b",
            r"\bunclear (?:target date|requirements)\b",
            r"\b(?:target date|requirements) unclear\b",
            r"\bneeds attention\b",
            r"\bslipping\b",
            r"\bblocked\b",
            r"\b(?:active|open|named|one) blockers?\b",
        ),
    ),
    (
        STATUS_GREEN,
        (
            r"\bon track\b",
            r"\bon schedule\b",
            r"\bas planned\b",
            r"\bto plan\b",
            r"\bno (?:active )?(?:blockers?|risks?)\b",
            r"\bhealthy\b",
            r"\bready to ship\b",
            r"\bwill ship\b",
        ),
    ),
)

STATUS_EMOJI = {
    "\U0001f7e2": STATUS_GREEN,
    "\U0001f7e1": STATUS_YELLOW,
    "\U0001f534": STATUS_RED,
}

STATUS_SORT = {
    STATUS_GREEN: 0,
    STATUS_YELLOW: 1,
    STATUS_RED: 2,
    STATUS_NOT_STARTED: 3,
    STATUS_MISSING: 4,
    STATUS_DONE: 5,
}

BLOCKER_STATUS_SORT = {
    STATUS_RED: 0,
    STATUS_YELLOW: 1,
    STATUS_GREEN: 2,
    STATUS_NOT_STARTED: 3,
    STATUS_MISSING: 4,
    STATUS_DONE: 5,
}

SECTION_NAMES = {
    "status": "Status",
    "done": "Done this week",
    "plan": "Plan for next week",
    "blockers": "Blockers / risks",
}

SECTION_ALIASES = {
    "status": {"status", "state"},
    "done": {
        "done",
        "done this week",
        "this week",
        "completed",
        "completed this week",
        "shipped",
        "shipped this week",
        "progress",
        "progress update",
        "weekly progress",
        "weekly progress update",
        "this week s progress",
        "discovery progress update",
    },
    "plan": {
        "plan",
        "plans",
        "next",
        "next up",
        "next week",
        "target next week",
        "target for next week",
        "target or plan for next week",
        "plan for next week",
        "planned for next week",
        "plans for next week",
        "plans next week",
        "planning for next week",
        "coming up",
        "next steps",
    },
    "blockers": {
        "blocker",
        "blockers",
        "risk",
        "risks",
        "risk blocker",
        "risk blockers",
        "risks blocker",
        "risks blockers",
        "blocker risk",
        "blocker risks",
        "blockers risk",
        "blockers risks",
        "risks and blockers",
        "risks or blockers",
        "blockers and risks",
        "blockers or risks",
        "dependencies",
        "dependency",
        "decisions",
        "decision",
        "decisions needed",
        "issues",
    },
}

REQUIRED_SECTIONS = ("status", "done", "plan", "blockers")
OPTIONAL_SECTIONS = ("blockers",)

NONE_VALUES = {
    "",
    "none",
    "none currently",
    "none right now",
    "no",
    "no blockers",
    "no blocker",
    "no blocker currently",
    "no blockers currently",
    "no blocker right now",
    "no blockers right now",
    "no risks",
    "no risk",
    "no risk currently",
    "no risks currently",
    "no risk right now",
    "no risks right now",
    "no material blocker identified",
    "no material blockers identified",
    "no material risk identified",
    "no material risks identified",
    "no issues",
    "no issue",
    "no dependencies",
    "no dependency",
    "no active blockers",
    "no active risks",
    "n/a",
    "na",
    "not applicable",
    "nothing",
    "absent",
    "-",
}

SHEET_COLUMNS = [
    "Mission key",
    "Mission name",
    "Mission URL",
    "Mission label",
    "DRI",
    "Status",
    "Jira progress %",
    "Due date",
    "Due date movement",
    "Done this week",
    "Plan for next week",
    "Blockers / risks",
    "Risk/blocker owners",
    "Risk/blocker days open",
    "Missing update?",
    "Missing update weeks",
    "DRI comment",
    "Hygiene issues",
]


@dataclass(frozen=True)
class ParsedUpdate:
    """Structured representation of a DRI weekly update comment."""

    status: str | None
    done_this_week: str
    plan_for_next_week: str
    blockers_risks: str
    template_valid: bool
    score: int
    risks: str = ""
    blockers: str = ""
    combined_risks_blockers: str = ""
    missing_sections: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Blocker:
    mission: str
    dri: str
    status: str
    text: str
    owner: str = ""
    days_open: str = ""
    first_seen_week: str = ""
    kind: str = ""  # "risk", "blocker", or "" (legacy combined)


@dataclass(frozen=True)
class CommentSelection:
    """Result of selecting the latest valid DRI update comment."""

    selected_comment: dict[str, Any] | None
    parsed_update: ParsedUpdate | None
    missing_update: bool
    malformed_update_seen: bool
    rejection_reasons: list[str] = field(default_factory=list)
    cover_author: bool = False


class ConfigError(ValueError):
    """Raised when a team configuration is not usable."""


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a JSON or YAML team config."""

    config_path = Path(path).expanduser()
    if not config_path.exists():
        raise ConfigError(
            f"Team config not found: {config_path}. "
            "Stop and ask for the correct local config; do not use example-team.yaml for named team runs."
        )
    text = config_path.read_text(encoding="utf-8")
    if config_path.suffix.lower() == ".json":
        return json.loads(text)
    if yaml is None:
        raise ConfigError("PyYAML is required to read YAML config files")
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ConfigError("Config root must be a mapping/object")
    return loaded


def validate_expected_team(
    config: dict[str, Any],
    *,
    expected_team_id: str | None = None,
    expected_team_name: str | None = None,
) -> list[str]:
    """Return errors when a config is valid but for the wrong requested team."""

    errors: list[str] = []
    actual_team_id = str(get_path(config, "team.id", "") or "")
    actual_team_name = str(get_path(config, "team.name", "") or "")

    if expected_team_id and normalize_team_identity(actual_team_id) != normalize_team_identity(expected_team_id):
        errors.append(f"Config team.id mismatch: expected {expected_team_id}, found {actual_team_id or '<missing>'}")
    if expected_team_name and normalize_team_identity(actual_team_name) != normalize_team_identity(expected_team_name):
        errors.append(f"Config team.name mismatch: expected {expected_team_name}, found {actual_team_name or '<missing>'}")
    return errors


def normalize_team_identity(value: str) -> str:
    """Normalize team ids/names so spaces, underscores, and hyphens compare safely."""

    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def validate_team_config(config: dict[str, Any]) -> list[str]:
    """Return actionable config validation errors."""

    errors: list[str] = []

    def require(path: str) -> Any:
        value = get_path(config, path)
        if value in (None, ""):
            errors.append(f"Missing required config value: {path}")
        return value

    require("team.id")
    require("team.name")
    timezone_name = require("team.timezone")
    if timezone_name:
        try:
            ZoneInfo(str(timezone_name))
        except ZoneInfoNotFoundError:
            errors.append(f"Invalid team.timezone: {timezone_name}")

    require("jira.base_url")
    if not (get_path(config, "jira.board_id") or get_path(config, "jira.project_key")):
        errors.append("jira.board_id or jira.project_key is required")
    require("jira.epic_issue_type")
    require("jira.mission_label_pattern")
    require("jira.fields.dri.field_id")
    require("jira.fields.due_date.field_id")
    require("jira.fields.status.field_id")

    require("weekly_update.window.start_day")
    require("weekly_update.window.start_time")
    require("weekly_update.window.cutoff_day")
    require("weekly_update.window.cutoff_time")

    minimum_score = get_path(config, "weekly_update.validation.minimum_score")
    if minimum_score is not None and int(minimum_score) < 1:
        errors.append("weekly_update.validation.minimum_score must be positive")
    optional_sections = get_path(config, "weekly_update.validation.optional_sections", [])
    if optional_sections and not isinstance(optional_sections, list):
        errors.append("weekly_update.validation.optional_sections must be a list when provided")
    else:
        unknown_sections = sorted(str(section) for section in optional_sections if section not in OPTIONAL_SECTIONS)
        if unknown_sections:
            errors.append(
                "weekly_update.validation.optional_sections contains unknown sections: "
                + ", ".join(unknown_sections)
            )

    spillover_config = get_path(config, "previous_month_spillover")
    if spillover_config is not None:
        if not isinstance(spillover_config, dict):
            errors.append("previous_month_spillover must be an object when provided")
        else:
            for key in ("enabled", "include_if_status_not_in_done_statuses"):
                value = spillover_config.get(key)
                if value is not None and not isinstance(value, bool):
                    errors.append(f"previous_month_spillover.{key} must be true or false")

    hygiene_config = get_path(config, "hygiene")
    if hygiene_config is not None:
        if not isinstance(hygiene_config, dict):
            errors.append("hygiene must be an object when provided")
        else:
            severity_overrides = hygiene_config.get("severity_overrides")
            if severity_overrides is not None:
                if not isinstance(severity_overrides, dict):
                    errors.append("hygiene.severity_overrides must be an object when provided")
                else:
                    invalid_severities = sorted(
                        {
                            str(severity)
                            for severity in severity_overrides.values()
                            if str(severity) not in {"red", "yellow", "info"}
                        }
                    )
                    if invalid_severities:
                        errors.append(
                            "hygiene.severity_overrides values must be red, yellow, or info: "
                            + ", ".join(invalid_severities)
                        )

    run_history_config = get_path(config, "run_history")
    if run_history_config is not None:
        if not isinstance(run_history_config, dict):
            errors.append("run_history must be an object when provided")
        else:
            enabled = run_history_config.get("enabled")
            if enabled is not None and not isinstance(enabled, bool):
                errors.append("run_history.enabled must be true or false")
            tab_name = str(run_history_config.get("tab_name", "") or "").strip()
            if "tab_name" in run_history_config and not tab_name:
                errors.append("run_history.tab_name must not be empty")

    require("sheet.tab_name_pattern")
    require("sheet.mode")
    if get_path(config, "sheet.spreadsheet_id") is not None:
        errors.append("sheet.spreadsheet_id is not supported; use sheet.folder_id and file_name_pattern")
    folder_id = str(get_path(config, "sheet.folder_id", "") or "").strip()
    if not folder_id:
        errors.append("Missing required config value: sheet.folder_id")
    elif REQUIRED_SHEET_FOLDER_ID and folder_id != REQUIRED_SHEET_FOLDER_ID:
        errors.append(
            "sheet.folder_id does not match the required folder id configured in "
            "WEEKLY_ROLLUP_REQUIRED_FOLDER_ID"
        )
    else:
        try:
            sheet_file_name(config)
        except (KeyError, ValueError) as exc:
            errors.append(f"Invalid sheet.file_name_pattern: {exc}")

    email_to = get_path(config, "email.to")
    if not isinstance(email_to, list) or not email_to:
        errors.append("email.to must contain at least one recipient")
    if get_path(config, "email.create_draft_only") is False:
        errors.append("email.create_draft_only must be true")
    for key in ("smtp_host", "smtp_port", "smtp_starttls"):
        if get_path(config, f"email.{key}") is not None:
            errors.append(f"email.{key} is not supported; use rendered draft output instead")

    return errors


def assert_valid_config(config: dict[str, Any]) -> None:
    errors = validate_team_config(config)
    if errors:
        raise ConfigError("\n".join(errors))


def sheet_file_name(config: dict[str, Any]) -> str:
    pattern = str(
        get_path(
            config,
            "sheet.file_name_pattern",
            "{team_name} - Mission Execution Updates",
        )
    )
    values = {
        "team_id": str(get_path(config, "team.id", "")),
        "team_name": str(get_path(config, "team.name", "")),
    }
    name = pattern.format(**values).strip()
    if not name:
        raise ValueError("resolved sheet file name is empty")
    return name


def get_path(data: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def month_label(month: int, year: int, pattern: str) -> str:
    month_name = date(year, month, 1).strftime("%B").lower()
    return pattern.format(month=month_name, year=year)


def month_label_display(label: Any) -> str:
    text = str(label or "").strip()
    match = re.search(r"\b([a-z]+)-(\d{4})$", text, flags=re.IGNORECASE)
    if not match:
        return text

    month_name = match.group(1).capitalize()
    return f"{month_name} {match.group(2)}"


def month_label_short_display(label: Any) -> str:
    display = month_label_display(label)
    return display.split(" ", 1)[0] if display else ""


def month_label_end_date(label: Any) -> date | None:
    text = str(label or "").strip()
    match = re.search(r"\b([a-z]+)-(\d{4})$", text, flags=re.IGNORECASE)
    if not match:
        return None

    try:
        month_number = datetime.strptime(match.group(1).title(), "%B").month
        year = int(match.group(2))
    except ValueError:
        return None

    next_month = date(year + (month_number // 12), (month_number % 12) + 1, 1)
    return next_month - timedelta(days=1)


def mission_effective_due_date(mission: dict[str, Any]) -> str:
    due_date = str(mission.get("due_date", "") or "").strip()
    return due_date


def week_tab_name(iso_week: int, pattern: str = "Week {iso_week}") -> str:
    return pattern.format(iso_week=iso_week)


def compute_week_window(
    target_date: date,
    timezone_name: str,
    window_config: dict[str, Any],
) -> tuple[datetime, datetime, int]:
    """Resolve the team-local weekly comment window."""

    timezone = ZoneInfo(timezone_name)
    local_midnight = datetime.combine(target_date, time.min, tzinfo=timezone)
    week_monday = local_midnight - timedelta(days=target_date.isoweekday() - 1)
    start = _datetime_for_weekday(
        week_monday,
        str(window_config["start_day"]),
        str(window_config["start_time"]),
    )
    cutoff = _datetime_for_weekday(
        week_monday,
        str(window_config["cutoff_day"]),
        str(window_config["cutoff_time"]),
    )
    if cutoff < start:
        cutoff += timedelta(days=7)
    return start, cutoff, target_date.isocalendar().week


def _datetime_for_weekday(week_monday: datetime, day_name: str, hhmm: str) -> datetime:
    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    normalized_day = day_name.strip().lower()
    if normalized_day not in weekdays:
        raise ValueError(f"Unsupported weekday: {day_name}")
    hours, minutes = [int(part) for part in hhmm.split(":", 1)]
    return (week_monday + timedelta(days=weekdays[normalized_day])).replace(
        hour=hours,
        minute=minutes,
        second=0,
        microsecond=0,
    )


def parse_update(
    body: Any,
    *,
    require_template_match: bool = True,
    minimum_score: int = 4,
    allow_section_aliases: bool = True,
    allow_unstructured_if_confident: bool = False,
    optional_sections: list[str] | tuple[str, ...] | None = None,
) -> ParsedUpdate:
    """Parse a weekly DRI update into the configured semantic sections.

    The parser keeps the legacy combined `blockers_risks` value for backward
    compatibility, and also tracks whether each line came from a `Risks:`
    heading, a `Blockers:` heading, or a legacy combined `Blockers / Risks`
    heading, so callers can render them separately when both are populated.
    """

    del allow_section_aliases, allow_unstructured_if_confident
    text = comment_body_to_text(body)
    sections: dict[str, list[str]] = {section: [] for section in REQUIRED_SECTIONS}
    risk_lines: list[str] = []
    blocker_lines: list[str] = []
    combined_lines: list[str] = []
    current_section: str | None = None
    blocker_heading_kind = ""

    def append_blocker_line(value: str) -> None:
        sections["blockers"].append(value)
        if blocker_heading_kind == "risk":
            risk_lines.append(value)
        elif blocker_heading_kind == "blocker":
            blocker_lines.append(value)
        else:
            combined_lines.append(value)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current_section:
                sections[current_section].append("")
                if current_section == "blockers":
                    if blocker_heading_kind == "risk":
                        risk_lines.append("")
                    elif blocker_heading_kind == "blocker":
                        blocker_lines.append("")
                    else:
                        combined_lines.append("")
            continue
        detected = detect_section_line(line)
        if detected:
            current_section, rest = detected
            if current_section == "blockers":
                blocker_heading_kind = risk_blocker_heading_kind(line)
            else:
                blocker_heading_kind = ""
            if rest:
                if current_section == "blockers":
                    append_blocker_line(rest)
                else:
                    sections[current_section].append(rest)
            continue
        if current_section:
            if current_section == "blockers":
                append_blocker_line(line)
            else:
                sections[current_section].append(line)

    values = {section: clean_section_value(lines) for section, lines in sections.items()}
    risks_value = clean_section_value(risk_lines)
    blockers_value = clean_section_value(blocker_lines)
    combined_value = clean_section_value(combined_lines)
    if blockers_are_none(risks_value):
        risks_value = ""
    if blockers_are_none(blockers_value):
        blockers_value = ""
    if blockers_are_none(combined_value):
        combined_value = ""

    status = normalize_status(values["status"])
    optional_section_set = set(optional_sections or []) & set(OPTIONAL_SECTIONS)
    missing_sections = [
        SECTION_NAMES[section]
        for section in REQUIRED_SECTIONS
        if not values[section] and section not in optional_section_set
    ]
    errors: list[str] = []
    if missing_sections:
        errors.append("Missing required sections: " + ", ".join(missing_sections))
    if values["status"] and not status:
        errors.append("Status must be Green, Yellow, Red, or the matching status emoji")
    if not values["status"]:
        errors.append("Missing status value")

    score = sum(1 for section in REQUIRED_SECTIONS if values[section])
    effective_minimum_score = min(minimum_score, len(REQUIRED_SECTIONS) - len(optional_section_set))
    template_valid = score >= effective_minimum_score and bool(status)
    if require_template_match:
        template_valid = template_valid and not missing_sections

    return ParsedUpdate(
        status=status,
        done_this_week=values["done"],
        plan_for_next_week=values["plan"],
        blockers_risks=values["blockers"],
        template_valid=template_valid,
        score=score,
        risks=risks_value,
        blockers=blockers_value,
        combined_risks_blockers=combined_value,
        missing_sections=missing_sections,
        errors=errors,
    )


def comment_body_to_text(body: Any) -> str:
    """Convert plain Jira comment text or Atlassian Document Format to text."""

    if body is None:
        return ""
    if isinstance(body, str):
        return body.replace("\r\n", "\n").replace("\r", "\n")
    if isinstance(body, dict):
        return _adf_to_text(body).strip()
    if isinstance(body, list):
        return "\n".join(comment_body_to_text(part) for part in body)
    return str(body)


_JIRA_BROWSE_RE = re.compile(r"/browse/([A-Z][A-Z0-9_]+-\d+)\b")


def _short_card_label(url: str) -> str:
    """Render a Jira/Confluence smart-card URL as a short readable token.

    Jira issue URLs render as the issue key (e.g. DEMO-100). Other URLs return
    empty so the caller falls back to the raw URL.
    """
    if not url:
        return ""
    match = _JIRA_BROWSE_RE.search(url)
    if match:
        return match.group(1)
    return ""


def _adf_to_text(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_to_text(item) for item in node)
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type")
    if node_type == "text":
        return str(node.get("text", ""))
    if node_type == "hardBreak":
        return "\n"
    if node_type == "emoji":
        attrs = node.get("attrs", {}) or {}
        return str(attrs.get("text") or attrs.get("shortName") or "")
    if node_type == "mention":
        attrs = node.get("attrs", {}) or {}
        return str(attrs.get("text") or attrs.get("displayName") or "")
    if node_type in {"inlineCard", "blockCard", "embedCard"}:
        attrs = node.get("attrs", {}) or {}
        url = str(attrs.get("url") or "")
        return _short_card_label(url) or url
    content = _adf_to_text(node.get("content", []))
    if node_type in {"paragraph", "heading", "listItem"}:
        return content + "\n"
    if node_type in {"bulletList", "orderedList"}:
        lines = [line for line in content.splitlines() if line.strip()]
        return "\n".join(f"- {line}" for line in lines) + "\n"
    return content


def detect_section_line(line: str) -> tuple[str, str] | None:
    cleaned = re.sub(r"^\s*(?:[-*]\s+|\d+[.)]\s+)", "", line)
    cleaned = re.sub(r"^\s*#+\s*", "", cleaned)
    cleaned = cleaned.replace("**", "").replace("__", "").strip()
    match = re.match(r"^(?P<label>[A-Za-z][A-Za-z0-9 /&+'-]{0,80})\s*[:\-]\s*(?P<rest>.*)$", cleaned)
    if not match:
        section = section_from_bare_label(cleaned)
        if section is None:
            return None
        return section, ""
    section = section_from_label(match.group("label"))
    if section is None:
        return None
    return section, match.group("rest").strip()


def section_from_bare_label(label: str) -> str | None:
    return section_from_alias(label)


def section_from_label(label: str) -> str | None:
    return section_from_alias(label)


def section_from_alias(label: str) -> str | None:
    normalized = normalize_label(label)
    for section, aliases in SECTION_ALIASES.items():
        if normalized in aliases:
            return section
    return None


def normalize_label(label: str) -> str:
    normalized = label.lower()
    normalized = normalized.replace("/", " ").replace("&", " ")
    normalized = re.sub(r"[^a-z0-9 ]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def clean_section_value(lines: list[str]) -> str:
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_RISK_HEADING_LABELS = {"risk", "risks"}
_BLOCKER_HEADING_LABELS = {
    "blocker",
    "blockers",
    "dependency",
    "dependencies",
    "decision",
    "decisions",
    "decisions needed",
}


def section_label_from_line(line: str) -> str:
    """Extract the heading label from a section line (with or without value)."""
    cleaned = re.sub(r"^\s*(?:[-*]\s+|\d+[.)]\s+)", "", line)
    cleaned = re.sub(r"^\s*#+\s*", "", cleaned)
    cleaned = cleaned.replace("**", "").replace("__", "").strip()
    match = re.match(r"^(?P<label>[A-Za-z][A-Za-z0-9 /&+'-]{0,80})\s*[:\-]", cleaned)
    return match.group("label") if match else cleaned


def risk_blocker_heading_kind(line: str) -> str:
    """Classify a blockers-section heading as 'risk', 'blocker', or '' (combined)."""
    normalized = normalize_label(section_label_from_line(line))
    if normalized in _RISK_HEADING_LABELS:
        return "risk"
    if normalized in _BLOCKER_HEADING_LABELS:
        return "blocker"
    return ""


def blockers_are_none(value: str) -> bool:
    """True when a blocker/risk value is a recognised explicit-none phrase."""
    if not value:
        return True
    normalized = normalize_label(value.strip())
    return normalized in NONE_VALUES


def normalize_status(value: str) -> str | None:
    for emoji, status in STATUS_EMOJI.items():
        if emoji in value:
            return status
    text = normalize_status_text(value)
    if not text:
        return None
    for word, status in STATUS_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return status
    for status, patterns in STATUS_PHRASES:
        if any(re.search(pattern, text) for pattern in patterns):
            return status
    return None


def normalize_status_text(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def blockers_are_none(value: str) -> bool:
    normalized = normalize_blocker_text(value)
    if normalized in NONE_VALUES:
        return True
    no_blocker_match = re.match(
        r"^no\s+(?:(?:active|hard|known|current|open|major|real|clear)\s+)*(?:blockers?|risks?)\b",
        normalized,
    )
    if not no_blocker_match:
        return False
    qualifier = normalized[no_blocker_match.end() :].strip(" ,;:-")
    if not qualifier:
        return True
    return not re.search(
        r"\b(?:but|except|however|although|pending|waiting|blocked|blocker|risk|issue|dependency|depends|delayed|delay)\b",
        qualifier,
    )


def normalize_blocker_text(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"^[\-*]\s*", "", normalized)
    normalized = re.sub(r"[.!]+$", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def blocker_items(blockers_text: str) -> list[str]:
    """Split the blockers section into stable row-level items."""

    if not blockers_text or blockers_are_none(blockers_text):
        return []
    raw_items = []
    for line in blockers_text.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^\s*(?:[-*]\s+|\d+[.)]\s+)", "", line)
        raw_items.append(line)
    return raw_items or [blockers_text.strip()]


def blocker_fingerprint(text: str) -> str:
    """Normalize blocker text for matching unresolved risks across weekly snapshots."""

    normalized = normalize_blocker_text(text)
    normalized = re.sub(r"\bowner\s*[:=-]\s*[^,;()]+", " ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bresponsible(?:\s+owner)?\s*[:=-]\s*[^,;()]+", " ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(
        r"\b(?:open|opened|unresolved|blocked)?\s*(?:for\s+)?\d+\s+days?\b",
        " ",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"[^a-z0-9@]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def extract_blockers(
    blockers_text: str,
    *,
    mission: str,
    dri: str,
    status: str,
    kind: str = "",
) -> list[Blocker]:
    """Split the blockers section into blocker rows.

    `kind` carries the section heading classification ("risk" / "blocker" /
    "") through to each Blocker so the email renderer can label rows.
    """

    blockers: list[Blocker] = []
    for item in blocker_items(blockers_text):
        if blockers_are_none(item):
            continue
        owner = detect_owner(item)
        days_open = detect_days_open(item)
        blockers.append(
            Blocker(
                mission=mission,
                dri=dri,
                status=status,
                text=item,
                owner=owner,
                days_open=days_open,
                kind=kind,
            )
        )
    return blockers


def detect_owner(text: str) -> str:
    mention = re.search(r"@([A-Za-z][A-Za-z0-9_. -]+)", text)
    if mention:
        return mention.group(1).strip()
    for pattern in (
        r"\bowner\s*[:=-]\s*([^,;()]+)",
        r"\bowned by\s+([^,;()]+)",
        r"\bresponsible(?:\s+owner)?\s*[:=-]\s*([^,;()]+)",
    ):
        owner = re.search(pattern, text, flags=re.IGNORECASE)
        if owner:
            return owner.group(1).strip()
    return ""


def detect_days_open(text: str) -> str:
    match = re.search(r"\b(\d+)\s+days?\b", text, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def find_latest_valid_dri_comment(
    comments: list[dict[str, Any]],
    dri: dict[str, Any] | None,
    window_start: datetime,
    window_end: datetime,
    *,
    parse_options: dict[str, Any] | None = None,
    cover_emails: list[str] | None = None,
) -> CommentSelection:
    """Select the latest valid DRI weekly update from Jira comments."""

    parse_options = parse_options or {}
    valid_candidates: list[tuple[datetime, dict[str, Any], ParsedUpdate]] = []
    rejection_reasons: list[str] = []
    malformed_seen = False

    for comment in comments:
        comment_id = str(comment.get("id") or comment.get("self") or "<unknown>")
        if is_deleted_or_internal(comment):
            rejection_reasons.append(f"{comment_id}: deleted or internal")
            continue
        if is_reply_comment(comment):
            rejection_reasons.append(f"{comment_id}: reply comment")
            continue
        body = comment_body_to_text(comment.get("body"))
        if not body.strip():
            rejection_reasons.append(f"{comment_id}: empty body")
            continue
        if not author_matches(comment.get("author", {}), dri, cover_emails):
            rejection_reasons.append(f"{comment_id}: author is not DRI")
            continue
        created = parse_jira_datetime(comment.get("created") or comment.get("updated"))
        if created is None:
            rejection_reasons.append(f"{comment_id}: missing timestamp")
            continue
        local_created = created.astimezone(window_start.tzinfo)
        if not (window_start <= local_created <= window_end):
            rejection_reasons.append(f"{comment_id}: outside weekly window")
            continue

        parsed = parse_update(body, **parse_options)
        if parsed.template_valid:
            valid_candidates.append((local_created, comment, parsed))
        else:
            malformed_seen = True
            rejection_reasons.append(f"{comment_id}: malformed DRI update")

    if not valid_candidates:
        return CommentSelection(
            selected_comment=None,
            parsed_update=None,
            missing_update=True,
            malformed_update_seen=malformed_seen,
            rejection_reasons=rejection_reasons,
        )

    valid_candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    _, selected_comment, parsed = valid_candidates[0]
    selected_is_cover = not _author_is_dri(selected_comment.get("author", {}), dri)
    return CommentSelection(
        selected_comment=selected_comment,
        parsed_update=parsed,
        missing_update=False,
        malformed_update_seen=False,
        rejection_reasons=rejection_reasons,
        cover_author=selected_is_cover,
    )


def is_deleted_or_internal(comment: dict[str, Any]) -> bool:
    if comment.get("deleted") or comment.get("isDeleted"):
        return True
    if comment.get("internal") is True:
        return True
    if comment.get("jsdPublic") is False:
        return True
    visibility = comment.get("visibility")
    if isinstance(visibility, dict) and visibility.get("type") == "internal":
        return True
    return False


def is_reply_comment(comment: dict[str, Any]) -> bool:
    return bool(
        comment.get("parentId")
        or comment.get("parent_id")
        or comment.get("inReplyTo")
        or comment.get("is_reply")
    )


def parse_jira_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=ZoneInfo("UTC"))
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo("UTC"))


def author_matches(
    author: dict[str, Any],
    dri: dict[str, Any] | None,
    cover_emails: list[str] | None = None,
) -> bool:
    if _author_is_dri(author, dri):
        return True
    return _author_is_cover(author, cover_emails)


def _author_is_dri(author: dict[str, Any], dri: dict[str, Any] | None) -> bool:
    if not dri:
        return False
    author_account_id = _first_value(author, "accountId", "account_id", "jira_account_id")
    dri_account_id = _first_value(dri, "accountId", "account_id", "jira_account_id")
    if author_account_id and dri_account_id:
        return str(author_account_id) == str(dri_account_id)

    author_email = normalize_identity(_first_value(author, "emailAddress", "email"))
    dri_email = normalize_identity(_first_value(dri, "emailAddress", "email"))
    if author_email and dri_email and author_email == dri_email:
        return True

    author_name = normalize_identity(
        _first_value(author, "displayName", "display_name", "jira_display_name", "name")
    )
    dri_name = normalize_identity(
        _first_value(dri, "displayName", "display_name", "jira_display_name", "name")
    )
    return bool(author_name and dri_name and author_name == dri_name)


def _author_is_cover(author: dict[str, Any], cover_emails: list[str] | None) -> bool:
    if not cover_emails:
        return False
    author_email = normalize_identity(_first_value(author, "emailAddress", "email"))
    if not author_email:
        return False
    for cover in cover_emails:
        if normalize_identity(cover) == author_email:
            return True
    return False


def _first_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if data.get(key):
            return data[key]
    return None


def normalize_identity(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


_OPS_MISSION_RE = re.compile(r"\b(?:ops|ops stream|operational|operational stream)\b")


def mission_exempt_from_linked_okr(mission: dict[str, Any]) -> bool:
    """Operational/KTLO missions are not expected to link to an OKR."""
    text = " ".join(
        str(mission.get(key) or "")
        for key in ("name", "summary", "mission", "title")
    )
    return bool(_OPS_MISSION_RE.search(normalize_identity(text)))


def evaluate_hygiene(
    mission: dict[str, Any],
    config: dict[str, Any],
    parsed_update: ParsedUpdate | None,
    *,
    missing_update: bool,
    malformed_update_seen: bool = False,
    previous_due_date: str | None = None,
    stale_weeks: int = 0,
    history_available: bool = True,
    target_date: date | None = None,
    is_done: bool = False,
    is_not_started: bool = False,
    start_signal_seen: bool = False,
) -> list[dict[str, str]]:
    """Evaluate data hygiene rules for a mission row."""

    issues: list[dict[str, str]] = []
    dri = mission.get("dri")
    if not dri:
        issues.append({"severity": "red", "message": "Missing DRI"})

    due_date = mission.get("due_date")
    effective_due_date = mission_effective_due_date(mission)
    if not due_date:
        issues.append({"severity": "red", "message": "Missing due date"})
    days_overdue = due_date_overdue_days(effective_due_date, target_date)
    if days_overdue > 0 and not is_done:
        issues.append({"severity": "red", "message": f"Due date overdue by {format_day_count(days_overdue)}"})

    stale_threshold = int(
        get_path(config, "weekly_update.validation.no_update_red_after_weeks", 2)
    )
    if not is_done and history_available and stale_weeks >= stale_threshold and stale_weeks > 0:
        issues.append({"severity": "red", "message": f"No update in {stale_weeks} weeks"})

    if not mission.get("linked_okr") and not mission_exempt_from_linked_okr(mission):
        issues.append({"severity": "yellow", "message": "Missing linked OKR"})
    if missing_update and not is_done:
        issues.append({"severity": "yellow", "message": "Missing weekly DRI update"})
    if malformed_update_seen and not is_done:
        issues.append({"severity": "yellow", "message": "Malformed weekly update"})
    if is_not_started and not is_done:
        if start_signal_seen:
            issues.append(
                {
                    "severity": "yellow",
                    "message": "Jira epic is To Do but update/progress suggests work has started",
                }
            )
        else:
            issues.append({"severity": "info", "message": "Jira epic is To Do; not started"})

    if history_available:
        if previous_due_date and due_date and previous_due_date != due_date:
            issues.append({"severity": "yellow", "message": "Due date changed"})
        elif due_date and previous_due_date is None:
            issues.append({"severity": "info", "message": "First observation of due date"})

    if parsed_update and parsed_update.status in {STATUS_YELLOW, STATUS_RED}:
        no_blockers = blockers_are_none(parsed_update.blockers_risks)
        no_plan = not parsed_update.plan_for_next_week.strip()
        if no_blockers and no_plan:
            issues.append(
                {
                    "severity": "yellow",
                    "message": "Yellow/red status without blocker or resolution path",
                }
            )
    if parsed_update and blockers_are_none(parsed_update.blockers_risks):
        issues.append({"severity": "info", "message": "No blockers reported"})

    if (
        mission.get("mission_type") == "spillover"
        and not any(issue["severity"] == "red" for issue in issues)
        and (not parsed_update or parsed_update.status != STATUS_RED)
    ):
        issues.append({"severity": "yellow", "message": "Delayed carryover mission still open"})

    return issues


def due_date_overdue_days(due_date: Any, target_date: date | None) -> int:
    if target_date is None:
        return 0
    text = str(due_date or "").strip()
    if not text:
        return 0
    try:
        parsed_due_date = date.fromisoformat(text)
    except ValueError:
        return 0
    return max((target_date - parsed_due_date).days, 0)


def format_day_count(days: int) -> str:
    return f"{days} day" if days == 1 else f"{days} days"


def mission_to_sheet_row(
    mission: dict[str, Any],
    config: dict[str, Any],
    parsed_update: ParsedUpdate | None,
    hygiene_issues: list[dict[str, str]],
    blockers: list[Blocker] | None = None,
    *,
    dri_comment: str = "",
    missing_update: bool = False,
    missing_update_weeks: int = 0,
    due_date_movement: str = "",
) -> list[str]:
    del config
    status = parsed_update.status if parsed_update else STATUS_MISSING
    blockers = blockers or []
    return [
        str(mission.get("key", "")),
        str(mission.get("name") or mission.get("summary") or ""),
        str(mission.get("url", "")),
        str(mission.get("original_month_label", "")),
        display_dri(mission.get("dri")),
        status or "",
        stringify_percent(mission.get("progress")),
        str(mission.get("due_date", "")),
        due_date_movement,
        parsed_update.done_this_week if parsed_update else "",
        parsed_update.plan_for_next_week if parsed_update else "",
        parsed_update.blockers_risks if parsed_update else "",
        blocker_owner_summary(blockers),
        blocker_age_summary(blockers),
        "yes" if missing_update else "no",
        str(missing_update_weeks) if missing_update_weeks else "",
        dri_comment,
        "; ".join(issue["message"] for issue in hygiene_issues),
    ]


def blocker_owner_summary(blockers: list[Blocker]) -> str:
    owners = []
    for blocker in blockers:
        owner = blocker.owner or "Unassigned"
        if owner not in owners:
            owners.append(owner)
    return "; ".join(owners)


def blocker_age_summary(blockers: list[Blocker]) -> str:
    parts = []
    for blocker in blockers:
        parts.append(f"{blocker.text}: {blocker_age_label(blocker.days_open)}")
    return " | ".join(parts)


def blocker_age_label(days_open: Any) -> str:
    value = str(days_open or "").strip()
    if not value:
        return "new risk"
    if value.isdigit():
        days = int(value)
        return format_day_count(days)
    return value


def stringify_percent(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return f"{round(value * 100) if value <= 1 else round(value)}%"
    text = str(value)
    return text if text.endswith("%") else f"{text}%"


def display_dri(dri: dict[str, Any] | None) -> str:
    if not dri:
        return ""
    return str(
        _first_value(dri, "displayName", "display_name", "jira_display_name", "name", "email")
        or ""
    )


def sheet_values(rows: list[list[str]]) -> list[list[str]]:
    return [SHEET_COLUMNS, *rows]


def render_email_draft(
    config: dict[str, Any],
    mission_rows: list[dict[str, Any]],
    *,
    iso_week: int,
    sheet_url: str = "",
    report_month_label: str = "",
) -> dict[str, Any]:
    """Render a draft-only email payload for EM review."""

    team_name = str(get_path(config, "team.name", ""))
    subject_pattern = str(
        get_path(
            config,
            "email.subject_pattern",
            "Weekly Mission Update - {team_name} - Week {iso_week}",
        )
    )
    subject = subject_pattern.format(team_name=team_name, iso_week=iso_week)
    to = [email for email in get_path(config, "email.to", []) or [] if email]
    cc = [email for email in get_path(config, "email.cc", []) or [] if email]
    bcc = [email for email in get_path(config, "email.bcc", []) or [] if email]
    from_address = str(get_path(config, "email.from_address", "") or get_path(config, "email.from", "") or "")
    signoff_name = str(
        get_path(config, "email.signoff_name", "")
        or get_path(config, "email.author", "")
        or get_path(config, "team.em_name", "")
        or ""
    )
    greeting = str(get_path(config, "email.greeting", "") or "Hi")
    signoff = str(get_path(config, "email.signoff", "") or "Kind Regards")

    summary = summarize_missions(mission_rows)
    sorted_rows = sorted(
        mission_rows,
        key=lambda row: STATUS_SORT.get(str(row.get("status", STATUS_MISSING)), 9),
    )
    blockers = collect_email_blockers(sorted_rows)
    hygiene = collect_email_hygiene(sorted_rows)

    html_body = render_html_email(
        subject,
        team_name,
        iso_week,
        summary,
        sorted_rows,
        blockers,
        hygiene,
        sheet_url,
        signoff,
        signoff_name,
        greeting,
        report_month_label=report_month_label,
    )
    text_body = render_text_email(
        subject,
        summary,
        sorted_rows,
        blockers,
        hygiene,
        sheet_url,
        signoff,
        signoff_name,
        greeting,
    )
    return {
        "create_draft_only": True,
        "from_address": from_address,
        "to": to,
        "cc": cc,
        "bcc": bcc,
        "subject": subject,
        "html_body": html_body,
        "text_body": text_body,
        "htmlBody": html_body,
        "plainTextBody": text_body,
    }


def summarize_missions(mission_rows: list[dict[str, Any]]) -> dict[str, int]:
    statuses = [row.get("status") for row in mission_rows]
    all_blockers = [b for row in mission_rows for b in row.get("blockers", [])]

    def _blocker_kind(b: Any) -> str:
        if isinstance(b, Blocker):
            return str(b.kind or "").lower()
        if isinstance(b, dict):
            return str(b.get("kind", "") or "").lower()
        return ""

    risks_count = sum(1 for b in all_blockers if _blocker_kind(b) == "risk")
    # Anything not explicitly a risk counts as a blocker (kind == "blocker" or
    # legacy combined kind == ""). Keeps backward-compat with the pre-split
    # single "blockers" total while exposing risks separately for the tiles.
    blockers_count = len(all_blockers) - risks_count
    return {
        "total": len(mission_rows),
        "green": statuses.count(STATUS_GREEN),
        "yellow": statuses.count(STATUS_YELLOW),
        "red": statuses.count(STATUS_RED),
        "done": statuses.count(STATUS_DONE),
        "not_started": statuses.count(STATUS_NOT_STARTED),
        "missing_updates": sum(1 for row in mission_rows if row.get("missing_update")),
        "blockers": len(all_blockers),  # legacy: total risks+blockers count
        "risks": risks_count,
        "blockers_only": blockers_count,
    }


def build_summary_primary_items(
    summary: dict[str, int],
    report_month_label: str = "",
    *,
    include_zero_statuses: bool = False,
) -> list[dict[str, Any]]:
    """Dynamic tile row for the email header.

    Always includes the total-count tile; the status / risk / blocker /
    missing-update tiles are dropped when their count is zero (unless
    include_zero_statuses is True) so the row stays uncluttered. Widths
    are recomputed so all visible tiles share the row evenly in a single
    header row.
    """
    month_name = month_label_display(report_month_label).split(" ", 1)[0] if report_month_label else "Current"
    items = [
        {
            "label": f"{month_name} Missions",
            "value": summary.get("total", 0),
            "color": "#132968",
            "always": True,
        },
        {"label": "On Track", "value": summary.get("green", 0), "color": "#16a34a"},
        {"label": "At Risk", "value": summary.get("yellow", 0), "color": "#f59e0b"},
        {"label": "Delayed", "value": summary.get("red", 0), "color": "#dc2626"},
        {"label": "Not Started", "value": summary.get("not_started", 0), "color": "#64748b"},
        {"label": "Done", "value": summary.get("done", 0), "color": "#132968"},
        {"label": "Risks", "value": summary.get("risks", 0), "color": "#f59e0b"},
        {"label": "Blockers", "value": summary.get("blockers_only", 0), "color": "#dc2626"},
        {"label": "Missing Updates", "value": summary.get("missing_updates", 0), "color": "#64748b"},
    ]
    visible = [
        item for item in items
        if item.get("always") or include_zero_statuses or int(item.get("value") or 0) > 0
    ]
    width = f"{100 / len(visible):.2f}%" if visible else "100%"
    return [{**item, "width": width} for item in visible]


def build_summary_attention_items(
    summary: dict[str, int],
    *,
    include_zeros: bool = False,
) -> list[dict[str, Any]]:
    """Deprecated: kept for backward compatibility with older tests / callers.

    The single-row primary layout now includes Risks / Blockers / Missing
    Updates inline. New callers should use build_summary_primary_items().
    """
    items = [
        {"label": "Risks", "value": summary.get("risks", 0), "color": "#f59e0b"},
        {"label": "Blockers", "value": summary.get("blockers_only", 0), "color": "#dc2626"},
        {"label": "Missing Updates", "value": summary.get("missing_updates", 0), "color": "#64748b"},
    ]
    visible = [item for item in items if include_zeros or int(item.get("value") or 0) > 0]
    width = f"{100 / len(visible):.2f}%" if visible else "100%"
    return [{**item, "width": width} for item in visible]


def render_html_email(
    subject: str,
    team_name: str,
    iso_week: int,
    summary: dict[str, int],
    rows: list[dict[str, Any]],
    blockers: list[dict[str, str]],
    hygiene: list[dict[str, str]],
    sheet_url: str,
    signoff: str,
    signoff_name: str,
    greeting: str,
    *,
    report_month_label: str = "",
) -> str:
    """Render a table-based HTML email body that works well in Gmail."""

    context = build_email_template_context(
        subject,
        team_name,
        iso_week,
        summary,
        rows,
        blockers,
        hygiene,
        sheet_url,
        signoff,
        signoff_name,
        greeting,
        report_month_label=report_month_label,
    )
    return email_template_environment().get_template(EMAIL_TEMPLATE_NAME).render(**context)


def email_template_environment() -> Environment:
    if Environment is None or FileSystemLoader is None or select_autoescape is None:
        raise ConfigError("Jinja2 is required to render the HTML email template")

    template_dir = Path(__file__).resolve().parents[1] / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    def nl2br(value: Any) -> Markup:
        if Markup is None or markup_escape is None:
            raise ConfigError("MarkupSafe is required to render the HTML email template")
        escaped = markup_escape(str(value or ""))
        return Markup(str(escaped).replace("\n", "<br>"))

    env.filters["nl2br"] = nl2br
    return env


def build_email_template_context(
    subject: str,
    team_name: str,
    iso_week: int,
    summary: dict[str, int],
    rows: list[dict[str, Any]],
    blockers: list[dict[str, str]],
    hygiene: list[dict[str, str]],
    sheet_url: str,
    signoff: str,
    signoff_name: str,
    greeting: str,
    *,
    report_month_label: str = "",
) -> dict[str, Any]:
    at_risk_count = summary["yellow"] + summary["red"]
    preview = (
        f"{summary['green']}/{summary['total']} missions on track, "
        f"{at_risk_count} at risk, {summary['missing_updates']} missing updates, "
        f"{summary['not_started']} not started, {summary['done']} done, "
        f"{summary['blockers']} blockers/risks"
    )
    return {
        "subject": subject,
        "team_name": team_name,
        "iso_week": iso_week,
        "preview": preview,
        "summary": summary,
        "at_risk_count": at_risk_count,
        "stat_cards": build_summary_stat_cards(summary),
        "summary_primary_items": build_summary_primary_items(summary, report_month_label),
        "summary_attention_items": build_summary_attention_items(summary),
        "mission_rows": build_template_mission_rows(rows),
        "blocker_rows": build_template_blocker_rows(blockers),
        "hygiene_groups": build_template_hygiene_groups(hygiene),
        "sheet_url": sheet_url,
        "signoff": signoff,
        "signoff_name": signoff_name,
        "greeting": greeting,
    }


def build_summary_stat_cards(summary: dict[str, int]) -> list[dict[str, Any]]:
    at_risk = summary["yellow"] + summary["red"]
    return [
        {"label": "On Track", "value": f"{summary['green']}/{summary['total']}", "color": "#16a34a"},
        {"label": "At Risk", "value": at_risk, "color": "#f59e0b"},
        {"label": "Blockers / Risks", "value": summary["blockers"], "color": "#dc2626"},
        {"label": "Missing Updates", "value": summary["missing_updates"], "color": "#64748b"},
    ]


def build_template_mission_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    template_rows = []
    for row in rows:
        status = str(row.get("status", ""))
        progress = str(row.get("progress", "") or "No progress")
        template_rows.append(
            {
                "mission": str(row.get("mission", "")),
                "mission_title": email_mission_title(row),
                "mission_url": str(row.get("mission_url", "")),
                "dri": str(row.get("dri", "") or "Unassigned"),
                "status": status or STATUS_MISSING,
                "status_label": email_status_label(status),
                "progress": progress,
                "progress_percent": progress_percent(progress),
                "due_date": email_due_date_display(
                    row.get("due_date", ""),
                    row.get("due_date_movement", ""),
                    row.get("due_date_overdue_days", 0),
                    row.get("original_due_date", ""),
                ),
                "done_this_week": str(row.get("done_this_week", "") or "No update captured."),
                "plan_for_next_week": str(row.get("plan_for_next_week", "") or "No plan captured."),
                "style": status_theme(status),
            }
        )
    return template_rows


def email_mission_title(row: dict[str, Any]) -> str:
    mission = str(row.get("mission", ""))
    month = str(row.get("month_label", "") or "").strip()
    return f"{mission} ({month})" if month else mission


def collect_email_blockers(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    for row in rows:
        for blocker in row.get("blockers", []):
            if isinstance(blocker, Blocker):
                blockers.append(blocker.__dict__)
            else:
                blockers.append(dict(blocker))
    blockers.sort(key=lambda blocker: BLOCKER_STATUS_SORT.get(blocker.get("status", ""), 9))
    return blockers


def collect_email_hygiene(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    hygiene: list[dict[str, str]] = []
    for row in rows:
        mission = str(row.get("mission", ""))
        for issue in row.get("hygiene", []):
            item = dict(issue)
            if str(item.get("severity", "")).lower() == "info":
                continue
            item["mission"] = mission
            hygiene.append(item)
    severity_order = {"red": 0, "yellow": 1, "info": 2}
    hygiene.sort(key=lambda item: severity_order.get(item.get("severity", ""), 9))
    return hygiene


def build_template_blocker_rows(blockers: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows = []
    for blocker in blockers:
        style = blocker_theme(str(blocker.get("status", "")))
        kind = str(blocker.get("kind", "") or "").lower()
        if kind == "risk":
            kind_label = "Risk"
        elif kind == "blocker":
            kind_label = "Blocker"
        else:
            kind_label = ""
        rows.append(
            {
                "mission": str(blocker.get("mission", "")),
                "text": str(blocker.get("text", "")),
                "dri": str(blocker.get("dri", "")),
                "owner": str(blocker.get("owner", "") or "Unassigned"),
                "days_open": str(blocker.get("days_open", "") or "Not provided"),
                "kind": kind,
                "kind_label": kind_label,
                "style": style,
            }
        )
    return rows


def build_template_hygiene_groups(hygiene: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for issue in hygiene:
        mission = str(issue.get("mission", ""))
        grouped.setdefault(mission, []).append(issue)

    severity_order = {"red": 0, "yellow": 1, "info": 2}
    rows = []
    for mission, issues in grouped.items():
        severity = min(
            (str(issue.get("severity", "")).lower() for issue in issues),
            key=lambda value: severity_order.get(value, 9),
        )
        style = severity_theme(severity)
        messages = "; ".join(str(issue.get("message", "")) for issue in issues if issue.get("message"))
        rows.append(
            {
                "mission": mission,
                "severity": severity or "info",
                "messages": messages,
                "style": style,
            }
        )
    return rows


def progress_percent(progress: str) -> int | None:
    match = re.search(r"\d+", progress)
    if not match:
        return None
    return max(0, min(100, int(match.group(0))))


def email_due_date_display(
    due_date: Any,
    movement: Any,
    overdue_days: Any = 0,
    original_due_date: Any = "",
) -> str:
    due_date_text = str(due_date or "").strip()
    if not due_date_text:
        return "No due date"

    note = email_due_date_note(due_date_text, original_due_date, movement, overdue_days)
    due_date_display = format_email_date(due_date_text)
    return f"{due_date_display} ({note})" if note else due_date_display


def email_due_date_note(
    current_due_date: Any,
    original_due_date: Any = "",
    movement: Any = "",
    overdue_days: Any = 0,
) -> str:
    movement_text = str(movement or "").strip()
    notes: list[str] = []
    current_date = parse_email_date(current_due_date)
    original_date = parse_email_date(original_due_date) or original_due_date_from_movement(movement_text)
    delta_days = None
    if current_date and original_date:
        delta_days = (current_date - original_date).days
    elif movement_text:
        delta_days = movement_delta_days(movement_text)

    if delta_days is not None and delta_days > 0:
        if original_date:
            notes.append(
                f"original: {format_email_date(original_date, reference_year=current_date.year if current_date else None)}"
            )
        notes.append(f"moved later {format_day_count(delta_days)}")
    elif delta_days is not None and delta_days < 0:
        if original_date:
            notes.append(
                f"original: {format_email_date(original_date, reference_year=current_date.year if current_date else None)}"
            )
        notes.append(f"moved earlier {format_day_count(abs(delta_days))}")

    overdue = parse_positive_int(overdue_days)
    if overdue > 0:
        notes.append(f"overdue {format_day_count(overdue)}")

    if not overdue:
        overdue_match = re.search(r"\boverdue by (\d+) days?\b", movement_text, flags=re.IGNORECASE)
        if overdue_match:
            notes.append(f"overdue {format_day_count(int(overdue_match.group(1)))}")

    return ", ".join(notes)


def parse_email_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text.split("T", 1)[0])
    except ValueError:
        return None


def format_email_date(value: Any, *, reference_year: int | None = None) -> str:
    parsed = parse_email_date(value)
    if not parsed:
        return str(value or "")
    base = f"{parsed.day} {parsed.strftime('%b')}"
    return f"{base} {parsed.year}" if reference_year and parsed.year != reference_year else base


def original_due_date_from_movement(movement: str) -> date | None:
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\s*->\s*\d{4}-\d{2}-\d{2}\b", movement)
    return parse_email_date(match.group(1)) if match else None


def movement_delta_days(movement: str) -> int | None:
    match = re.search(r"\(([+-]\d+)d\)", movement)
    return int(match.group(1)) if match else None


def parse_positive_int(value: Any) -> int:
    try:
        return max(int(str(value)), 0)
    except (TypeError, ValueError):
        return 0


def status_theme(status: str) -> dict[str, str]:
    if status == STATUS_GREEN:
        return {
            "color": "#16a34a",
            "badge_bg": "#dcfce7",
            "row_bg": "#f0fdf4",
            "soft_bg": "#f0fdf4",
            "border": "#e2e8f0",
        }
    if status == STATUS_YELLOW:
        return {
            "color": "#b45309",
            "badge_bg": "#fef3c7",
            "row_bg": "#fffbeb",
            "soft_bg": "#fffbeb",
            "border": "#e2e8f0",
        }
    if status == STATUS_RED:
        return {
            "color": "#dc2626",
            "badge_bg": "#fee2e2",
            "row_bg": "#fef2f2",
            "soft_bg": "#fef2f2",
            "border": "#e2e8f0",
        }
    if status == STATUS_DONE:
        return {
            "color": "#2563eb",
            "badge_bg": "#dbeafe",
            "row_bg": "#eff6ff",
            "soft_bg": "#eff6ff",
            "border": "#bfdbfe",
        }
    if status == STATUS_NOT_STARTED:
        return {
            "color": "#475569",
            "badge_bg": "#e2e8f0",
            "row_bg": "#f8fafc",
            "soft_bg": "#f8fafc",
            "border": "#e2e8f0",
        }
    return {
        "color": "#64748b",
        "badge_bg": "#e2e8f0",
        "row_bg": "#f8fafc",
        "soft_bg": "#f8fafc",
        "border": "#e2e8f0",
    }


def email_status_label(status: str) -> str:
    if status == STATUS_GREEN:
        return "On Track"
    if status == STATUS_YELLOW:
        return "At Risk"
    if status == STATUS_RED:
        return "Delayed"
    if status == STATUS_DONE:
        return "Done"
    if status == STATUS_NOT_STARTED:
        return "Not Started"
    return "Missing Updates"


def blocker_theme(status: str) -> dict[str, str]:
    if status == STATUS_RED:
        accent = "#dc2626"
    elif status == STATUS_YELLOW:
        accent = "#f59e0b"
    elif status == STATUS_GREEN:
        accent = "#16a34a"
    else:
        accent = "#64748b"
    return {
        "color": "#334155",
        "accent": accent,
        "soft_bg": "#f8fafc",
        "border": "#e2e8f0",
    }


def severity_theme(severity: str) -> dict[str, str]:
    if severity == "red":
        return {"color": "#dc2626", "bg": "#fee2e2"}
    if severity == "yellow":
        return {"color": "#f59e0b", "bg": "#fef3c7"}
    return {"color": "#64748b", "bg": "#e2e8f0"}


def render_text_email(
    subject: str,
    summary: dict[str, int],
    rows: list[dict[str, Any]],
    blockers: list[dict[str, str]],
    hygiene: list[dict[str, str]],
    sheet_url: str,
    signoff: str,
    signoff_name: str,
    greeting: str,
) -> str:
    at_risk = summary["yellow"] + summary["red"]
    lines = [
        subject,
        "",
        "SUMMARY",
        f"- On track: {summary['green']}/{summary['total']}",
        f"- At risk: {at_risk} ({summary['red']} red, {summary['yellow']} yellow)",
        f"- Not started: {summary['not_started']}",
        f"- Done: {summary['done']}",
        f"- Missing updates: {summary['missing_updates']}",
        f"- Blockers / risks: {summary['blockers']}",
        "",
        greeting,
        "",
        "Please find the latest mission health report.",
        "",
        "MISSION UPDATES",
        "Sorted by status: on track, at risk, delayed, not started, missing, done.",
        "",
    ]
    for row in rows:
        status_value = str(row.get("status", "") or STATUS_MISSING)
        status = email_status_label(status_value).upper()
        progress = str(row.get("progress", "") or "n/a")
        due_date = email_due_date_display(
            row.get("due_date", ""),
            row.get("due_date_movement", ""),
            row.get("due_date_overdue_days", 0),
            row.get("original_due_date", ""),
        )
        mission = str(row.get("mission", ""))
        title = email_mission_title(row)
        lines.extend(
            [
                f"[{status}] {title}",
                f"DRI: {row.get('dri', '') or 'Unassigned'}",
                f"Progress: {progress} | Due: {due_date}",
            ]
        )
        if row.get("mission_url"):
            lines.append(f"Link: {row.get('mission_url')}")
        lines.extend(
            [
                f"Done this week: {row.get('done_this_week', '') or 'No update captured.'}",
                f"Plan for next week: {row.get('plan_for_next_week', '') or 'No plan captured.'}",
                "",
            ]
        )

    lines.extend(["BLOCKERS / RISKS"])
    if blockers:
        for blocker in blockers:
            owner = blocker.get("owner", "") or "Unassigned"
            days_open = blocker.get("days_open", "") or "Not provided"
            kind = str(blocker.get("kind", "") or "").lower()
            kind_prefix = "[Risk] " if kind == "risk" else ("[Blocker] " if kind == "blocker" else "")
            lines.extend(
                [
                    f"- {kind_prefix}{blocker.get('mission', '')}: {blocker.get('text', '')}",
                    f"  DRI: {blocker.get('dri', '')} | Owner: {owner} | Days open: {days_open}",
                ]
            )
    else:
        lines.append("- No active blockers reported.")
    if hygiene:
        lines.extend(["", "DATA HYGIENE"])
        grouped: dict[str, list[dict[str, str]]] = {}
        for issue in hygiene:
            mission = str(issue.get("mission", ""))
            grouped.setdefault(mission, []).append(issue)
        severity_order = {"red": 0, "yellow": 1, "info": 2}
        for mission, issues in grouped.items():
            severity = min(
                (str(issue.get("severity", "")).upper() for issue in issues),
                key=lambda value: severity_order.get(value.lower(), 9),
            )
            messages = "; ".join(
                str(issue.get("message", "")) for issue in issues if issue.get("message")
            )
            lines.append(f"- {mission}: {messages} ({severity})")
    if sheet_url:
        lines.extend(["", "WEEKLY SHEET", sheet_url])
    lines.extend(["", signoff, signoff_name])
    return "\n".join(lines)


def mission_email_row(
    mission: dict[str, Any],
    parsed_update: ParsedUpdate | None,
    hygiene: list[dict[str, str]],
    blockers: list[Blocker],
    *,
    missing_update: bool,
    missing_update_weeks: int = 0,
    due_date_movement: str = "",
    due_date_overdue_days: int = 0,
    original_due_date: str = "",
) -> dict[str, Any]:
    return {
        "mission": str(mission.get("name") or mission.get("summary") or mission.get("key") or ""),
        "mission_url": str(mission.get("url", "")),
        "month_label": month_label_short_display(mission.get("original_month_label", "")),
        "dri": display_dri(mission.get("dri")),
        "status": parsed_update.status if parsed_update else STATUS_MISSING,
        "progress": stringify_percent(mission.get("progress")),
        "due_date": str(mission.get("due_date", "")),
        "due_date_movement": due_date_movement,
        "due_date_overdue_days": due_date_overdue_days,
        "original_due_date": str(original_due_date or ""),
        "done_this_week": parsed_update.done_this_week if parsed_update else "",
        "plan_for_next_week": parsed_update.plan_for_next_week if parsed_update else "",
        "blockers": blockers,
        "hygiene": hygiene,
        "missing_update": missing_update,
        "missing_update_weeks": missing_update_weeks,
    }
