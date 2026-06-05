from datetime import datetime
import json
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from mission_rollup import STATUS_GREEN, find_latest_valid_dri_comment  # noqa: E402


TZ = ZoneInfo("Europe/Prague")
WINDOW_START = datetime(2026, 6, 1, 0, 0, tzinfo=TZ)
WINDOW_END = datetime(2026, 6, 5, 17, 0, tzinfo=TZ)
DRI = {"accountId": "ada-account", "displayName": "Ada Lovelace"}


def valid_body(status="Green"):
    return (
        f"Status: {status}\n"
        "Done this week: Merged checkout validation PR.\n"
        "Target for next week: Roll out to 10%.\n"
        "Blockers / Risks: none"
    )


class CommentSelectionTest(unittest.TestCase):
    def test_latest_valid_selected_not_latest_dri_comment(self):
        comments = json.loads((ROOT / "tests/fixtures/comments.json").read_text())

        selection = find_latest_valid_dri_comment(comments, DRI, WINDOW_START, WINDOW_END)

        self.assertFalse(selection.missing_update)
        self.assertEqual(selection.selected_comment["id"], "valid-1500")
        self.assertEqual(selection.parsed_update.status, STATUS_GREEN)
        self.assertFalse(selection.malformed_update_seen)

    def test_malformed_seen_when_no_valid_update_exists(self):
        comments = [
            {
                "id": "typo-1600",
                "created": "2026-06-04T16:00:00+02:00",
                "author": DRI,
                "body": "fixed typo above",
            }
        ]

        selection = find_latest_valid_dri_comment(comments, DRI, WINDOW_START, WINDOW_END)

        self.assertTrue(selection.missing_update)
        self.assertTrue(selection.malformed_update_seen)

    def test_non_dri_update_does_not_count(self):
        comments = [
            {
                "id": "em-update",
                "created": "2026-06-04T15:00:00+02:00",
                "author": {"accountId": "em-account", "displayName": "EM"},
                "body": valid_body(),
            }
        ]

        selection = find_latest_valid_dri_comment(comments, DRI, WINDOW_START, WINDOW_END)

        self.assertTrue(selection.missing_update)
        self.assertIn("author is not DRI", selection.rejection_reasons[0])

    def test_outside_weekly_window_does_not_count(self):
        comments = [
            {
                "id": "late",
                "created": "2026-06-05T18:00:00+02:00",
                "author": DRI,
                "body": valid_body(),
            }
        ]

        selection = find_latest_valid_dri_comment(comments, DRI, WINDOW_START, WINDOW_END)

        self.assertTrue(selection.missing_update)
        self.assertIn("outside weekly window", selection.rejection_reasons[0])

    def test_latest_of_two_valid_updates_is_selected(self):
        comments = [
            {
                "id": "first",
                "created": "2026-06-04T10:00:00+02:00",
                "author": DRI,
                "body": valid_body("Yellow"),
            },
            {
                "id": "second",
                "created": "2026-06-04T15:00:00+02:00",
                "author": DRI,
                "body": valid_body("Green"),
            },
        ]

        selection = find_latest_valid_dri_comment(comments, DRI, WINDOW_START, WINDOW_END)

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
        dri = {"displayName": "Ada Lovelace"}

        selection = find_latest_valid_dri_comment(comments, dri, WINDOW_START, WINDOW_END)

        self.assertFalse(selection.missing_update)
        self.assertEqual(selection.selected_comment["id"], "display-name")


if __name__ == "__main__":
    unittest.main()
