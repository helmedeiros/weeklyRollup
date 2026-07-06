# Test Scenarios

## Objective Discovery

1. Current objective label is included.
2. Previous month label with done status is excluded from carryover.
3. Previous month label with future due date remains a current objective.
4. Previous month label with past due date is included as delayed carryover.
5. Previous month label with no due date remains visible after that label month
   with missing-due-date hygiene, without displaying an assumed due date.
6. No objective label is excluded from main report.
7. Correct label but wrong board/project is excluded unless config allows
   cross-project.

## Leader Engineer Validation

8. Epic assignee is used as the Engineering Leader Engineer.
9. Missing assignee is red hygiene.
10. No configured team-member roster is required or enforced.
11. Comment author account ID matching wins; email/display name is fallback.

## Comment Detection

12. Latest Leader Engineer comment with valid template is selected.
13. Latest Leader Engineer comment "fixed typo above" is ignored when a previous valid
    update exists.
14. EM update does not count.
15. PM update does not count.
16. Leader Engineer comment outside weekly window is missing this week.
17. Leader Engineer comment after Friday cutoff is not counted for current week.
18. If two valid Leader Engineer updates exist in the window, latest valid is selected.
19. Missing blockers section is valid when status, done, and plan are present.
20. `blockers: none` is valid.
21. Aliases like `Next week`, `Target for next week`, and bare heading lines
    are valid.
22. Casual note with status only is invalid.

## Parsing

23. Status emoji values parse correctly.
24. Green, Yellow, Red, and similar delivery-status wording parse correctly;
    `Done` is not a valid weekly health value unless the Jira Epic itself is in
    a done status.
25. Missing status is invalid.
26. Multiple blockers with owners are extracted.
27. `blockers: none` and benign "no blockers, monitoring..." wording create no
    blocker row.
28. Yellow/red status with neither blocker nor resolution path creates a hygiene
    warning.
29. Benign wording such as `No hard blocker right now.` creates no blocker row.

## Progress And OKR Hygiene

30. Epic progress is computed from child issue statuses.
31. Done children are detected by Jira status category or configured done
    statuses.
32. Subtasks are ignored for Epic progress.
33. Epic with no child issues has blank progress.
34. Linked OKR is read from issue property `okr.value.parentId`.
35. Missing or 404 OKR property creates missing linked OKR hygiene only.

## Jira Status Hygiene

36. Jira `To Do` with no update and no progress is shown as `Not Started`.
37. Jira `To Do` with a valid update keeps the parsed status and gets hygiene
    that work appears to have started.
38. Jira `To Do` with progress but no valid update is still missing this week
    and gets stale-Jira-status hygiene.

## Sheet

39. Missing week tab is created.
40. Existing week tab is replaced according to config.
41. Previous week tab is not modified.
42. Existing team spreadsheet is resolved by exact file name in configured
    Drive folder.
43. Missing team spreadsheet is created in the configured Drive folder.
44. Weekly tab is named `Week <ISO week number>`.
45. Sheet rows do not include `Run date`, `Week`, or `Team` columns.
46. Sheet rows include `Objective label`.
47. Sheet rows include `Leader Engineer comment`.
48. Sheet rows do not include `Template valid?` or `Linked OKR` columns.
49. Sheet write failure still returns draft email.
50. Due date changed vs previous sheet row is shown as date movement.
51. No previous row is not shown as movement.
52. Overdue objectives show overdue days in due date movement.

## Email

53. No blockers shows `No active blockers reported.`
54. Missing updates make the data hygiene block visible.
55. Missing linked OKR appears under data hygiene.
56. All green with no actionable hygiene omits the data hygiene section.
57. Done objectives render with blue status styling.
58. Red/yellow risks are shown first.
59. Objective title includes the objective month in parentheses.
60. Due date line shows moved later/earlier days and overdue days when relevant.
61. Recipients come from explicit `email.to`, `email.cc`, and `email.bcc`
    config lists.
62. Email output is rendered as copy-pastable HTML and plain text.
63. Raw MIME request is written when `--email-source raw-mime-plan` is used.
64. No credential-backed or direct-send path is available.

## General

65. No Jira epics found produces an empty run summary.
66. Jira API partial failure reports failed team/board.
67. Missing required config fails fast with actionable error.
68. Re-running the same input is deterministic.
