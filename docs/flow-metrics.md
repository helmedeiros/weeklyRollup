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

### Change-failure rate and MTTR — trailing-window reliability

Failures and incidents are *rare events*: over a single week off ~10 deploys,
CFR is just binary noise (0% or 12.5%) and MTTR often has no sample. That is why
DORA measures both over a longer window. Here they are **team-scoped** and
computed over a **trailing 4-week (~28-day) window** (`RELIABILITY_SCOPES` /
`RELIABILITY_WEEKS`), which makes them stable, meaningful, and trend-bearing:

- **Change-failure rate** — `{ unit: "ratio", value, deploys_total, deploys_failed, window_days }`.
  **Counts are the source of truth**: `value == deploys_failed / deploys_total`,
  so the rate and the counts can never disagree (the "6.2% but 0 of 8" bug).
  `null` value only if there were no deploys across the whole window.
- **MTTR** — `{ unit: "minutes", p50, p90, incidents, window_days }`. Median and
  p90 of incident-recovery times over the window. An incident-free window is
  `incidents: 0` with null percentiles — "no incidents", not "not measured".

Both are **team scope only** (`null` at engineer/objective — incidents map to
neither a person nor an epic) and do **not** ladder through the key. The demo
accumulates each week's deploys + incidents (seeded per team-week, so a week's
events are stable across overlapping windows) and reads the last four weeks
together. Per-week failure probability and incident rate rise with the team's
weekly outcome health, so CFR and MTTR **follow the goal trajectory with a
realistic lag** — a team sliding toward *blocked* sees its reliability degrade
over the following weeks, and recover as it climbs back.

To make them real, the event store needs the incident pipeline: deployment
events tagged with a failure/rollback signal (→ CFR) and `event_type='incident'`
open→resolved timestamps (→ MTTR), queried with `days≈28`. See
`DataToolsFlowMetricsProvider`.

## Optional display

The dashboard flow section is a single `#team-flow-block`; the rest of the page
renders without it. It can be put behind a config flag once the real feed is
extracted and presented, so teams without a wired source simply don't show it.
