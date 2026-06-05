# CLAUDE.md

## Project Overview

`jira-mcp` is an MCP server for **Jira, Confluence, and OKR Board** integration via Atlassian OAuth 2.0 (3LO) with SSO support, automatic token refresh, encrypted file-based storage, and API-token based OKR Board access. Bundled inside the `weeklyRollup` project as its Jira data source.

## Project Status

Operational. Works against any Atlassian Cloud tenant the authenticated user has access to. Supports Jira and Confluence APIs with full management capabilities, plus OKR Board (OBoard) workspace/objective tooling.

## Build & Run

```bash
npm install          # Install dependencies
npm run auth         # OAuth flow (port 3002)
npm run start        # Start MCP server
```

## Architecture

```
src/
  index.js       - MCP server (stdio transport)
  auth.js        - OAuth 2.0 with token refresh
  jira.js        - JiraAPI wrapper with field sets + management
  confluence.js  - ConfluenceAPI wrapper with field sets + watches
  okrboard.js    - OKR Board API wrapper (API-Token auth)
  tools.js       - 52 MCP tool definitions
  file-store.js  - Encrypted JSON file storage
  crypto.js      - AES-256-GCM encryption

.data/
  store.enc      - Encrypted user/token/config data
```

## Tools (52 total)

**Jira Read (6):** list_projects, get_project, search_issues, get_issue, get_issue_comments, add_comment

**Jira Project Management (4):** create_project, update_project, delete_project, get_project_statuses

**Jira Field Management (7):** list_fields, create_field, update_field, delete_field, trash_field, restore_field, list_trashed_fields

**Jira Status Management (4):** list_statuses, create_statuses, update_statuses, delete_statuses

**Jira Workflow Management (4):** list_workflows, create_workflows, update_workflows, get_workflow_schemes

**Confluence (10):** list_spaces, get_space, list_pages, get_page, search_confluence, get_page_labels, get_watched_content, is_watching_content, watch_content, unwatch_content

**Config (5):** get_config, set_config, list_config, set_default_field_set, set_default_confluence_field_set

**OKR Board (12):** set_okrboard_token, set_okrboard_base_url, get_okrboard_connection, list_okr_workspaces, list_okr_intervals, list_okr_groups, list_okr_users, list_okr_objectives, create_okr_objective, update_okr_objective, update_okr_key_result, delete_okr_key_result

## Authentication

OAuth 2.0 (3LO) with SSO. Tokens encrypted with AES-256-GCM, stored in `.data/store.enc`.

**Jira:** `read:jira-work`, `read:jira-user`, `write:jira-work`, `manage:jira-configuration`, `manage:jira-project`

**Confluence:** `read:page:confluence`, `read:space:confluence`, `read:label:confluence`, `search:confluence`, `read:watcher:confluence`, `write:watcher:confluence`

**Common:** `read:me`, `offline_access`

**OKR Board:** API token via per-user config (`okrboard_api_token`) or `.env` fallback (`OKRBOARD_API_TOKEN`), with optional base URL override (`okrboard_base_url` / `OKRBOARD_BASE_URL`)

## Field Sets

**Jira:** minimal (key, summary, status) → standard (+assignee, dates) → extended (+labels) → full (all)

**Confluence:** minimal (id, title) → standard (+version) → extended (+labels) → full (+body)

## Claude Integration

```bash
claude mcp add jira node /path/to/jira-mcp/src/index.js
```

## Testing

```bash
npm test  # Run unit tests with coverage (207 tests)
```

## Current State (v1.4.2)

- 207 unit tests with Jest
- Migrated from PostgreSQL to encrypted file-based storage
- Confluence uses granular OAuth scopes compatible with the current REST API v2 setup
- OKR Board source restored locally with `.env` fallback for `OKRBOARD_API_TOKEN` and `OKRBOARD_BASE_URL`
- Run `npm run auth` to create `.data/store.enc` with your Atlassian credentials
