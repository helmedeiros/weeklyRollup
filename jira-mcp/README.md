# jira-mcp

MCP (Model Context Protocol) server for **Jira, Confluence, and OKR Board** integration with OAuth 2.0 authentication and multi-user support. Bundled inside the `weeklyRollup` project as its Jira data source.

## Features

- OAuth 2.0 (3LO) authentication with SSO support
- Automatic token refresh
- Encrypted file-based storage (no database required)
- AES-256-GCM token encryption
- Configurable field sets per user (for both Jira and Confluence)
- OKR Board (Oboard) API integration with API-token auth
- 52 MCP tools (25 Jira + 10 Confluence + 5 Config + 12 OKR Board)

## Setup

### 1. Create Atlassian OAuth App

#### Step 1: Open Developer Console
1. Go to **https://developer.atlassian.com/console/myapps/**
2. Sign in with your Atlassian account

#### Step 2: Create New App
1. Click **"Create"** button (top right)
2. Select **"OAuth 2.0 integration"**
3. Enter app name: `Weekly Rollup Jira MCP` (or your preferred name)
4. Check the agreement checkbox
5. Click **"Create"**

#### Step 3: Configure Permissions (Scopes)
1. In your app, go to **"Permissions"** in the left sidebar

**Jira API:**
2. Click **"Add"** next to **"Jira API"**
3. Click **"Configure"** next to Jira API
4. Add these scopes (click "Edit Scopes"):
   - `read:jira-work` - Read Jira project and issue data
   - `read:jira-user` - Read user information
   - `write:jira-work` - Create and edit issues and comments
   - `manage:jira-configuration` - Manage statuses, workflows, and custom fields
   - `manage:jira-project` - Create, update, and delete Jira projects

**Confluence API:**
5. Go back to **"Permissions"**
6. Click **"Add"** next to **"Confluence API"**
7. Click **"Configure"** next to Confluence API
8. Add these scopes:
   - `read:page:confluence` - Read Confluence pages via REST API v2
   - `read:space:confluence` - Read Confluence spaces via REST API v2
   - `read:label:confluence` - Read page labels via REST API v2
   - `search:confluence` - Search Confluence content
   - `read:watcher:confluence` - Read page watch status
   - `write:watcher:confluence` - Watch and unwatch Confluence content

**User Identity:**
9. Go back to **"Permissions"**
10. Click **"Add"** next to **"User identity API"**
11. Add scope:
   - `read:me` - Read user email for multi-user support

#### Step 4: Configure Authorization
1. Go to **"Authorization"** in the left sidebar
2. Click **"Add"** next to **"OAuth 2.0 (3LO)"**
3. Enter callback URL: `http://localhost:3002/callback`
4. Click **"Save changes"**

#### Step 5: Get Credentials
1. Go to **"Settings"** in the left sidebar
2. Copy **"Client ID"**
3. Copy **"Secret"** (you may need to generate one)

### 2. Configure Environment

Create `.env` file in the project root:

```bash
# Atlassian OAuth 2.0 Configuration
ATLASSIAN_CLIENT_ID=your-client-id-from-step-5
ATLASSIAN_CLIENT_SECRET=your-secret-from-step-5
ATLASSIAN_REDIRECT_URI=http://localhost:3002/callback
ATLASSIAN_CLOUD_ID=will-be-auto-filled

# OAuth URLs (standard, no need to change)
ATLASSIAN_AUTH_URL=https://auth.atlassian.com/authorize
ATLASSIAN_TOKEN_URL=https://auth.atlassian.com/oauth/token
ATLASSIAN_RESOURCES_URL=https://api.atlassian.com/oauth/token/accessible-resources

# OAuth Scopes (Jira + Confluence)
ATLASSIAN_SCOPES=read:jira-work read:jira-user write:jira-work manage:jira-configuration manage:jira-project read:me offline_access read:page:confluence read:space:confluence read:label:confluence search:confluence read:watcher:confluence write:watcher:confluence

# OKR Board (optional)
OKRBOARD_API_TOKEN=your-okr-board-api-token
OKRBOARD_BASE_URL=https://backend.okr-api.com/api/v1

# Server Configuration
AUTH_PORT=3002

# Token Encryption (generate with command below)
TOKEN_ENCRYPTION_KEY=your-64-char-hex-key

# Default user (for CLI usage)
JIRA_USER_EMAIL=your-email@domain.com
```

Generate encryption key:
```bash
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

### 3. Install & Authenticate

```bash
# Install dependencies
npm install

# Run OAuth authentication (opens browser)
npm run auth
```

The browser will open to Atlassian login. After authenticating:
- Your tokens are encrypted and stored in `.data/store.enc`
- Your email is extracted from the OAuth response
- Default config is created for your user
- If you changed scopes, re-run `npm run auth` so Atlassian issues a fresh grant with the updated permissions

### 3a. Configure OKR Board

OKR Board does not use Atlassian OAuth scopes. It uses its own API token.

You can configure it in either of these ways:

1. Via `.env`:
```bash
OKRBOARD_API_TOKEN=your-okr-board-api-token
OKRBOARD_BASE_URL=https://backend.okr-api.com/api/v1
```

2. Via MCP config tools after the server is running:
   - `set_okrboard_token`
   - `set_okrboard_base_url`

Where to get the token:
- Open the Oboard app in Jira
- Go to Oboard settings / API token settings
- Copy the API token and place it in `OKRBOARD_API_TOKEN` or set it with `set_okrboard_token`

Runtime behavior:
- The server first looks for per-user stored config (`okrboard_api_token`, `okrboard_base_url`)
- If that is not configured, it falls back to `.env` values (`OKRBOARD_API_TOKEN`, `OKRBOARD_BASE_URL`)
- If no OKR Board base URL is configured anywhere, it defaults to `https://backend.okr-api.com/api/v1`

### 4. Add to MCP Clients

**Claude Code (CLI):**
```bash
claude mcp add jira node /path/to/jira-mcp/src/index.js
```

**Claude Desktop** - Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "jira": {
      "command": "node",
      "args": ["/path/to/jira-mcp/src/index.js"]
    }
  }
}
```

**Codex CLI:**
```bash
codex mcp add jira -- node /path/to/jira-mcp/src/index.js
```

You can inspect configured MCP servers in Codex with:
```bash
codex mcp --help
```

**Codex CLI via `~/.codex/config.toml`:**
```toml
[mcp_servers.jira]
command = "node"
args = ["/path/to/jira-mcp/src/index.js"]
cwd = "/path/to/jira-mcp"
```

Notes for Codex CLI:
- User-level MCP config lives in `~/.codex/config.toml`
- You can also use a project-scoped `.codex/config.toml` in trusted projects
- This server reads Atlassian and OKR Board credentials from the repo `.env` file and from encrypted local config in `.data/store.enc`

## OAuth Scopes Reference

### Jira Scopes
| Scope | Purpose | Required |
|-------|---------|----------|
| `read:jira-work` | Read projects, issues, comments | Yes |
| `read:jira-user` | Read user profiles | Yes |
| `write:jira-work` | Add comments, update issues | Yes |
| `manage:jira-configuration` | Manage statuses, workflows, fields | For management |
| `manage:jira-project` | Create, update, delete projects | For management |

### Confluence Scopes
| Scope | Purpose | Required |
|-------|---------|----------|
| `read:page:confluence` | Read pages through Confluence REST API v2 | Yes |
| `read:space:confluence` | Read space information through Confluence REST API v2 | Yes |
| `read:label:confluence` | Read page labels | Yes |
| `search:confluence` | Search content | Yes |
| `read:watcher:confluence` | Read watch status and watched content | Yes |
| `write:watcher:confluence` | Watch/unwatch content | Yes |

### Common Scopes
| Scope | Purpose | Required |
|-------|---------|----------|
| `read:me` | Get authenticated user's email | Yes |
| `offline_access` | Refresh tokens (long-lived access) | Yes |

## Available Tools (52 total)

### Jira Read Tools (6)
| Tool | Description |
|------|-------------|
| `list_projects` | List Jira projects |
| `get_project` | Get project details |
| `search_issues` | Search with JQL |
| `get_issue` | Get issue details |
| `get_issue_comments` | Get issue comments |
| `add_comment` | Add comment to issue |

### Jira Project Management (4)
| Tool | Description |
|------|-------------|
| `create_project` | Create new Jira project |
| `update_project` | Update project settings |
| `delete_project` | Delete a project (irreversible) |
| `get_project_statuses` | Get available statuses for a project |

### Jira Field Management (7)
| Tool | Description |
|------|-------------|
| `list_fields` | List all fields (system + custom) |
| `create_field` | Create custom field |
| `update_field` | Update custom field |
| `delete_field` | Permanently delete custom field |
| `trash_field` | Move field to trash |
| `restore_field` | Restore field from trash |
| `list_trashed_fields` | List fields in trash |

### Jira Status Management (4)
| Tool | Description |
|------|-------------|
| `list_statuses` | Search/list statuses |
| `create_statuses` | Bulk create statuses |
| `update_statuses` | Bulk update statuses |
| `delete_statuses` | Bulk delete statuses |

### Jira Workflow Management (4)
| Tool | Description |
|------|-------------|
| `list_workflows` | Search workflows |
| `create_workflows` | Create workflows |
| `update_workflows` | Update workflows |
| `get_workflow_schemes` | Get workflow schemes for project |

### Confluence Tools (10)
| Tool | Description |
|------|-------------|
| `list_spaces` | List Confluence spaces |
| `get_space` | Get space details by ID or key |
| `list_pages` | List pages (optionally by space) |
| `get_page` | Get page details with body content |
| `search_confluence` | Search content with CQL |
| `get_page_labels` | Get labels on a page |
| `get_watched_content` | Get pages you're watching |
| `is_watching_content` | Check if watching a page |
| `watch_content` | Start watching a page |
| `unwatch_content` | Stop watching a page |

### Config Tools (5)
| Tool | Description |
|------|-------------|
| `get_config` | Get user config value |
| `set_config` | Set user config value |
| `list_config` | List all user config |
| `set_default_field_set` | Set default Jira field set |
| `set_default_confluence_field_set` | Set default Confluence field set |

### OKR Board Tools (12)
| Tool | Description |
|------|-------------|
| `set_okrboard_token` | Set OKR Board API token for the current user |
| `set_okrboard_base_url` | Set OKR Board API base URL |
| `get_okrboard_connection` | Check OKR Board connection status |
| `list_okr_workspaces` | List OKR Board workspaces |
| `list_okr_intervals` | List OKR Board intervals for a workspace |
| `list_okr_groups` | List OKR Board groups for a workspace |
| `list_okr_users` | List OKR Board users for a workspace |
| `list_okr_objectives` | List OKR Board objectives, key results, and linked items |
| `create_okr_objective` | Create an OKR Board objective |
| `update_okr_objective` | Update an OKR Board objective |
| `update_okr_key_result` | Update an OKR Board key result |
| `delete_okr_key_result` | Delete an OKR Board key result |

## Field Sets

Control which fields are returned to reduce payload size.

### Jira Field Sets
- `minimal` - key, summary, status, priority, type
- `standard` - + assignee, reporter, dates
- `extended` - + labels, components, versions
- `full` - all fields including description

### Confluence Field Sets
- `minimal` - id, title, status, spaceId
- `standard` - + version, createdAt, authorId
- `extended` - + labels, properties
- `full` - + body content (storage format)

## Multi-User Support

Each user authenticates via SSO with their email. Tokens and config are stored per-user in an encrypted local file (`.data/store.enc`).

To add another user:
```bash
npm run auth  # New user logs in via browser
```

## Troubleshooting

### "Invalid callback URL" error
- Ensure `http://localhost:3002/callback` is added in Atlassian Developer Console → Authorization → OAuth 2.0 (3LO)

### "Insufficient scope" error
- Add all required scopes in Developer Console → Permissions
- Re-run `npm run auth` to get new tokens with updated scopes

### Confluence returns "scope does not match"
- Confirm the Confluence OAuth scopes in Developer Console exactly match the scopes listed in this README
- Re-run `npm run auth` after saving scope changes
- Restart the MCP server if it is still holding older in-memory auth state

### OKR Board token not configured
- Set `OKRBOARD_API_TOKEN` in `.env`, or call `set_okrboard_token`
- Optionally set `OKRBOARD_BASE_URL` if you are not using the default cloud API
- Verify with `get_okrboard_connection`

### Token refresh fails
- Delete `.data/store.enc` to reset all tokens
- Re-run `npm run auth`

## Scripts

```bash
npm run auth    # Run OAuth authentication
npm run start   # Start MCP server
npm test        # Run unit tests with coverage
```
