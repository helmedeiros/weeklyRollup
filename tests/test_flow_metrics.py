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

    def test_unavailable_metrics_are_none_not_zero(self):
        block = self.provider.fetch(FlowScope("team", "eta"), _window())
        self.assertIsNone(block["dora"]["change_failure_rate"])
        self.assertIsNone(block["dora"]["mttr"])

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


class DataToolsStubTest(unittest.TestCase):
    def test_fetch_raises_until_wired(self):
        provider = DataToolsFlowMetricsProvider("https://godebug.example")
        with self.assertRaises(FlowMetricsError):
            provider.fetch(FlowScope("team", "eta"), _window())


if __name__ == "__main__":
    unittest.main()
