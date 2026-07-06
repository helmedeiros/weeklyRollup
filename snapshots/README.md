# snapshots/

Canonical per-team-per-week JSON snapshots written by
`scripts/run_rollup.py --sheet-source live`.

Layout:

```
snapshots/
  <team-id>/
    <YYYY>-Www.json      # one file per ISO week per team
  _aggregates/           # populated by scripts/aggregate_snapshots.py
    <YYYY>-Www.json
  _dashboards/           # populated by scripts/render_dashboard.py
    <YYYY>-Www.html
```

Each `<YYYY>-Www.json` describes one team at one week: business unit,
totals per bucket (`done` / `spillover_on_track` / `spillover_at_risk` /
`spillover_blocked` / `missing`), delivery rate, and every mission's
identity + parsed status + Jira status + due-date state + hygiene flags.

Reserved directories starting with `_` are for derived artefacts; do
not put team snapshots there.

The bucket rule lives in `scripts/run_rollup.py::_bucket_for_mission()`
so every downstream reader agrees on classification.
