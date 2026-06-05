# Sheet Format

Each team has one spreadsheet in the configured Google Drive folder, so the team
is implied by the sheet file itself. The file name is derived from
`sheet.file_name_pattern`, usually:

`<Team name> - Mission Execution Updates`

Every run first checks the configured folder for an exact spreadsheet file-name
match. If the file exists in the folder, write to it. If it does not exist,
create a new Google Sheet with that file name in the folder before writing.
Next runs must resolve that existing folder sheet and add or replace the weekly
tab there.

Each weekly run creates or replaces one tab:

`Week <ISO week number>`

The week is implied by the tab name. Do not include separate `Run date`, `Week`,
or `Team` columns in the weekly tab.

Columns:

1. Mission key
2. Mission name
3. Mission URL
4. Mission label
5. DRI
6. Status
7. Jira progress %
8. Due date
9. Due date movement
10. Done this week
11. Plan for next week
12. Blockers / risks
13. Risk/blocker owners
14. Risk/blocker days open
15. Missing update?
16. Missing update weeks
17. DRI comment
18. Hygiene issues

`Jira progress %` is status-based Epic progress calculated from child issues:
done child issues divided by total non-subtask child issues.

`DRI comment` contains the full selected valid DRI weekly update comment. It is
blank when no valid DRI comment exists for the week.

Do not add standalone `Template valid?` or `Linked OKR` columns. Template
validity is an internal selection/validation detail. Missing linked OKR appears
under `Hygiene issues`.

`Mission label` keeps the raw Jira mission label, for example
`mission-may-2026`. The email renders this more readably in mission titles,
for example `Mission name (May)`.

`Due date movement` is an audit field. It compares the current Jira due date to
the earliest observable real due date in sheet history. If no Jira due date was
ever observed, the run leaves movement empty until Jira provides a due date. The
field can show date movement such as `2025-10-01 -> 2026-06-11 (+253d)` or
overdue state such as `overdue by 1 day`.

When Jira has no due date, the run keeps the actual `Due date` cell empty,
raises a missing-due-date hygiene issue, and does not display an assumed due
date as if it were real. Previous-month open missions with no due date still
remain visible after their label month so they are not silently dropped.

`Missing update weeks` stores the current consecutive missing-update streak.

`Status` may include `Not Started` for Jira Epics that are still `To Do` and
have no valid/malformed weekly update and no non-zero progress. Those rows do
not count as missing updates. If Jira remains `To Do` but update/progress
signals show work has started, the mission keeps its parsed rollup status and
the hygiene column warns that the Jira status appears stale.

The spreadsheet also contains a system-owned `_Run History` tab. This is the
preferred persistence source for previous due date comparison,
no-update-in-N-weeks detection, risk/blocker age tracking, first observed date,
done date, and cycle time. Each run writes one row per mission with a stable
`Run ID`; reruns replace rows with the same `Run ID` instead of appending
duplicates.

If `_Run History` is empty or unavailable, history logic falls back to prior
weekly tabs. The fallback reads the week from prior tab names
(`Week <ISO week number>`), with support for older tabs that still contain a
`Week` column.
