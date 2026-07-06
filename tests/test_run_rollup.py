from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_rollup import (  # noqa: E402
    FixtureJiraAdapter,
    FixtureSheetAdapter,
    JiraAdapter,
    McpPlanSheetAdapter,
    RawMimePlanEmailAdapter,
    RUN_HISTORY_COLUMNS,
    RollupAdapterError,
    _bucket_for_objective,
    apply_issue_property_fields,
    build_team_snapshot,
    child_issue_progress,
    child_issue_start_signal_seen,
    collect_jira_snapshot,
    due_date_change_status,
    due_date_movement_label,
    field_value,
    objective_start_signal_seen,
    objective_status_categories,
    normalize_jira_issue,
    normalize_jira_progress,
    run_rollup,
    sheet_url_with_gid,
)
from objective_rollup import load_config  # noqa: E402


class FailingJiraAdapter(JiraAdapter):
    def search_objective_epics(self, config, label):
        raise RollupAdapterError("Jira unavailable")

    def get_comments(self, objective, window_start, window_end):
        return []


def run_history_row(**values):
    row = {column: "" for column in RUN_HISTORY_COLUMNS}
    row.update(values)
    return [row[column] for column in RUN_HISTORY_COLUMNS]


class RunRollupTest(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "tests/fixtures/team-config.yaml")
        self.jira_fixture = ROOT / "tests/fixtures/run-jira.json"
        self.sheet_fixture = ROOT / "tests/fixtures/run-sheet-history.json"

    def test_end_to_end_fixture_run_filters_objectives_and_writes_summary(self):
        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(self.jira_fixture),
            sheet_adapter=FixtureSheetAdapter(self.sheet_fixture),
        )

        self.assertEqual(result["month_label"], "objective-june-2026")
        self.assertEqual(result["iso_week"], 23)
        self.assertEqual(result["objective_count"], 2)
        self.assertEqual(result["current_objective_count"], 2)
        self.assertEqual(result["spillover_objective_count"], 0)
        self.assertEqual(result["status_counts"]["green"], 1)
        self.assertEqual(result["status_counts"]["missing"], 1)
        self.assertEqual(result["missing_update_count"], 1)
        self.assertEqual(result["stale_update_count"], 1)
        self.assertEqual(result["due_date_changed_count"], 1)
        self.assertEqual(result["due_date_moved_later_count"], 1)
        self.assertEqual(result["due_date_moved_earlier_count"], 0)
        self.assertGreaterEqual(result["hygiene_issue_counts"]["red"], 1)
        self.assertGreaterEqual(result["hygiene_issue_counts"]["yellow"], 1)
        self.assertEqual(result["run_summary"]["current_month_objective_count"], 2)
        self.assertEqual(result["run_summary"]["spillover_objective_count"], 0)
        self.assertEqual(result["run_summary"]["stale_update_count"], 1)
        self.assertEqual(result["run_summary"]["due_date_changed_count"], 1)
        self.assertEqual(result["run_summary"]["due_date_moved_later_count"], 1)
        self.assertEqual(result["run_summary"]["due_date_moved_earlier_count"], 0)
        self.assertEqual(result["run_summary"]["completed_objective_count"], 0)
        self.assertEqual(result["run_summary"]["active_objective_count"], 2)
        self.assertEqual(result["run_summary"]["completion_rate"], 0.0)
        self.assertIsNone(result["run_summary"]["average_cycle_time_days"])
        self.assertEqual(result["run_summary"]["active_objective_average_age_days"], 0)
        self.assertEqual(result["run_summary"]["recurring_missing_update_count"], 1)
        self.assertEqual(result["run_summary"]["sheet_write_status"], "written")
        self.assertEqual(result["run_summary"]["run_history_read_status"], "fallback_weekly_sheet")
        self.assertEqual(result["run_summary"]["run_history_write_status"], "written")
        self.assertEqual(result["run_summary"]["draft_status"], "not_requested")
        self.assertEqual(result["run_summary"]["preview_status"], "rendered")
        self.assertEqual(result["metrics"]["objective_count"], 2)
        self.assertEqual(result["metrics"]["completed_objective_count"], 0)
        self.assertEqual(result["metrics"]["active_objective_count"], 2)
        self.assertEqual(result["metrics"]["completion_rate"], 0.0)
        self.assertIsNone(result["metrics"]["average_cycle_time_days"])
        self.assertEqual(result["metrics"]["active_objective_average_age_days"], 0)
        self.assertEqual(result["metrics"]["overdue_objective_count"], 0)
        self.assertEqual(result["metrics"]["recurring_missing_update_count"], 1)
        self.assertEqual(result["metrics"]["due_date_moved_later_count"], 1)
        self.assertEqual(result["metrics"]["due_date_moved_earlier_count"], 0)
        self.assertEqual(result["sheet_write"]["status"], "written")
        self.assertEqual(result["sheet_write"]["tab_name"], "Week 23")
        self.assertEqual(result["run_history"]["source"], "weekly_sheet")
        self.assertEqual(result["run_history_write"]["status"], "written")
        self.assertEqual(result["run_history"]["current_run_values"][0], RUN_HISTORY_COLUMNS)
        self.assertEqual(len(result["run_history"]["current_run_values"]), 3)
        self.assertEqual([objective["key"] for objective in result["objectives"]], ["TEST-1", "TEST-2"])
        self.assertIn("Leader Engineer comment", result["sheet_values"][0])
        self.assertIn("Objective label", result["sheet_values"][0])
        self.assertIn("Missing update weeks", result["sheet_values"][0])
        self.assertNotIn("Template valid?", result["sheet_values"][0])
        comment_index = result["sheet_values"][0].index("Leader Engineer comment")
        self.assertIn("Merged checkout validation PR", result["sheet_values"][1][comment_index])
        label_index = result["sheet_values"][0].index("Objective label")
        self.assertEqual(result["sheet_values"][1][label_index], "objective-june-2026")
        movement_index = result["sheet_values"][0].index("Due date movement")
        self.assertEqual(result["sheet_values"][1][movement_index], "")
        self.assertEqual(result["sheet_values"][2][movement_index], "2026-06-25 -> 2026-06-30 (+5d)")
        missing_weeks_index = result["sheet_values"][0].index("Missing update weeks")
        self.assertEqual(result["sheet_values"][1][missing_weeks_index], "")
        self.assertEqual(result["sheet_values"][2][missing_weeks_index], "2")
        objectives_by_key = {objective["key"]: objective for objective in result["objectives"]}
        self.assertEqual(objectives_by_key["TEST-2"]["missing_update_weeks"], 2)

        hygiene = [issue["message"] for issue in result["hygiene_issues"]]
        self.assertIn("Missing linked OKR", hygiene)
        self.assertIn("Missing weekly Leader Engineer update", hygiene)
        self.assertIn("Due date changed", hygiene)
        self.assertIn("No update in 2 weeks", hygiene)

    def test_phase_2_metrics_summarize_completion_cycle_age_overdue_and_recurring_misses(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-DONE-METRIC",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Completed objective",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-06-01",
                    "progress": "100%",
                    "linked_okr": "KR-DONE",
                    "status": "Done",
                    "comments": [
                        {
                            "id": "done-metric-valid",
                            "created": "2026-06-04T15:00:00+02:00",
                            "author": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                            "body": (
                                "Status: Green\n"
                                "Done: Completed launch.\n"
                                "Plan: Monitor production.\n"
                                "Blockers: none"
                            ),
                        }
                    ],
                },
                {
                    "key": "TEST-ACTIVE-METRIC",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Active objective",
                    "leader_engineer": {"accountId": "grace-account", "displayName": "Grace Hopper"},
                    "due_date": "2026-06-30",
                    "progress": "50%",
                    "linked_okr": "KR-ACTIVE",
                    "status": "In Progress",
                    "comments": [
                        {
                            "id": "active-metric-valid",
                            "created": "2026-06-04T15:00:00+02:00",
                            "author": {"accountId": "grace-account", "displayName": "Grace Hopper"},
                            "body": (
                                "Status: Green\n"
                                "Done: Built first slice.\n"
                                "Plan: Expand rollout.\n"
                                "Blockers: none"
                            ),
                        }
                    ],
                },
                {
                    "key": "TEST-OVERDUE-METRIC",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Active overdue objective",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-06-01",
                    "progress": "30%",
                    "linked_okr": "KR-OVERDUE",
                    "status": "In Progress",
                    "comments": [
                        {
                            "id": "overdue-metric-valid",
                            "created": "2026-06-04T15:00:00+02:00",
                            "author": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                            "body": (
                                "Status: Yellow\n"
                                "Done: Replanned delayed launch.\n"
                                "Plan: Close open rollout work.\n"
                                "Blockers: dependency on QA capacity"
                            ),
                        }
                    ],
                },
                {
                    "key": "TEST-STALE-METRIC",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Recurring missing update objective",
                    "leader_engineer": {"accountId": "grace-account", "displayName": "Grace Hopper"},
                    "due_date": "2026-06-30",
                    "progress": "10%",
                    "linked_okr": "KR-STALE",
                    "status": "In Progress",
                    "comments": [],
                },
            ]
        }
        adapter = FixtureSheetAdapter()
        adapter.run_history_values = [
            RUN_HISTORY_COLUMNS,
            run_history_row(
                **{
                    "Run ID": "test-team:2026-W21:2026-05-22",
                    "Target date": "2026-05-22",
                    "ISO week": "21",
                    "Objective key": "TEST-DONE-METRIC",
                    "Current due date": "2026-06-01",
                    "First observed date": "2026-05-22",
                    "Is done": "no",
                    "Missing update?": "no",
                }
            ),
            run_history_row(
                **{
                    "Run ID": "test-team:2026-W22:2026-05-29",
                    "Target date": "2026-05-29",
                    "ISO week": "22",
                    "Objective key": "TEST-ACTIVE-METRIC",
                    "Current due date": "2026-06-30",
                    "First observed date": "2026-05-29",
                    "Is done": "no",
                    "Missing update?": "no",
                }
            ),
            run_history_row(
                **{
                    "Run ID": "test-team:2026-W21:2026-05-22",
                    "Target date": "2026-05-22",
                    "ISO week": "21",
                    "Objective key": "TEST-OVERDUE-METRIC",
                    "Current due date": "2026-06-01",
                    "First observed date": "2026-05-22",
                    "Is done": "no",
                    "Missing update?": "no",
                }
            ),
            run_history_row(
                **{
                    "Run ID": "test-team:2026-W22:2026-05-29",
                    "Target date": "2026-05-29",
                    "ISO week": "22",
                    "Objective key": "TEST-STALE-METRIC",
                    "Current due date": "2026-06-30",
                    "First observed date": "2026-05-29",
                    "Is done": "no",
                    "Missing update?": "yes",
                }
            ),
        ]

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(data=jira_data),
            sheet_adapter=adapter,
        )

        self.assertEqual(result["metrics"]["objective_count"], 4)
        self.assertEqual(result["metrics"]["completed_objective_count"], 1)
        self.assertEqual(result["metrics"]["active_objective_count"], 3)
        self.assertEqual(result["metrics"]["completion_rate"], 0.25)
        self.assertEqual(result["metrics"]["average_cycle_time_days"], 14)
        self.assertEqual(result["metrics"]["active_objective_average_age_days"], 9.3)
        self.assertEqual(result["metrics"]["overdue_objective_count"], 1)
        self.assertEqual(result["metrics"]["recurring_missing_update_count"], 1)
        self.assertEqual(result["run_summary"]["completed_objective_count"], 1)
        self.assertEqual(result["run_summary"]["active_objective_count"], 3)
        self.assertEqual(result["run_summary"]["completion_rate"], 0.25)
        self.assertEqual(result["run_summary"]["average_cycle_time_days"], 14)
        self.assertEqual(result["run_summary"]["active_objective_average_age_days"], 9.3)
        self.assertEqual(result["run_summary"]["overdue_objective_count"], 1)
        self.assertEqual(result["run_summary"]["recurring_missing_update_count"], 1)
        objectives_by_key = {objective["key"]: objective for objective in result["objectives"]}
        self.assertEqual(objectives_by_key["TEST-DONE-METRIC"]["cycle_time_days"], 14)
        self.assertEqual(objectives_by_key["TEST-DONE-METRIC"]["active_age_days"], "")
        self.assertEqual(objectives_by_key["TEST-ACTIVE-METRIC"]["active_age_days"], 7)
        self.assertEqual(objectives_by_key["TEST-OVERDUE-METRIC"]["active_age_days"], 14)
        self.assertTrue(objectives_by_key["TEST-STALE-METRIC"]["recurring_missing_update"])

    def test_run_history_is_preferred_over_weekly_tab_history(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-HISTORY",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Objective with durable history",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-06-30",
                    "progress": "50%",
                    "linked_okr": "KR-HISTORY",
                    "status": "In Progress",
                    "comments": [
                        {
                            "id": "history-valid",
                            "created": "2026-06-04T15:00:00+02:00",
                            "author": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                            "body": (
                                "Status: Green\n"
                                "Done: Kept implementation on track.\n"
                                "Plan: Finish rollout checks.\n"
                                "Blockers: none"
                            ),
                        }
                    ],
                }
            ]
        }
        sheet_adapter = FixtureSheetAdapter()
        sheet_adapter.run_history_values = [
            RUN_HISTORY_COLUMNS,
            run_history_row(
                **{
                    "History version": "1",
                    "Run ID": "test-team:2026-W22:2026-05-29",
                    "Team ID": "test-team",
                    "Target date": "2026-05-29",
                    "ISO week": "22",
                    "Objective key": "TEST-HISTORY",
                    "Objective name": "Objective with durable history",
                    "Original due date": "2026-06-10",
                    "Current due date": "2026-06-20",
                    "Missing update?": "yes",
                    "First observed date": "2026-05-22",
                    "Is done": "no",
                }
            ),
        ]
        sheet_adapter.data = {
            "history_tabs": [
                {
                    "name": "Week 22",
                    "values": [
                        ["Objective key", "Objective name", "Due date", "Due date movement", "Missing update?"],
                        ["TEST-HISTORY", "Objective with durable history", "2026-06-25", "", "no"],
                    ],
                }
            ]
        }

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(data=jira_data),
            sheet_adapter=sheet_adapter,
        )

        objective = result["objectives"][0]
        self.assertEqual(result["run_history"]["source"], "run_history")
        self.assertEqual(result["run_history"]["read_status"], "loaded")
        self.assertEqual(objective["previous_due_date"], "2026-06-20")
        self.assertEqual(objective["original_due_date"], "2026-06-10")
        self.assertEqual(objective["due_date_movement"], "2026-06-10 -> 2026-06-30 (+20d)")
        self.assertEqual(objective["first_observed_date"], "2026-05-22")
        self.assertEqual(objective["active_age_days"], 14)

    def test_run_history_write_replaces_same_run_id_rows(self):
        adapter = FixtureSheetAdapter()
        run_id = "test-team:2026-W23:2026-06-05"
        adapter.run_history_values = [
            RUN_HISTORY_COLUMNS,
            run_history_row(**{"Run ID": run_id, "Objective key": "OLD-ROW"}),
            run_history_row(**{"Run ID": "test-team:2026-W22:2026-05-29", "Objective key": "PREVIOUS-ROW"}),
        ]

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(self.jira_fixture),
            sheet_adapter=adapter,
        )

        headers = adapter.run_history_values[0]
        run_id_index = headers.index("Run ID")
        key_index = headers.index("Objective key")
        current_run_keys = [
            row[key_index]
            for row in adapter.run_history_values[1:]
            if row[run_id_index] == run_id
        ]
        all_keys = [row[key_index] for row in adapter.run_history_values[1:]]
        self.assertEqual(sorted(current_run_keys), ["TEST-1", "TEST-2"])
        self.assertIn("PREVIOUS-ROW", all_keys)
        self.assertNotIn("OLD-ROW", all_keys)
        self.assertEqual(result["run_history_write"]["row_count"], 2)

    def test_run_history_tracks_first_observed_done_date_and_cycle_time(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-DONE-CYCLE",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Objective completed this week",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-06-30",
                    "progress": "100%",
                    "linked_okr": "KR-DONE",
                    "status": "Done",
                    "comments": [
                        {
                            "id": "done-valid",
                            "created": "2026-06-04T15:00:00+02:00",
                            "author": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                            "body": (
                                "Status: Green\n"
                                "Done: Completed rollout.\n"
                                "Plan: Monitor adoption.\n"
                                "Blockers: none"
                            ),
                        }
                    ],
                }
            ]
        }
        adapter = FixtureSheetAdapter()
        adapter.run_history_values = [
            RUN_HISTORY_COLUMNS,
            run_history_row(
                **{
                    "Run ID": "test-team:2026-W21:2026-05-22",
                    "Target date": "2026-05-22",
                    "ISO week": "21",
                    "Objective key": "TEST-DONE-CYCLE",
                    "Objective name": "Objective completed this week",
                    "Current due date": "2026-06-30",
                    "First observed date": "2026-05-22",
                    "Is done": "no",
                }
            ),
        ]

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(data=jira_data),
            sheet_adapter=adapter,
        )

        objective = result["objectives"][0]
        self.assertTrue(objective["is_done"])
        self.assertEqual(objective["status"], "Done")
        self.assertEqual(result["status_counts"]["done"], 1)
        self.assertEqual(objective["first_observed_date"], "2026-05-22")
        self.assertEqual(objective["done_date"], "2026-06-05")
        self.assertEqual(objective["cycle_time_days"], 14)
        self.assertEqual(objective["active_age_days"], "")
        done_date_index = result["run_history"]["current_run_values"][0].index("Done date")
        cycle_index = result["run_history"]["current_run_values"][0].index("Cycle time days")
        self.assertEqual(result["run_history"]["current_run_values"][1][done_date_index], "2026-06-05")
        self.assertEqual(result["run_history"]["current_run_values"][1][cycle_index], "14")

    def test_previous_month_done_epic_is_excluded_from_spillover(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-CURRENT",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Current objective",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-06-30",
                    "progress": "10%",
                    "linked_okr": "KR-1",
                    "status": "In Progress",
                    "comments": [],
                },
                {
                    "key": "TEST-DONE",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-may-2026"],
                    "summary": "Done previous objective",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-05-31",
                    "progress": "100%",
                    "linked_okr": "KR-OLD",
                    "status": "Done",
                    "comments": [],
                },
            ]
        }

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(data=jira_data),
            sheet_adapter=FixtureSheetAdapter(),
        )

        self.assertEqual(result["current_objective_count"], 1)
        self.assertEqual(result["spillover_objective_count"], 0)
        self.assertEqual([objective["key"] for objective in result["objectives"]], ["TEST-CURRENT"])

    def test_current_month_done_epic_without_update_is_not_missing(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-DONE-NO-UPDATE",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Done objective without this week update",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-06-30",
                    "progress": "100%",
                    "linked_okr": "KR-DONE",
                    "status": "Done",
                    "comments": [],
                }
            ]
        }

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(data=jira_data),
            sheet_adapter=FixtureSheetAdapter(),
        )

        objective = result["objectives"][0]
        self.assertEqual(objective["status"], "Done")
        self.assertFalse(objective["missing_update"])
        hygiene = [issue["message"] for issue in objective["hygiene"]]
        self.assertNotIn("Missing weekly Leader Engineer update", hygiene)
        self.assertEqual(result["missing_update_count"], 0)

    def test_comment_done_status_does_not_mark_open_epic_done(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-OPEN-DONE-COMMENT",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Open objective with done comment",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-06-30",
                    "progress": "80%",
                    "linked_okr": "KR-OPEN",
                    "status": "In Progress",
                    "comments": [
                        {
                            "id": "open-done-comment",
                            "created": "2026-06-04T15:00:00+02:00",
                            "author": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                            "body": (
                                "Status: Done\n"
                                "Done: Completed rollout.\n"
                                "Plan: Monitor adoption.\n"
                                "Blockers: none"
                            ),
                        }
                    ],
                }
            ]
        }

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(data=jira_data),
            sheet_adapter=FixtureSheetAdapter(),
        )

        objective = result["objectives"][0]
        self.assertFalse(objective["is_done"])
        self.assertEqual(objective["status"], "Missing")
        self.assertTrue(objective["missing_update"])
        self.assertEqual(result["status_counts"]["done"], 0)
        self.assertEqual(result["status_counts"]["missing"], 1)

    def test_to_do_epic_without_start_signal_is_not_started_not_missing(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-NOT-STARTED",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Queued objective",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-06-30",
                    "progress": "0%",
                    "linked_okr": "KR-QUEUED",
                    "status": "To Do",
                    "comments": [],
                }
            ]
        }

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(data=jira_data),
            sheet_adapter=FixtureSheetAdapter(),
        )

        objective = result["objectives"][0]
        self.assertEqual(objective["status"], "Not Started")
        self.assertFalse(objective["missing_update"])
        self.assertEqual(result["missing_update_count"], 0)
        self.assertEqual(result["status_counts"]["not_started"], 1)
        self.assertEqual(result["status_counts"]["missing"], 0)
        hygiene = [issue["message"] for issue in objective["hygiene"]]
        self.assertIn("Jira epic is To Do; not started", hygiene)
        self.assertNotIn("Missing weekly Leader Engineer update", hygiene)

    def test_to_do_epic_with_valid_update_is_reported_and_hygiene_warns(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-TODO-ACTIVE",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Started objective still in To Do",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-06-30",
                    "progress": "0%",
                    "linked_okr": "KR-ACTIVE",
                    "status": "To Do",
                    "comments": [
                        {
                            "id": "todo-active-valid",
                            "created": "2026-06-04T15:00:00+02:00",
                            "author": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                            "body": (
                                "Status: Green\n"
                                "Done: Started discovery with stakeholders.\n"
                                "Plan: Continue implementation.\n"
                                "Blockers: none"
                            ),
                        }
                    ],
                }
            ]
        }

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(data=jira_data),
            sheet_adapter=FixtureSheetAdapter(),
        )

        objective = result["objectives"][0]
        self.assertEqual(objective["status"], "Green")
        self.assertFalse(objective["missing_update"])
        self.assertEqual(result["status_counts"]["green"], 1)
        self.assertEqual(result["status_counts"]["not_started"], 0)
        hygiene = [issue["message"] for issue in objective["hygiene"]]
        self.assertIn("Jira epic is To Do but update/progress suggests work has started", hygiene)

    def test_to_do_epic_with_progress_but_no_update_is_missing_and_hygiene_warns(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-TODO-PROGRESS",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Progressed objective still in To Do",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-06-30",
                    "progress": "50%",
                    "linked_okr": "KR-PROGRESS",
                    "status": "To Do",
                    "comments": [],
                }
            ]
        }

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(data=jira_data),
            sheet_adapter=FixtureSheetAdapter(),
        )

        objective = result["objectives"][0]
        self.assertEqual(objective["status"], "Missing")
        self.assertTrue(objective["missing_update"])
        self.assertEqual(result["missing_update_count"], 1)
        self.assertEqual(result["status_counts"]["not_started"], 0)
        hygiene = [issue["message"] for issue in objective["hygiene"]]
        self.assertIn("Missing weekly Leader Engineer update", hygiene)
        self.assertIn("Jira epic is To Do but update/progress suggests work has started", hygiene)

    def test_previous_month_non_done_epic_is_included_as_spillover(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-CURRENT",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Current objective",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-06-30",
                    "progress": "10%",
                    "linked_okr": "KR-1",
                    "status": "In Progress",
                    "comments": [],
                },
                {
                    "key": "TEST-SPILL",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-may-2026"],
                    "summary": "Open previous objective",
                    "leader_engineer": {"accountId": "grace-account", "displayName": "Grace Hopper"},
                    "due_date": "2026-05-31",
                    "progress": "50%",
                    "linked_okr": "KR-SPILL",
                    "status": "In Progress",
                    "comments": [],
                },
            ]
        }

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(data=jira_data),
            sheet_adapter=FixtureSheetAdapter(),
        )

        self.assertEqual(result["current_objective_count"], 1)
        self.assertEqual(result["spillover_objective_count"], 1)
        objectives_by_key = {objective["key"]: objective for objective in result["objectives"]}
        self.assertEqual(objectives_by_key["TEST-CURRENT"]["objective_type"], "current")
        self.assertEqual(objectives_by_key["TEST-SPILL"]["objective_type"], "spillover")
        self.assertEqual(objectives_by_key["TEST-SPILL"]["original_month_label"], "objective-may-2026")

    def test_current_month_overdue_epic_stays_current_and_shows_delay(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-LATE",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Current objective already overdue",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-06-01",
                    "progress": "30%",
                    "linked_okr": "KR-LATE",
                    "status": "In Progress",
                    "comments": [
                        {
                            "id": "late-valid",
                            "created": "2026-06-04T15:00:00+02:00",
                            "author": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                            "body": (
                                "Status: Green\n"
                                "Done: Shipped the first slice.\n"
                                "Plan: Rebaseline the remaining rollout.\n"
                                "Blockers: dependency on partner readiness"
                            ),
                        }
                    ],
                }
            ]
        }

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(data=jira_data),
            sheet_adapter=FixtureSheetAdapter(),
        )

        self.assertEqual(result["current_objective_count"], 1)
        self.assertEqual(result["spillover_objective_count"], 0)
        self.assertEqual(result["status_counts"]["red"], 1)
        self.assertEqual(result["overdue_objective_count"], 1)
        objective = result["objectives"][0]
        self.assertEqual(objective["objective_type"], "current")
        self.assertEqual(objective["status"], "Red")
        self.assertEqual(objective["due_date_overdue_days"], 4)
        status_index = result["sheet_values"][0].index("Status")
        self.assertEqual(result["sheet_values"][1][status_index], "Red")
        movement_index = result["sheet_values"][0].index("Due date movement")
        self.assertEqual(
            result["sheet_values"][1][movement_index],
            "overdue by 4 days",
        )
        hygiene = [issue["message"] for issue in result["hygiene_issues"]]
        self.assertIn("Due date overdue by 4 days", hygiene)
        self.assertIn("[DELAYED] Current objective already overdue", result["draft_email"]["text_body"])
        self.assertIn("Due: 1 Jun (overdue 4 days)", result["draft_email"]["text_body"])
        self.assertIn("Due: 1 Jun (overdue 4 days)", result["draft_email"]["html_body"])
        self.assertNotIn("Due date movement:", result["draft_email"]["text_body"])
        self.assertNotIn("Movement:", result["draft_email"]["html_body"])

    def test_previous_month_epic_with_future_due_date_is_included_as_current(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-CURRENT",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-july-2026"],
                    "summary": "Current July objective",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-07-31",
                    "progress": "10%",
                    "linked_okr": "KR-1",
                    "status": "In Progress",
                    "comments": [],
                },
                {
                    "key": "TEST-JUNE-LONG",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "June objective planned through mid July",
                    "leader_engineer": {"accountId": "grace-account", "displayName": "Grace Hopper"},
                    "due_date": "2026-07-15",
                    "progress": "50%",
                    "linked_okr": "KR-SPILL",
                    "status": "In Progress",
                    "comments": [],
                },
            ]
        }

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 7, 3),
            jira_adapter=FixtureJiraAdapter(data=jira_data),
            sheet_adapter=FixtureSheetAdapter(),
        )

        self.assertEqual(result["current_objective_count"], 2)
        self.assertEqual(result["spillover_objective_count"], 0)
        self.assertEqual([objective["key"] for objective in result["objectives"]], ["TEST-CURRENT", "TEST-JUNE-LONG"])
        label_index = result["sheet_values"][0].index("Objective label")
        rows_by_key = {row[0]: row for row in result["sheet_values"][1:]}
        self.assertEqual(rows_by_key["TEST-JUNE-LONG"][label_index], "objective-june-2026")
        objectives_by_key = {objective["key"]: objective for objective in result["objectives"]}
        self.assertEqual(objectives_by_key["TEST-JUNE-LONG"]["objective_type"], "current")
        self.assertEqual(objectives_by_key["TEST-JUNE-LONG"]["original_month_label"], "objective-june-2026")

    def test_previous_month_epic_with_past_due_date_is_spillover(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-CURRENT",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-july-2026"],
                    "summary": "Current July objective",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-07-31",
                    "progress": "10%",
                    "linked_okr": "KR-1",
                    "status": "In Progress",
                    "comments": [],
                },
                {
                    "key": "TEST-JUNE-PAST",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "June objective overdue in July",
                    "leader_engineer": {"accountId": "grace-account", "displayName": "Grace Hopper"},
                    "due_date": "2026-07-01",
                    "progress": "50%",
                    "linked_okr": "KR-SPILL",
                    "status": "In Progress",
                    "comments": [],
                },
            ]
        }

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 7, 3),
            jira_adapter=FixtureJiraAdapter(data=jira_data),
            sheet_adapter=FixtureSheetAdapter(),
        )

        self.assertEqual(result["current_objective_count"], 1)
        self.assertEqual(result["spillover_objective_count"], 1)
        objectives_by_key = {objective["key"]: objective for objective in result["objectives"]}
        self.assertEqual(objectives_by_key["TEST-JUNE-PAST"]["objective_type"], "spillover")
        self.assertEqual(objectives_by_key["TEST-JUNE-PAST"]["original_month_label"], "objective-june-2026")

    def test_previous_month_epic_without_due_date_spills_after_label_month_end(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-CURRENT",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-july-2026"],
                    "summary": "Current July objective",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-07-31",
                    "progress": "10%",
                    "linked_okr": "KR-1",
                    "status": "In Progress",
                    "comments": [],
                },
                {
                    "key": "TEST-JUNE-NO-DUE",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "June objective with missing due date",
                    "leader_engineer": {"accountId": "grace-account", "displayName": "Grace Hopper"},
                    "due_date": "",
                    "progress": "50%",
                    "linked_okr": "KR-SPILL",
                    "status": "In Progress",
                    "comments": [
                        {
                            "id": "no-due-valid",
                            "created": "2026-07-02T15:00:00+02:00",
                            "author": {"accountId": "grace-account", "displayName": "Grace Hopper"},
                            "body": (
                                "Status: Green\n"
                                "Done: Continued rollout.\n"
                                "Plan: Finish remaining launch items.\n"
                                "Blockers: none"
                            ),
                        }
                    ],
                },
            ]
        }

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 7, 3),
            jira_adapter=FixtureJiraAdapter(data=jira_data),
            sheet_adapter=FixtureSheetAdapter(),
        )

        self.assertEqual(result["current_objective_count"], 1)
        self.assertEqual(result["spillover_objective_count"], 1)
        objectives_by_key = {objective["key"]: objective for objective in result["objectives"]}
        self.assertEqual(objectives_by_key["TEST-JUNE-NO-DUE"]["objective_type"], "spillover")
        self.assertEqual(objectives_by_key["TEST-JUNE-NO-DUE"]["original_month_label"], "objective-june-2026")
        self.assertEqual(objectives_by_key["TEST-JUNE-NO-DUE"]["status"], "Green")
        self.assertNotIn("assumed_due_date", objectives_by_key["TEST-JUNE-NO-DUE"])
        self.assertEqual(objectives_by_key["TEST-JUNE-NO-DUE"]["due_date_overdue_days"], 0)
        self.assertEqual(objectives_by_key["TEST-JUNE-NO-DUE"]["due_date_movement"], "")
        self.assertIn("Due: No due date", result["draft_email"]["text_body"])
        self.assertNotIn("assumed", result["draft_email"]["text_body"])
        hygiene = [issue["message"] for issue in result["hygiene_issues"]]
        self.assertIn("Missing due date", hygiene)
        self.assertNotIn("Assumed due date 2026-06-30 overdue by 3 days", hygiene)

    def test_due_date_movement_label_shows_date_delta(self):
        self.assertEqual(
            due_date_movement_label("2026-06-11", "2026-05-27", observed_before=True),
            "2026-05-27 -> 2026-06-11 (+15d)",
        )
        self.assertEqual(
            due_date_movement_label("2026-06-04", "2026-06-11", observed_before=True),
            "2026-06-11 -> 2026-06-04 (-7d)",
        )
        self.assertEqual(
            due_date_movement_label("2026-06-30", None, observed_before=False),
            "",
        )
        self.assertEqual(
            due_date_movement_label("", "2026-06-30", observed_before=True),
            "",
        )
        self.assertEqual(
            due_date_change_status("2026-06-30", "2026-06-30", observed_before=True),
            "unchanged",
        )
        self.assertEqual(
            due_date_movement_label(
                "2026-06-01",
                "2026-06-01",
                observed_before=True,
                target_date=__import__("datetime").date(2026, 6, 5),
            ),
            "overdue by 4 days",
        )

    def test_original_due_date_survives_previous_movement_history(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-MOVED",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Objective with remembered original due date",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-06-11",
                    "progress": "40%",
                    "linked_okr": "KR-MOVED",
                    "status": "In Progress",
                    "comments": [
                        {
                            "id": "moved-valid",
                            "created": "2026-06-04T15:00:00+02:00",
                            "author": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                            "body": (
                                "Status: Green\n"
                                "Done: Confirmed revised launch scope.\n"
                                "Plan: Close remaining rollout work.\n"
                                "Blockers: none"
                            ),
                        }
                    ],
                }
            ]
        }
        sheet_adapter = FixtureSheetAdapter()
        sheet_adapter.data = {
            "history_tabs": [
                {
                    "name": "Week 22",
                    "values": [
                        [
                            "Objective key",
                            "Objective name",
                            "Due date",
                            "Due date movement",
                            "Missing update?",
                        ],
                        [
                            "TEST-MOVED",
                            "Objective with remembered original due date",
                            "2026-06-11",
                            "2025-10-01 -> 2026-06-11 (+253d)",
                            "no",
                        ],
                    ],
                }
            ]
        }

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(data=jira_data),
            sheet_adapter=sheet_adapter,
        )

        objective = result["objectives"][0]
        self.assertEqual(objective["original_due_date"], "2025-10-01")
        self.assertEqual(objective["due_date_change_status"], "changed")
        self.assertEqual(objective["due_date_movement"], "2025-10-01 -> 2026-06-11 (+253d)")
        movement_index = result["sheet_values"][0].index("Due date movement")
        self.assertEqual(result["sheet_values"][1][movement_index], "2025-10-01 -> 2026-06-11 (+253d)")
        self.assertIn(
            "Due: 11 Jun (original: 1 Oct 2025, moved later 253 days)",
            result["draft_email"]["text_body"],
        )

    def test_missing_historical_due_date_uses_current_as_first_observed_original(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-NO-DUE-HISTORY",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-may-2026"],
                    "summary": "Objective that gained a due date",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-06-11",
                    "progress": "40%",
                    "linked_okr": "KR-MOVED",
                    "status": "In Progress",
                    "comments": [
                        {
                            "id": "gained-due-valid",
                            "created": "2026-06-04T15:00:00+02:00",
                            "author": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                            "body": (
                                "Status: Green\n"
                                "Done: Added missing due date.\n"
                                "Plan: Finish carryover work.\n"
                                "Blockers: none"
                            ),
                        }
                    ],
                }
            ]
        }
        sheet_adapter = FixtureSheetAdapter()
        sheet_adapter.data = {
            "history_tabs": [
                {
                    "name": "Week 22",
                    "values": [
                        ["Objective key", "Objective name", "Due date", "Missing update?"],
                        ["TEST-NO-DUE-HISTORY", "Objective that gained a due date", "", "no"],
                    ],
                }
            ]
        }

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(data=jira_data),
            sheet_adapter=sheet_adapter,
        )

        objective = result["objectives"][0]
        self.assertEqual(objective["objective_type"], "current")
        self.assertEqual(objective["original_due_date"], "2026-06-11")
        self.assertEqual(objective["due_date_change_status"], "first_observed")
        self.assertEqual(objective["due_date_movement"], "")
        self.assertIn("Due: 11 Jun", result["draft_email"]["text_body"])
        self.assertNotIn("original: 31 May", result["draft_email"]["text_body"])

    def test_collected_jira_snapshot_can_drive_rollup_without_live_adapter(self):
        snapshot = collect_jira_snapshot(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(self.jira_fixture),
            source="test-jira-mcp",
        )

        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter.from_data(snapshot),
            sheet_adapter=FixtureSheetAdapter(self.sheet_fixture),
            jira_snapshot=snapshot,
        )

        self.assertEqual(snapshot["source"], "test-jira-mcp")
        self.assertEqual(snapshot["month_label"], "objective-june-2026")
        self.assertEqual([objective["key"] for objective in snapshot["objectives"]], ["TEST-1", "TEST-2"])
        self.assertIn("comments", snapshot["objectives"][0])
        self.assertEqual(result["objective_count"], 2)
        self.assertEqual(result["jira_snapshot"]["objective_count"], 2)
        self.assertEqual([objective["key"] for objective in result["objectives"]], ["TEST-1", "TEST-2"])

    def test_mcp_plan_sheet_adapter_returns_codex_write_request(self):
        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(self.jira_fixture),
            sheet_adapter=McpPlanSheetAdapter(),
        )

        self.assertEqual(result["sheet_write"]["status"], "mcp_plan")
        self.assertEqual(result["sheet_write"]["spreadsheet_id"], "")
        self.assertEqual(result["sheet_write"]["request"]["tab_name"], "Week 23")
        self.assertEqual(result["sheet_write"]["request"]["spreadsheet_id"], "")
        self.assertEqual(result["sheet_write"]["request"]["folder_id"], "test-folder-id-fixture-only")
        self.assertEqual(result["sheet_write"]["request"]["file_name"], "Test Team - Objective Execution Updates")
        self.assertEqual(result["sheet_write"]["request"]["email_link"]["target"], "current_week_tab")
        self.assertEqual(result["sheet_write"]["request"]["email_link"]["tab_name"], "Week 23")
        self.assertIn("weekly_tab_sheetId", result["sheet_write"]["request"]["email_link"]["url_format"])
        self.assertTrue(result["sheet_write"]["request"]["spreadsheet_resolution"]["create_if_missing"])
        self.assertTrue(result["sheet_write"]["request"]["spreadsheet_resolution"]["reuse_existing"])
        self.assertEqual(
            result["sheet_write"]["request"]["spreadsheet_resolution"]["strategy"],
            "folder_file_name_then_create",
        )
        self.assertNotIn("configured_spreadsheet_id", result["sheet_write"]["request"]["spreadsheet_resolution"])
        self.assertIn("exact spreadsheet file_name match", " ".join(result["sheet_write"]["request"]["mcp_steps"]))
        self.assertIn("create_google_sheet", " ".join(result["sheet_write"]["request"]["mcp_steps"]))
        self.assertIn("sheet_add_sheet", " ".join(result["sheet_write"]["request"]["mcp_steps"]))
        self.assertIn("sheet_update_values", " ".join(result["sheet_write"]["request"]["mcp_steps"]))
        self.assertIn("sheetId/gid for tab_name", " ".join(result["sheet_write"]["request"]["mcp_steps"]))

    def test_email_uses_resolved_sheet_url_when_provided(self):
        sheet_url = "https://docs.google.com/spreadsheets/d/resolved-sheet-123"
        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(self.jira_fixture),
            sheet_adapter=McpPlanSheetAdapter(),
            sheet_url_override=sheet_url,
        )

        self.assertEqual(result["sheet_url"], sheet_url)
        self.assertIn(sheet_url, result["draft_email"]["html_body"])
        self.assertIn(sheet_url, result["draft_email"]["text_body"])
        self.assertNotIn("https://drive.google.com/drive/folders", result["draft_email"]["text_body"])

    def test_email_uses_current_week_tab_gid_when_provided(self):
        sheet_url = "https://docs.google.com/spreadsheets/d/resolved-sheet-123/edit"
        tab_url = "https://docs.google.com/spreadsheets/d/resolved-sheet-123/edit#gid=week23gid"
        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(self.jira_fixture),
            sheet_adapter=McpPlanSheetAdapter(),
            sheet_url_override=sheet_url,
            sheet_tab_gid="week23gid",
        )

        self.assertEqual(result["sheet_url"], tab_url)
        self.assertIn(tab_url, result["draft_email"]["html_body"])
        self.assertIn(tab_url, result["draft_email"]["text_body"])

    def test_email_does_not_link_shared_folder_when_sheet_url_is_unknown(self):
        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(self.jira_fixture),
            sheet_adapter=McpPlanSheetAdapter(),
        )

        self.assertEqual(result["sheet_url"], "")
        self.assertNotIn("https://drive.google.com/drive/folders", result["draft_email"]["html_body"])
        self.assertNotIn("https://drive.google.com/drive/folders", result["draft_email"]["text_body"])
        self.assertNotIn("Open weekly objective sheet", result["draft_email"]["html_body"])

    def test_sheet_url_with_gid_replaces_existing_gid_and_ignores_folder_links(self):
        self.assertEqual(
            sheet_url_with_gid(
                "https://docs.google.com/spreadsheets/d/sheet-123/edit#gid=oldgid",
                "newgid",
            ),
            "https://docs.google.com/spreadsheets/d/sheet-123/edit#gid=newgid",
        )
        self.assertEqual(
            sheet_url_with_gid("https://drive.google.com/drive/folders/folder-123", "newgid"),
            "https://drive.google.com/drive/folders/folder-123",
        )

    def test_mcp_plan_without_history_marks_due_date_history_unavailable(self):
        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(self.jira_fixture),
            sheet_adapter=McpPlanSheetAdapter(),
        )

        movement_index = result["sheet_values"][0].index("Due date movement")
        self.assertEqual(result["sheet_values"][1][movement_index], "history unavailable: 2026-06-30")
        missing_weeks_index = result["sheet_values"][0].index("Missing update weeks")
        self.assertEqual(result["sheet_values"][2][missing_weeks_index], "1")
        self.assertTrue(
            any("Sheet history was not loaded" in warning["message"] for warning in result["warnings"])
        )
        hygiene = [issue["message"] for issue in result["hygiene_issues"]]
        self.assertNotIn("First observation of due date", hygiene)

    def test_raw_mime_plan_email_adapter_returns_html_capable_request(self):
        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(self.jira_fixture),
            sheet_adapter=FixtureSheetAdapter(self.sheet_fixture),
            email_adapter=RawMimePlanEmailAdapter(),
        )

        request = result["email_create"]["request"]
        self.assertEqual(result["email_create"]["status"], "raw_mime_plan")
        self.assertEqual(request["api"], "gmail.users.drafts.create")
        self.assertEqual(request["body_source"], "raw_mime.multipart_alternative")
        self.assertEqual(request["mime_type"], "multipart/alternative")
        self.assertTrue(request["html_capable"])
        self.assertFalse(request["mcp_tool_compatible"])
        self.assertIn("plainTextBody", request)
        self.assertIn("htmlBody", request)
        # Banner now mirrors the subject (upstream f7cbd7b19 / 8a5f22851 port).
        self.assertIn(result["draft_email"]["subject"], request["htmlBody"])
        self.assertNotIn("Weekly Objective Report", request["htmlBody"])
        self.assertIn("message", request["body"])
        self.assertIn("raw", request["body"]["message"])

    def test_sheet_write_failure_still_returns_draft_email(self):
        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FixtureJiraAdapter(self.jira_fixture),
            sheet_adapter=FixtureSheetAdapter(ROOT / "tests/fixtures/run-sheet-fail.json"),
        )

        self.assertEqual(result["sheet_write"]["status"], "failed")
        self.assertIn("draft email", result["sheet_write"]["message"])
        self.assertIn("Weekly Objective Update", result["draft_email"]["subject"])
        self.assertEqual(result["errors"][0]["source"], "sheet_write")

    def test_no_epics_found_does_not_crash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_path = Path(temp_dir) / "empty-jira.json"
            fixture_path.write_text(json.dumps({"objectives": []}), encoding="utf-8")
            result = run_rollup(
                self.config,
                target_date=__import__("datetime").date(2026, 6, 5),
                jira_adapter=FixtureJiraAdapter(fixture_path),
                sheet_adapter=FixtureSheetAdapter(),
            )

        self.assertEqual(result["objective_count"], 0)
        self.assertEqual(result["sheet_write"]["row_count"], 0)
        self.assertEqual(result["warnings"][0]["source"], "jira")
        self.assertIn("No epics found with objective label objective-june-2026", result["warnings"][0]["message"])
        self.assertIn("objective-{month}-{year}", result["warnings"][0]["message"])
        self.assertIn("No objectives found", result["draft_email"]["html_body"])

    def test_jira_failure_reports_failed_board_and_still_returns_email(self):
        result = run_rollup(
            self.config,
            target_date=__import__("datetime").date(2026, 6, 5),
            jira_adapter=FailingJiraAdapter(),
            sheet_adapter=FixtureSheetAdapter(),
        )

        self.assertEqual(result["objective_count"], 0)
        self.assertEqual(result["errors"][0]["source"], "jira")
        self.assertEqual(result["warnings"], [])
        self.assertIn("Jira unavailable", result["errors"][0]["message"])
        self.assertIn("Weekly Objective Update", result["draft_email"]["subject"])

    def test_blocker_age_uses_first_seen_week_from_sheet_history(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-RISK",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Core platform dependency",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-06-30",
                    "progress": "25%",
                    "linked_okr": "KR-1",
                    "status": "In Progress",
                    "comments": [
                        {
                            "id": "risk-update",
                            "created": "2026-06-04T15:00:00+02:00",
                            "author": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                            "body": (
                                "Status: Yellow\n"
                                "Done this week: API contract reviewed.\n"
                                "Target for next week: Confirm rollout path.\n"
                                "Blockers / Risks:\n"
                                "- Waiting for @Core Platform, open 3 days"
                            ),
                        }
                    ],
                }
            ]
        }
        history = {
            "history_tabs": [
                {
                    "name": "Week 21",
                    "values": [
                        [
                            "Objective key",
                            "Objective name",
                            "Objective URL",
                            "Leader Engineer",
                            "Status",
                            "Jira progress %",
                            "Due date",
                            "Due date changed?",
                            "Done this week",
                            "Plan for next week",
                            "Blockers / risks",
                            "Risk/blocker owners",
                            "Risk/blocker days open",
                            "Missing update?",
                            "Leader Engineer comment",
                            "Hygiene issues",
                        ],
                        [
                            "TEST-RISK",
                            "Core platform dependency",
                            "",
                            "Ada Lovelace",
                            "Yellow",
                            "25%",
                            "2026-06-30",
                            "no",
                            "Started work",
                            "Continue",
                            "Waiting for @Core Platform",
                            "Core Platform",
                            "0 days",
                            "no",
                            "",
                            "",
                        ],
                    ],
                },
                {
                    "name": "Week 22",
                    "values": [
                        [
                            "Objective key",
                            "Objective name",
                            "Objective URL",
                            "Leader Engineer",
                            "Status",
                            "Jira progress %",
                            "Due date",
                            "Due date changed?",
                            "Done this week",
                            "Plan for next week",
                            "Blockers / risks",
                            "Missing update?",
                            "Leader Engineer comment",
                            "Hygiene issues",
                        ],
                        [
                            "TEST-RISK",
                            "Core platform dependency",
                            "",
                            "Ada Lovelace",
                            "Yellow",
                            "25%",
                            "2026-06-30",
                            "no",
                            "Still blocked",
                            "Continue",
                            "Waiting for @Core Platform, open 7 days",
                            "no",
                            "",
                            "",
                        ],
                    ],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            jira_path = Path(temp_dir) / "jira.json"
            history_path = Path(temp_dir) / "history.json"
            jira_path.write_text(json.dumps(jira_data), encoding="utf-8")
            history_path.write_text(json.dumps(history), encoding="utf-8")

            result = run_rollup(
                self.config,
                target_date=__import__("datetime").date(2026, 6, 5),
                jira_adapter=FixtureJiraAdapter(jira_path),
                sheet_adapter=FixtureSheetAdapter(history_path),
            )

        blocker = result["objectives"][0]["blockers"][0]
        self.assertEqual(blocker["owner"], "Core Platform")
        self.assertEqual(blocker["days_open"], "14")
        self.assertEqual(blocker["first_seen_week"], "21")
        self.assertIn("Days open: 14", result["draft_email"]["text_body"])
        age_column = result["sheet_values"][0].index("Risk/blocker days open")
        self.assertIn("14 days", result["sheet_values"][1][age_column])

    def test_changed_blocker_text_is_new_in_sheet_history(self):
        jira_data = {
            "objectives": [
                {
                    "key": "TEST-RISK",
                    "project_key": "TEST",
                    "board_id": "42",
                    "issue_type": "Epic",
                    "labels": ["objective-june-2026"],
                    "summary": "Legal approval",
                    "leader_engineer": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                    "due_date": "2026-06-30",
                    "progress": "25%",
                    "linked_okr": "KR-1",
                    "status": "In Progress",
                    "comments": [
                        {
                            "id": "risk-update",
                            "created": "2026-06-04T15:00:00+02:00",
                            "author": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
                            "body": (
                                "Status: Yellow\n"
                                "Done this week: Legal review started.\n"
                                "Target for next week: Get final approval.\n"
                                "Blockers / Risks: Waiting for @Legal"
                            ),
                        }
                    ],
                }
            ]
        }
        history = {
            "history_tabs": [
                {
                    "name": "Week 22",
                    "values": [
                        [
                            "Objective key",
                            "Objective name",
                            "Objective URL",
                            "Leader Engineer",
                            "Status",
                            "Jira progress %",
                            "Due date",
                            "Due date changed?",
                            "Done this week",
                            "Plan for next week",
                            "Blockers / risks",
                            "Missing update?",
                            "Leader Engineer comment",
                            "Hygiene issues",
                        ],
                        [
                            "TEST-RISK",
                            "Legal approval",
                            "",
                            "Ada Lovelace",
                            "Yellow",
                            "25%",
                            "2026-06-30",
                            "no",
                            "Blocked",
                            "Continue",
                            "Waiting for @Core Platform",
                            "no",
                            "",
                            "",
                        ],
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            jira_path = Path(temp_dir) / "jira.json"
            history_path = Path(temp_dir) / "history.json"
            jira_path.write_text(json.dumps(jira_data), encoding="utf-8")
            history_path.write_text(json.dumps(history), encoding="utf-8")

            result = run_rollup(
                self.config,
                target_date=__import__("datetime").date(2026, 6, 5),
                jira_adapter=FixtureJiraAdapter(jira_path),
                sheet_adapter=FixtureSheetAdapter(history_path),
            )

        blocker = result["objectives"][0]["blockers"][0]
        self.assertEqual(blocker["days_open"], "new risk")
        self.assertEqual(blocker["first_seen_week"], "23")
        self.assertIn("Days open: new risk", result["draft_email"]["text_body"])
        age_column = result["sheet_values"][0].index("Risk/blocker days open")
        self.assertIn("new risk", result["sheet_values"][1][age_column])
        self.assertNotIn("new risk days", result["sheet_values"][1][age_column])

    def test_output_files_are_written_when_requested(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot = collect_jira_snapshot(
                self.config,
                target_date=__import__("datetime").date(2026, 6, 5),
                jira_adapter=FixtureJiraAdapter(self.jira_fixture),
                source="test-jira-mcp",
            )
            result = run_rollup(
                self.config,
                target_date=__import__("datetime").date(2026, 6, 5),
                jira_adapter=FixtureJiraAdapter.from_data(snapshot),
                sheet_adapter=McpPlanSheetAdapter(),
                email_adapter=RawMimePlanEmailAdapter(),
                jira_snapshot=snapshot,
                output_dir=temp_dir,
            )

            for path in result["output_files"].values():
                self.assertTrue(Path(path).exists())
            self.assertIn("data_snapshot", result["output_files"])
            self.assertIn("email_mcp_request", result["output_files"])
            self.assertIn("email_mime", result["output_files"])
            self.assertIn("gmail_raw_draft_request", result["output_files"])
            snapshot_file = json.loads(Path(result["output_files"]["data_snapshot"]).read_text(encoding="utf-8"))
            self.assertEqual(snapshot_file["source"], "test-jira-mcp")
            result_file = json.loads(Path(result["output_files"]["result_json"]).read_text(encoding="utf-8"))
            self.assertEqual(result_file["jira_snapshot"]["objective_count"], 2)
            raw_request = json.loads(Path(result["output_files"]["gmail_raw_draft_request"]).read_text(encoding="utf-8"))
            self.assertEqual(raw_request["api"], "gmail.users.drafts.create")
            self.assertIn("plainTextBody", raw_request)
            self.assertIn("htmlBody", raw_request)
            mime_text = Path(result["output_files"]["email_mime"]).read_text(encoding="utf-8")
            self.assertIn("multipart/alternative", mime_text)
            self.assertIn("Content-Type: text/html", mime_text)

    def test_empty_jira_fields_do_not_render_python_literals(self):
        self.assertEqual(field_value({"duedate": None}, "duedate"), "")
        self.assertEqual(normalize_jira_progress({"progress": 0, "total": 0}), "")

    def test_child_issue_progress_source_does_not_use_time_tracking_progress(self):
        config = {
            "jira": {
                "base_url": "https://example.atlassian.net",
                "fields": {
                    "leader_engineer": {"field_id": "assignee"},
                    "due_date": {"field_id": "duedate"},
                    "linked_okr": {"field_id": ""},
                    "progress": {
                        "source": "child_issue_progress",
                        "field_id": "",
                    },
                    "status": {"field_id": "status"},
                },
            }
        }
        issue = {
            "key": "DM-10",
            "fields": {
                "summary": "Objective",
                "progress": {"progress": 1, "total": 2},
                "aggregateprogress": {"progress": 1, "total": 2},
            },
        }

        self.assertEqual(normalize_jira_issue(issue, config)["progress"], "")

    def test_child_issue_progress_uses_done_children_over_total_children(self):
        children = [
            {
                "key": "DM-158",
                "fields": {
                    "status": {
                        "name": "Done",
                        "statusCategory": {"key": "done", "name": "Done"},
                    },
                    "issuetype": {"name": "Task", "subtask": False},
                },
            },
            {
                "key": "DM-166",
                "fields": {
                    "status": {
                        "name": "In Progress",
                        "statusCategory": {"key": "indeterminate", "name": "In Progress"},
                    },
                    "issuetype": {"name": "Task", "subtask": False},
                },
            },
        ]

        self.assertEqual(child_issue_progress(children, self.config), "50%")

    def test_issue_property_source_reads_okr_parent_id(self):
        config = {
            "jira": {
                "fields": {
                    "linked_okr": {
                        "source": "issue_property",
                        "property_key": "okr",
                        "path": "value.parentId",
                        "field_id": "",
                    }
                }
            }
        }
        objective = {
            "key": "DM-1",
            "properties": {
                "okr": {
                    "value": {
                        "parentId": "OM-18311",
                    }
                }
            },
        }

        apply_issue_property_fields(objective, config, FixtureJiraAdapter(self.jira_fixture))

        self.assertEqual(objective["linked_okr"], "OM-18311")

    def test_missing_issue_property_source_clears_linked_okr(self):
        config = {
            "jira": {
                "fields": {
                    "linked_okr": {
                        "source": "issue_property",
                        "property_key": "okr",
                        "path": "value.parentId",
                        "field_id": "",
                    }
                }
            }
        }
        objective = {
            "key": "DM-1",
            "properties": {},
            "linked_okr": "stale-value",
        }

        apply_issue_property_fields(objective, config, FixtureJiraAdapter(self.jira_fixture))

        self.assertEqual(objective["linked_okr"], "")


class StartSignalTest(unittest.TestCase):
    def test_child_in_progress_counts_as_start_signal(self):
        objective = {
            "children": [
                {
                    "fields": {
                        "issuetype": {"subtask": False},
                        "status": {"statusCategory": {"key": "indeterminate", "name": "In Progress"}},
                    }
                }
            ]
        }
        self.assertTrue(child_issue_start_signal_seen(objective))
        self.assertTrue(objective_start_signal_seen(objective, None))

    def test_child_done_counts_as_start_signal(self):
        objective = {
            "children": [
                {
                    "fields": {
                        "issuetype": {"subtask": False},
                        "status": {"statusCategory": {"key": "done", "name": "Done"}},
                    }
                }
            ]
        }
        self.assertTrue(child_issue_start_signal_seen(objective))

    def test_subtask_children_are_ignored(self):
        objective = {
            "children": [
                {
                    "fields": {
                        "issuetype": {"subtask": True},
                        "status": {"statusCategory": {"key": "indeterminate", "name": "In Progress"}},
                    }
                }
            ]
        }
        self.assertFalse(child_issue_start_signal_seen(objective))

    def test_to_do_children_are_not_start_signal(self):
        objective = {
            "children": [
                {
                    "fields": {
                        "issuetype": {"subtask": False},
                        "status": {"statusCategory": {"key": "new", "name": "To Do"}},
                    }
                }
            ]
        }
        self.assertFalse(child_issue_start_signal_seen(objective))
        self.assertFalse(objective_start_signal_seen(objective, None))

    def test_objective_status_categories_aggregates_paths(self):
        objective = {
            "status_category": "in progress",
            "status": {"statusCategory": {"key": "indeterminate", "name": "In Progress"}},
        }
        cats = objective_status_categories(objective)
        self.assertIn("in progress", cats)
        self.assertIn("indeterminate", cats)


class TeamSnapshotTest(unittest.TestCase):
    def _config(self):
        return {
            "team": {"id": "test-team", "name": "Test Team", "business_unit": "B2C"},
        }

    def _result(self, objectives):
        return {
            "target_date": "2026-06-30",
            "iso_week": 27,
            "month_label": "objective-june-2026",
            "objectives": objectives,
        }

    def test_bucket_done_wins_over_reported_status(self):
        # Jira status Done + parsed status Green ⇒ done bucket, not spillover_on_track.
        self.assertEqual(
            _bucket_for_objective({"is_done": True, "status": "Green", "jira_status": "Done"}),
            "done",
        )

    def test_bucket_missing_when_no_update(self):
        self.assertEqual(
            _bucket_for_objective({"is_done": False, "missing_update": True, "status": "Missing"}),
            "missing",
        )

    def test_bucket_spillover_from_reported_status(self):
        for status, bucket in [
            ("Green", "spillover_on_track"),
            ("Yellow", "spillover_at_risk"),
            ("Red", "spillover_blocked"),
        ]:
            with self.subTest(status=status):
                self.assertEqual(
                    _bucket_for_objective({
                        "is_done": False,
                        "missing_update": False,
                        "status": status,
                        "jira_status": "In Progress",
                    }),
                    bucket,
                )

    def test_snapshot_totals_add_up_and_carry_business_unit(self):
        payload = build_team_snapshot(
            self._result([
                {"key": "T-1", "status": "Green", "jira_status": "Done", "is_done": True},
                {"key": "T-2", "status": "Yellow", "jira_status": "In Progress"},
                {"key": "T-3", "status": "Red", "jira_status": "In Progress"},
                {"key": "T-4", "status": "Missing", "missing_update": True},
            ]),
            self._config(),
        )
        self.assertEqual(payload["team"]["business_unit"], "B2C")
        totals = payload["totals"]
        self.assertEqual(totals["objectives"], 4)
        self.assertEqual(totals["done"], 1)
        self.assertEqual(totals["spillover_at_risk"], 1)
        self.assertEqual(totals["spillover_blocked"], 1)
        self.assertEqual(totals["missing"], 1)
        self.assertEqual(totals["delivery_rate"], 0.25)
        self.assertEqual(payload["week"]["iso_week"], 27)

    def test_snapshot_empty_objectives_yields_zero_delivery_rate(self):
        payload = build_team_snapshot(self._result([]), self._config())
        self.assertEqual(payload["totals"]["objectives"], 0)
        self.assertEqual(payload["totals"]["delivery_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
