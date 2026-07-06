from datetime import date, datetime
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from objective_rollup import (  # noqa: E402
    SHEET_COLUMNS,
    compute_week_window,
    month_label,
    month_label_display,
    month_label_end_date,
    month_label_short_display,
    sheet_values,
    week_tab_name,
)


class SheetTabNamingTest(unittest.TestCase):
    def test_week_tab_name_uses_iso_week_number(self):
        self.assertEqual(week_tab_name(24, "Week {iso_week}"), "Week 24")

    def test_month_label_uses_lowercase_month_name(self):
        self.assertEqual(month_label(6, 2026, "objective-{month}-{year}"), "objective-june-2026")

    def test_month_label_display_uses_readable_month(self):
        self.assertEqual(month_label_display("objective-may-2026"), "May 2026")
        self.assertEqual(month_label_display("objective-june-2026"), "June 2026")
        self.assertEqual(month_label_short_display("objective-may-2026"), "May")
        self.assertEqual(month_label_short_display("objective-june-2026"), "June")

    def test_month_label_end_date_uses_last_day_of_month(self):
        self.assertEqual(month_label_end_date("objective-may-2026"), date(2026, 5, 31))
        self.assertEqual(month_label_end_date("objective-february-2028"), date(2028, 2, 29))

    def test_week_window_uses_team_timezone(self):
        start, cutoff, week = compute_week_window(
            date(2026, 6, 4),
            "Europe/Prague",
            {
                "start_day": "monday",
                "start_time": "00:00",
                "cutoff_day": "friday",
                "cutoff_time": "17:00",
            },
        )

        self.assertEqual(week, 23)
        self.assertEqual(start, datetime(2026, 6, 1, 0, 0, tzinfo=ZoneInfo("Europe/Prague")))
        self.assertEqual(cutoff, datetime(2026, 6, 5, 17, 0, tzinfo=ZoneInfo("Europe/Prague")))

    def test_sheet_values_add_headers(self):
        values = sheet_values([["DM-1"]])

        self.assertEqual(values[0], SHEET_COLUMNS)
        self.assertEqual(values[1], ["DM-1"])

    def test_sheet_headers_keep_review_fields_without_comment_diagnostics(self):
        self.assertIn("Leader Engineer comment", SHEET_COLUMNS)
        self.assertIn("Hygiene issues", SHEET_COLUMNS)
        self.assertNotIn("Run date", SHEET_COLUMNS)
        self.assertNotIn("Week", SHEET_COLUMNS)
        self.assertNotIn("Team", SHEET_COLUMNS)
        self.assertNotIn("Template valid?", SHEET_COLUMNS)
        self.assertNotIn("Linked OKR", SHEET_COLUMNS)
        self.assertNotIn("Latest valid comment timestamp", SHEET_COLUMNS)
        self.assertNotIn("Latest valid comment URL", SHEET_COLUMNS)


if __name__ == "__main__":
    unittest.main()
