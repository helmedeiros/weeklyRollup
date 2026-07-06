"""Turn a team snapshot into a self-contained email draft.

The heavy lifting is delegated to ``objective_rollup.render_email_draft``
so that demo emails go through the same production template used by
``run_rollup.py``. This module is only responsible for:

- mapping a snapshot's objectives/updates into the row shape the template
  renderer expects;
- synthesising deterministic weekly Leader Engineer updates for demo
  snapshots (:func:`synth_leader_engineer_update`);
- providing a lightweight Markdown format for retroactive regeneration.
"""

from __future__ import annotations

import random
from typing import Any

from objective_rollup import (
    STATUS_DONE,
    STATUS_GREEN,
    STATUS_MISSING,
    STATUS_RED,
    STATUS_YELLOW,
    render_email_draft,
)


BUCKET_TO_STATUS = {
    "done": STATUS_DONE,
    "spillover_on_track": STATUS_GREEN,
    "spillover_at_risk": STATUS_YELLOW,
    "spillover_blocked": STATUS_RED,
    "missing": STATUS_MISSING,
}

BUCKET_LABEL = {
    "done": "Done",
    "spillover_on_track": "Spillover on track",
    "spillover_at_risk": "Spillover at risk",
    "spillover_blocked": "Spillover blocked",
    "missing": "Missing update",
}

STATUS_WORD = {
    "done": "Green",
    "spillover_on_track": "Green",
    "spillover_at_risk": "Yellow",
    "spillover_blocked": "Red",
    "missing": "Missing",
}

MONTH_NAME = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December",
}

# Deterministic phrase pools for demo-side LE update synthesis.
DONE_PHRASES = {
    "done": [
        "Shipped the last remaining PR and confirmed the target metric moved as expected.",
        "Wrapped the rollout to 100% and the guardrail dashboards stayed green.",
        "Closed the final ticket in the epic and archived the working doc.",
        "Landed the migration cutover; no incidents in the follow-up window.",
    ],
    "spillover_on_track": [
        "Landed 3 of 5 PRs; last two under review with a partner team.",
        "Cleared the staging soak; production rollout scheduled for early next week.",
        "Feature flag is enabled for internal cohorts; watching latency and error rate.",
        "Prep work is done; kickoff of the customer-facing rollout starts Monday.",
    ],
    "spillover_at_risk": [
        "Slipped the promised design review; rescheduling for later this week.",
        "Discovered a regression in the smoke tests that pushed the merge back.",
        "Waiting on a dependency from an adjacent team; escalation opened.",
        "Scope grew after user testing; trimming to hit the reduced target.",
    ],
    "spillover_blocked": [
        "Blocked on a vendor change; ticket open with them since Tuesday.",
        "Legal review outstanding — no code path until the sign-off lands.",
        "Waiting on infra migration that was pushed to the next quarter.",
        "Incident on adjacent service consumed the week; work is paused.",
    ],
    "missing": [
        "No update was captured this week.",
        "Owner was out; update will land in the next report.",
        "Update deferred pending a decision from the steering meeting.",
    ],
}

TARGET_PHRASES = {
    "done": [
        "Monitor for the next 2 weeks; no active work planned.",
        "Move to maintenance; capture learnings into the runbook.",
        "Hand off to the on-call rotation and close the epic.",
    ],
    "spillover_on_track": [
        "Ship remaining PRs; start canary rollout by Wednesday.",
        "Complete the final code review and enable the feature flag globally.",
        "Wrap the last integration test and hand off to QA.",
    ],
    "spillover_at_risk": [
        "Reduce scope to the top-2 use cases and land a partial fix.",
        "Realign with the partner team and reset the delivery date.",
        "Focus on removing the current blocker; deprioritise nice-to-haves.",
    ],
    "spillover_blocked": [
        "Unblock the vendor conversation and get an ETA.",
        "Pick up a related workstream while the primary path stays blocked.",
        "Reassign to a different owner so the current one can help elsewhere.",
    ],
    "missing": [
        "Post an update by Friday capturing what shifted.",
        "Sync with the owner and file the missing update retroactively.",
    ],
}

BLOCKER_PHRASES = {
    "spillover_at_risk": [
        "Design review pending from the sibling team.",
        "A single reviewer is a bottleneck; needs a delegate.",
    ],
    "spillover_blocked": [
        "External vendor SLA slipping; no eta.",
        "Legal sign-off outstanding.",
        "Infra migration blocking rollout; owner: platform.",
    ],
    "missing": [
        "No owner reachable this week.",
    ],
}


def synth_leader_engineer_update(
    objective: dict[str, Any],
    team_name: str,
    iso_year: int,
    iso_week: int,
) -> dict[str, Any]:
    """Deterministically synthesise a weekly update body for one objective."""
    seed = f"update-{team_name}-{iso_year}-{iso_week}-{objective.get('key', '')}"
    rng = random.Random(seed)
    bucket = objective.get("bucket", "done")
    author = objective.get("leader_engineer", "")
    status_word = STATUS_WORD.get(bucket, "Green")

    done = rng.choice(DONE_PHRASES.get(bucket, DONE_PHRASES["done"]))
    target = rng.choice(TARGET_PHRASES.get(bucket, TARGET_PHRASES["done"]))
    blockers_pool = BLOCKER_PHRASES.get(bucket, [])
    blockers = rng.choice(blockers_pool) if blockers_pool else ""

    return {
        "author": author,
        "status": status_word,
        "done_this_week": done,
        "target_next_week": target,
        "blockers": blockers,
    }


# --- Snapshot -> production email pipeline -----------------------------


def _snapshot_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Map snapshot objectives into the row shape ``render_email_draft`` expects."""
    week = snapshot.get("week", {})
    month_label = str(week.get("month_label") or "").replace("objective-", "").strip()
    rows: list[dict[str, Any]] = []
    for o in snapshot.get("objectives", []):
        update = o.get("update") or {}
        bucket = o.get("bucket", "done")
        status = BUCKET_TO_STATUS.get(bucket, STATUS_MISSING)
        rows.append({
            "objective": o.get("name", ""),
            "objective_url": o.get("url", ""),
            "leader_engineer": o.get("leader_engineer", "") or "Unassigned",
            "status": status,
            "progress": o.get("progress", "") or "No progress",
            "due_date": o.get("effective_due_date", "") or "",
            "due_date_movement": "",
            "due_date_overdue_days": int(o.get("due_date_overdue_days") or 0),
            "original_due_date": "",
            "done_this_week": update.get("done_this_week", "") or "No update captured.",
            "plan_for_next_week": update.get("target_next_week", "") or "No plan captured.",
            "blockers": _blockers_for_row(update, o, status),
            "hygiene": [],
            "missing_update": bool(o.get("missing_update")),
            "month_label": month_label,
        })
    return rows


def _blockers_for_row(update: dict[str, Any], obj: dict[str, Any], status: str) -> list[dict[str, Any]]:
    text = (update.get("blockers") or "").strip()
    if not text:
        return []
    kind = "blocker" if obj.get("bucket") == "spillover_blocked" else "risk"
    author = update.get("author") or obj.get("leader_engineer") or ""
    return [{
        "kind": kind,
        "text": text,
        "leader_engineer": author,
        "owner": author,
        "days_open": "n/a",
        "objective": obj.get("name", ""),
        "status": status,
    }]


def _snapshot_config(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Minimum viable config so ``render_email_draft`` produces a demo email."""
    return {
        "team": {"name": snapshot.get("team", {}).get("name", "")},
        "email": {
            "subject_pattern": "Weekly Objective Update — {team_name} — Week {iso_week}",
            "greeting": "Hi team,",
            "signoff": "Kind Regards",
            "signoff_name": "Engineering Manager",
        },
    }


def build_email_draft(snapshot: dict[str, Any]) -> dict[str, str]:
    """Render the production-template email for a snapshot.

    Returns a dict with ``subject``, ``html`` and ``text`` keys.
    """
    draft = render_email_draft(
        _snapshot_config(snapshot),
        _snapshot_rows(snapshot),
        iso_week=int(snapshot.get("week", {}).get("iso_week") or 0),
        report_month_label=str(snapshot.get("week", {}).get("month_label") or ""),
    )
    return {
        "subject": draft["subject"],
        "html": draft["html_body"],
        "text": draft["text_body"],
    }


def build_email_html(snapshot: dict[str, Any]) -> str:
    return build_email_draft(snapshot)["html"]


def build_email_text(snapshot: dict[str, Any]) -> str:
    return build_email_draft(snapshot)["text"]


# --- Markdown for retroactive regeneration ----------------------------


def _pretty_date(target: str) -> str:
    from datetime import date
    try:
        d = date.fromisoformat(target)
        return f"{MONTH_NAME[d.month]} {d.day}, {d.year}"
    except Exception:
        return target


def build_markdown(snapshot: dict[str, Any]) -> str:
    """Markdown / Confluence-friendly report."""
    team = snapshot.get("team", {})
    week = snapshot.get("week", {})
    totals = snapshot.get("totals", {})
    objectives = snapshot.get("objectives", [])
    subject = f"Weekly Objective Update — {team.get('name', '')} — Week {week.get('iso_week', '')}"
    date_label = _pretty_date(week.get("target_date", ""))
    rate = (totals.get("delivery_rate") or 0) * 100

    lines = [
        f"# {subject}",
        "",
        f"**{team.get('name', '')}** · Week {week.get('iso_week', '')} · {date_label}",
        "",
        f"**Delivery rate:** {rate:.1f}%  ({totals.get('done', 0)} of {totals.get('objectives', 0)} done)",
        "",
        f"| Done | On track | At risk | Blocked | Missing |",
        f"|------|----------|---------|---------|---------|",
        f"| {totals.get('done', 0)} | {totals.get('spillover_on_track', 0)} | {totals.get('spillover_at_risk', 0)} | {totals.get('spillover_blocked', 0)} | {totals.get('missing', 0)} |",
        "",
        "## Objective updates",
        "",
    ]
    order = {"spillover_blocked": 0, "spillover_at_risk": 1, "missing": 2, "spillover_on_track": 3, "done": 4}
    for obj in sorted(objectives, key=lambda o: (order.get(o.get("bucket", ""), 99), o.get("key", ""))):
        bucket = obj.get("bucket", "done")
        label = BUCKET_LABEL.get(bucket, bucket)
        update = obj.get("update") or {}
        author = update.get("author") or obj.get("leader_engineer", "")
        lines.append(f"### `{obj.get('key', '')}` · {obj.get('name', '')}  \\[{label}]")
        lines.append(
            f"Owner: **{author}** · Jira: {obj.get('jira_status', '')}"
            + (f" · Progress: {obj['progress']}" if obj.get('progress') else "")
        )
        lines.append("")
        if update.get("done_this_week"):
            lines.append(f"**Done this week:** {update['done_this_week']}")
        if update.get("target_next_week"):
            lines.append(f"**Plan for next week:** {update['target_next_week']}")
        if update.get("blockers"):
            lines.append(f"**Blockers / Risks:** {update['blockers']}")
        lines.append("")
    return "\n".join(lines)
