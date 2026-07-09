# Engineering flow metrics

DORA + code-review metrics (deploy frequency, lead time, time-to-first-review,
review→approved, rework) attached to the weekly rollup at three scopes:
**team → engineer → objective**, all laddering through the shared Jira key.

## Status: illustrative, not measured

> The flow metrics shown in the dashboard are **illustrative data, not
> measured**. They need a real source (the engineering event store / GitHub,
> via [`data-tools`](https://github.com/) goDebug) and the provider integration
> step before they can be trusted — see `DataToolsFlowMetricsProvider` in
> `scripts/flow_metrics.py`. Everything else in the rollup (objectives, status,
> progress, blockers, email) reflects the actual data.

Today the only producer is `DemoFlowMetricsProvider`: deterministic, seeded per
(scope, window), biased by each objective's weekly outcome so a struggling
epic reads worse. It is coherent — a single-key engineer equals their epic; a
team is the median across its engineers — but the numbers are invented.

This note is deliberately kept out of the dashboard UI; the dashboard renders
the metrics without a provenance badge. The caveat lives here (and in the code)
so the reader of this repo knows what is real and what is pending.

## The seam (so going live is a drop-in)

- **Data contract** — `build_flow_block()` produces one block shape, with
  explicit units, percentile objects, and `null` (not `0`) for the not-yet-
  wired change-failure-rate and MTTR. Field names/units mirror the goDebug
  service so the mapping is thin.
- **Producer port** — `FlowMetricsProvider.fetch(scope, window)`. Swapping the
  provider is the only change needed; no renderer or snapshot-shape change.
- **Identity contract** — teams by `jira_abbrev` / `github_team_slug` / repos,
  engineers by GitHub login, objectives by epic key. The demo fills real-shaped
  keys with invented values.

## To make it real

1. **Wire a source.** `DataToolsFlowMetricsProvider.fetch()` calls the goDebug
   REST API:
   - team scope → `GET /team/api/dora-metrics` + `/delivery-metrics`
     with `team=<jira_abbrev>&repos=<repos>&days=<n>`
   - engineer scope → the same, plus `&member=<github_login>`
   - objective scope → needs PR→epic attribution (Jira key in branch/PR/commit),
     which does not exist upstream yet; keep `coverage.prs_linked_to_objective`
     honest until it does.
2. **Normalise** the API response through `build_flow_block()` (field mapping is
   recorded in the provider docstring).
3. **Switch the producer** behind a flag mirroring `--jira-source`
   (e.g. `--flow-source demo|data-tools`).

Change-failure-rate and MTTR stay `null` until the incident feed is added
upstream.

## Optional display

The dashboard flow section is a single `#team-flow-block`; the rest of the page
renders without it. It can be put behind a config flag once the real feed is
extracted and presented, so teams without a wired source simply don't show it.
