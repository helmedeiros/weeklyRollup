"""Generate a fully synthetic team-snapshot dataset for the public dashboard.

Every value here is invented for demonstration. No team names, objective
keys, Leader Engineers, or KPIs mirror any real organisation. Re-run this script
whenever you want to refresh the shape of the demo dataset.

The output layout matches ``snapshots/``: each team gets a JSON file at
``demo-snapshots/<team-id>/<YYYY>-Www.json``.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

DEMO_WEEK = {"iso_year": 2026, "iso_week": 27, "target_date": "2026-06-30", "month_label": "objective-june-2026"}

# Twelve teams across four business units (B2C, B2B, Platform, Coverage).
# Numbers below drive the invented status mix — one team is a clean 100%,
# a couple hover in the 60-80% band, one takes on a blocked objective.
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


def generate() -> None:
    root = Path(__file__).resolve().parent.parent / "demo-snapshots"
    random.seed(1234)  # deterministic file contents
    for team_id, team_name, business_unit, buckets in TEAMS:
        total, done, on_track, at_risk, blocked, missing = buckets
        assert total == sum(buckets[1:]), f"bucket totals mismatch for {team_id}"

        objectives = []
        pool = OBJECTIVE_NAMES[business_unit]
        used_leader_engineers: list[str] = []
        prefix = "M"
        counter = 100
        def _make(bucket: str, objective_status: str, jira_status: str) -> dict:
            nonlocal counter
            counter += 1
            title = pool[counter % len(pool)]
            leader_engineer = random.choice(LEADER_ENGINEER_POOL)
            used_leader_engineers.append(leader_engineer)
            key = f"{prefix}{team_id.split('-')[0].upper()[:4]}-{counter}"
            return {
                "key": key,
                "name": title,
                "url": f"https://example.invalid/objectives/{key}",
                "leader_engineer": leader_engineer,
                "status": objective_status,
                "jira_status": jira_status,
                "is_done": bucket == "done",
                "missing_update": bucket == "missing",
                "effective_due_date": "2026-06-30" if bucket in {"done", "spillover_on_track", "spillover_at_risk"} else "2026-07-10",
                "due_date_overdue_days": 0,
                "progress": "100%" if bucket == "done" else f"{random.randint(30, 90)}%",
                "bucket": bucket,
                "hygiene_severity": "info" if bucket == "done" else ("yellow" if bucket in {"spillover_at_risk", "missing"} else "info"),
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
            "week": DEMO_WEEK,
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
        out = root / team_id / f"{DEMO_WEEK['iso_year']}-W{DEMO_WEEK['iso_week']:02d}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {out}")


if __name__ == "__main__":
    generate()
