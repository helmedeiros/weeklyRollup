from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from aggregate_snapshots import build_aggregate  # noqa: E402


def snapshot(team_id: str, name: str, business_unit: str, buckets: tuple[int, int, int, int, int]) -> dict:
    done, on_track, at_risk, blocked, missing = buckets
    total = sum(buckets)
    return {
        "team": {"id": team_id, "name": name, "business_unit": business_unit},
        "week": {"iso_year": 2026, "iso_week": 27, "target_date": "2026-06-30", "month_label": "mission-june-2026"},
        "totals": {
            "missions": total,
            "delivery_rate": round(done / total, 4) if total else 0.0,
            "done": done,
            "spillover_on_track": on_track,
            "spillover_at_risk": at_risk,
            "spillover_blocked": blocked,
            "missing": missing,
        },
        "missions": [],
    }


class AggregateSnapshotsTest(unittest.TestCase):
    def test_totals_sum_across_teams(self):
        aggregate = build_aggregate([
            snapshot("t-a", "Team A", "B2C", (5, 0, 0, 0, 0)),
            snapshot("t-b", "Team B", "B2C", (2, 1, 1, 0, 0)),
            snapshot("t-c", "Team C", "Platform", (3, 0, 0, 1, 0)),
        ])
        totals = aggregate["totals"]
        self.assertEqual(totals["teams"], 3)
        self.assertEqual(totals["missions"], 13)
        self.assertEqual(totals["done"], 10)
        self.assertEqual(totals["spillover_at_risk"], 1)
        self.assertEqual(totals["spillover_blocked"], 1)
        self.assertAlmostEqual(totals["delivery_rate"], 10 / 13, places=4)

    def test_business_units_grouped_and_sorted(self):
        aggregate = build_aggregate([
            snapshot("t-a", "Team A", "B2C", (5, 0, 0, 0, 0)),
            snapshot("t-b", "Team B", "Platform", (2, 1, 0, 0, 0)),
            snapshot("t-c", "Team C", "B2C", (0, 0, 0, 0, 2)),
        ])
        by_name = {row["business_unit"]: row for row in aggregate["business_units"]}
        self.assertEqual(by_name["B2C"]["team_count"], 2)
        self.assertEqual(by_name["B2C"]["done"], 5)
        self.assertEqual(by_name["B2C"]["missing"], 2)
        self.assertEqual(by_name["Platform"]["team_count"], 1)

    def test_team_rows_sorted_by_delivery_rate_desc(self):
        aggregate = build_aggregate([
            snapshot("mid", "Middle Team", "B2C", (3, 1, 0, 0, 0)),
            snapshot("full", "Full Team", "B2C", (4, 0, 0, 0, 0)),
            snapshot("low", "Low Team", "B2C", (1, 2, 1, 0, 0)),
        ])
        team_ids = [row["team_id"] for row in aggregate["teams"]]
        self.assertEqual(team_ids, ["full", "mid", "low"])

    def test_unassigned_bu_when_missing(self):
        aggregate = build_aggregate([
            snapshot("x", "Team X", "", (1, 0, 0, 0, 0)),
        ])
        self.assertEqual(aggregate["business_units"][0]["business_unit"], "Unassigned")


if __name__ == "__main__":
    unittest.main()
