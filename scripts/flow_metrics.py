"""Engineering-flow metrics: contract, port, and providers.

Hexagonal seam for DORA + code-review metrics attached to the weekly rollup
at three scopes: ``team`` / ``engineer`` / ``objective``.

Design contracts (see docs for the long form):

1. **Data contract** — :func:`build_flow_block` returns the one block shape
   that snapshots persist and the dashboard renders. Field names and units
   mirror what the ``data-tools`` goDebug service already returns so the
   future adapter is a thin mapping, not a translation. Every metric carries
   an explicit ``unit``; percentiles are objects (p50/p85/p99, or p50/p99 for
   lead time); unavailable metrics (change-failure-rate, MTTR) are ``None``,
   never a fake ``0``.

2. **Producer contract** — :class:`FlowMetricsProvider` is the PORT. Both the
   fake and the future live adapter implement ``fetch(scope, window) -> block``.
   Swapping providers is the only change required to go live; no renderer or
   snapshot-shape change.

3. **Identity contract** — :class:`FlowScope` keys work the same way the live
   feed will resolve them: teams by ``jira_abbrev`` / ``github_team_slug`` /
   repos, engineers by GitHub ``login`` (not display name), objectives by epic
   key (plus future linked PR numbers). The demo fills real-*shaped* keys with
   invented values so the eventual swap is lossless.

Providers:

- :class:`DemoFlowMetricsProvider` — deterministic fake used today. Metrics are
  seeded per (scope, window) and biased by the scope's outcome hints, so a
  struggling team/engineer/objective shows worse flow (that is the whole point:
  surfacing bottlenecks).
- :class:`DataToolsFlowMetricsProvider` — prepared stub for the future
  integration against the goDebug REST API
  (``GET /team/api/dora-metrics`` + ``GET /team/api/delivery-metrics``).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


CONTRACT_VERSION = 1

VALID_LEVELS = ("team", "engineer", "objective")

# Units, centralised so the fake and the live adapter cannot drift apart.
UNIT_LEAD_TIME = "minutes"          # data-tools returns lead time in calendar minutes
UNIT_REVIEW = "business_hours"      # data-tools review/rework times are Berlin business hours
UNIT_DEPLOY_FREQ = "deploys/week"
UNIT_RATIO = "ratio"                # change-failure rate: 0.0 .. 1.0
UNIT_MTTR = "minutes"               # incident open -> resolved, calendar minutes

# Change-failure rate and MTTR are team/service reliability metrics measured
# over a trailing multi-week window (failures and incidents are rare events —
# a single week is just noise). They live at team scope only.
RELIABILITY_SCOPES = ("team",)
RELIABILITY_WEEKS = 4  # trailing window length, in weeks

# How much each weekly outcome degrades flow health, 0.0 (best) .. 1.0 (worst).
_OUTCOME_HEALTH = {
    "done": 0.0,
    "on_track": 0.2,
    "at_risk": 0.6,
    "missing": 0.8,
    "blocked": 1.0,
}


@dataclass(frozen=True)
class FlowWindow:
    """The measurement window a flow block covers."""

    iso_year: int
    iso_week: int
    from_date: str
    to_date: str
    days: int

    @property
    def key(self) -> str:
        return f"{self.iso_year}-W{self.iso_week:02d}"


@dataclass(frozen=True)
class FlowScope:
    """Identity of the thing being measured.

    ``outcomes`` are demo-only bias hints (the weekly outcomes of the
    objectives inside this scope). Live adapters ignore them; the fake uses
    them to make numbers tell a coherent bottleneck story.
    """

    level: str
    ref: str
    display: str | None = None
    outcomes: tuple[str, ...] = field(default_factory=tuple)
    health_bias: float = 0.0  # demo-only: a team's persistent performance signature

    def __post_init__(self) -> None:
        if self.level not in VALID_LEVELS:
            raise ValueError(f"Unknown flow scope level: {self.level!r}")

    @property
    def health(self) -> float:
        """0.0 = healthy, 1.0 = maximally struggling."""
        base = 0.3 if not self.outcomes else (
            sum(_OUTCOME_HEALTH.get(o, 0.3) for o in self.outcomes) / len(self.outcomes)
        )
        return max(0.0, min(1.0, base + self.health_bias))


def build_flow_block(
    *,
    scope: FlowScope,
    window: FlowWindow,
    source: str,
    coverage: dict[str, Any],
    dora: dict[str, Any],
    review: dict[str, Any],
    trends: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the versioned flow-metrics block (the data contract).

    Both providers funnel through here so the persisted/rendered shape is
    guaranteed identical whatever the source.
    """
    return {
        "contract_version": CONTRACT_VERSION,
        "source": source,
        "scope": {"level": scope.level, "ref": scope.ref, "display": scope.display},
        "window": {
            "from": window.from_date,
            "to": window.to_date,
            "days": window.days,
        },
        "coverage": coverage,
        "dora": dora,
        "review": review,
        "trends": trends if trends is not None else {},
    }


def _median(values: list[float]) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    """Linear-interpolated percentile of an already-sorted list."""
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * (p / 100)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo))


def _median_pcts(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    """Median each percentile across child metric blocks (median-of-medians)."""
    unit = metrics[0]["unit"]
    out: dict[str, Any] = {"unit": unit}
    for p in ("p50", "p85", "p99"):
        if p in metrics[0]:
            out[p] = round(_median([m[p] for m in metrics]) or 0, 1)
    return out


def aggregate_flow_blocks(
    children: list[dict[str, Any]],
    *,
    scope: FlowScope,
    window: FlowWindow,
    source: str,
) -> dict[str, Any]:
    """Roll child blocks up into one, laddering through the shared Jira key.

    Everything ties back to the same epic/story identifier: an engineer's
    block is the median across the keys they own; a team's is the median
    across its engineers. Percentiles use median-of-medians (matching
    data-tools); PR volume and deploy counts sum. A single-key engineer
    therefore reads *identically* to that objective — no drift.
    """
    if not children:
        raise FlowMetricsError("aggregate_flow_blocks needs at least one child block")

    review = {
        name: _median_pcts([c["review"][name] for c in children])
        for name in ("time_to_first_review", "review_to_approved", "rework_time")
    }
    review["pr_count"] = sum(c["review"]["pr_count"] for c in children)

    lead = [c["dora"]["lead_time"] for c in children]
    lead_time = {
        "unit": lead[0]["unit"],
        "p50": round(_median([m["p50"] for m in lead]) or 0),
        "p99": round(_median([m["p99"] for m in lead]) or 0),
    }
    deploys = [c["dora"]["deployment_frequency"] for c in children]
    total_deploys = sum(m["total"] for m in deploys)
    deploy_freq = {
        "unit": deploys[0]["unit"],
        "total": total_deploys,
        "weekly_average": round(total_deploys / (window.days / 7), 1) if window.days else 0.0,
    }

    is_obj = scope.level == "objective"
    coverage = {
        "prs_total": sum(c["coverage"]["prs_total"] for c in children),
        "prs_measured": sum(c["coverage"]["prs_measured"] for c in children),
        "prs_linked_to_objective": (
            sum(c["coverage"]["prs_linked_to_objective"] or 0 for c in children) if is_obj else None
        ),
    }

    # Reliability metrics (CFR + MTTR) are trailing-window and team-scoped; they
    # do not ladder through the key, so aggregation leaves them None. A team
    # block gets them injected from FlowMetricsProvider.reliability().
    return build_flow_block(
        scope=scope,
        window=window,
        source=source,
        coverage=coverage,
        dora={
            "deployment_frequency": deploy_freq,
            "lead_time": lead_time,
            "change_failure_rate": None,
            "mttr": None,
        },
        review=review,
    )


class FlowMetricsError(RuntimeError):
    """Raised when a flow-metrics provider fails."""


class FlowMetricsProvider:
    """Port: supplies an engineering-flow block for a scope + window."""

    source = "unknown"

    def fetch(self, scope: FlowScope, window: FlowWindow) -> dict[str, Any]:
        raise NotImplementedError


def _lerp(healthy: float, struggling: float, health: float) -> float:
    return healthy + (struggling - healthy) * health


class DemoFlowMetricsProvider(FlowMetricsProvider):
    """Deterministic fake. Same (scope, window) always yields the same block."""

    source = "faked"

    # PR volume per scope level: (healthy, struggling) totals in the window.
    _PR_TOTALS = {
        "objective": (7, 2),
        "engineer": (16, 4),
        "team": (44, 12),
    }
    # Deploy frequency per scope level: (healthy, struggling) deploys/week.
    # Objective atoms stay small because engineer/team totals sum from them.
    _DEPLOY_FREQ = {
        "objective": (2.2, 0.4),
        "engineer": (5.0, 1.2),
        "team": (14.0, 3.5),
    }

    def fetch(self, scope: FlowScope, window: FlowWindow) -> dict[str, Any]:
        rng = random.Random(f"flow|{self.source}|{scope.level}|{scope.ref}|{window.key}")
        h = scope.health

        # --- code-review metrics (business hours), tied by real relationships ---
        # A PR is created, waits for a first review, goes through rework, then is
        # approved. So first-review and rework are fractions of the full
        # ready->approved time, never larger than it.
        approve_p50 = _lerp(4.0, 46.0, h) * rng.uniform(0.9, 1.1)
        approve = self._pcts(approve_p50, rng, UNIT_REVIEW)
        ttfr = self._pcts(approve_p50 * rng.uniform(0.3, 0.6), rng, UNIT_REVIEW)
        rework = self._pcts(approve_p50 * rng.uniform(0.25, 0.55), rng, UNIT_REVIEW)

        # --- DORA ---
        # Lead time = PR created -> deployed, so it always dominates review time
        # (review is a leg of it) plus a deploy-pipeline wait that grows with
        # struggle.
        lead_hours = approve_p50 * rng.uniform(1.6, 3.2) + _lerp(2.0, 20.0, h)
        lead_p50 = round(lead_hours * 60)
        lead_time = {
            "unit": UNIT_LEAD_TIME,
            "p50": lead_p50,
            "p99": round(lead_p50 * rng.uniform(2.6, 3.4)),
        }
        deploy_hi, deploy_lo = self._DEPLOY_FREQ.get(scope.level, (6.5, 1.5))
        weekly_avg = round(_lerp(deploy_hi, deploy_lo, h) * rng.uniform(0.85, 1.15), 1)
        deploy_total = max(0, round(weekly_avg * (window.days / 7)))
        deploy_freq = {
            "unit": UNIT_DEPLOY_FREQ,
            "total": deploy_total,
            "weekly_average": weekly_avg,
        }

        # --- coverage / PR volume ---
        healthy_total, struggling_total = self._PR_TOTALS.get(scope.level, (10, 3))
        prs_total = max(1, round(_lerp(healthy_total, struggling_total, h) * rng.uniform(0.85, 1.15)))
        prs_measured = max(0, prs_total - rng.randint(0, 1))
        coverage = {
            "prs_total": prs_total,
            "prs_measured": prs_measured,
            # Attribution coverage only exists at objective scope; the demo
            # fakes the link, so every counted PR is "linked".
            "prs_linked_to_objective": prs_total if scope.level == "objective" else None,
        }

        return build_flow_block(
            scope=scope,
            window=window,
            source=self.source,
            coverage=coverage,
            dora={
                "deployment_frequency": deploy_freq,
                "lead_time": lead_time,
                # Reliability metrics are trailing-window and team-scoped; the
                # demo composes them via reliability() and injects at team scope.
                "change_failure_rate": None,
                "mttr": None,
            },
            review={
                "time_to_first_review": ttfr,
                "review_to_approved": approve,
                "rework_time": rework,
                "pr_count": prs_measured,
            },
        )

    @staticmethod
    def _pcts(p50: float, rng: random.Random, unit: str) -> dict[str, Any]:
        p50 = round(max(0.1, p50 * rng.uniform(0.9, 1.1)), 1)
        return {
            "unit": unit,
            "p50": p50,
            "p85": round(p50 * rng.uniform(1.6, 2.0), 1),
            "p99": round(p50 * rng.uniform(2.8, 3.6), 1),
        }

    def reliability(
        self,
        team_ref: str,
        weeks: list[tuple[str, float, int]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Trailing-window change-failure rate + MTTR for a team.

        ``weeks`` is a chronological list of ``(week_key, health, deploys)`` for
        the trailing window (most recent last). Per-week failure and incident
        events are seeded by ``(team_ref, week_key)`` so a given week's events
        are identical no matter which overlapping window observes them.

        Counts are the source of truth: ``value == deploys_failed /
        deploys_total`` exactly, so the rate and the counts can never disagree.
        """
        total_deploys = 0
        total_failed = 0
        durations: list[int] = []
        for week_key, health, deploys in weeks:
            rng = random.Random(f"reliability|{team_ref}|{week_key}")
            fail_prob = _lerp(0.02, 0.30, health)
            total_deploys += deploys
            total_failed += sum(1 for _ in range(deploys) if rng.random() < fail_prob)
            n_incidents = max(0, round(_lerp(0.15, 2.2, health) + rng.uniform(-0.5, 0.6)))
            durations += [
                round(_lerp(20.0, 240.0, health) * rng.uniform(0.6, 1.6))
                for _ in range(n_incidents)
            ]

        window_days = 7 * len(weeks)
        change_failure_rate = {
            "unit": UNIT_RATIO,
            "window_days": window_days,
            "value": round(total_failed / total_deploys, 4) if total_deploys else None,
            "deploys_total": total_deploys,
            "deploys_failed": total_failed,
        }
        durations.sort()
        mttr = {
            "unit": UNIT_MTTR,
            "window_days": window_days,
            "p50": _percentile(durations, 50),
            "p90": _percentile(durations, 90),
            "incidents": len(durations),
        }
        return change_failure_rate, mttr


class DataToolsFlowMetricsProvider(FlowMetricsProvider):
    """Prepared stub for the future live integration (not wired yet).

    When we decide to go live, implement :meth:`fetch` by calling the goDebug
    REST API and normalising into :func:`build_flow_block`:

    - team scope   -> ``GET /team/api/dora-metrics?team=<jira_abbrev>&repos=<repos>&days=<n>``
                      and ``GET /team/api/delivery-metrics?team=<jira_abbrev>&repos=<repos>&days=<n>``
    - engineer     -> the same endpoints with ``&member=<github_login>``
    - objective    -> requires PR->epic attribution (does not exist upstream yet);
                      leave ``coverage.prs_linked_to_objective`` honest until it does.

    Field mapping (data-tools -> contract):
      deployment_frequency.{total, weekly_average}      -> dora.deployment_frequency
      lead_time.{p50, p99} (minutes)                    -> dora.lead_time
      delivery.review_time.{p50, p85, p99} (biz hours)  -> review.review_to_approved
      delivery.rework_time.{...}                        -> review.rework_time
      (first-reviewer-action timing)                    -> review.time_to_first_review

    Change-failure rate and MTTR are team-scoped reliability metrics over a
    trailing ~30-day window (RELIABILITY_SCOPES / RELIABILITY_WEEKS), fed by the
    incident pipeline in the event store (event_type='deployment' with a
    failure/rollback signal, and event_type='incident' open->resolved times).
    Call the API with days~=28 and normalise:
      failed_deploys / total_deploys (window)           -> dora.change_failure_rate
        {value, deploys_total, deploys_failed, window_days}; value == failed/total
      p50/p90(incident resolved - opened) (window)      -> dora.mttr
        {p50, p90, incidents, window_days}; incidents==0 -> null percentiles
    Both are null at engineer/objective scope.
    """

    source = "data-tools"

    def __init__(self, base_url: str, *, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def fetch(self, scope: FlowScope, window: FlowWindow) -> dict[str, Any]:
        raise FlowMetricsError(
            "DataToolsFlowMetricsProvider is not wired yet. Map (scope, window) "
            "to the goDebug /team/api/dora-metrics and /team/api/delivery-metrics "
            "endpoints, then normalise via build_flow_block(). See class docstring."
        )
