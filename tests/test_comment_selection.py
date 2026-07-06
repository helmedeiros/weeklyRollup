from datetime import datetime
import json
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from objective_rollup import STATUS_GREEN, find_latest_valid_leader_engineer_comment  # noqa: E402


TZ = ZoneInfo("Europe/Prague")
WINDOW_START = datetime(2026, 6, 1, 0, 0, tzinfo=TZ)
WINDOW_END = datetime(2026, 6, 5, 17, 0, tzinfo=TZ)
LEADER_ENGINEER = {"accountId": "ada-account", "displayName": "Ada Lovelace"}


def valid_body(status="Green"):
    return (
        f"Status: {status}\n"
        "Done this week: Merged checkout validation PR.\n"
        "Target for next week: Roll out to 10%.\n"
        "Blockers / Risks: none"
    )


class CommentSelectionTest(unittest.TestCase):
    def test_latest_valid_selected_not_latest_leader_engineer_comment(self):
        comments = json.loads((ROOT / "tests/fixtures/comments.json").read_text())

        selection = find_latest_valid_leader_engineer_comment(comments, LEADER_ENGINEER, WINDOW_START, WINDOW_END)

        self.assertFalse(selection.missing_update)
        self.assertEqual(selection.selected_comment["id"], "valid-1500")
        self.assertEqual(selection.parsed_update.status, STATUS_GREEN)
        self.assertFalse(selection.malformed_update_seen)

    def test_malformed_seen_when_no_valid_update_exists(self):
        comments = [
            {
                "id": "typo-1600",
                "created": "2026-06-04T16:00:00+02:00",
                "author": LEADER_ENGINEER,
                "body": "fixed typo above",
            }
        ]

        selection = find_latest_valid_leader_engineer_comment(comments, LEADER_ENGINEER, WINDOW_START, WINDOW_END)

        self.assertTrue(selection.missing_update)
        self.assertTrue(selection.malformed_update_seen)

    def test_non_leader_engineer_update_does_not_count(self):
        comments = [
            {
                "id": "em-update",
                "created": "2026-06-04T15:00:00+02:00",
                "author": {"accountId": "em-account", "displayName": "EM"},
                "body": valid_body(),
            }
        ]

        selection = find_latest_valid_leader_engineer_comment(comments, LEADER_ENGINEER, WINDOW_START, WINDOW_END)

        self.assertTrue(selection.missing_update)
        self.assertIn("author is not Leader Engineer", selection.rejection_reasons[0])

    def test_cover_author_accepted_when_leader_engineer_did_not_comment(self):
        comments = [
            {
                "id": "em-cover",
                "created": "2026-06-04T15:00:00+02:00",
                "author": {
                    "accountId": "em-account",
                    "displayName": "Helio Medeiros",
                    "emailAddress": "cover.author@example.com",
                },
                "body": valid_body(),
            }
        ]

        selection = find_latest_valid_leader_engineer_comment(
            comments,
            LEADER_ENGINEER,
            WINDOW_START,
            WINDOW_END,
            cover_emails=["cover.author@example.com"],
        )

        self.assertFalse(selection.missing_update)
        self.assertTrue(selection.cover_author)
        self.assertEqual(selection.selected_comment["id"], "em-cover")
        self.assertEqual(selection.parsed_update.status, STATUS_GREEN)

    def test_cover_author_match_is_case_insensitive(self):
        comments = [
            {
                "id": "em-cover-upper",
                "created": "2026-06-04T15:00:00+02:00",
                "author": {
                    "accountId": "em-account",
                    "displayName": "Helio Medeiros",
                    "emailAddress": "Cover.Author@Example.com",
                },
                "body": valid_body(),
            }
        ]

        selection = find_latest_valid_leader_engineer_comment(
            comments,
            LEADER_ENGINEER,
            WINDOW_START,
            WINDOW_END,
            cover_emails=["cover.author@example.com"],
        )

        self.assertFalse(selection.missing_update)
        self.assertTrue(selection.cover_author)

    def test_leader_engineer_comment_does_not_flag_cover_author(self):
        comments = [
            {
                "id": "leader_engineer-comment",
                "created": "2026-06-04T10:00:00+02:00",
                "author": LEADER_ENGINEER,
                "body": valid_body(),
            }
        ]

        selection = find_latest_valid_leader_engineer_comment(
            comments,
            LEADER_ENGINEER,
            WINDOW_START,
            WINDOW_END,
            cover_emails=["cover.author@example.com"],
        )

        self.assertFalse(selection.missing_update)
        self.assertFalse(selection.cover_author)

    def test_outside_weekly_window_does_not_count(self):
        comments = [
            {
                "id": "late",
                "created": "2026-06-05T18:00:00+02:00",
                "author": LEADER_ENGINEER,
                "body": valid_body(),
            }
        ]

        selection = find_latest_valid_leader_engineer_comment(comments, LEADER_ENGINEER, WINDOW_START, WINDOW_END)

        self.assertTrue(selection.missing_update)
        self.assertIn("outside weekly window", selection.rejection_reasons[0])

    def test_latest_of_two_valid_updates_is_selected(self):
        comments = [
            {
                "id": "first",
                "created": "2026-06-04T10:00:00+02:00",
                "author": LEADER_ENGINEER,
                "body": valid_body("Yellow"),
            },
            {
                "id": "second",
                "created": "2026-06-04T15:00:00+02:00",
                "author": LEADER_ENGINEER,
                "body": valid_body("Green"),
            },
        ]

        selection = find_latest_valid_leader_engineer_comment(comments, LEADER_ENGINEER, WINDOW_START, WINDOW_END)

        self.assertEqual(selection.selected_comment["id"], "second")
        self.assertEqual(selection.parsed_update.status, STATUS_GREEN)

    def test_display_name_fallback_matches_when_account_id_missing(self):
        comments = [
            {
                "id": "display-name",
                "created": "2026-06-04T15:00:00+02:00",
                "author": {"displayName": "Ada Lovelace"},
                "body": valid_body(),
            }
        ]
        leader_engineer = {"displayName": "Ada Lovelace"}

        selection = find_latest_valid_leader_engineer_comment(comments, leader_engineer, WINDOW_START, WINDOW_END)

        self.assertFalse(selection.missing_update)
        self.assertEqual(selection.selected_comment["id"], "display-name")


if __name__ == "__main__":
    unittest.main()
