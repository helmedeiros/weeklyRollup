# Functional Spec

## Goal

Create a skill that helps Engineering Managers generate weekly objective rollups
from Jira Epics. The skill is config-driven per team, identifies current monthly
objective Epics plus relevant previous-month carryover, finds the latest valid Leader Engineer
weekly update comment, writes a weekly tab into the team sheet, and generates a
visually clean draft email.

Team membership is not tracked in config. The Engineering Leader Engineer is the Jira Epic
assignee for that objective.

Team spreadsheets live in the configured Google Drive folder. The team sheet
file name is derived from `sheet.file_name_pattern`; each run checks that
folder for an exact file-name match. If the sheet exists, write the weekly tab
there. If it does not exist, create a new Google Sheet with that name in the
folder before writing. Future runs must resolve the same folder sheet and add or
replace the weekly tab there.

The skill must not send email automatically.

## Workflow

1. Load team config.
2. Resolve target month, year, week number, and weekly update window using the
   configured team timezone.
3. Build the monthly objective label: `objective-<month>-<year>`.
4. Query Jira for Epics on the configured board/project with the monthly objective
   label.
5. Query the previous monthly objective label when carryover tracking is enabled.
   Previous-month objectives with a future Jira due date remain current; objectives
   at or past their real Jira due date are treated as delayed carryover. If Jira
   has no due date, the objective remains visible after its label month with
   missing-due-date hygiene, but the run does not display an assumed due date as
   if it were real.
6. For each Epic, pull objective key, objective name, Jira URL, Leader Engineer, due date,
   child-issue progress, linked OKR parent objective for hygiene validation,
   status/category, and comments.
7. Validate Epic hygiene.
8. Find the latest valid Leader Engineer weekly update comment.
9. Parse the update into status, done this week, plan for next week, and
   blockers/risks.
10. Treat a Jira Epic in `To Do` with no valid/malformed update and no non-zero
   progress as `Not Started`, not a missing update. If Jira remains `To Do` but
   progress or update comments show work has started, keep the objective
   reportable and add a hygiene warning.
11. Resolve the team spreadsheet from the configured folder and file name,
   creating it if needed.
12. Create or replace the configured `Week <ISO week>` team sheet tab.
13. Write one normalized row per objective into that tab.
14. Generate a draft email body.
15. Return draft email, sheet write result, objective count, status counts,
    blocker count, due-date movement/overdue counts, and hygiene issues.

## Progress

Progress is calculated from child issues rather than Jira Epic progress fields:

- pull child issues for the Epic
- ignore subtasks
- count children whose status category is done or whose status is listed in
  `jira.done_statuses`
- progress is `done children / total children`
- if an Epic has no child issues, progress is blank

## Linked OKR

Linked OKR validation reads the Jira issue property `okr` and uses
`value.parentId` as the OKR parent objective ID. If the property is missing or
returns 404, treat the Epic as missing a linked OKR.

Linked OKR is not a standalone sheet or email column. Missing linked OKR appears
only as a hygiene issue.

Do not pull OKR board updates in this version.

## Latest Valid Leader Engineer Comment

A comment is eligible only if:

- author matches the Epic Leader Engineer
- timestamp is inside the team-local weekly window
- body is non-empty
- comment is not deleted or internal-only
- comment is not a reply comment

A comment is valid only if it mostly matches the Leader Engineer weekly update template. The
parser accepts both inline labels, such as `Status: Green`, and headings with
values on following lines, such as `Status` followed by `🟢`.

Required semantic sections:

1. Status
2. Done this week
3. Target or plan for next week

Optional semantic section:

4. Blockers or risks

Only blockers/risks can be optional. A valid update needs at least the three
required sections and a parseable status.

Selection rule: pick the latest valid comment, not the latest Leader Engineer comment.
Follow-up notes such as typo fixes or FYIs do not count unless they contain a
valid weekly update. If a valid update exists, malformed follow-up notes should
not create a hygiene warning.

## Hygiene Rules

Red:

- missing Leader Engineer
- missing due date
- due date overdue for an active objective
- no valid update for configured N weeks

Yellow:

- missing linked OKR
- missing valid update this week
- malformed Leader Engineer update when there is no valid Leader Engineer update
- yellow/red status without blocker or resolution path
- due date changed
- Jira Epic is still `To Do` but update/progress suggests work has started
- delayed carryover objective still open, unless already red

Info:

- first observation of due date
- no blockers reported
- Jira Epic is `To Do` and no start signal was observed
