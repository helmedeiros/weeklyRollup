---
name: objective-weekly-rollup
description: Generate weekly Engineer-Owned Objective rollups from Jira Epic objective updates, write the team sheet, and render a copy-pastable HTML email draft for EM review.
---

# Objective Weekly Rollup

Use this skill when an Engineering Manager asks for the weekly Engineer-Owned
Objective rollup for a team.

## Guardrails

- Do not store email credentials, Jira API credentials, or local auth tokens for
  this skill.
- Do not send email directly from this skill. Render copy-pastable HTML/text
  output and, when requested, a draft request for an already authenticated
  connector/API client that can preserve HTML formatting.
- Do not pull OKR board updates.
- Do not create dashboards, Slack nudges, or monthly review decks.
- Do not add credentials, tokens, PII, or sensitive raw customer data to this repo.
- Do not commit local configs with real team data. `config/delivery_*.yaml`,
  `config/*local*.yaml`, and `output/` must stay ignored.
- Before any Jira, Sheet, or email adapter run, confirm the requested team's
  local config exists, matches the requested team, and passes validation. Never
  fall back to `config/example-team.yaml` or another team's config for a named
  team run.
- Treat team config and the bundled reference/specification docs as the source
  of truth.

## Inputs

The EM must provide a team config matching `config/team-config.schema.json`. The config
must include the Jira board or project, timezone, Jira field IDs, and Google
Sheet target. Email recipients are explicit in `email.to`, `email.cc`, and
`email.bcc`.

Start by copying `config/example-team.yaml` to a local config file and filling in
the team-specific values.

Email tone is configured per team:

- `email.greeting`: opening line, default `Hi`
- `email.signoff`: closing line, default `Kind Regards`
- `email.signoff_name`: sender name shown under the closing line

## Workflow

Run commands from `${CODEX_HOME:-$HOME/.codex}/skills/objective-weekly-rollup`
or from this repository folder: `skills/objective-weekly-rollup`.

1. Locate the requested team's local config and validate it before running
   anything:
   `python3 scripts/validate_config.py config/<team>.yaml --expect-team-id <team-id>`
   If the config is missing, invalid, or for another team, stop and ask for the
   correct config path. The config must include `sheet.folder_id` pointing at
   the Google Drive folder that owns every team's rollup spreadsheet. Runtime
   enforcement of a specific folder id is optional via
   `WEEKLY_ROLLUP_REQUIRED_FOLDER_ID`.
2. Run the orchestrator with any capable Jira source. The normalized Jira data
   must include epics, labels, Leader Engineer, due date, status, comments, progress, and
   the linked OKR field/property when available. The bundled `--jira-source mcp`
   adapter uses the bundled in-tree `jira-mcp/`; use `--jira-source snapshot` when another
   authenticated Jira route has already collected the same snapshot shape:
   `python3 scripts/run_rollup.py --config config/<team>.yaml --expect-team-id <team-id> --date <YYYY-MM-DD> --jira-source mcp --sheet-source mcp-plan --email-source raw-mime-plan --output-dir output/<team>-week-<N>`
   To make the MCP retrieval phase explicit, first run
   `python3 scripts/run_rollup.py --config config/<team>.yaml --expect-team-id <team-id> --date <YYYY-MM-DD> --jira-source mcp --collect-jira-snapshot-only --output-dir output/<team>-week-<N>`,
   then run
   `python3 scripts/run_rollup.py --config config/<team>.yaml --expect-team-id <team-id> --date <YYYY-MM-DD> --jira-source snapshot --jira-snapshot output/<team>-week-<N>/data-snapshot-<YYYY-MM-DD>.json --sheet-source mcp-plan --email-source raw-mime-plan --output-dir output/<team>-week-<N>`.
3. If `sheet_write.status` is `mcp_plan`, execute the generated Google Drive MCP
   request:
   - resolve the team spreadsheet by exact folder/file-name match
   - create the team-named spreadsheet in that folder if it is missing
   - add the target `Week <ISO week>` tab if missing
   - clear the target tab if it exists
   - update values starting at `A1`
   - add a basic filter, freeze the header, and auto-size columns
   - capture the resolved spreadsheet URL and the `sheetId`/`gid` of the
     current `Week <ISO week>` tab; final email output should link to that
     exact weekly tab, not only to the parent folder, the first tab, or
     `_Run History`
4. If `run_history_write.status` is `mcp_plan`, execute the generated
   run-history request:
   - use the same resolved team spreadsheet
   - add `_Run History` if missing
   - read existing history rows
   - remove rows with the same `Run ID`
   - append the current run rows and write the merged table from `A1`
5. Use the rendered email output:
   - If the team sheet already exists, resolve its spreadsheet URL before the
     final email draft. On the first run for a team, capture the newly created
     spreadsheet URL and the current week tab `gid`, then rerun the snapshot
     phase with `--sheet-url <resolved Google Sheet URL>` and
     `--sheet-tab-gid <current Week N tab sheetId>` so the final draft opens
     the weekly tab for this run.
   - If the resolved spreadsheet URL is not available yet, leave the sheet link
     empty; do not link the email button to the shared Drive folder.
   - If `--output-dir` is provided, open `draft-email.html` or copy from
     `draft-email.txt`.
   - If an already-authenticated local connector/API client can create an HTML
     draft, use the rendered HTML or raw-MIME request with that route.
   - If no email connector is available, stop with the copy-pastable rendered
     subject/body; this is an expected successful outcome.
   - Do not use a plain-text-only draft helper for formatted HTML drafts.
6. Return the run summary, sheet result, run-history result, draft email
   payload/files, objective count, status counts, blocker count, and hygiene
   issues.

The orchestrator handles target date, team timezone, ISO week, monthly objective
label, Jira objective discovery, Leader Engineer comment filtering, latest valid comment
selection, parsing, hygiene, sheet row construction, and draft email rendering.

For test runs without live systems, use:

`python3 scripts/run_rollup.py --config tests/fixtures/team-config.yaml --date 2026-06-05 --jira-source fixture --jira-fixture tests/fixtures/run-jira.json --sheet-source fixture --sheet-fixture tests/fixtures/run-sheet-history.json --email-source none --output-dir output/test-week-23`

## Local Helpers

- `scripts/objective_rollup.py` contains deterministic business logic.
- `scripts/run_rollup.py` is the main Codex-invoked weekly runner.
- `scripts/parse_update.py` parses a single comment.
- `scripts/render_email.py` renders a draft email payload from normalized rows.
- `templates/objective-email.html` is the editable HTML email template for
  layout, copy, and inline colors/styles.
- `scripts/write_sheet.py` prepares the sheet values. In Codex, use the Google
  Drive MCP sheet tools to perform the actual tab creation/replacement/write.

## Adapter Modes

- Jira `mcp`: uses the in-tree `jira-mcp/` server bundled with this project.
- Jira `snapshot`: reads a previously collected `data-snapshot-YYYY-MM-DD.json`
  with no live Jira calls; use this for other authenticated Jira routes that can
  provide the normalized snapshot shape.
- Jira `fixture`: reads local fixture JSON for tests and dry-runs.
- Sheet `mcp-plan`: returns an explicit Google Drive MCP write request for Codex
  to execute.
- Sheet `fixture`: simulates sheet history and writes for deterministic tests.
- Email `raw-mime-plan`: returns a raw MIME draft request with `message.raw` for
  Codex or another HTML-capable client to execute.
- Email `none`: renders copy-pastable draft email output but does not prepare a
  connector draft request.

## Weekly Update Template

The latest valid Leader Engineer comment must include these semantic sections:

- Status
- Done this week
- Target or plan for next week
- Blockers or risks, unless the team config marks blockers as optional

Accepted status values are green, yellow, red, done/completed, the matching
status emoji, or delivery wording such as on track, at risk, delayed, or off
track. Jira done status wins over weekly health display for current-month
objectives, and prior-month done objectives are not reported in later months.
Aliases such as `state`, `completed`, `next week`, `coming up`, `dependencies`,
and `decisions needed` are supported.

## Output

Return a concise run summary, the sheet result, and the rendered draft email
payload/files. If the sheet write or draft-request preparation fails, still
return the rendered email output and report the failure clearly.
