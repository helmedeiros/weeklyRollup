from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from mission_rollup import (  # noqa: E402
    author_matches,
    load_config,
    sheet_file_name,
    validate_expected_team,
    validate_team_config,
)


class ConfigValidationTest(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "tests/fixtures/team-config.yaml")

    def test_fixture_config_is_valid(self):
        self.assertEqual(validate_team_config(self.config), [])

    def test_missing_sheet_folder_fails_fast(self):
        config = deepcopy(self.config)
        config["sheet"]["folder_id"] = ""

        errors = validate_team_config(config)

        self.assertIn("Missing required config value: sheet.folder_id", errors)

    def test_spreadsheet_id_is_rejected(self):
        config = deepcopy(self.config)
        config["sheet"]["spreadsheet_id"] = "spreadsheet-123"

        errors = validate_team_config(config)

        self.assertIn("sheet.spreadsheet_id is not supported; use sheet.folder_id and file_name_pattern", errors)

    def test_wrong_sheet_folder_fails_fast_when_required_id_is_set(self):
        import os
        from unittest.mock import patch

        config = deepcopy(self.config)
        config["sheet"]["folder_id"] = "another-folder-id"

        with patch("mission_rollup.REQUIRED_SHEET_FOLDER_ID", "expected-folder-id"):
            errors = validate_team_config(config)

        self.assertTrue(
            any("does not match the required folder id" in message for message in errors),
            f"Expected a mismatch error in {errors}",
        )

    def test_folder_id_enforcement_is_skipped_when_env_is_unset(self):
        from unittest.mock import patch

        config = deepcopy(self.config)
        config["sheet"]["folder_id"] = "some-other-folder"

        with patch("mission_rollup.REQUIRED_SHEET_FOLDER_ID", ""):
            errors = validate_team_config(config)

        self.assertFalse(
            any("required folder id" in message for message in errors),
            f"No enforcement expected when required id is unset; got {errors}",
        )

    def test_folder_only_sheet_config_is_valid(self):
        config = deepcopy(self.config)

        self.assertEqual(validate_team_config(config), [])
        self.assertEqual(sheet_file_name(config), "Test Team - Mission Execution Updates")

    def test_smtp_email_config_is_rejected(self):
        config = deepcopy(self.config)
        config["email"]["smtp_host"] = "smtp.gmail.com"

        errors = validate_team_config(config)

        self.assertIn("email.smtp_host is not supported; use rendered draft output instead", errors)

    def test_invalid_timezone_is_actionable(self):
        config = deepcopy(self.config)
        config["team"]["timezone"] = "Not/AZone"

        errors = validate_team_config(config)

        self.assertIn("Invalid team.timezone: Not/AZone", errors)

    def test_email_must_be_draft_only(self):
        config = deepcopy(self.config)
        config["email"]["create_draft_only"] = False

        errors = validate_team_config(config)

        self.assertIn("email.create_draft_only must be true", errors)

    def test_optional_spillover_config_is_validated(self):
        config = deepcopy(self.config)
        config["previous_month_spillover"] = {
            "enabled": "yes",
            "include_if_status_not_in_done_statuses": True,
        }

        errors = validate_team_config(config)

        self.assertIn("previous_month_spillover.enabled must be true or false", errors)

    def test_optional_hygiene_severity_overrides_are_validated(self):
        config = deepcopy(self.config)
        config["hygiene"] = {"severity_overrides": {"missing_linked_okr": "purple"}}

        errors = validate_team_config(config)

        self.assertIn(
            "hygiene.severity_overrides values must be red, yellow, or info: purple",
            errors,
        )

    def test_optional_run_history_config_is_validated(self):
        config = deepcopy(self.config)
        config["run_history"] = {"enabled": "yes", "tab_name": ""}

        errors = validate_team_config(config)

        self.assertIn("run_history.enabled must be true or false", errors)
        self.assertIn("run_history.tab_name must not be empty", errors)

    def test_account_id_matching_wins(self):
        author = {"accountId": "ada-account", "displayName": "Someone Else"}
        dri = {"accountId": "ada-account", "displayName": "Ada Lovelace"}

        self.assertTrue(author_matches(author, dri))

    def test_expected_team_identity_allows_separator_variants(self):
        errors = validate_expected_team(
            self.config,
            expected_team_id="test-team",
            expected_team_name="Test_Team",
        )

        self.assertEqual(errors, [])

    def test_expected_team_identity_fails_wrong_config(self):
        errors = validate_expected_team(
            self.config,
            expected_team_id="delivery-managers",
            expected_team_name="Delivery Managers",
        )

        self.assertIn("Config team.id mismatch: expected delivery-managers, found test-team", errors)
        self.assertIn("Config team.name mismatch: expected Delivery Managers, found Test Team", errors)

    def test_config_schema_does_not_add_sizing_field(self):
        schema = json.loads((ROOT / "config/team-config.schema.json").read_text(encoding="utf-8"))
        jira_fields = schema["properties"]["jira"]["properties"]["fields"]["properties"]

        self.assertNotIn("size", jira_fields)
        self.assertNotIn("sizing", jira_fields)

    def test_config_schema_does_not_include_functional_leads(self):
        schema = json.loads((ROOT / "config/team-config.schema.json").read_text(encoding="utf-8"))
        team_fields = schema["properties"]["team"]["properties"]
        email_fields = schema["properties"]["email"]["properties"]
        required_email_fields = schema["properties"]["email"]["required"]

        self.assertNotIn("functional_leads", team_fields)
        self.assertNotIn("cc_from_functional_leads", email_fields)
        self.assertNotIn("cc_from_functional_leads", required_email_fields)
        self.assertIn("cc", email_fields)

    def test_config_schema_does_not_allow_legacy_fields(self):
        schema = json.loads((ROOT / "config/team-config.schema.json").read_text(encoding="utf-8"))
        sheet_fields = schema["properties"]["sheet"]["properties"]
        email_fields = schema["properties"]["email"]["properties"]

        self.assertNotIn("spreadsheet_id", sheet_fields)
        self.assertNotIn("smtp_host", email_fields)
        self.assertNotIn("smtp_port", email_fields)
        self.assertNotIn("smtp_starttls", email_fields)

    def test_config_schema_allows_optional_carryover_and_hygiene_blocks(self):
        schema = json.loads((ROOT / "config/team-config.schema.json").read_text(encoding="utf-8"))

        self.assertIn("previous_month_spillover", schema["properties"])
        self.assertIn("hygiene", schema["properties"])
        self.assertIn("run_history", schema["properties"])


if __name__ == "__main__":
    unittest.main()
