from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from objective_rollup import (  # noqa: E402
    STATUS_DONE,
    STATUS_GREEN,
    STATUS_MISSING,
    STATUS_RED,
    STATUS_YELLOW,
    load_config,
    render_email_draft,
)


class RenderEmailTest(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "tests/fixtures/team-config.yaml")

    def test_render_is_draft_only_with_default_recipients(self):
        draft = render_email_draft(
            self.config,
            [
                {
                    "objective": "Checkout refund automation",
                    "month_label": "June",
                    "leader_engineer": "Ada Lovelace",
                    "status": STATUS_GREEN,
                    "progress": "50%",
                    "due_date": "2026-06-30",
                    "done_this_week": "Merged validation PR.",
                    "plan_for_next_week": "Roll out to 10%.",
                    "blockers": [],
                    "hygiene": [],
                    "missing_update": False,
                }
            ],
            iso_week=23,
            sheet_url="https://docs.google.com/spreadsheets/d/spreadsheet-123",
        )

        self.assertTrue(draft["create_draft_only"])
        self.assertEqual(draft["to"], ["objective-report@example.com"])
        self.assertEqual(draft["cc"], ["reviewer@example.com"])
        self.assertEqual(draft["bcc"], [])
        self.assertEqual(draft["plainTextBody"], draft["text_body"])
        self.assertEqual(draft["htmlBody"], draft["html_body"])
        self.assertIn("Weekly Objective Update", draft["subject"])
        # Banner now mirrors the subject; the old fixed "Weekly Objective Report"
        # heading was removed (upstream f7cbd7b19 / 8a5f22851 port).
        self.assertIn(draft["subject"], draft["html_body"])
        self.assertNotIn("Weekly Objective Report", draft["html_body"])
        self.assertIn("#132968", draft["html_body"])
        self.assertIn("On Track", draft["html_body"])
        self.assertNotIn("{{", draft["html_body"])
        self.assertNotIn("{%", draft["html_body"])
        self.assertNotIn("Linked OKR", draft["html_body"])
        self.assertIn("No active blockers reported.", draft["html_body"])
        self.assertNotIn("Data Hygiene", draft["html_body"])
        self.assertNotIn("DATA HYGIENE", draft["text_body"])
        self.assertNotIn("No data hygiene issues found.", draft["html_body"])
        self.assertNotIn("No data hygiene issues found.", draft["text_body"])
        self.assertIn("Hi<br><br>", draft["html_body"])
        self.assertNotIn("Hi team", draft["html_body"])
        self.assertIn("Kind Regards<br>", draft["html_body"])
        self.assertNotIn("Draft generated for EM review", draft["html_body"])
        self.assertNotIn("Please verify before sending", draft["html_body"])
        self.assertIn("On Track</span>", draft["html_body"])
        self.assertIn("Checkout refund automation (June)", draft["html_body"])
        self.assertIn("[ON TRACK] Checkout refund automation (June)", draft["text_body"])
        self.assertIn("background-color:#f0fdf4", draft["html_body"])
        self.assertTrue((ROOT / "templates/objective-email.html").exists())

    def test_greeting_is_configurable(self):
        config = dict(self.config)
        config["email"] = dict(self.config["email"])
        config["email"]["greeting"] = "Hello"

        draft = render_email_draft(config, [], iso_week=23)

        self.assertIn("Hello<br><br>", draft["html_body"])
        self.assertIn("\nHello\n\nPlease find", draft["text_body"])

    def test_due_date_delay_is_rendered_inline_without_movement_row(self):
        draft = render_email_draft(
            self.config,
            [
                {
                    "objective": "Delivery strategy",
                    "month_label": "May",
                    "leader_engineer": "Ada Lovelace",
                    "status": STATUS_RED,
                    "progress": "50%",
                    "due_date": "2026-06-11",
                    "due_date_movement": "2025-10-01 -> 2026-06-11 (+253d)",
                    "due_date_overdue_days": 0,
                    "done_this_week": "RACI, roadmap, AHM playbook",
                    "plan_for_next_week": "Roadmap pt2",
                    "blockers": [],
                    "hygiene": [],
                    "missing_update": False,
                },
                {
                    "objective": "Overdue moved objective",
                    "month_label": "June",
                    "leader_engineer": "Grace Hopper",
                    "status": STATUS_RED,
                    "progress": "40%",
                    "due_date": "2026-06-01",
                    "due_date_movement": "2026-05-01 -> 2026-06-01 (+31d)",
                    "due_date_overdue_days": 4,
                    "done_this_week": "Replanned rollout",
                    "plan_for_next_week": "Close overdue items",
                    "blockers": [],
                    "hygiene": [],
                    "missing_update": False,
                },
                {
                    "objective": "Pulled-in objective",
                    "month_label": "June",
                    "leader_engineer": "Katherine Johnson",
                    "status": STATUS_GREEN,
                    "progress": "80%",
                    "due_date": "2026-06-04",
                    "due_date_movement": "2026-06-11 -> 2026-06-04 (-7d)",
                    "due_date_overdue_days": 0,
                    "done_this_week": "Pulled in launch",
                    "plan_for_next_week": "Monitor",
                    "blockers": [],
                    "hygiene": [],
                    "missing_update": False,
                }
            ],
            iso_week=23,
        )

        self.assertIn(
            "Due: 11 Jun (original: 1 Oct 2025, moved later 253 days)",
            draft["text_body"],
        )
        self.assertIn(
            "Due: 11 Jun (original: 1 Oct 2025, moved later 253 days)",
            draft["html_body"],
        )
        self.assertIn(
            "Due: 1 Jun (original: 1 May, moved later 31 days, overdue 4 days)",
            draft["text_body"],
        )
        self.assertIn(
            "Due: 4 Jun (original: 11 Jun, moved earlier 7 days)",
            draft["text_body"],
        )
        self.assertIn("[DELAYED] Delivery strategy (May)", draft["text_body"])
        self.assertIn("Delivery strategy (May)", draft["html_body"])
        self.assertNotIn("Due date movement:", draft["text_body"])
        self.assertNotIn("Movement:", draft["html_body"])
        self.assertNotIn("spillover", draft["text_body"].lower())
        self.assertNotIn("spillover", draft["html_body"].lower())

    def test_signoff_is_configurable(self):
        config = dict(self.config)
        config["email"] = dict(self.config["email"])
        config["email"]["signoff"] = "Thanks"
        config["email"]["signoff_name"] = "Ada"

        draft = render_email_draft(config, [], iso_week=23)

        self.assertIn("Thanks<br>", draft["html_body"])
        self.assertIn(">Ada</strong>", draft["html_body"])
        self.assertIn("\nThanks\nAda", draft["text_body"])

    def test_objectives_sort_on_track_at_risk_delayed_missing(self):
        draft = render_email_draft(
            self.config,
            [
                {
                    "objective": "Green objective",
                    "leader_engineer": "Grace Hopper",
                    "status": STATUS_GREEN,
                    "progress": "80%",
                    "due_date": "2026-06-30",
                    "done_this_week": "Done",
                    "plan_for_next_week": "Continue",
                    "blockers": [],
                    "hygiene": [],
                    "missing_update": False,
                },
                {
                    "objective": "Yellow objective",
                    "leader_engineer": "Katherine Johnson",
                    "status": STATUS_YELLOW,
                    "progress": "60%",
                    "due_date": "2026-06-30",
                    "done_this_week": "In progress",
                    "plan_for_next_week": "Reduce risk",
                    "blockers": [],
                    "hygiene": [],
                    "missing_update": False,
                },
                {
                    "objective": "Missing objective",
                    "leader_engineer": "Mary Jackson",
                    "status": STATUS_MISSING,
                    "progress": "0%",
                    "due_date": "",
                    "done_this_week": "",
                    "plan_for_next_week": "",
                    "blockers": [],
                    "hygiene": [],
                    "missing_update": True,
                },
                {
                    "objective": "Red objective",
                    "leader_engineer": "Ada Lovelace",
                    "status": STATUS_RED,
                    "progress": "20%",
                    "due_date": "2026-06-30",
                    "done_this_week": "Blocked",
                    "plan_for_next_week": "Replan",
                    "blockers": [
                        {
                            "objective": "Red objective",
                            "leader_engineer": "Ada Lovelace",
                            "status": STATUS_RED,
                            "text": "Decision needed",
                            "owner": "Lead",
                            "days_open": "2",
                        }
                    ],
                    "hygiene": [{"severity": "yellow", "message": "Missing linked OKR"}],
                    "missing_update": False,
                },
                {
                    "objective": "Done objective",
                    "leader_engineer": "Dorothy Vaughan",
                    "status": STATUS_DONE,
                    "progress": "100%",
                    "due_date": "2026-06-30",
                    "done_this_week": "Completed",
                    "plan_for_next_week": "Monitor",
                    "blockers": [],
                    "hygiene": [],
                    "missing_update": False,
                },
            ],
            iso_week=23,
        )

        self.assertLess(draft["text_body"].index("Green objective"), draft["text_body"].index("Yellow objective"))
        self.assertLess(draft["text_body"].index("Yellow objective"), draft["text_body"].index("Red objective"))
        self.assertLess(draft["text_body"].index("Red objective"), draft["text_body"].index("Missing objective"))
        self.assertLess(draft["text_body"].index("Missing objective"), draft["text_body"].index("Done objective"))
        self.assertIn("Missing linked OKR", draft["text_body"])
        self.assertLess(draft["html_body"].index("Green objective"), draft["html_body"].index("Yellow objective"))
        self.assertLess(draft["html_body"].index("Yellow objective"), draft["html_body"].index("Red objective"))
        self.assertLess(draft["html_body"].index("Red objective"), draft["html_body"].index("Missing objective"))
        self.assertLess(draft["html_body"].index("Missing objective"), draft["html_body"].index("Done objective"))
        self.assertIn("Done</span>", draft["html_body"])
        self.assertIn("background-color:#dbeafe", draft["html_body"])
        self.assertIn("color:#2563eb", draft["html_body"])

    def test_hygiene_uses_color_marker_without_visible_severity_label(self):
        draft = render_email_draft(
            self.config,
            [
                {
                    "objective": "Hygiene objective",
                    "leader_engineer": "Ada Lovelace",
                    "status": STATUS_GREEN,
                    "progress": "50%",
                    "due_date": "2026-06-30",
                    "done_this_week": "Done",
                    "plan_for_next_week": "Continue",
                    "blockers": [],
                    "hygiene": [{"severity": "red", "message": "Missing due date"}],
                    "missing_update": False,
                }
            ],
            iso_week=23,
        )

        hygiene_section = draft["html_body"].split("Data Hygiene", 1)[1]
        self.assertIn("Missing due date", hygiene_section)
        self.assertNotIn(">red<", hygiene_section.lower())

    def test_hygiene_section_is_omitted_when_only_info_or_empty(self):
        draft = render_email_draft(
            self.config,
            [
                {
                    "objective": "Clean objective",
                    "leader_engineer": "Ada Lovelace",
                    "status": STATUS_GREEN,
                    "progress": "50%",
                    "due_date": "2026-06-30",
                    "done_this_week": "Done",
                    "plan_for_next_week": "Continue",
                    "blockers": [],
                    "hygiene": [{"severity": "info", "message": "No blockers reported"}],
                    "missing_update": False,
                }
            ],
            iso_week=23,
        )

        self.assertNotIn("Data Hygiene", draft["html_body"])
        self.assertNotIn("DATA HYGIENE", draft["text_body"])
        self.assertNotIn("No data hygiene issues found.", draft["html_body"])
        self.assertNotIn("No data hygiene issues found.", draft["text_body"])


if __name__ == "__main__":
    unittest.main()
