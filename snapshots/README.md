# snapshots/

Real weekly snapshots produced by `scripts/run_rollup.py --sheet-source live`
land in this directory. Its content is **gitignored on purpose** — real
snapshots reference internal identifiers and are not committed.

See `../demo-snapshots/` for the tracked, fully synthetic dataset that
feeds the public dashboard.

Layout the runner writes here:

```
snapshots/
  <team-id>/
    <YYYY>-Www.json          # one file per ISO week per team
  _aggregates/               # populated by scripts/aggregate_snapshots.py
    <YYYY>-Www.json
  _dashboards/               # populated by scripts/render_dashboard.py
    <YYYY>-Www.html
```

Each `<YYYY>-Www.json` describes one team at one week: business unit,
totals per bucket (`done` / `spillover_on_track` / `spillover_at_risk` /
`spillover_blocked` / `missing`), delivery rate, and every objective's
identity + parsed status + Jira status + due-date state + hygiene flags.

The bucket classifier lives in `scripts/run_rollup.py::_bucket_for_objective()`
so every downstream reader (aggregator, dashboard, spreadsheets) agrees
on classification.
