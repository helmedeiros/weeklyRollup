"""Turn a team snapshot into a self-contained email draft.

This module is the shared pipeline used by both the demo generator and the
retroactive regeneration CLI. It emits three formats:

- ``build_email_html(snapshot)`` — inlined HTML suitable for pasting into
  a mail client or previewing inside the dashboard modal.
- ``build_email_text(snapshot)`` — plain-text fallback with the same
  structure.
- ``build_markdown(snapshot)`` — Confluence-friendly markdown summary.

The demo generator also imports :func:`synth_leader_engineer_update`,
which produces a deterministic "Done this week / Target next week /
Blockers" body per objective based on a team+week+key seed so that
regenerating the dataset is reproducible.
"""

from __future__ import annotations

import random
from html import escape
from typing import Any


BUCKET_DISPLAY = {
    "done": ("Done", "#16a34a", "#dcf3e0"),
    "spillover_on_track": ("Spillover on track", "#0f766e", "#d1f2ee"),
    "spillover_at_risk": ("Spillover at risk", "#b45309", "#fdecc9"),
    "spillover_blocked": ("Spillover blocked", "#b91c1c", "#fbd6d6"),
    "missing": ("Missing update", "#475569", "#e6ecf5"),
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

# Deterministic-ish phrase pools per bucket. The generator picks one at
# random with a seed so a given team+week+key always produces the same
# blurb.
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


def _subject(snapshot: dict[str, Any]) -> str:
    week = snapshot.get("week", {})
    team = snapshot.get("team", {})
    return f"Objectives Rollup — {team.get('name', '')} — Week {week.get('iso_week', '')}"


def _pretty_date(target: str) -> str:
    from datetime import date
    try:
        d = date.fromisoformat(target)
        return f"{MONTH_NAME[d.month]} {d.day}, {d.year}"
    except Exception:
        return target


def build_email_html(snapshot: dict[str, Any]) -> str:
    """Return a self-contained HTML string previewing the weekly draft."""
    team = snapshot.get("team", {})
    week = snapshot.get("week", {})
    totals = snapshot.get("totals", {})
    objectives = snapshot.get("objectives", [])

    subject = _subject(snapshot)
    date_label = _pretty_date(week.get("target_date", ""))
    rate = (totals.get("delivery_rate") or 0) * 100

    def bucket_order(o: dict[str, Any]) -> int:
        order = {"spillover_blocked": 0, "spillover_at_risk": 1, "missing": 2, "spillover_on_track": 3, "done": 4}
        return order.get(o.get("bucket", ""), 99)

    sorted_objectives = sorted(objectives, key=lambda o: (bucket_order(o), o.get("key", "")))

    obj_html: list[str] = []
    for obj in sorted_objectives:
        bucket = obj.get("bucket", "done")
        label, fg, bg = BUCKET_DISPLAY.get(bucket, BUCKET_DISPLAY["done"])
        update = obj.get("update") or {}
        done = update.get("done_this_week", "")
        target_line = update.get("target_next_week", "")
        blockers = update.get("blockers", "")
        author = update.get("author") or obj.get("leader_engineer", "")
        progress = obj.get("progress", "")

        blocker_html = (
            f'<div style="margin-top:6px;color:#b45309;"><strong>Blockers:</strong> {escape(blockers)}</div>'
            if blockers else ""
        )
        obj_html.append(f"""
<div style="margin:12px 0;padding:14px 16px;border:1px solid #e2e8f0;border-radius:8px;background:#ffffff;">
  <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="border-collapse:collapse;">
    <tr>
      <td>
        <span style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:#132968;background:#eaf1fb;padding:2px 8px;border-radius:4px;">{escape(obj.get('key', ''))}</span>
        <strong style="margin-left:8px;color:#132968;">{escape(obj.get('name', ''))}</strong>
      </td>
      <td style="text-align:right;">
        <span style="font-size:11px;font-weight:700;padding:4px 10px;border-radius:999px;background:{bg};color:{fg};text-transform:uppercase;letter-spacing:0.5px;">{escape(label)}</span>
      </td>
    </tr>
  </table>
  <div style="color:#64748b;font-size:12px;margin-top:6px;">{escape(author)} · {escape(obj.get('jira_status', ''))}{f' · {escape(progress)}' if progress else ''}</div>
  {f'<div style="margin-top:10px;"><strong>Done this week:</strong> {escape(done)}</div>' if done else ''}
  {f'<div style="margin-top:4px;"><strong>Target next week:</strong> {escape(target_line)}</div>' if target_line else ''}
  {blocker_html}
</div>""")

    stats_html = f"""
<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="text-align:center;border-collapse:collapse;background:#f8fafc;">
  <tr>
    <td style="padding:12px;"><div style="font-family:Verdana,sans-serif;font-size:25px;font-weight:bold;color:#16a34a;">{totals.get('done', 0)}</div><div style="font-family:Verdana,sans-serif;font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;padding-top:4px;">Done</div></td>
    <td style="padding:12px;"><div style="font-family:Verdana,sans-serif;font-size:25px;font-weight:bold;color:#0d9488;">{totals.get('spillover_on_track', 0)}</div><div style="font-family:Verdana,sans-serif;font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;padding-top:4px;">On track</div></td>
    <td style="padding:12px;"><div style="font-family:Verdana,sans-serif;font-size:25px;font-weight:bold;color:#f59e0b;">{totals.get('spillover_at_risk', 0)}</div><div style="font-family:Verdana,sans-serif;font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;padding-top:4px;">At risk</div></td>
    <td style="padding:12px;"><div style="font-family:Verdana,sans-serif;font-size:25px;font-weight:bold;color:#dc2626;">{totals.get('spillover_blocked', 0)}</div><div style="font-family:Verdana,sans-serif;font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;padding-top:4px;">Blocked</div></td>
    <td style="padding:12px;"><div style="font-family:Verdana,sans-serif;font-size:25px;font-weight:bold;color:#475569;">{totals.get('missing', 0)}</div><div style="font-family:Verdana,sans-serif;font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;padding-top:4px;">Missing</div></td>
  </tr>
</table>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background-color:#f1f2f6;font-family:Verdana,sans-serif;color:#334155;">
<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="border-collapse:collapse;background:#f1f2f6;">
  <tr>
    <td align="center" style="padding:16px 8px;">
      <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="760" style="border-collapse:collapse;width:760px;max-width:100%;background-color:#ffffff;">
        <tr>
          <td style="background-color:#132968;padding:28px;text-align:center;">
            <div style="font-family:Verdana,sans-serif;font-size:12px;color:#cfe4ff;text-transform:uppercase;letter-spacing:2px;">{escape(team.get('name', ''))}</div>
            <div style="font-family:Verdana,sans-serif;font-size:24px;font-weight:bold;color:#ffffff;padding-top:8px;">Week {week.get('iso_week', '')} — {escape(date_label)}</div>
            <div style="font-family:Verdana,sans-serif;font-size:12px;color:#cfe4ff;padding-top:6px;">Delivery rate: {rate:.1f}%</div>
          </td>
        </tr>
        <tr><td style="padding:12px;">{stats_html}</td></tr>
        <tr>
          <td style="padding:22px 28px 8px;font-family:Verdana,sans-serif;font-size:14px;color:#334155;line-height:1.6;">
            Hi team,<br><br>
            Please find the latest objective health report for <strong style="color:#132968;">{escape(team.get('name', ''))}</strong>.
          </td>
        </tr>
        <tr>
          <td style="padding:0 28px 28px;">
            <h2 style="font-family:Verdana,sans-serif;font-size:16px;color:#132968;border-bottom:2px solid #132968;padding-bottom:8px;margin:12px 0 8px;">Objective updates</h2>
            {''.join(obj_html)}
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>
"""


def build_email_text(snapshot: dict[str, Any]) -> str:
    """Plain-text fallback that mirrors the HTML structure."""
    team = snapshot.get("team", {})
    week = snapshot.get("week", {})
    totals = snapshot.get("totals", {})
    objectives = snapshot.get("objectives", [])
    subject = _subject(snapshot)
    date_label = _pretty_date(week.get("target_date", ""))
    rate = (totals.get("delivery_rate") or 0) * 100

    lines = [
        subject,
        "=" * len(subject),
        "",
        f"{team.get('name', '')} — Week {week.get('iso_week', '')} ({date_label})",
        f"Delivery rate: {rate:.1f}% ({totals.get('done', 0)} of {totals.get('objectives', 0)} done)",
        "",
        f"Done: {totals.get('done', 0)}  |  On track: {totals.get('spillover_on_track', 0)}  |  At risk: {totals.get('spillover_at_risk', 0)}  |  Blocked: {totals.get('spillover_blocked', 0)}  |  Missing: {totals.get('missing', 0)}",
        "",
        "Objective updates",
        "-----------------",
        "",
    ]
    order = {"spillover_blocked": 0, "spillover_at_risk": 1, "missing": 2, "spillover_on_track": 3, "done": 4}
    for obj in sorted(objectives, key=lambda o: (order.get(o.get("bucket", ""), 99), o.get("key", ""))):
        bucket = obj.get("bucket", "done")
        label = BUCKET_DISPLAY.get(bucket, BUCKET_DISPLAY["done"])[0]
        update = obj.get("update") or {}
        author = update.get("author") or obj.get("leader_engineer", "")
        lines.append(f"[{label}] {obj.get('key', '')} — {obj.get('name', '')}")
        meta = f"    {author} · {obj.get('jira_status', '')}"
        if obj.get("progress"): meta += f" · {obj['progress']}"
        lines.append(meta)
        if update.get("done_this_week"):
            lines.append(f"    Done this week: {update['done_this_week']}")
        if update.get("target_next_week"):
            lines.append(f"    Target next week: {update['target_next_week']}")
        if update.get("blockers"):
            lines.append(f"    Blockers: {update['blockers']}")
        lines.append("")
    return "\n".join(lines)


def build_markdown(snapshot: dict[str, Any]) -> str:
    """Markdown / Confluence-friendly report."""
    team = snapshot.get("team", {})
    week = snapshot.get("week", {})
    totals = snapshot.get("totals", {})
    objectives = snapshot.get("objectives", [])
    subject = _subject(snapshot)
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
        label = BUCKET_DISPLAY.get(bucket, BUCKET_DISPLAY["done"])[0]
        update = obj.get("update") or {}
        author = update.get("author") or obj.get("leader_engineer", "")
        lines.append(f"### `{obj.get('key', '')}` · {obj.get('name', '')}  \\[{label}]")
        lines.append(f"Owner: **{author}** · Jira: {obj.get('jira_status', '')}" + (f" · Progress: {obj['progress']}" if obj.get('progress') else ""))
        lines.append("")
        if update.get("done_this_week"):
            lines.append(f"**Done this week:** {update['done_this_week']}")
        if update.get("target_next_week"):
            lines.append(f"**Target next week:** {update['target_next_week']}")
        if update.get("blockers"):
            lines.append(f"**Blockers:** {update['blockers']}")
        lines.append("")
    return "\n".join(lines)
