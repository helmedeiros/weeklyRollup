# demo-snapshots/

Tracked, fully-synthetic dataset that feeds the public dashboard.
Every team name, objective key, Leader Engineer, KPI, and status here is invented
for demonstration; nothing references any real organisation.

The layout mirrors `snapshots/` (which is gitignored):

```
demo-snapshots/
  <team-id>/
    <YYYY>-Www.json
  _aggregates/
    <YYYY>-Www.json
  _dashboards/
    <YYYY>-Www.html
```

The dashboard renderer and aggregator default to reading from this
folder. To render against your real (local) `snapshots/` folder
instead, run them with `--snapshots-dir snapshots`.
