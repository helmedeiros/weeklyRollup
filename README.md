# Mission Weekly Rollup

Weekly mission reporting helper for EM-owned mission updates.

It collects mission Epics from Jira, parses the latest valid DRI weekly update,
prepares the weekly Google Sheet tab, and renders a formatted HTML email with a
plain-text fallback.

## What It Does

- finds Jira Epic missions by monthly label, for example `mission-may-2026`
- reads only Engineering DRI comments for the current weekly window
- parses status, work done, plan, and blockers/risks
- writes a normalized weekly sheet tab
- renders a mission health email from `templates/mission-email.html`
- persists durable run history in a `_Run History` sheet tab
- computes completion, cycle-time, active-age, overdue, and recurring-miss metrics
- marks untouched Jira `To Do` missions as `Not Started` instead of missing
  updates, while warning when Jira still says `To Do` but progress or update
  comments show work has started
- creates copy-pastable email output instead of sending email directly

## Local Setup

Run commands from this folder:

```bash
cd skills/mission-weekly-rollup
```

Create a local team config:

```bash
cp config/example-team.yaml config/<your-team-local>.yaml
python3 scripts/validate_config.py config/<your-team-local>.yaml --expect-team-id <team-id>
```

Do not commit local team configs, generated `output/`, credentials, tokens, or
real Sheet/Drive IDs. They are ignored by `.gitignore`.

For live Jira runs, use any Jira source that can provide the normalized mission
snapshot shape: epics, labels, DRI, due date, status, comments, progress, and
the linked OKR field/property when available. The bundled `--jira-source mcp`
adapter uses the Omio Jira MCP checkout and is recommended when issue
properties or Omio-specific fields are needed. If another Jira connector is
already authenticated, collect the same snapshot shape with that connector and
run the deterministic phase with `--jira-source snapshot`.

## Team Config

Every team config must set `sheet.folder_id` to
`1-TOdt6Er1_EitTIIaalW1vyTMPxRdjcK`. The team spreadsheet must live in that
shared folder. The sheet file name is derived from the team name via
`sheet.file_name_pattern`; if that sheet does not exist in the folder, create it
there, and future runs should resolve the same existing sheet before adding or
replacing the weekly tab.

Important email fields:

```yaml
email:
  from_address: "em@example.com"
  preview_to: "em@example.com"
  to:
    - "mission-report@example.com"
  cc: []
  bcc: []
  greeting: "Hi"
  signoff: "Kind Regards"
  signoff_name: "Engineering Manager"
```

For teams that prefer a shorter close:

```yaml
email:
  greeting: "Hi"
  signoff: "Thanks"
  signoff_name: "Engineering Manager"
```

The linked OKR hygiene mapping stays under `jira.fields.linked_okr`:

```yaml
jira:
  fields:
    linked_okr:
      source: "issue_property"
      property_key: "okr"
      path: "value.parentId"
      field_id: ""
```

## Run The Flow

Preflight guardrail: before any live Jira, Sheet, or email run, validate that
the requested team's config exists and matches the requested team. Do not use
`config/example-team.yaml` or another team's local config for a named team run.

Live run with the bundled Omio Jira MCP adapter. This first collects Jira data
into `data-snapshot-YYYY-MM-DD.json`, then runs the deterministic
parser/renderer from that snapshot:

```bash
python3 scripts/run_rollup.py \
  --config config/<your-team-local>.yaml \
  --expect-team-id <team-id> \
  --date YYYY-MM-DD \
  --jira-source mcp \
  --sheet-source mcp-plan \
  --email-source raw-mime-plan \
  --output-dir output/<team>-week-<N>
```

If `--output-dir` is provided, the runner creates local review artifacts there:

- `rollup-result.json`
- `data-snapshot-YYYY-MM-DD.json`
- `draft-email.html`
- `draft-email.txt`
- `draft-email.eml`
- `sheet-values.json`
- `sheet-mcp-request.json`
- `run-history-values.json`
- `run-history-mcp-request.json`
- `gmail-raw-draft-request.json`

To split the MCP retrieval phase from the deterministic rollup phase:

```bash
python3 scripts/run_rollup.py \
  --config config/<your-team-local>.yaml \
  --expect-team-id <team-id> \
  --date YYYY-MM-DD \
  --jira-source mcp \
  --collect-jira-snapshot-only \
  --output-dir output/<team>-week-<N>

python3 scripts/run_rollup.py \
  --config config/<your-team-local>.yaml \
  --expect-team-id <team-id> \
  --date YYYY-MM-DD \
  --jira-source snapshot \
  --jira-snapshot output/<team>-week-<N>/data-snapshot-YYYY-MM-DD.json \
  --sheet-source mcp-plan \
  --sheet-url <resolved Google Sheet URL> \
  --sheet-tab-gid <current Week N tab sheetId> \
  --email-source raw-mime-plan \
  --output-dir output/<team>-week-<N>
```

If the sheet result is `mcp_plan`, use the generated sheet request to update the
Google Sheet through the Google Drive/Sheets connector: look in `sheet.folder_id`
for the exact team sheet name, create it in that folder if missing, add/clear
the week tab, write values from `A1`, then freeze the header, add a filter, and
auto-size columns. After the weekly tab exists, capture its Google Sheets
`sheetId` from `sheet_list_sheets`; this is the tab `gid`. For existing team
sheets, resolve the spreadsheet URL before the final email draft. On a team's
first run, capture the newly created spreadsheet URL. Rerun the snapshot phase
with `--sheet-url <resolved Google Sheet URL>` and
`--sheet-tab-gid <current Week N tab sheetId>` so the email opens the current
week tab directly, not the first tab or `_Run History`.
If the resolved spreadsheet URL is not known yet, the draft omits the sheet
button instead of linking to the shared Drive folder.

The runner also prepares `_Run History` updates. Use
`run-history-mcp-request.json` to update that tab: read existing history rows,
drop rows with the same `Run ID`, append the current run rows, then write the
merged table back. This keeps reruns idempotent while preserving prior weeks.

## Email Draft

The skill does not store email passwords and does not send email directly. Use
any already-authenticated local or connector route that can create an HTML
draft. If a raw-MIME-capable route is available, use
`gmail-raw-draft-request.json`; if not, open `draft-email.html` and use
`draft-email.txt` as the plain-text fallback.

When `--output-dir` is not provided, the JSON result still includes
`draft_email.subject`, `draft_email.text_body`, and `draft_email.html_body`.

## Metrics

Each run includes a `metrics` object in `rollup-result.json` and mirrors the key
values in `run_summary`. These metrics are computed from the current run plus
the team-level `_Run History` tab:

- completed and active mission counts
- completion rate
- average cycle time for completed missions
- average age for active missions
- active overdue mission count
- recurring missing-update count

The weekly sheet stays human-facing; `_Run History` remains the durable source
for recomputing these metrics later.

## Dry Run

Use fixtures for a deterministic local run:

```bash
python3 scripts/run_rollup.py \
  --config tests/fixtures/team-config.yaml \
  --date 2026-06-05 \
  --jira-source fixture \
  --jira-fixture tests/fixtures/run-jira.json \
  --sheet-source fixture \
  --sheet-fixture tests/fixtures/run-sheet-history.json \
  --email-source none \
  --output-dir output/test-week-23
```

## Tests

```bash
python3 -m unittest discover -s tests
python3 scripts/validate_config.py config/example-team.yaml
```

## Guardrails

- do not commit credentials, tokens, PII, generated outputs, or real local team configs
- do not use plain-text-only draft helpers for formatted HTML email
- do not store email credentials or local auth tokens for this skill
- do not send email directly from this skill
