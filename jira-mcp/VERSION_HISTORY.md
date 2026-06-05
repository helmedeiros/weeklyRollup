# VERSION_HISTORY.md

## v1.4.2 - 2026-03-13
### Changed
- Migrated Confluence OAuth scopes to Atlassian's current granular scope model for v2 API compatibility
- Added explicit scope validation so Confluence tools fail with a re-link instruction instead of Atlassian's opaque `scope does not match` error
- Restored OKR Board source code (`src/okrboard.js`) and re-added 12 OKR Board MCP tools
- Added `.env` fallback support for `OKRBOARD_API_TOKEN` and `OKRBOARD_BASE_URL`
- Updated MCP server version metadata to `1.4.2`

## v1.4.1 - 2026-02-04
### Added
- `test-projects.js` - Test script listing first 3 active projects with 5 recent issues each
- Filters out deprecated projects (contains "zzz", "deprecated", "[rip]", "- old")
- Updated `npm test` to run test-projects.js

## v1.4.0 - 2026-02-04
### Changed
- **Storage:** Migrated from PostgreSQL to encrypted file-based storage
- Data stored in `.data/store.enc` (encrypted JSON with AES-256-GCM)
- No database dependency - simpler setup
- Portable - just copy `.data/` folder to migrate

### Removed
- PostgreSQL dependency (`pg` package)
- `src/db.js` and `src/token-store.js` (replaced by `src/file-store.js`)
- Database configuration (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD)

### Added
- `src/file-store.js` - Unified encrypted file storage module
- `.data/` directory for encrypted token storage

## v1.3.0 - 2026-02-04
### Added
- **Jira Project Management (4 tools):** create_project, update_project, delete_project, get_project_statuses
- **Jira Field Management (7 tools):** list_fields, create_field, update_field, delete_field, trash_field, restore_field, list_trashed_fields
- **Jira Status Management (4 tools):** list_statuses, create_statuses, update_statuses, delete_statuses
- **Jira Workflow Management (4 tools):** list_workflows, create_workflows, update_workflows, get_workflow_schemes
- New scopes: `manage:jira-configuration`, `manage:jira-project`
- Total tools: 40 (25 Jira + 10 Confluence + 5 Config)

### Security Audit
- Verified `.env` never committed to git
- Confirmed AES-256-GCM encryption working
- Token refresh with expiry buffer implemented

## v1.2.0 - 2026-01-27
### Added
- Confluence watch tools: `get_watched_content`, `is_watching_content`, `watch_content`, `unwatch_content`
- New scope: `write:confluence-content` for watch operations
- Total tools: 21 (6 Jira + 10 Confluence + 5 Config)

### Notes
- `get_watched_content` uses CQL `watcher = currentUser()` which has known bug CONFCLOUD-70064

## v1.1.0 - 2026-01-27
### Added
- Confluence API integration (REST API v2)
- Confluence tools: `list_spaces`, `get_space`, `list_pages`, `get_page`, `search_confluence`, `get_page_labels`
- Confluence field sets (minimal, standard, extended, full)
- `set_default_confluence_field_set` config tool
- Confluence scopes: `read:confluence-content.all`, `read:confluence-space.summary`, `search:confluence`

## v1.0.0 - 2026-01-26
### Initial Release
- Jira API integration via OAuth 2.0 (3LO)
- SSO support with automatic token refresh
- Multi-user PostgreSQL storage with AES-256-GCM encryption
- Jira tools: `list_projects`, `get_project`, `search_issues`, `get_issue`, `get_issue_comments`, `add_comment`
- Config tools: `get_config`, `set_config`, `list_config`, `set_default_field_set`
- Configurable field sets for Jira
