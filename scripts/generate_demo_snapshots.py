"""Generate a fully synthetic team-snapshot dataset for the public dashboard.

Every value here is invented for demonstration. No team names, objective
keys, Leader Engineers, or KPIs mirror any real organisation.

Data model:

- Each team owns a fresh **monthly cohort** of objectives. A cohort's
  objectives only appear in the weeks whose target-Wednesday falls in
  that calendar month. When the month rolls over, the previous cohort
  disappears and a brand-new set of objectives arrives (mirroring how
  the tool is used in production).
- Every objective has a target outcome for the month (done / on-track /
  at-risk / blocked / missing) chosen at cohort build time. Progress
  moves week-by-week toward that target, with small deterministic noise,
  so weekly reports show a real trajectory instead of a static 100%.
- Files are still emitted one per ISO week per team at
  ``demo-snapshots/<team-id>/<YYYY>-Www.json``.
"""

from __future__ import annotations

import json
import random
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

from email_from_snapshot import (
    build_email_draft,
    synth_leader_engineer_update,
)
from flow_metrics import (
    DemoFlowMetricsProvider,
    FlowScope,
    FlowWindow,
    aggregate_flow_blocks,
)


ISO_YEAR = 2026
FIRST_WEEK = 6   # 2026-W06: Mon Feb 2 - Sun Feb 8
LAST_WEEK = 31   # 2026-W31: Mon Jul 27 - Sun Aug 2

MONTH_NAME_LOWER = {
    1: "january", 2: "february", 3: "march", 4: "april", 5: "may", 6: "june",
    7: "july", 8: "august", 9: "september", 10: "october", 11: "november", 12: "december",
}
MONTH_NAME_DISPLAY = {k: v.capitalize() for k, v in MONTH_NAME_LOWER.items()}


# Team roster + monthly cohort size + business unit.
TEAMS = [
    ("alpha-foundations",   "Alpha Foundations",    "Platform", 5),
    ("beta-payments",       "Beta Payments Core",   "Platform", 6),
    ("gamma-runtime",       "Gamma Runtime",        "Platform", 5),
    ("delta-data-platform", "Delta Data Platform",  "Platform", 4),
    ("epsilon-growth",      "Epsilon Growth",       "B2C",      6),
    ("zeta-search",         "Zeta Search Discovery","B2C",      4),
    ("eta-checkout",        "Eta Checkout",         "B2C",      5),
    ("theta-post-booking",  "Theta Post-Booking",   "B2C",      5),
    ("iota-partners",       "Iota Partner Portal",  "B2B",      4),
    ("kappa-enterprise",    "Kappa Enterprise Ops", "B2B",      4),
    ("lambda-ingestion",    "Lambda Ingestion",     "Coverage", 5),
    ("mu-content-ops",      "Mu Content Ops",       "Coverage", 5),
]

OBJECTIVE_TITLES = {
    "Platform": [
        "Zero-downtime restart choreography",
        "Feature flag rollout guardrails",
        "Golden-path SLO board",
        "Observability sampling refresh",
        "Warm-cache eviction policy",
        "Rate-limiter fairness audit",
        "Deprecation channel rollout",
        "Service topology drift alarm",
        "Config drift auto-repair",
        "Runtime resource budgets",
    ],
    "B2C": [
        "Homepage skeleton refresh",
        "Cart persistence across surfaces",
        "Personalised trip recommendations",
        "Purchase confirmation clarity",
        "Refund status transparency",
        "Payment method reorder",
        "Passenger name-change flow",
        "Search relevance re-ranker",
        "Loyalty perks eligibility banner",
        "Checkout abandonment nudge",
    ],
    "B2B": [
        "Partner API rate-limit v2",
        "Onboarding self-serve wizard",
        "Compliance audit trail",
        "Partner billing reconciliation",
        "SLA breach notifier",
        "Reseller webhook v3",
        "Contract-tier feature gating",
    ],
    "Coverage": [
        "Provider content ingestion QA",
        "Cross-locale asset governance",
        "Publisher content freshness",
        "Cadence dashboard for editors",
        "Broken-image sentinel",
        "Content lint gate",
        "Legacy asset migration",
    ],
}

LEADER_ENGINEER_POOL = [
    "Ava Thornton", "Bram Larsson", "Cai Nguyen", "Dara Okonjo", "Ellis Marín",
    "Frida Ohno", "Gali Tomori", "Hiro Vasquez", "Ines Marchetti", "Jules Cabrera",
    "Kai Ostberg", "Lena Rihanna", "Milo Anders", "Nya Sardar", "Odin Barone",
    "Pia Rivas", "Quinn Yates", "Rio Delacroix", "Sana Rowe", "Tomo Ilves",
]


def _login(name: str) -> str:
    """Stable GitHub-shaped login (first initial + surname), ascii-folded.

    Identity contract: engineer-scope flow metrics resolve on login, never on
    display name, so the demo keys engineers the same way the live feed will.
    """
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    parts = folded.lower().replace(".", "").split()
    return f"{parts[0][0]}{parts[-1]}"


LEADER_ENGINEER_LOGIN = {name: _login(name) for name in LEADER_ENGINEER_POOL}


def _team_identity(team_id: str) -> dict:
    """Real-shaped join keys (invented values) for the future live adapter."""
    return {
        "jira_abbrev": team_id.split("-")[0].upper()[:4],
        "github_team_slug": team_id,
        "repos": [f"omio/{team_id}"],
    }


FLOW = DemoFlowMetricsProvider()

# Weighted outcome distribution: (label, weight)
OUTCOME_WEIGHTS = [
    ("done", 0.55),
    ("on_track", 0.20),
    ("at_risk", 0.15),
    ("blocked", 0.05),
    ("missing", 0.05),
]

BUCKET_OF_OUTCOME = {
    "done": "done",
    "on_track": "spillover_on_track",
    "at_risk": "spillover_at_risk",
    "blocked": "spillover_blocked",
    "missing": "missing",
}


def weighted_choice(weights, rng):
    total = sum(w for _, w in weights)
    r = rng.random() * total
    acc = 0.0
    for value, weight in weights:
        acc += weight
        if r < acc:
            return value
    return weights[-1][0]


def month_of_iso_week(iso_year: int, iso_week: int) -> tuple[int, int]:
    """Return (calendar_year, calendar_month) for the ISO week's Wednesday."""
    target = date.fromisocalendar(iso_year, iso_week, 3)
    return target.year, target.month


def weeks_by_month(iso_year: int, first: int, last: int) -> dict[tuple[int, int], list[int]]:
    grouped: dict[tuple[int, int], list[int]] = defaultdict(list)
    for w in range(first, last + 1):
        y, m = month_of_iso_week(iso_year, w)
        grouped[(y, m)].append(w)
    return dict(grouped)


def last_day_of_month(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1).replace(day=1) - (date(year, month + 1, 1) - date(year, month, 28)).__class__(days=(date(year, month + 1, 1) - date(year, month + 1, 1)).days)


def _last_day(year: int, month: int) -> date:
    """Return the last calendar day of the month."""
    from calendar import monthrange
    return date(year, month, monthrange(year, month)[1])


def build_cohort(
    team_id: str,
    business_unit: str,
    year: int,
    month: int,
    cohort_size: int,
    weeks_in_month: list[int],
) -> list[dict]:
    """Return the objectives for one team-month, with per-week progression."""
    rng = random.Random(f"cohort-{team_id}-{year}-{month}")
    titles = OBJECTIVE_TITLES[business_unit]
    quarter = (month - 1) // 3 + 1
    month_display = MONTH_NAME_DISPLAY[month]
    prefix = team_id.split("-")[0].upper()[:4]
    yy_mm = f"{year % 100:02d}{month:02d}"
    n_weeks = len(weeks_in_month)

    picked_titles = rng.sample(titles, k=min(cohort_size, len(titles)))
    if len(picked_titles) < cohort_size:
        picked_titles += [rng.choice(titles) for _ in range(cohort_size - len(picked_titles))]

    objectives: list[dict] = []
    for i in range(cohort_size):
        outcome = weighted_choice(OUTCOME_WEIGHTS, rng)
        obj_rng = random.Random(f"obj-{team_id}-{year}-{month}-{i}")
        title = picked_titles[i]

        # Final progress per outcome
        if outcome == "done":
            final_pct = 100
        elif outcome == "on_track":
            final_pct = obj_rng.randint(60, 85)
        elif outcome == "at_risk":
            final_pct = obj_rng.randint(35, 55)
        elif outcome == "blocked":
            final_pct = obj_rng.randint(10, 30)
        elif outcome == "missing":
            final_pct = obj_rng.randint(20, 60)
        else:
            final_pct = 100

        # Starting progress (early in the month)
        start_pct = min(final_pct, obj_rng.randint(10, 25))

        # Weekly progression: near-linear with small noise, monotone increasing.
        progress_by_week: list[int] = []
        for w_idx in range(n_weeks):
            if n_weeks == 1:
                pct = final_pct
            else:
                fraction = w_idx / (n_weeks - 1)
                linear = start_pct + (final_pct - start_pct) * fraction
                noise = obj_rng.randint(-4, 4)
                pct = max(0, min(100, int(round(linear + noise))))
            progress_by_week.append(pct)
        for w in range(1, n_weeks):
            progress_by_week[w] = max(progress_by_week[w], progress_by_week[w - 1])
        progress_by_week[-1] = final_pct

        # Bucket per week. Non-final weeks show the ramp-up story; the
        # final week snaps to the outcome so end-of-month totals match
        # the promised distribution.
        buckets_by_week: list[str] = []
        for w_idx, pct in enumerate(progress_by_week):
            is_final = w_idx == n_weeks - 1
            if is_final:
                bucket = BUCKET_OF_OUTCOME[outcome]
            elif pct >= 100:
                bucket = "done"
            else:
                bucket = _mid_week_bucket(outcome, w_idx, n_weeks)
            buckets_by_week.append(bucket)

        objectives.append({
            "key": f"M{prefix}-{yy_mm}-{i + 1:02d}",
            "name": f"Q{quarter} {year} [{month_display}]: {title}",
            "leader_engineer": obj_rng.choice(LEADER_ENGINEER_POOL),
            "outcome": outcome,
            "progress_by_week": progress_by_week,
            "buckets_by_week": buckets_by_week,
            "target_month": (year, month),
        })
    return objectives


def _mid_week_bucket(outcome: str, w_idx: int, n_weeks: int) -> str:
    """Non-final-week bucket, capturing when trouble typically appears.

    ``done`` / ``on_track`` outcomes stay on-track through the month.
    ``at_risk`` outcomes slip roughly halfway through.
    ``blocked`` outcomes get blocked after the first third.
    ``missing`` outcomes only appear as missing on the final week.
    """
    if outcome in ("done", "on_track", "missing"):
        return "spillover_on_track"
    if outcome == "at_risk":
        return "spillover_on_track" if w_idx < n_weeks / 2 else "spillover_at_risk"
    if outcome == "blocked":
        return "spillover_on_track" if w_idx < n_weeks / 3 else "spillover_blocked"
    return "spillover_on_track"


def _status_word(bucket: str) -> str:
    return {
        "done": "Done",
        "spillover_on_track": "Green",
        "spillover_at_risk": "Yellow",
        "spillover_blocked": "Red",
        "missing": "Missing",
    }.get(bucket, "Green")


def _jira_status(bucket: str) -> str:
    return {
        "done": "Done",
        "spillover_on_track": "In Progress",
        "spillover_at_risk": "In Progress",
        "spillover_blocked": "Blocked",
        "missing": "In Progress",
    }.get(bucket, "In Progress")


def generate() -> None:
    root = Path(__file__).resolve().parent.parent / "demo-snapshots"
    by_month = weeks_by_month(ISO_YEAR, FIRST_WEEK, LAST_WEEK)

    # Pre-build every cohort so weekly snapshots just index into them.
    cohorts: dict[tuple[str, int, int], list[dict]] = {}
    for team_id, _, business_unit, cohort_size in TEAMS:
        for (year, month), weeks_in_month in by_month.items():
            cohorts[(team_id, year, month)] = build_cohort(
                team_id, business_unit, year, month, cohort_size, weeks_in_month,
            )

    for iso_week in range(FIRST_WEEK, LAST_WEEK + 1):
        target = date.fromisocalendar(ISO_YEAR, iso_week, 3)
        year, month = target.year, target.month
        weeks_in_this_month = by_month[(year, month)]
        week_idx = weeks_in_this_month.index(iso_week)
        due_day = _last_day(year, month).isoformat()

        week_start = date.fromisocalendar(ISO_YEAR, iso_week, 1)
        week_end = date.fromisocalendar(ISO_YEAR, iso_week, 7)
        window = FlowWindow(
            iso_year=ISO_YEAR,
            iso_week=iso_week,
            from_date=week_start.isoformat(),
            to_date=week_end.isoformat(),
            days=7,
        )

        for team_id, team_name, business_unit, _ in TEAMS:
            cohort = cohorts[(team_id, year, month)]

            objectives: list[dict] = []
            totals = {b: 0 for b in ("done", "spillover_on_track", "spillover_at_risk", "spillover_blocked", "missing")}
            engineers_seen: dict[str, dict] = {}
            for src in cohort:
                bucket = src["buckets_by_week"][week_idx]
                progress = src["progress_by_week"][week_idx]
                login = LEADER_ENGINEER_LOGIN[src["leader_engineer"]]
                obj = {
                    "key": src["key"],
                    "name": src["name"],
                    "url": f"https://example.invalid/objectives/{src['key']}",
                    "leader_engineer": src["leader_engineer"],
                    "leader_engineer_login": login,
                    "status": _status_word(bucket),
                    "jira_status": _jira_status(bucket),
                    "is_done": bucket == "done",
                    "missing_update": bucket == "missing",
                    "effective_due_date": due_day,
                    "due_date_overdue_days": 0,
                    "progress": f"{progress}%",
                    "bucket": bucket,
                    "outcome": src["outcome"],
                    "hygiene_severity": "yellow" if bucket in {"spillover_at_risk", "missing"} else "info",
                    "hygiene": [],
                    "blockers": [],
                }
                obj["update"] = synth_leader_engineer_update(obj, team_name, ISO_YEAR, iso_week)
                # The Jira key is the atomic unit: everything ladders up from it.
                obj_flow = FLOW.fetch(
                    FlowScope("objective", src["key"], src["name"], (src["outcome"],)),
                    window,
                )
                obj["flow_metrics"] = obj_flow
                objectives.append(obj)
                totals[bucket] += 1

                eng = engineers_seen.setdefault(
                    login,
                    {"login": login, "name": src["leader_engineer"], "objective_keys": [], "_blocks": []},
                )
                eng["objective_keys"].append(src["key"])
                eng["_blocks"].append(obj_flow)

            # Engineer flow = median across the keys they own; team = median
            # across its engineers (median-of-medians, like data-tools).
            engineers = []
            engineer_blocks = []
            for login, eng in sorted(engineers_seen.items()):
                flow = aggregate_flow_blocks(
                    eng.pop("_blocks"),
                    scope=FlowScope("engineer", login, eng["name"]),
                    window=window,
                    source=FLOW.source,
                )
                engineer_blocks.append(flow)
                engineers.append({**eng, "flow_metrics": flow})

            team_flow = aggregate_flow_blocks(
                engineer_blocks,
                scope=FlowScope("team", team_id, team_name),
                window=window,
                source=FLOW.source,
            )

            total = sum(totals.values())
            payload = {
                "schema_version": 4,
                "team": {
                    "id": team_id,
                    "name": team_name,
                    "business_unit": business_unit,
                    **_team_identity(team_id),
                },
                "week": {
                    "iso_year": ISO_YEAR,
                    "iso_week": iso_week,
                    "target_date": target.isoformat(),
                    "month_label": f"objective-{MONTH_NAME_LOWER[month]}-{year}",
                },
                "totals": {
                    "objectives": total,
                    "delivery_rate": round(totals["done"] / total, 4) if total else 0.0,
                    "done": totals["done"],
                    "spillover_on_track": totals["spillover_on_track"],
                    "spillover_at_risk": totals["spillover_at_risk"],
                    "spillover_blocked": totals["spillover_blocked"],
                    "missing": totals["missing"],
                },
                "flow_metrics": team_flow,
                "engineers": engineers,
                "objectives": objectives,
            }
            draft = build_email_draft(payload)
            payload["outputs"] = {"email": draft}

            out = root / team_id / f"{ISO_YEAR}-W{iso_week:02d}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"wrote {out}")


if __name__ == "__main__":
    generate()
