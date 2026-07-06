"""Generate a fully synthetic team-snapshot dataset for the public dashboard.

Every value here is invented for demonstration. No team names, objective
keys, Leader Engineers, or KPIs mirror any real organisation. Re-run this script
whenever you want to refresh the shape of the demo dataset.

The output layout matches ``snapshots/``: each team gets one JSON file per
month at ``demo-snapshots/<team-id>/<YYYY>-Www.json``. Six months are emitted
(Feb-Jul 2026) so the dashboard can demo a rolling range picker.
"""

from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path


MONTHS: list[tuple[int, int]] = [
    (2026, 2),
    (2026, 3),
    (2026, 4),
    (2026, 5),
    (2026, 6),
    (2026, 7),
]

MONTH_NAME = {
    1: "january", 2: "february", 3: "march", 4: "april", 5: "may", 6: "june",
    7: "july", 8: "august", 9: "september", 10: "october", 11: "november", 12: "december",
}

# Baseline shape per team. (total, done, on_track, at_risk, blocked, missing)
# Every month is a small deterministic perturbation of these.
TEAMS = [
    ("alpha-foundations",   "Alpha Foundations",    "Platform", (8, 8, 0, 0, 0, 0)),
    ("beta-payments",       "Beta Payments Core",   "Platform", (7, 6, 1, 0, 0, 0)),
    ("gamma-runtime",       "Gamma Runtime",        "Platform", (6, 5, 0, 1, 0, 0)),
    ("delta-data-platform", "Delta Data Platform",  "Platform", (5, 5, 0, 0, 0, 0)),
    ("epsilon-growth",      "Epsilon Growth",       "B2C",      (9, 6, 2, 1, 0, 0)),
    ("zeta-search",         "Zeta Search Discovery","B2C",      (4, 3, 0, 0, 1, 0)),
    ("eta-checkout",        "Eta Checkout",         "B2C",      (5, 5, 0, 0, 0, 0)),
    ("theta-post-booking",  "Theta Post-Booking",   "B2C",      (6, 4, 1, 0, 0, 1)),
    ("iota-partners",       "Iota Partner Portal",  "B2B",      (5, 4, 1, 0, 0, 0)),
    ("kappa-enterprise",    "Kappa Enterprise Ops", "B2B",      (4, 4, 0, 0, 0, 0)),
    ("lambda-ingestion",    "Lambda Ingestion",     "Coverage", (6, 4, 0, 1, 1, 0)),
    ("mu-content-ops",      "Mu Content Ops",       "Coverage", (5, 3, 1, 0, 0, 1)),
]

OBJECTIVE_NAMES = {
    "Platform": [
        "Zero-downtime restart choreography",
        "Feature flag rollout guardrails",
        "Golden-path SLO board",
        "Observability sampling refresh",
        "Warm-cache eviction policy",
    ],
    "B2C": [
        "Homepage skeleton refresh",
        "Cart persistence across surfaces",
        "Personalised trip recommendations",
        "Purchase confirmation clarity",
        "Refund status transparency",
    ],
    "B2B": [
        "Partner API rate-limit v2",
        "Onboarding self-serve wizard",
        "Compliance audit trail",
        "Partner billing reconciliation",
    ],
    "Coverage": [
        "Provider content ingestion QA",
        "Cross-locale asset governance",
        "Publisher content freshness",
        "Cadence dashboard for editors",
        "Broken-image sentinel",
    ],
}

LEADER_ENGINEER_POOL = [
    "Ava Thornton", "Bram Larsson", "Cai Nguyen", "Dara Okonjo", "Ellis Marín",
    "Frida Ohno", "Gali Tomori", "Hiro Vasquez", "Ines Marchetti", "Jules Cabrera",
    "Kai Ostberg", "Lena Rihanna", "Milo Anders", "Nya Sardar", "Odin Barone",
    "Pia Rivas", "Quinn Yates", "Rio Delacroix", "Sana Rowe", "Tomo Ilves",
]


def month_variant(base: tuple[int, int, int, int, int, int], month_index: int, team_id: str) -> tuple[int, int, int, int, int, int]:
    """Deterministically perturb the base bucket layout for a given month/team."""
    rng = random.Random(f"variant-{month_index}-{team_id}")
    total, done, on_track, at_risk, blocked, missing = base
    counts = {
        "done": done,
        "on_track": on_track,
        "at_risk": at_risk,
        "blocked": blocked,
        "missing": missing,
    }
    moves = [
        ("done", "on_track"),
        ("done", "at_risk"),
        ("on_track", "done"),
        ("at_risk", "done"),
        ("at_risk", "blocked"),
        ("blocked", "at_risk"),
        ("done", "missing"),
        ("missing", "done"),
    ]
    for _ in range(rng.randint(0, 2)):
        src, dst = rng.choice(moves)
        if counts[src] > 0:
            counts[src] -= 1
            counts[dst] += 1
    result = (total, counts["done"], counts["on_track"], counts["at_risk"], counts["blocked"], counts["missing"])
    assert result[0] == sum(result[1:]), f"variant total mismatch for {team_id} m={month_index}"
    return result


def generate() -> None:
    root = Path(__file__).resolve().parent.parent / "demo-snapshots"

    for month_index, (year, month) in enumerate(MONTHS):
        target = date(year, month, 15)
        iso_year, iso_week, _ = target.isocalendar()
        week = {
            "iso_year": iso_year,
            "iso_week": iso_week,
            "target_date": target.isoformat(),
            "month_label": f"objective-{MONTH_NAME[month]}-{year}",
        }
        # One seed per month so leader-engineer / objective-name picks stay stable.
        random.seed(1234 + month_index)

        for team_id, team_name, business_unit, base_buckets in TEAMS:
            buckets = month_variant(base_buckets, month_index, team_id)
            total, done, on_track, at_risk, blocked, missing = buckets

            objectives = []
            pool = OBJECTIVE_NAMES[business_unit]
            counter = 100 + month_index * 10

            def _make(bucket: str, objective_status: str, jira_status: str) -> dict:
                nonlocal counter
                counter += 1
                title = pool[counter % len(pool)]
                leader_engineer = random.choice(LEADER_ENGINEER_POOL)
                key = f"M{team_id.split('-')[0].upper()[:4]}-{counter}"
                return {
                    "key": key,
                    "name": title,
                    "url": f"https://example.invalid/objectives/{key}",
                    "leader_engineer": leader_engineer,
                    "status": objective_status,
                    "jira_status": jira_status,
                    "is_done": bucket == "done",
                    "missing_update": bucket == "missing",
                    "effective_due_date": target.isoformat(),
                    "due_date_overdue_days": 0,
                    "progress": "100%" if bucket == "done" else f"{random.randint(30, 90)}%",
                    "bucket": bucket,
                    "hygiene_severity": "yellow" if bucket in {"spillover_at_risk", "missing"} else "info",
                    "hygiene": [],
                    "blockers": [],
                }

            for _ in range(done):
                objectives.append(_make("done", "Green", "Done"))
            for _ in range(on_track):
                objectives.append(_make("spillover_on_track", "Green", "In Progress"))
            for _ in range(at_risk):
                objectives.append(_make("spillover_at_risk", "Yellow", "In Progress"))
            for _ in range(blocked):
                objectives.append(_make("spillover_blocked", "Red", "In Progress"))
            for _ in range(missing):
                objectives.append(_make("missing", "Missing", "In Progress"))

            payload = {
                "schema_version": 1,
                "team": {"id": team_id, "name": team_name, "business_unit": business_unit},
                "week": week,
                "totals": {
                    "objectives": total,
                    "delivery_rate": round(done / total, 4) if total else 0.0,
                    "done": done,
                    "spillover_on_track": on_track,
                    "spillover_at_risk": at_risk,
                    "spillover_blocked": blocked,
                    "missing": missing,
                },
                "objectives": objectives,
            }
            out = root / team_id / f"{iso_year}-W{iso_week:02d}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"wrote {out}")


if __name__ == "__main__":
    generate()
