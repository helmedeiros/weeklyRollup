from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from mission_rollup import STATUS_GREEN, STATUS_RED, STATUS_YELLOW  # noqa: E402
from write_dri_update import (  # noqa: E402
    CollectedSections,
    EpicState,
    build_adf_body,
    build_template_text,
    parse_status_input,
    render_menu,
    validate_sections,
)


def make_sections(status=STATUS_GREEN, blockers="") -> CollectedSections:
    return CollectedSections(
        status=status,
        done_this_week="Closed two stories and posted demo.",
        target_next_week="Validate partner edge cases.",
        blockers_risks=blockers,
    )


class TemplateBuilderTest(unittest.TestCase):
    def test_template_includes_status_emoji_and_required_sections(self):
        text = build_template_text(make_sections(STATUS_YELLOW))
        self.assertIn("Status: \U0001F7E1", text)
        self.assertIn("Done this week: Closed two stories", text)
        self.assertIn("Target for next week: Validate partner edge cases.", text)

    def test_template_omits_blockers_when_empty(self):
        text = build_template_text(make_sections(blockers=""))
        self.assertNotIn("Blockers / Risks", text)

    def test_template_includes_blockers_when_present(self):
        text = build_template_text(make_sections(blockers="Owner named in Jira."))
        self.assertIn("Blockers / Risks: Owner named in Jira.", text)


class ValidationLoopTest(unittest.TestCase):
    def test_valid_sections_pass_with_blockers_optional(self):
        ok, errors = validate_sections(
            make_sections(STATUS_RED, blockers=""),
            {"optional_sections": ["blockers"], "require_template_match": True, "minimum_score": 3},
        )
        self.assertTrue(ok, errors)

    def test_unknown_status_is_rejected(self):
        bogus = CollectedSections(
            status="Maybe",  # not a recognised emoji or word
            done_this_week="x",
            target_next_week="y",
            blockers_risks="",
        )
        with self.assertRaises(KeyError):
            build_template_text(bogus)


class AdfBuilderTest(unittest.TestCase):
    def test_adf_status_paragraph_carries_emoji_node(self):
        adf = build_adf_body(make_sections(STATUS_YELLOW))
        status_para = adf["content"][0]
        self.assertEqual(status_para["type"], "paragraph")
        types = [c["type"] for c in status_para["content"]]
        self.assertEqual(types, ["text", "emoji"])
        emoji = status_para["content"][1]
        self.assertEqual(emoji["attrs"]["text"], "\U0001F7E1")
        self.assertEqual(emoji["attrs"]["shortName"], ":yellow_circle:")

    def test_adf_omits_blockers_paragraph_when_empty(self):
        adf = build_adf_body(make_sections(blockers=""))
        bodies = [
            "".join(c.get("text", "") for c in p.get("content", []))
            for p in adf["content"]
        ]
        self.assertFalse(any("Blockers / Risks" in b for b in bodies))


class StatusInputTest(unittest.TestCase):
    def test_recognises_green_word(self):
        self.assertEqual(parse_status_input("Green"), STATUS_GREEN)

    def test_recognises_emoji(self):
        self.assertEqual(parse_status_input("\U0001F7E1"), STATUS_YELLOW)

    def test_rejects_done_as_weekly_status(self):
        # "Done" is a delivery state, not a weekly health status.
        self.assertIsNone(parse_status_input("Done"))

    def test_empty_input_returns_none(self):
        self.assertIsNone(parse_status_input(""))


class MenuRenderingTest(unittest.TestCase):
    def test_menu_lists_epics_with_status_and_dri(self):
        epics = [
            EpicState(
                key="DEMO-200",
                summary="Onboarding conversion refresh",
                url="https://example.atlassian.net/browse/DEMO-200",
                dri_name="Ada Lovelace",
                update_status="missing",
                update_summary="No DRI weekly update",
            ),
            EpicState(
                key="DEMO-300",
                summary="Amenities disclosure V2",
                url="https://example.atlassian.net/browse/DEMO-300",
                dri_name="Grace Hopper",
                update_status="valid \U0001F7E2",
                update_summary="Latest valid update by Grace Hopper",
            ),
        ]
        menu = render_menu(epics)
        self.assertIn(" 1. [missing", menu)
        self.assertIn("DEMO-200", menu)
        self.assertIn("Ada Lovelace", menu)
        self.assertIn(" 2. [valid", menu)
        self.assertIn("Grace Hopper", menu)


if __name__ == "__main__":
    unittest.main()
