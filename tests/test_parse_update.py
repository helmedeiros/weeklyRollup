from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from mission_rollup import (  # noqa: E402
    STATUS_GREEN,
    STATUS_RED,
    STATUS_YELLOW,
    comment_body_to_text,
    evaluate_hygiene,
    extract_blockers,
    parse_update,
)


class ParseUpdateTest(unittest.TestCase):
    def test_parses_required_template_with_status_emoji(self):
        parsed = parse_update(
            "Status: \U0001f7e2\n"
            "Done this week: Merged refund automation PR.\n"
            "Target for next week: Roll out to 10%.\n"
            "Blockers / Risks: none"
        )

        self.assertTrue(parsed.template_valid)
        self.assertEqual(parsed.status, STATUS_GREEN)
        self.assertEqual(parsed.score, 4)
        self.assertEqual(parsed.blockers_risks, "none")

    def test_parses_template_headings_with_values_on_following_lines(self):
        parsed = parse_update(
            "Status\n"
            "\U0001f7e2\n"
            "Done this week\n"
            "All issues are in progress. Meetings held with B2B teams.\n"
            "Target for next week\n"
            "Communicate to engineers and kick-off new process.\n"
            "Blockers / Risks\xa0\n"
            "Testing is limited, due to no missions and process starting from June."
        )

        self.assertTrue(parsed.template_valid)
        self.assertEqual(parsed.status, STATUS_GREEN)
        self.assertEqual(parsed.score, 4)
        self.assertIn("All issues are in progress", parsed.done_this_week)
        self.assertIn("Communicate to engineers", parsed.plan_for_next_week)
        self.assertIn("Testing is limited", parsed.blockers_risks)

    def test_parses_aliases_and_status_words(self):
        parsed = parse_update(
            "State: Yellow\n"
            "Completed: Closed two stories and posted demo.\n"
            "Next week: Validate partner edge cases.\n"
            "Dependencies: @Platform to confirm API timeout by Monday."
        )

        self.assertTrue(parsed.template_valid)
        self.assertEqual(parsed.status, STATUS_YELLOW)
        self.assertIn("Closed two stories", parsed.done_this_week)
        self.assertIn("partner edge cases", parsed.plan_for_next_week)

    def test_risks_slash_blockers_alias_starts_blocker_section(self):
        parsed = parse_update(
            "- Status: at risk\n"
            "- Done this week: maintenence report\n"
            "- Next week: experiments analysis\n"
            "- Risks/blockers: qa freelancer not utilized fully"
        )

        self.assertTrue(parsed.template_valid)
        self.assertEqual(parsed.status, STATUS_YELLOW)
        self.assertEqual(parsed.plan_for_next_week, "experiments analysis")
        self.assertEqual(parsed.blockers_risks, "qa freelancer not utilized fully")

    def test_missing_blockers_section_is_invalid(self):
        parsed = parse_update(
            "Status: Green\n"
            "Done this week: Closed stories.\n"
            "Plan: Continue rollout."
        )

        self.assertFalse(parsed.template_valid)
        self.assertIn("Blockers / risks", parsed.missing_sections)

    def test_optional_blockers_section_allows_three_of_four_template(self):
        parsed = parse_update(
            "Status: at risk,\n"
            "Done this week: stakeholders, program kick off\n"
            "Next week: risks & timeline\n"
            "New date: in June",
            minimum_score=3,
            optional_sections=["blockers"],
        )

        self.assertTrue(parsed.template_valid)
        self.assertEqual(parsed.status, STATUS_YELLOW)
        self.assertEqual(parsed.score, 3)
        self.assertEqual(parsed.blockers_risks, "")
        self.assertEqual(parsed.missing_sections, [])

    def test_optional_blockers_still_requires_done_and_plan(self):
        parsed = parse_update(
            "Status: Yellow\n"
            "Done this week: stakeholders, program kick off\n"
            "Blockers / risks: Timeline risk",
            minimum_score=3,
            optional_sections=["blockers"],
        )

        self.assertFalse(parsed.template_valid)
        self.assertIn("Plan for next week", parsed.missing_sections)

    def test_only_blockers_can_be_optional(self):
        parsed = parse_update(
            "Status: Yellow\n"
            "Done this week: stakeholders, program kick off\n"
            "Blockers / risks: Timeline risk",
            minimum_score=3,
            optional_sections=["plan"],
        )

        self.assertFalse(parsed.template_valid)
        self.assertIn("Plan for next week", parsed.missing_sections)

    def test_casual_status_note_is_invalid(self):
        parsed = parse_update("\U0001f7e2 still fine, fixed typo above")

        self.assertFalse(parsed.template_valid)
        self.assertIn("Status", parsed.missing_sections)

    def test_red_status_parses(self):
        parsed = parse_update(
            "Status: Red\n"
            "Done: Investigation only.\n"
            "Plan: Replan with EM.\n"
            "Risks: Capacity gap remains."
        )

        self.assertTrue(parsed.template_valid)
        self.assertEqual(parsed.status, STATUS_RED)

    def test_done_status_is_not_valid_weekly_health(self):
        parsed = parse_update(
            "Status: Done\n"
            "Done: Completed rollout.\n"
            "Plan: Monitor adoption.\n"
            "Blockers: none"
        )

        self.assertFalse(parsed.template_valid)
        self.assertIsNone(parsed.status)
        self.assertIn("Status must be Green, Yellow, Red, or the matching status emoji", parsed.errors)

    def test_status_delivery_language_parses(self):
        cases = [
            ("On track to ship agreed scope by the due date", STATUS_GREEN),
            ("at risk,", STATUS_YELLOW),
            ("Unclear target date and scope concern", STATUS_YELLOW),
            ("Delayed more than two weeks", STATUS_RED),
            ("Off track, will not ship without replan", STATUS_RED),
        ]

        for status_text, expected_status in cases:
            with self.subTest(status_text=status_text):
                parsed = parse_update(
                    f"Status: {status_text}\n"
                    "Done: Closed two stories.\n"
                    "Plan: Resolve the remaining item next week.\n"
                    "Blockers / risks: Owner named in Jira."
                )

                self.assertTrue(parsed.template_valid)
                self.assertEqual(parsed.status, expected_status)

    def test_core_platform_is_not_treated_as_section_header(self):
        parsed = parse_update(
            "Status: Yellow\n"
            "Done this week: Core platform review completed.\n"
            "Target for next week: Continue integration.\n"
            "Blockers / Risks:\n"
            "risk from core platform\n"
            "owner: Platform team"
        )

        self.assertTrue(parsed.template_valid)
        self.assertEqual(parsed.status, STATUS_YELLOW)
        self.assertIn("risk from core platform", parsed.blockers_risks)
        self.assertIn("owner: Platform team", parsed.blockers_risks)

    def test_risk_from_core_platform_inline_text_remains_risk_content(self):
        parsed = parse_update(
            "Status: Yellow\n"
            "Done this week: API contract is drafted.\n"
            "Target for next week: Confirm rollout plan.\n"
            "Blockers / Risks: risk from core platform"
        )

        self.assertTrue(parsed.template_valid)
        self.assertEqual(parsed.blockers_risks, "risk from core platform")

    def test_known_blocker_alias_decisions_needed_still_parses(self):
        parsed = parse_update(
            "Status: Yellow\n"
            "Done this week: Scope proposal prepared.\n"
            "Plan for next week: Confirm final owner.\n"
            "Decisions needed: PM lead to approve scope."
        )

        self.assertTrue(parsed.template_valid)
        self.assertIn("PM lead", parsed.blockers_risks)

    def test_extracts_blockers_with_owner_and_days_open(self):
        blockers = extract_blockers(
            "- Waiting for @Data Platform export, open 3 days\n"
            "- Owner: PM Lead to decide scope",
            mission="Checkout refund automation",
            dri="Ada Lovelace",
            status=STATUS_YELLOW,
        )

        self.assertEqual(len(blockers), 2)
        self.assertEqual(blockers[0].owner, "Data Platform export")
        self.assertEqual(blockers[0].days_open, "3")
        self.assertEqual(blockers[1].owner, "PM Lead to decide scope")

    def test_none_blockers_create_no_rows(self):
        blockers = extract_blockers(
            "none",
            mission="Checkout refund automation",
            dri="Ada Lovelace",
            status=STATUS_GREEN,
        )

        self.assertEqual(blockers, [])

    def test_no_active_blockers_with_context_create_no_rows(self):
        blockers = extract_blockers(
            "No active blockers, monitoring rollout.",
            mission="Delay Repay for Uber",
            dri="Ada Lovelace",
            status=STATUS_GREEN,
        )

        self.assertEqual(blockers, [])

    def test_non_blocker_phrases_with_follow_up_context_create_no_rows(self):
        cases = [
            "No blockers, monitoring rollout.",
            "No hard blocker right now.",
            "No current risk right now.",
            "No risks - metrics are being watched.",
            "No active risks; continuing QA validation.",
        ]

        for blockers_text in cases:
            with self.subTest(blockers_text=blockers_text):
                parsed = parse_update(
                    "Status: Green\n"
                    "Done: Continued rollout.\n"
                    "Plan: Keep monitoring.\n"
                    f"Blockers / risks: {blockers_text}"
                )

                self.assertTrue(parsed.template_valid)
                self.assertEqual(
                    extract_blockers(
                        parsed.blockers_risks,
                        mission="Delay Repay for Uber",
                        dri="Ada Lovelace",
                        status=STATUS_GREEN,
                    ),
                    [],
                )

    def test_no_blockers_with_exception_still_creates_risk_row(self):
        blockers = extract_blockers(
            "No blockers except QA capacity risk.",
            mission="Delay Repay for Uber",
            dri="Ada Lovelace",
            status=STATUS_YELLOW,
        )

        self.assertEqual(len(blockers), 1)
        self.assertIn("QA capacity risk", blockers[0].text)

    def test_hygiene_warns_for_missing_resolution_path(self):
        config = {
            "team": {},
            "weekly_update": {"validation": {"no_update_red_after_weeks": 2}},
        }
        parsed = parse_update(
            "Status: Yellow\n"
            "Done: Closed one story.\n"
            "Plan: \n"
            "Blockers: none",
            require_template_match=False,
            minimum_score=3,
        )
        mission = {
            "dri": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
            "due_date": "2026-06-30",
            "linked_okr": "KR-1",
        }

        issues = evaluate_hygiene(
            mission,
            config,
            parsed,
            missing_update=False,
            previous_due_date="2026-06-30",
        )

        self.assertIn(
            "Yellow/red status without blocker or resolution path",
            [issue["message"] for issue in issues],
        )

    def test_hygiene_flags_open_delayed_carryover_mission(self):
        config = {
            "team": {},
            "weekly_update": {"validation": {"no_update_red_after_weeks": 2}},
        }
        parsed = parse_update(
            "Status: Green\n"
            "Done: Closed one story.\n"
            "Plan: Continue rollout.\n"
            "Blockers: none"
        )
        mission = {
            "mission_type": "spillover",
            "dri": {"accountId": "ada-account", "displayName": "Ada Lovelace"},
            "due_date": "2026-05-31",
            "linked_okr": "KR-1",
        }

        issues = evaluate_hygiene(
            mission,
            config,
            parsed,
            missing_update=False,
            previous_due_date="2026-05-31",
        )

        issue_by_message = {issue["message"]: issue for issue in issues}
        self.assertEqual(
            issue_by_message["Delayed carryover mission still open"]["severity"],
            "yellow",
        )


class AdfEmojiTest(unittest.TestCase):
    def test_adf_emoji_node_yields_character(self):
        adf = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Status: "},
                        {
                            "type": "emoji",
                            "attrs": {
                                "shortName": ":yellow_circle:",
                                "id": "1f7e1",
                                "text": "\U0001f7e1",
                            },
                        },
                    ],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Done this week: shipped."}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Target for next week: validate."}],
                },
            ],
        }
        text = comment_body_to_text(adf)
        self.assertIn("\U0001f7e1", text)
        parsed = parse_update(text, optional_sections=["blockers"])
        self.assertTrue(parsed.template_valid)
        self.assertEqual(parsed.status, STATUS_YELLOW)

    def test_planned_for_next_week_heading_maps_to_plan(self):
        # Regression: Madhura's update wrote "Planned For Next Week" as a heading
        # without a colon. The plan section was absorbed into done and the
        # update was marked malformed.
        parsed = parse_update(
            "Status: On Track\n"
            "Done This Week\n"
            "Aligned with Data on the input-file ticket.\n"
            "Built an agent to identify reachable users.\n"
            "Planned For Next Week\n"
            "Review recommendations with CRM and fine-tune the decision logic.\n"
            "Coordinate with CRM to set up campaigns.\n"
            "Blockers / Risks\n"
            "Next week is short; CRM review may slip.",
            optional_sections=["blockers"],
        )
        self.assertTrue(parsed.template_valid)
        self.assertEqual(parsed.status, STATUS_GREEN)
        self.assertIn("Aligned with Data", parsed.done_this_week)
        self.assertNotIn("Planned For Next Week", parsed.done_this_week)
        self.assertIn("Review recommendations", parsed.plan_for_next_week)
        self.assertIn("CRM review may slip", parsed.blockers_risks)

    def test_progress_update_heading_maps_to_done(self):
        parsed = parse_update(
            "Status: \U0001f7e1\n"
            "Discovery Progress Update\n"
            "Reviewed mission brief and aligned with enabler teams.\n"
            "Target for next week: Confirm available signals.\n"
            "Blockers / Risks: Dataset not confirmed yet.",
            optional_sections=["blockers"],
        )
        self.assertTrue(parsed.template_valid)
        self.assertEqual(parsed.status, STATUS_YELLOW)
        self.assertIn("Reviewed mission brief", parsed.done_this_week)

    def test_adf_mention_node_yields_text(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Talked to "},
                        {
                            "type": "mention",
                            "attrs": {
                                "id": "abc",
                                "text": "@Helio",
                                "displayName": "Helio",
                            },
                        },
                    ],
                }
            ],
        }
        self.assertIn("@Helio", comment_body_to_text(adf))


if __name__ == "__main__":
    unittest.main()
