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

    def __post_init__(self) -> None:
        if self.level not in VALID_LEVELS:
            raise ValueError(f"Unknown flow scope level: {self.level!r}")

    @property
    def health(self) -> float:
        """0.0 = healthy, 1.0 = maximally struggling."""
        if not self.outcomes:
            return 0.3
        return sum(_OUTCOME_HEALTH.get(o, 0.3) for o in self.outcomes) / len(self.outcomes)


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

    def fetch(self, scope: FlowScope, window: FlowWindow) -> dict[str, Any]:
        rng = random.Random(f"flow|{self.source}|{scope.level}|{scope.ref}|{window.key}")
        h = scope.health

        # --- code-review metrics (business hours) ---
        ttfr = self._pcts(_lerp(2.0, 22.0, h), rng, UNIT_REVIEW)
        approve = self._pcts(_lerp(4.0, 46.0, h), rng, UNIT_REVIEW)
        rework = self._pcts(_lerp(1.0, 16.0, h), rng, UNIT_REVIEW)

        # --- DORA ---
        lead_p50 = round(_lerp(480.0, 6800.0, h) * rng.uniform(0.9, 1.1))
        lead_time = {
            "unit": UNIT_LEAD_TIME,
            "p50": lead_p50,
            "p99": round(lead_p50 * rng.uniform(2.8, 3.6)),
        }
        weekly_avg = round(_lerp(6.5, 1.5, h) * rng.uniform(0.85, 1.15), 1)
        deploy_freq = {
            "unit": UNIT_DEPLOY_FREQ,
            "total": max(0, round(weekly_avg * (window.days / 7))),
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
                # Not wired in data-tools yet -> explicitly absent, not zero.
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
      change-failure-rate / MTTR                        -> None until the incident pipeline lands
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
