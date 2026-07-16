from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from flow_metrics import (  # noqa: E402
    CONTRACT_VERSION,
    UNIT_LEAD_TIME,
    UNIT_REVIEW,
    DataToolsFlowMetricsProvider,
    DemoFlowMetricsProvider,
    FlowMetricsError,
    FlowScope,
    FlowWindow,
    aggregate_flow_blocks,
)


def _window(week: int = 23) -> FlowWindow:
    return FlowWindow(
        iso_year=2026,
        iso_week=week,
        from_date="2026-06-01",
        to_date="2026-06-07",
        days=7,
    )


class FlowScopeTest(unittest.TestCase):
    def test_rejects_unknown_level(self):
        with self.assertRaises(ValueError):
            FlowScope(level="squad", ref="x")

    def test_health_defaults_when_no_hints(self):
        self.assertAlmostEqual(FlowScope("team", "t").health, 0.3)

    def test_health_scales_with_outcomes(self):
        healthy = FlowScope("team", "t", outcomes=("done", "done")).health
        struggling = FlowScope("team", "t", outcomes=("blocked", "blocked")).health
        self.assertLess(healthy, struggling)
        self.assertEqual(healthy, 0.0)
        self.assertEqual(struggling, 1.0)


class DemoContractTest(unittest.TestCase):
    def setUp(self):
        self.provider = DemoFlowMetricsProvider()

    def test_block_has_contract_shape(self):
        block = self.provider.fetch(FlowScope("objective", "MABC-2606-01"), _window())
        self.assertEqual(block["contract_version"], CONTRACT_VERSION)
        self.assertEqual(block["source"], "faked")
        self.assertEqual(block["scope"]["level"], "objective")
        self.assertEqual(block["window"]["days"], 7)
        for key in ("coverage", "dora", "review", "trends"):
            self.assertIn(key, block)

    def test_units_are_explicit_and_stable(self):
        block = self.provider.fetch(FlowScope("team", "eta"), _window())
        self.assertEqual(block["dora"]["lead_time"]["unit"], UNIT_LEAD_TIME)
        self.assertEqual(block["review"]["review_to_approved"]["unit"], UNIT_REVIEW)
        self.assertEqual(block["review"]["time_to_first_review"]["unit"], UNIT_REVIEW)

    def test_reliability_metrics_absent_from_fetch(self):
        # CFR/MTTR are trailing-window team metrics composed via reliability(),
        # not produced by a single-week fetch at any scope.
        for level in ("team", "engineer", "objective"):
            dora = self.provider.fetch(FlowScope(level, "x", outcomes=("at_risk",)), _window())["dora"]
            self.assertIsNone(dora["change_failure_rate"])
            self.assertIsNone(dora["mttr"])

    def test_review_percentiles_are_ordered(self):
        block = self.provider.fetch(FlowScope("engineer", "athornton"), _window())
        m = block["review"]["review_to_approved"]
        self.assertLessEqual(m["p50"], m["p85"])
        self.assertLessEqual(m["p85"], m["p99"])

    def test_cross_metric_relationships_hold(self):
        # First review and rework are legs of review->approved; lead time (a
        # PR's whole create->deploy journey) dominates review time.
        for outcome in ("done", "on_track", "at_risk", "blocked", "missing"):
            b = self.provider.fetch(FlowScope("objective", "K", outcomes=(outcome,)), _window())
            ttfr = b["review"]["time_to_first_review"]["p50"]
            approve = b["review"]["review_to_approved"]["p50"]
            rework = b["review"]["rework_time"]["p50"]
            lead_hours = b["dora"]["lead_time"]["p50"] / 60
            self.assertLessEqual(ttfr, approve, outcome)
            self.assertLessEqual(rework, approve, outcome)
            self.assertGreaterEqual(lead_hours, approve, outcome)

    def test_health_bias_shifts_and_clamps(self):
        self.assertGreater(FlowScope("team", "t", outcomes=("done",), health_bias=0.4).health, 0.0)
        self.assertEqual(FlowScope("team", "t", health_bias=5.0).health, 1.0)
        self.assertEqual(FlowScope("team", "t", outcomes=("done",), health_bias=-5.0).health, 0.0)

    def test_attribution_coverage_only_at_objective_scope(self):
        obj = self.provider.fetch(FlowScope("objective", "MABC-2606-01"), _window())
        team = self.provider.fetch(FlowScope("team", "eta"), _window())
        self.assertIsNotNone(obj["coverage"]["prs_linked_to_objective"])
        self.assertIsNone(team["coverage"]["prs_linked_to_objective"])

    def test_coverage_measured_not_greater_than_total(self):
        block = self.provider.fetch(FlowScope("team", "eta"), _window())
        cov = block["coverage"]
        self.assertLessEqual(cov["prs_measured"], cov["prs_total"])

    def test_deterministic_for_same_scope_and_window(self):
        scope, window = FlowScope("team", "eta"), _window()
        self.assertEqual(self.provider.fetch(scope, window), self.provider.fetch(scope, window))

    def test_varies_by_window(self):
        scope = FlowScope("team", "eta")
        self.assertNotEqual(self.provider.fetch(scope, _window(23)), self.provider.fetch(scope, _window(24)))

    def test_struggling_scope_has_slower_reviews(self):
        window = _window()
        healthy = self.provider.fetch(FlowScope("team", "eta", outcomes=("done", "done", "done")), window)
        struggling = self.provider.fetch(FlowScope("team", "eta", outcomes=("blocked", "blocked", "blocked")), window)
        self.assertLess(
            healthy["review"]["review_to_approved"]["p50"],
            struggling["review"]["review_to_approved"]["p50"],
        )
        self.assertGreater(
            healthy["dora"]["deployment_frequency"]["weekly_average"],
            struggling["dora"]["deployment_frequency"]["weekly_average"],
        )


class AggregateFlowTest(unittest.TestCase):
    def setUp(self):
        self.provider = DemoFlowMetricsProvider()
        self.window = _window()

    def _obj(self, key, outcome):
        return self.provider.fetch(FlowScope("objective", key, outcomes=(outcome,)), self.window)

    def test_empty_children_raises(self):
        with self.assertRaises(FlowMetricsError):
            aggregate_flow_blocks([], scope=FlowScope("engineer", "x"), window=self.window, source="faked")

    def test_single_key_engineer_equals_its_objective(self):
        # The core coherence property: one owned key -> identical review timings.
        obj = self._obj("MABC-2606-02", "at_risk")
        eng = aggregate_flow_blocks(
            [obj], scope=FlowScope("engineer", "aowner"), window=self.window, source="faked"
        )
        for name in ("time_to_first_review", "review_to_approved", "rework_time"):
            self.assertEqual(eng["review"][name]["p50"], obj["review"][name]["p50"])
        self.assertEqual(eng["dora"]["lead_time"]["p50"], obj["dora"]["lead_time"]["p50"])

    def test_pr_counts_and_deploys_sum(self):
        children = [self._obj("MABC-2606-01", "done"), self._obj("MABC-2606-02", "blocked")]
        agg = aggregate_flow_blocks(
            children, scope=FlowScope("team", "t"), window=self.window, source="faked"
        )
        self.assertEqual(
            agg["coverage"]["prs_total"], sum(c["coverage"]["prs_total"] for c in children)
        )
        self.assertEqual(
            agg["dora"]["deployment_frequency"]["total"],
            sum(c["dora"]["deployment_frequency"]["total"] for c in children),
        )

    def test_percentiles_stay_ordered_after_aggregation(self):
        children = [self._obj(f"MABC-2606-0{i}", o) for i, o in enumerate(("done", "at_risk", "blocked"), 1)]
        agg = aggregate_flow_blocks(
            children, scope=FlowScope("engineer", "e"), window=self.window, source="faked"
        )
        m = agg["review"]["review_to_approved"]
        self.assertLessEqual(m["p50"], m["p85"])
        self.assertLessEqual(m["p85"], m["p99"])

    def test_attribution_coverage_none_above_objective_scope(self):
        children = [self._obj("MABC-2606-01", "done")]
        eng = aggregate_flow_blocks(
            children, scope=FlowScope("engineer", "e"), window=self.window, source="faked"
        )
        self.assertIsNone(eng["coverage"]["prs_linked_to_objective"])

    def test_reliability_stays_none_through_aggregation(self):
        children = [self._obj("MABC-2606-01", "blocked")]
        agg = aggregate_flow_blocks(
            children, scope=FlowScope("team", "t"), window=self.window, source="faked"
        )
        self.assertIsNone(agg["dora"]["change_failure_rate"])
        self.assertIsNone(agg["dora"]["mttr"])


class ReliabilityTest(unittest.TestCase):
    def setUp(self):
        self.provider = DemoFlowMetricsProvider()

    def _weeks(self, health, deploys, n=4):
        return [(f"2026-W{20 + i:02d}", health, deploys) for i in range(n)]

    def test_cfr_value_equals_failed_over_total(self):
        # The invariant the report violated: rate and counts can never disagree.
        for health in (0.0, 0.3, 0.6, 1.0):
            cfr, _ = self.provider.reliability("eta", self._weeks(health, 12))
            self.assertEqual(cfr["value"], round(cfr["deploys_failed"] / cfr["deploys_total"], 4))
            self.assertLessEqual(cfr["deploys_failed"], cfr["deploys_total"])

    def test_window_days_reflects_trailing_weeks(self):
        cfr, mttr = self.provider.reliability("eta", self._weeks(0.5, 10, n=4))
        self.assertEqual(cfr["window_days"], 28)
        self.assertEqual(mttr["window_days"], 28)

    def test_struggling_team_has_higher_cfr_and_slower_mttr(self):
        healthy_cfr, healthy_mttr = self.provider.reliability("t", self._weeks(0.0, 40))
        rough_cfr, rough_mttr = self.provider.reliability("t", self._weeks(1.0, 40))
        self.assertLess(healthy_cfr["value"], rough_cfr["value"])
        self.assertGreater(rough_mttr["incidents"], healthy_mttr["incidents"])

    def test_same_week_events_stable_across_overlapping_windows(self):
        # A week's failures/incidents are identical whether seen from a window
        # ending at W23 or W24 — trailing sums stay consistent.
        w = [("2026-W22", 0.5, 15), ("2026-W23", 0.5, 15)]
        first, _ = self.provider.reliability("t", w[:1])
        both, _ = self.provider.reliability("t", w)
        # the W22 contribution is unchanged when W23 is appended
        self.assertEqual(both["deploys_total"] - first["deploys_total"], 15)

    def test_quiet_window_has_null_percentiles(self):
        # A healthy team with few deploys can go a whole window incident-free.
        found = False
        for wk in range(6, 30):
            _, mttr = self.provider.reliability("calm", [(f"2026-W{wk:02d}", 0.0, 8)])
            if mttr["incidents"] == 0:
                found = True
                self.assertIsNone(mttr["p50"])
                self.assertIsNone(mttr["p90"])
        self.assertTrue(found)


class DataToolsStubTest(unittest.TestCase):
    def test_fetch_raises_until_wired(self):
        provider = DataToolsFlowMetricsProvider("https://godebug.example")
        with self.assertRaises(FlowMetricsError):
            provider.fetch(FlowScope("team", "eta"), _window())


if __name__ == "__main__":
    unittest.main()
