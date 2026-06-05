const { JiraAPI, FIELD_SETS } = require('./jira');
const { ConfluenceAPI, CONFLUENCE_FIELD_SETS } = require('./confluence');
const { OkrBoardAPI, DEFAULT_BASE_URL } = require('./okrboard');
const fileStore = require('./file-store');
const { getCurrentUser } = require('./auth');

const jira = new JiraAPI();
const confluence = new ConfluenceAPI();
const okrboard = new OkrBoardAPI();
let storeInitialized = false;

function ensureStore() {
  if (!storeInitialized) {
    fileStore.init();
    storeInitialized = true;
  }
}

const TOOLS = [
  // === Jira Tools ===
  {
    name: 'list_projects',
    description: 'List Jira projects accessible to the user',
    inputSchema: {
      type: 'object',
      properties: {
        maxResults: {
          type: 'number',
          description: 'Maximum projects to return (default 50, max 200)',
          default: 50
        }
      }
    }
  },
  {
    name: 'get_project',
    description: 'Get details of a specific Jira project',
    inputSchema: {
      type: 'object',
      properties: {
        projectKey: {
          type: 'string',
          description: 'Project key (e.g., PROJ) or ID'
        }
      },
      required: ['projectKey']
    }
  },
  {
    name: 'search_issues',
    description: 'Search Jira issues using JQL. Requires bounded queries (add project, date, or other filters).',
    inputSchema: {
      type: 'object',
      properties: {
        jql: {
          type: 'string',
          description: 'JQL query (must be bounded, e.g., "project = PROJ AND created >= -7d")'
        },
        maxResults: {
          type: 'number',
          description: 'Maximum issues to return (default 20, max 100)',
          default: 20
        },
        nextPageToken: {
          type: 'string',
          description: 'Token for pagination (from previous response)'
        },
        fieldSet: {
          type: 'string',
          enum: ['minimal', 'standard', 'extended', 'full'],
          description: 'Field set to return. Uses user default if not specified.'
        }
      },
      required: ['jql']
    }
  },
  {
    name: 'get_issue',
    description: 'Get details of a specific Jira issue',
    inputSchema: {
      type: 'object',
      properties: {
        issueKey: {
          type: 'string',
          description: 'Issue key (e.g., PROJ-123) or ID'
        },
        fieldSet: {
          type: 'string',
          enum: ['minimal', 'standard', 'extended', 'full'],
          description: 'Field set to return. Uses user default if not specified.'
        }
      },
      required: ['issueKey']
    }
  },
  {
    name: 'get_issue_comments',
    description: 'Get comments on a Jira issue',
    inputSchema: {
      type: 'object',
      properties: {
        issueKey: {
          type: 'string',
          description: 'Issue key (e.g., PROJ-123) or ID'
        },
        maxResults: {
          type: 'number',
          description: 'Maximum comments to return (default 10)',
          default: 10
        }
      },
      required: ['issueKey']
    }
  },
  {
    name: 'add_comment',
    description: 'Add a comment to a Jira issue',
    inputSchema: {
      type: 'object',
      properties: {
        issueKey: {
          type: 'string',
          description: 'Issue key (e.g., PROJ-123) or ID'
        },
        body: {
          type: 'string',
          description: 'Comment text'
        }
      },
      required: ['issueKey', 'body']
    }
  },

  // === Jira Project Management Tools ===
  {
    name: 'create_project',
    description: 'Create a new Jira project',
    inputSchema: {
      type: 'object',
      properties: {
        key: {
          type: 'string',
          description: 'Unique project key (e.g., PROJ)'
        },
        name: {
          type: 'string',
          description: 'Project name'
        },
        projectTypeKey: {
          type: 'string',
          enum: ['software', 'service_desk', 'business'],
          description: 'Project type (default: software)'
        },
        projectTemplateKey: {
          type: 'string',
          description: 'Template key (e.g., com.pyxis.greenhopper.jira:gh-simplified-agility-kanban)'
        },
        description: {
          type: 'string',
          description: 'Project description'
        },
        leadAccountId: {
          type: 'string',
          description: 'Account ID of project lead'
        },
        assigneeType: {
          type: 'string',
          enum: ['PROJECT_LEAD', 'UNASSIGNED'],
          description: 'Default assignee type'
        }
      },
      required: ['key', 'name']
    }
  },
  {
    name: 'update_project',
    description: 'Update an existing Jira project',
    inputSchema: {
      type: 'object',
      properties: {
        projectKey: {
          type: 'string',
          description: 'Project key or ID'
        },
        name: {
          type: 'string',
          description: 'New project name'
        },
        description: {
          type: 'string',
          description: 'New project description'
        },
        leadAccountId: {
          type: 'string',
          description: 'New project lead account ID'
        },
        assigneeType: {
          type: 'string',
          enum: ['PROJECT_LEAD', 'UNASSIGNED'],
          description: 'Default assignee type'
        }
      },
      required: ['projectKey']
    }
  },
  {
    name: 'delete_project',
    description: 'Delete a Jira project (WARNING: This is irreversible)',
    inputSchema: {
      type: 'object',
      properties: {
        projectKey: {
          type: 'string',
          description: 'Project key or ID to delete'
        }
      },
      required: ['projectKey']
    }
  },
  {
    name: 'get_project_statuses',
    description: 'Get available statuses for each issue type in a project',
    inputSchema: {
      type: 'object',
      properties: {
        projectKey: {
          type: 'string',
          description: 'Project key or ID'
        }
      },
      required: ['projectKey']
    }
  },

  // === Jira Field Management Tools ===
  {
    name: 'list_fields',
    description: 'List all Jira fields (system and custom)',
    inputSchema: {
      type: 'object',
      properties: {}
    }
  },
  {
    name: 'create_field',
    description: 'Create a custom Jira field',
    inputSchema: {
      type: 'object',
      properties: {
        name: {
          type: 'string',
          description: 'Field name'
        },
        description: {
          type: 'string',
          description: 'Field description'
        },
        type: {
          type: 'string',
          description: 'Field type (e.g., com.atlassian.jira.plugin.system.customfieldtypes:textfield)'
        },
        searcherKey: {
          type: 'string',
          description: 'Searcher key for the field'
        }
      },
      required: ['name', 'type']
    }
  },
  {
    name: 'update_field',
    description: 'Update a custom Jira field',
    inputSchema: {
      type: 'object',
      properties: {
        fieldId: {
          type: 'string',
          description: 'Field ID (e.g., customfield_10001)'
        },
        name: {
          type: 'string',
          description: 'New field name'
        },
        description: {
          type: 'string',
          description: 'New field description'
        }
      },
      required: ['fieldId']
    }
  },
  {
    name: 'delete_field',
    description: 'Permanently delete a custom Jira field (WARNING: Irreversible)',
    inputSchema: {
      type: 'object',
      properties: {
        fieldId: {
          type: 'string',
          description: 'Field ID to delete (e.g., customfield_10001)'
        }
      },
      required: ['fieldId']
    }
  },
  {
    name: 'trash_field',
    description: 'Move a custom Jira field to trash (can be restored)',
    inputSchema: {
      type: 'object',
      properties: {
        fieldId: {
          type: 'string',
          description: 'Field ID to trash (e.g., customfield_10001)'
        }
      },
      required: ['fieldId']
    }
  },
  {
    name: 'restore_field',
    description: 'Restore a custom Jira field from trash',
    inputSchema: {
      type: 'object',
      properties: {
        fieldId: {
          type: 'string',
          description: 'Field ID to restore (e.g., customfield_10001)'
        }
      },
      required: ['fieldId']
    }
  },
  {
    name: 'list_trashed_fields',
    description: 'List custom Jira fields in trash',
    inputSchema: {
      type: 'object',
      properties: {}
    }
  },

  // === Jira Status Management Tools ===
  {
    name: 'list_statuses',
    description: 'Search and list Jira statuses',
    inputSchema: {
      type: 'object',
      properties: {
        projectId: {
          type: 'string',
          description: 'Filter by project ID'
        },
        searchString: {
          type: 'string',
          description: 'Search string to filter statuses'
        },
        maxResults: {
          type: 'number',
          description: 'Maximum results (default 50)',
          default: 50
        },
        startAt: {
          type: 'number',
          description: 'Start index for pagination',
          default: 0
        }
      }
    }
  },
  {
    name: 'create_statuses',
    description: 'Create new Jira statuses in bulk',
    inputSchema: {
      type: 'object',
      properties: {
        statuses: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              name: { type: 'string', description: 'Status name' },
              statusCategory: { type: 'string', enum: ['TODO', 'IN_PROGRESS', 'DONE'], description: 'Status category' },
              description: { type: 'string', description: 'Status description' }
            },
            required: ['name', 'statusCategory']
          },
          description: 'Array of statuses to create'
        },
        scope: {
          type: 'object',
          properties: {
            type: { type: 'string', enum: ['PROJECT', 'GLOBAL'], description: 'Scope type' },
            projectId: { type: 'string', description: 'Project ID (required if type is PROJECT)' }
          },
          required: ['type'],
          description: 'Scope for the statuses'
        }
      },
      required: ['statuses', 'scope']
    }
  },
  {
    name: 'update_statuses',
    description: 'Update existing Jira statuses in bulk',
    inputSchema: {
      type: 'object',
      properties: {
        statuses: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              id: { type: 'string', description: 'Status ID' },
              name: { type: 'string', description: 'New status name' },
              statusCategory: { type: 'string', enum: ['TODO', 'IN_PROGRESS', 'DONE'], description: 'New status category' },
              description: { type: 'string', description: 'New status description' }
            },
            required: ['id']
          },
          description: 'Array of statuses to update'
        }
      },
      required: ['statuses']
    }
  },
  {
    name: 'delete_statuses',
    description: 'Delete Jira statuses in bulk',
    inputSchema: {
      type: 'object',
      properties: {
        ids: {
          type: 'array',
          items: { type: 'string' },
          description: 'Array of status IDs to delete'
        }
      },
      required: ['ids']
    }
  },

  // === Jira Workflow Management Tools ===
  {
    name: 'list_workflows',
    description: 'Search and list Jira workflows',
    inputSchema: {
      type: 'object',
      properties: {
        workflowName: {
          type: 'string',
          description: 'Filter by workflow name'
        },
        projectId: {
          type: 'string',
          description: 'Filter by project ID'
        },
        maxResults: {
          type: 'number',
          description: 'Maximum results (default 50)',
          default: 50
        },
        startAt: {
          type: 'number',
          description: 'Start index for pagination',
          default: 0
        }
      }
    }
  },
  {
    name: 'create_workflows',
    description: 'Create new Jira workflows',
    inputSchema: {
      type: 'object',
      properties: {
        workflows: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              name: { type: 'string', description: 'Workflow name' },
              description: { type: 'string', description: 'Workflow description' },
              statuses: { type: 'array', items: { type: 'object' }, description: 'Array of status references' },
              transitions: { type: 'array', items: { type: 'object' }, description: 'Array of transitions' }
            },
            required: ['name']
          },
          description: 'Array of workflows to create'
        },
        scope: {
          type: 'object',
          properties: {
            type: { type: 'string', enum: ['PROJECT', 'GLOBAL'], description: 'Scope type' },
            projectId: { type: 'string', description: 'Project ID (required if type is PROJECT)' }
          },
          required: ['type'],
          description: 'Scope for the workflows'
        }
      },
      required: ['workflows', 'scope']
    }
  },
  {
    name: 'update_workflows',
    description: 'Update existing Jira workflows',
    inputSchema: {
      type: 'object',
      properties: {
        workflows: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              id: { type: 'string', description: 'Workflow ID' },
              version: { type: 'object', description: 'Workflow version' },
              statuses: { type: 'array', items: { type: 'object' }, description: 'Updated statuses' },
              transitions: { type: 'array', items: { type: 'object' }, description: 'Updated transitions' }
            },
            required: ['id', 'version']
          },
          description: 'Array of workflows to update'
        }
      },
      required: ['workflows']
    }
  },
  {
    name: 'get_workflow_schemes',
    description: 'Get workflow schemes for a project',
    inputSchema: {
      type: 'object',
      properties: {
        projectId: {
          type: 'string',
          description: 'Project ID'
        }
      },
      required: ['projectId']
    }
  },

  // === Confluence Tools ===
  {
    name: 'list_spaces',
    description: 'List Confluence spaces accessible to the user',
    inputSchema: {
      type: 'object',
      properties: {
        limit: {
          type: 'number',
          description: 'Maximum spaces to return (default 25, max 250)',
          default: 25
        },
        type: {
          type: 'string',
          enum: ['global', 'personal'],
          description: 'Filter by space type'
        },
        status: {
          type: 'string',
          enum: ['current', 'archived'],
          description: 'Filter by status (default: current)',
          default: 'current'
        },
        cursor: {
          type: 'string',
          description: 'Pagination cursor from previous response'
        }
      }
    }
  },
  {
    name: 'get_space',
    description: 'Get details of a Confluence space by ID or key',
    inputSchema: {
      type: 'object',
      properties: {
        spaceIdOrKey: {
          type: 'string',
          description: 'Space ID (numeric) or key (e.g., "TEAM")'
        }
      },
      required: ['spaceIdOrKey']
    }
  },
  {
    name: 'list_pages',
    description: 'List Confluence pages, optionally filtered by space',
    inputSchema: {
      type: 'object',
      properties: {
        spaceId: {
          type: 'string',
          description: 'Space ID to filter pages (optional)'
        },
        limit: {
          type: 'number',
          description: 'Maximum pages to return (default 25, max 250)',
          default: 25
        },
        status: {
          type: 'string',
          enum: ['current', 'archived', 'trashed'],
          description: 'Filter by status (default: current)'
        },
        sort: {
          type: 'string',
          enum: ['-modified-date', 'modified-date', '-created-date', 'created-date', 'title', '-title'],
          description: 'Sort order (default: -modified-date = newest first)'
        },
        fieldSet: {
          type: 'string',
          enum: ['minimal', 'standard', 'extended', 'full'],
          description: 'Field set to return. Uses user default if not specified.'
        },
        cursor: {
          type: 'string',
          description: 'Pagination cursor from previous response'
        }
      }
    }
  },
  {
    name: 'get_page',
    description: 'Get details of a Confluence page by ID',
    inputSchema: {
      type: 'object',
      properties: {
        pageId: {
          type: 'string',
          description: 'Page ID'
        },
        fieldSet: {
          type: 'string',
          enum: ['minimal', 'standard', 'extended', 'full'],
          description: 'Field set to return. Uses user default if not specified.'
        },
        bodyFormat: {
          type: 'string',
          enum: ['storage', 'atlas_doc_format', 'view'],
          description: 'Body format to retrieve (overrides fieldSet default)'
        }
      },
      required: ['pageId']
    }
  },
  {
    name: 'search_confluence',
    description: 'Search Confluence content using CQL text search',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'Search text query'
        },
        spaceKey: {
          type: 'string',
          description: 'Filter results to a specific space key'
        },
        type: {
          type: 'string',
          enum: ['page', 'blogpost', 'comment', 'attachment'],
          description: 'Filter by content type'
        },
        limit: {
          type: 'number',
          description: 'Maximum results to return (default 25, max 100)',
          default: 25
        },
        cursor: {
          type: 'string',
          description: 'Pagination cursor from previous response'
        }
      },
      required: ['query']
    }
  },
  {
    name: 'get_page_labels',
    description: 'Get labels attached to a Confluence page',
    inputSchema: {
      type: 'object',
      properties: {
        pageId: {
          type: 'string',
          description: 'Page ID'
        }
      },
      required: ['pageId']
    }
  },
  {
    name: 'get_watched_content',
    description: 'Get Confluence content (pages/blogs) that you are watching',
    inputSchema: {
      type: 'object',
      properties: {
        type: {
          type: 'string',
          enum: ['page', 'blogpost'],
          description: 'Filter by content type (default: page)'
        },
        limit: {
          type: 'number',
          description: 'Maximum results to return (default 25, max 100)',
          default: 25
        },
        start: {
          type: 'number',
          description: 'Start index for pagination (default 0)',
          default: 0
        }
      }
    }
  },
  {
    name: 'is_watching_content',
    description: 'Check if you are watching a specific Confluence page or content',
    inputSchema: {
      type: 'object',
      properties: {
        contentId: {
          type: 'string',
          description: 'Content/Page ID to check'
        }
      },
      required: ['contentId']
    }
  },
  {
    name: 'watch_content',
    description: 'Start watching a Confluence page or content',
    inputSchema: {
      type: 'object',
      properties: {
        contentId: {
          type: 'string',
          description: 'Content/Page ID to watch'
        }
      },
      required: ['contentId']
    }
  },
  {
    name: 'unwatch_content',
    description: 'Stop watching a Confluence page or content',
    inputSchema: {
      type: 'object',
      properties: {
        contentId: {
          type: 'string',
          description: 'Content/Page ID to stop watching'
        }
      },
      required: ['contentId']
    }
  },

  // === Config Tools ===
  {
    name: 'get_config',
    description: 'Get user configuration value',
    inputSchema: {
      type: 'object',
      properties: {
        key: {
          type: 'string',
          description: 'Config key (e.g., "default_field_set")'
        }
      },
      required: ['key']
    }
  },
  {
    name: 'set_config',
    description: 'Set user configuration value',
    inputSchema: {
      type: 'object',
      properties: {
        key: {
          type: 'string',
          description: 'Config key (e.g., "default_field_set")'
        },
        value: {
          type: 'string',
          description: 'Config value'
        }
      },
      required: ['key', 'value']
    }
  },
  {
    name: 'list_config',
    description: 'List all user configuration values',
    inputSchema: {
      type: 'object',
      properties: {}
    }
  },
  {
    name: 'set_default_field_set',
    description: 'Set the default field set for Jira issue queries',
    inputSchema: {
      type: 'object',
      properties: {
        fieldSet: {
          type: 'string',
          enum: ['minimal', 'standard', 'extended', 'full'],
          description: 'Default field set to use for Jira'
        }
      },
      required: ['fieldSet']
    }
  },
  {
    name: 'set_default_confluence_field_set',
    description: 'Set the default field set for Confluence page queries',
    inputSchema: {
      type: 'object',
      properties: {
        fieldSet: {
          type: 'string',
          enum: ['minimal', 'standard', 'extended', 'full'],
          description: 'Default field set to use for Confluence'
        }
      },
      required: ['fieldSet']
    }
  },

  // === OKR Board Tools ===
  {
    name: 'set_okrboard_token',
    description: 'Set OKR Board API token for the current user',
    inputSchema: {
      type: 'object',
      properties: {
        token: {
          type: 'string',
          description: 'Oboard API token (from Oboard app settings in Jira)'
        }
      },
      required: ['token']
    }
  },
  {
    name: 'set_okrboard_base_url',
    description: 'Set OKR Board API base URL (cloud or self-hosted)',
    inputSchema: {
      type: 'object',
      properties: {
        baseUrl: {
          type: 'string',
          description: `API base URL (default: ${DEFAULT_BASE_URL})`
        }
      },
      required: ['baseUrl']
    }
  },
  {
    name: 'get_okrboard_connection',
    description: 'Get OKR Board connection status for the current user',
    inputSchema: {
      type: 'object',
      properties: {}
    }
  },
  {
    name: 'list_okr_workspaces',
    description: 'List OKR Board workspaces',
    inputSchema: {
      type: 'object',
      properties: {}
    }
  },
  {
    name: 'list_okr_intervals',
    description: 'List OKR Board intervals (cycles) for a workspace',
    inputSchema: {
      type: 'object',
      properties: {
        workspaceId: {
          type: 'string',
          description: 'Workspace ID'
        }
      },
      required: ['workspaceId']
    }
  },
  {
    name: 'list_okr_groups',
    description: 'List OKR Board groups for a workspace',
    inputSchema: {
      type: 'object',
      properties: {
        workspaceId: {
          type: 'string',
          description: 'Workspace ID'
        }
      },
      required: ['workspaceId']
    }
  },
  {
    name: 'list_okr_users',
    description: 'List OKR Board users for a workspace',
    inputSchema: {
      type: 'object',
      properties: {
        workspaceId: {
          type: 'string',
          description: 'Workspace ID'
        }
      },
      required: ['workspaceId']
    }
  },
  {
    name: 'list_okr_objectives',
    description: 'List OKR Board elements (objectives, KRs, and linked items) for a workspace/interval. Progress % is taken from element gradeToUse (Oboard UI Progress).',
    inputSchema: {
      type: 'object',
      properties: {
        workspaceId: {
          type: 'string',
          description: 'Workspace ID'
        },
        intervalId: {
          type: 'string',
          description: 'Interval ID (optional)'
        },
        startAt: {
          type: 'number',
          description: 'Pagination offset (default 0)'
        },
        maxResults: {
          type: 'number',
          description: 'Page size hint (default 200, max 500)'
        }
      },
      required: ['workspaceId']
    }
  },
  {
    name: 'create_okr_objective',
    description: 'Create an OKR Board objective',
    inputSchema: {
      type: 'object',
      properties: {
        workspaceId: {
          type: 'string',
          description: 'Workspace ID'
        },
        intervalId: {
          type: 'string',
          description: 'Interval ID'
        },
        groupId: {
          type: 'string',
          description: 'Group ID'
        },
        name: {
          type: 'string',
          description: 'Objective name'
        },
        typeId: {
          type: 'string',
          description: 'Objective type ID'
        },
        objective: {
          type: 'object',
          description: 'Additional objective payload fields'
        }
      },
      required: ['workspaceId', 'intervalId', 'groupId', 'name', 'typeId']
    }
  },
  {
    name: 'update_okr_objective',
    description: 'Update an OKR Board objective',
    inputSchema: {
      type: 'object',
      properties: {
        objectiveId: {
          type: 'string',
          description: 'Objective ID'
        },
        workspaceId: {
          type: 'string',
          description: 'Workspace ID'
        },
        intervalId: {
          type: 'string',
          description: 'Interval ID'
        },
        groupId: {
          type: 'string',
          description: 'Group ID'
        },
        name: {
          type: 'string',
          description: 'Objective name'
        },
        typeId: {
          type: 'string',
          description: 'Objective type ID'
        },
        objective: {
          type: 'object',
          description: 'Additional objective payload fields'
        }
      },
      required: ['objectiveId']
    }
  },
  {
    name: 'update_okr_key_result',
    description: 'Update an OKR Board key result',
    inputSchema: {
      type: 'object',
      properties: {
        keyResultId: {
          type: 'string',
          description: 'Key result ID'
        },
        keyResult: {
          type: 'object',
          description: 'Key result payload fields'
        }
      },
      required: ['keyResultId']
    }
  },
  {
    name: 'delete_okr_key_result',
    description: 'Delete an OKR Board key result (and nested items)',
    inputSchema: {
      type: 'object',
      properties: {
        keyResultId: {
          type: 'string',
          description: 'Key result ID'
        },
        payload: {
          type: 'object',
          description: 'Optional delete payload (endpoint-specific fields)'
        }
      },
      required: ['keyResultId']
    }
  }
];

/**
 * Get effective field set for Jira (user default or specified)
 */
async function getEffectiveFieldSet(specified) {
  if (specified) return specified;

  ensureStore();
  const email = getCurrentUser();
  if (email) {
    const defaultFieldSet = await fileStore.getConfig(email, 'default_field_set');
    if (defaultFieldSet && FIELD_SETS[defaultFieldSet]) {
      return defaultFieldSet;
    }
  }
  return 'minimal';
}

/**
 * Get effective field set for Confluence (user default or specified)
 */
async function getEffectiveConfluenceFieldSet(specified) {
  if (specified) return specified;

  ensureStore();
  const email = getCurrentUser();
  if (email) {
    // First check Confluence-specific default
    const confluenceFieldSet = await fileStore.getConfig(email, 'default_confluence_field_set');
    if (confluenceFieldSet && CONFLUENCE_FIELD_SETS[confluenceFieldSet]) {
      return confluenceFieldSet;
    }
    // Fall back to general default
    const defaultFieldSet = await fileStore.getConfig(email, 'default_field_set');
    if (defaultFieldSet && CONFLUENCE_FIELD_SETS[defaultFieldSet]) {
      return defaultFieldSet;
    }
  }
  return 'minimal';
}

async function handleToolCall(name, args) {
  ensureStore();
  const email = getCurrentUser();

  switch (name) {
    // === Jira Tools ===
    case 'list_projects': {
      const maxResults = Math.min(args.maxResults || 50, 200);
      const projects = await jira.listProjects(maxResults);
      return { projects, count: projects.length };
    }

    case 'get_project': {
      const project = await jira.getProject(args.projectKey);
      return project;
    }

    case 'search_issues': {
      const maxResults = Math.min(args.maxResults || 20, 100);
      const fieldSet = await getEffectiveFieldSet(args.fieldSet);
      const result = await jira.searchIssues(args.jql, {
        maxResults,
        nextPageToken: args.nextPageToken || null,
        fieldSet
      });
      return { ...result, fieldSet };
    }

    case 'get_issue': {
      const fieldSet = await getEffectiveFieldSet(args.fieldSet) || 'standard';
      const issue = await jira.getIssue(args.issueKey, fieldSet);
      return issue;
    }

    case 'get_issue_comments': {
      const maxResults = Math.min(args.maxResults || 10, 50);
      const comments = await jira.getIssueComments(args.issueKey, maxResults);
      return comments;
    }

    case 'add_comment': {
      const comment = await jira.addComment(args.issueKey, args.body);
      return comment;
    }

    // === Jira Project Management ===
    case 'create_project': {
      const data = {
        key: args.key,
        name: args.name,
        projectTypeKey: args.projectTypeKey || 'software'
      };
      if (args.projectTemplateKey) data.projectTemplateKey = args.projectTemplateKey;
      if (args.description) data.description = args.description;
      if (args.leadAccountId) data.leadAccountId = args.leadAccountId;
      if (args.assigneeType) data.assigneeType = args.assigneeType;
      return await jira.createProject(data);
    }

    case 'update_project': {
      const data = {};
      if (args.name) data.name = args.name;
      if (args.description) data.description = args.description;
      if (args.leadAccountId) data.leadAccountId = args.leadAccountId;
      if (args.assigneeType) data.assigneeType = args.assigneeType;
      return await jira.updateProject(args.projectKey, data);
    }

    case 'delete_project': {
      return await jira.deleteProject(args.projectKey);
    }

    case 'get_project_statuses': {
      return await jira.getProjectStatuses(args.projectKey);
    }

    // === Jira Field Management ===
    case 'list_fields': {
      const fields = await jira.listFields();
      return { fields, count: fields.length };
    }

    case 'create_field': {
      const data = {
        name: args.name,
        type: args.type
      };
      if (args.description) data.description = args.description;
      if (args.searcherKey) data.searcherKey = args.searcherKey;
      return await jira.createField(data);
    }

    case 'update_field': {
      const data = {};
      if (args.name) data.name = args.name;
      if (args.description) data.description = args.description;
      return await jira.updateField(args.fieldId, data);
    }

    case 'delete_field': {
      return await jira.deleteField(args.fieldId);
    }

    case 'trash_field': {
      return await jira.trashField(args.fieldId);
    }

    case 'restore_field': {
      return await jira.restoreField(args.fieldId);
    }

    case 'list_trashed_fields': {
      return await jira.listTrashedFields();
    }

    // === Jira Status Management ===
    case 'list_statuses': {
      return await jira.listStatuses({
        projectId: args.projectId,
        searchString: args.searchString,
        maxResults: Math.min(args.maxResults || 50, 200),
        startAt: args.startAt || 0
      });
    }

    case 'create_statuses': {
      return await jira.createStatuses({
        statuses: args.statuses,
        scope: args.scope
      });
    }

    case 'update_statuses': {
      return await jira.updateStatuses(args.statuses);
    }

    case 'delete_statuses': {
      return await jira.deleteStatuses(args.ids);
    }

    // === Jira Workflow Management ===
    case 'list_workflows': {
      return await jira.listWorkflows({
        workflowName: args.workflowName,
        projectId: args.projectId,
        maxResults: Math.min(args.maxResults || 50, 200),
        startAt: args.startAt || 0
      });
    }

    case 'create_workflows': {
      return await jira.createWorkflows({
        workflows: args.workflows,
        scope: args.scope
      });
    }

    case 'update_workflows': {
      return await jira.updateWorkflows({
        workflows: args.workflows
      });
    }

    case 'get_workflow_schemes': {
      return await jira.getWorkflowSchemes(args.projectId);
    }

    // === Confluence Tools ===
    case 'list_spaces': {
      const result = await confluence.listSpaces({
        limit: args.limit,
        cursor: args.cursor,
        type: args.type,
        status: args.status || 'current'
      });
      return { ...result, count: result.spaces.length };
    }

    case 'get_space': {
      const idOrKey = args.spaceIdOrKey;
      // If it looks like a numeric ID, use getSpace; otherwise search by key
      if (/^\d+$/.test(idOrKey)) {
        return await confluence.getSpace(idOrKey);
      } else {
        return await confluence.getSpaceByKey(idOrKey);
      }
    }

    case 'list_pages': {
      const fieldSet = await getEffectiveConfluenceFieldSet(args.fieldSet);
      const result = await confluence.listPages({
        spaceId: args.spaceId,
        limit: args.limit,
        cursor: args.cursor,
        status: args.status || 'current',
        sort: args.sort || '-modified-date',
        fieldSet
      });
      return { ...result, count: result.pages.length, fieldSet };
    }

    case 'get_page': {
      const fieldSet = await getEffectiveConfluenceFieldSet(args.fieldSet) || 'standard';
      const page = await confluence.getPage(args.pageId, {
        fieldSet,
        bodyFormat: args.bodyFormat
      });
      return page;
    }

    case 'search_confluence': {
      const result = await confluence.searchContent(args.query, {
        limit: Math.min(args.limit || 25, 100),
        cursor: args.cursor,
        spaceKey: args.spaceKey,
        type: args.type
      });
      return { ...result, count: result.results.length };
    }

    case 'get_page_labels': {
      const labels = await confluence.getPageLabels(args.pageId);
      return labels;
    }

    case 'get_watched_content': {
      const result = await confluence.getWatchedContent({
        type: args.type || 'page',
        limit: Math.min(args.limit || 25, 100),
        start: args.start || 0
      });
      return { ...result, count: result.results.length };
    }

    case 'is_watching_content': {
      return await confluence.isWatchingContent(args.contentId);
    }

    case 'watch_content': {
      return await confluence.watchContent(args.contentId);
    }

    case 'unwatch_content': {
      return await confluence.unwatchContent(args.contentId);
    }

    // === Config Tools ===
    case 'get_config': {
      if (!email) throw new Error('No user set');
      const value = await fileStore.getConfig(email, args.key);
      return { key: args.key, value };
    }

    case 'set_config': {
      if (!email) throw new Error('No user set');
      await fileStore.setConfig(email, args.key, args.value);
      return { key: args.key, value: args.value, updated: true };
    }

    case 'list_config': {
      if (!email) throw new Error('No user set');
      const config = await fileStore.getUserConfig(email);
      return { email, config };
    }

    case 'set_default_field_set': {
      if (!email) throw new Error('No user set');
      if (!FIELD_SETS[args.fieldSet]) {
        throw new Error(`Invalid field set: ${args.fieldSet}. Valid: ${Object.keys(FIELD_SETS).join(', ')}`);
      }
      await fileStore.setConfig(email, 'default_field_set', args.fieldSet);
      return { default_field_set: args.fieldSet, updated: true };
    }

    case 'set_default_confluence_field_set': {
      if (!email) throw new Error('No user set');
      if (!CONFLUENCE_FIELD_SETS[args.fieldSet]) {
        throw new Error(`Invalid field set: ${args.fieldSet}. Valid: ${Object.keys(CONFLUENCE_FIELD_SETS).join(', ')}`);
      }
      await fileStore.setConfig(email, 'default_confluence_field_set', args.fieldSet);
      return { default_confluence_field_set: args.fieldSet, updated: true };
    }

    // === OKR Board Tools ===
    case 'set_okrboard_token': {
      if (!email) throw new Error('No user set');
      await fileStore.setConfig(email, 'okrboard_api_token', args.token);
      return { okrboard_api_token: 'configured', updated: true };
    }

    case 'set_okrboard_base_url': {
      if (!email) throw new Error('No user set');
      const normalized = args.baseUrl.replace(/\/+$/, '');
      await fileStore.setConfig(email, 'okrboard_base_url', normalized);
      return { okrboard_base_url: normalized, updated: true };
    }

    case 'get_okrboard_connection': {
      if (!email) throw new Error('No user set');
      const token = await fileStore.getConfig(email, 'okrboard_api_token');
      const baseUrl = await fileStore.getConfig(email, 'okrboard_base_url');
      return {
        email,
        configured: !!(token || process.env.OKRBOARD_API_TOKEN),
        baseUrl: baseUrl || process.env.OKRBOARD_BASE_URL || DEFAULT_BASE_URL
      };
    }

    case 'list_okr_workspaces': {
      const workspaces = await okrboard.listWorkspaces();
      return {
        workspaces,
        count: Array.isArray(workspaces) ? workspaces.length : undefined
      };
    }

    case 'list_okr_intervals': {
      const intervals = await okrboard.listIntervals(args.workspaceId);
      return {
        workspaceId: args.workspaceId,
        intervals,
        count: Array.isArray(intervals) ? intervals.length : undefined
      };
    }

    case 'list_okr_groups': {
      const groups = await okrboard.listGroups(args.workspaceId);
      return {
        workspaceId: args.workspaceId,
        groups,
        count: Array.isArray(groups) ? groups.length : undefined
      };
    }

    case 'list_okr_users': {
      const users = await okrboard.listUsers(args.workspaceId);
      return {
        workspaceId: args.workspaceId,
        users,
        count: Array.isArray(users) ? users.length : undefined
      };
    }

    case 'list_okr_objectives': {
      const objectives = await okrboard.listObjectives(args.workspaceId, {
        intervalId: args.intervalId,
        startAt: args.startAt || 0,
        maxResults: args.maxResults || 200
      });

      const elements = Array.isArray(objectives)
        ? objectives.map((item) => ({
            id: item.id,
            displayId: item.displayId,
            name: item.name,
            level: item.levelName,
            parentId: item.parentId,
            intervalId: item.intervalId,
            intervalName: item.intervalName,
            progressPercent: item.gradeToUse,
            owners: (item.users || []).map((u) => ({
              accountId: u.accountId,
              email: u.email,
              displayName: u.displayName || u.name
            })),
            groups: (item.groups || []).map((g) => ({
              id: g.id,
              name: g.name
            }))
          }))
        : [];

      return {
        workspaceId: args.workspaceId,
        intervalId: args.intervalId || null,
        startAt: args.startAt || 0,
        progressMetric: 'gradeToUse',
        progressField: 'progressPercent',
        elements,
        count: elements.length
      };
    }

    case 'create_okr_objective': {
      const payload = {
        ...(args.objective || {}),
        workspaceId: args.workspaceId,
        intervalId: args.intervalId,
        groupId: args.groupId,
        name: args.name,
        typeId: args.typeId
      };
      return await okrboard.createObjective(payload);
    }

    case 'update_okr_objective': {
      const payload = {
        ...(args.objective || {}),
        objectiveId: args.objectiveId
      };
      if (args.workspaceId) payload.workspaceId = args.workspaceId;
      if (args.intervalId) payload.intervalId = args.intervalId;
      if (args.groupId) payload.groupId = args.groupId;
      if (args.name) payload.name = args.name;
      if (args.typeId) payload.typeId = args.typeId;
      return await okrboard.updateObjective(payload);
    }

    case 'update_okr_key_result': {
      const payload = {
        ...(args.keyResult || {}),
        keyResultId: args.keyResultId
      };
      return await okrboard.updateKeyResult(payload);
    }

    case 'delete_okr_key_result': {
      const payload = {
        ...(args.payload || {}),
        keyResultId: args.keyResultId
      };
      return await okrboard.deleteKeyResult(payload);
    }

    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

module.exports = { TOOLS, handleToolCall };
