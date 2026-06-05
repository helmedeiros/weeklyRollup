/**
 * Unit tests for tools.js
 */

jest.mock('../src/jira', () => {
  const mockJiraAPI = {
    listProjects: jest.fn(),
    getProject: jest.fn(),
    searchIssues: jest.fn(),
    getIssue: jest.fn(),
    getIssueComments: jest.fn(),
    addComment: jest.fn(),
    createProject: jest.fn(),
    updateProject: jest.fn(),
    deleteProject: jest.fn(),
    getProjectStatuses: jest.fn(),
    listFields: jest.fn(),
    createField: jest.fn(),
    updateField: jest.fn(),
    deleteField: jest.fn(),
    trashField: jest.fn(),
    restoreField: jest.fn(),
    listTrashedFields: jest.fn(),
    listStatuses: jest.fn(),
    createStatuses: jest.fn(),
    updateStatuses: jest.fn(),
    deleteStatuses: jest.fn(),
    listWorkflows: jest.fn(),
    createWorkflows: jest.fn(),
    updateWorkflows: jest.fn(),
    getWorkflowSchemes: jest.fn()
  };

  return {
    JiraAPI: jest.fn(() => mockJiraAPI),
    FIELD_SETS: {
      minimal: ['key', 'summary', 'status'],
      standard: ['key', 'summary', 'status', 'assignee'],
      extended: ['key', 'summary', 'status', 'assignee', 'labels'],
      full: ['*all']
    },
    __mockInstance: mockJiraAPI
  };
});

jest.mock('../src/confluence', () => {
  const mockConfluenceAPI = {
    listSpaces: jest.fn(),
    getSpace: jest.fn(),
    getSpaceByKey: jest.fn(),
    listPages: jest.fn(),
    getPage: jest.fn(),
    searchContent: jest.fn(),
    getPageLabels: jest.fn(),
    getWatchedContent: jest.fn(),
    isWatchingContent: jest.fn(),
    watchContent: jest.fn(),
    unwatchContent: jest.fn()
  };

  return {
    ConfluenceAPI: jest.fn(() => mockConfluenceAPI),
    CONFLUENCE_FIELD_SETS: {
      minimal: { include: [], bodyFormat: null },
      standard: { include: ['version'], bodyFormat: null },
      extended: { include: ['version', 'labels'], bodyFormat: null },
      full: { include: ['version', 'labels', 'operations'], bodyFormat: 'storage' }
    },
    __mockInstance: mockConfluenceAPI
  };
});

jest.mock('../src/okrboard', () => {
  const mockOkrBoardAPI = {
    listWorkspaces: jest.fn(),
    listIntervals: jest.fn(),
    listGroups: jest.fn(),
    listUsers: jest.fn(),
    listObjectives: jest.fn(),
    createObjective: jest.fn(),
    updateObjective: jest.fn(),
    updateKeyResult: jest.fn(),
    deleteKeyResult: jest.fn()
  };

  return {
    OkrBoardAPI: jest.fn(() => mockOkrBoardAPI),
    DEFAULT_BASE_URL: 'https://backend.okr-api.com/api/v1',
    __mockInstance: mockOkrBoardAPI
  };
});

jest.mock('../src/file-store', () => ({
  init: jest.fn(),
  getConfig: jest.fn(),
  setConfig: jest.fn(),
  getUserConfig: jest.fn()
}));

jest.mock('../src/auth', () => ({
  getCurrentUser: jest.fn()
}));

describe('tools module', () => {
  let TOOLS;
  let handleToolCall;
  let jiraMock;
  let confluenceMock;
  let okrboardMock;
  let fileStore;
  let auth;

  beforeEach(() => {
    jest.resetModules();
    jest.clearAllMocks();

    const toolsModule = require('../src/tools');
    TOOLS = toolsModule.TOOLS;
    handleToolCall = toolsModule.handleToolCall;

    jiraMock = require('../src/jira').__mockInstance;
    confluenceMock = require('../src/confluence').__mockInstance;
    okrboardMock = require('../src/okrboard').__mockInstance;
    fileStore = require('../src/file-store');
    auth = require('../src/auth');

    auth.getCurrentUser.mockReturnValue('test@example.com');
    delete process.env.OKRBOARD_API_TOKEN;
    delete process.env.OKRBOARD_BASE_URL;
  });

  describe('TOOLS array', () => {
    it('should have 52 tools defined', () => {
      expect(TOOLS).toHaveLength(52);
    });

    it('should have all Jira read tools', () => {
      const jiraReadTools = ['list_projects', 'get_project', 'search_issues', 'get_issue', 'get_issue_comments', 'add_comment'];
      jiraReadTools.forEach(name => {
        expect(TOOLS.find(t => t.name === name)).toBeDefined();
      });
    });

    it('should have all Jira project management tools', () => {
      const projectTools = ['create_project', 'update_project', 'delete_project', 'get_project_statuses'];
      projectTools.forEach(name => {
        expect(TOOLS.find(t => t.name === name)).toBeDefined();
      });
    });

    it('should have all Jira field management tools', () => {
      const fieldTools = ['list_fields', 'create_field', 'update_field', 'delete_field', 'trash_field', 'restore_field', 'list_trashed_fields'];
      fieldTools.forEach(name => {
        expect(TOOLS.find(t => t.name === name)).toBeDefined();
      });
    });

    it('should have all Confluence tools', () => {
      const confluenceTools = ['list_spaces', 'get_space', 'list_pages', 'get_page', 'search_confluence', 'get_page_labels', 'get_watched_content', 'is_watching_content', 'watch_content', 'unwatch_content'];
      confluenceTools.forEach(name => {
        expect(TOOLS.find(t => t.name === name)).toBeDefined();
      });
    });

    it('should have all config tools', () => {
      const configTools = ['get_config', 'set_config', 'list_config', 'set_default_field_set', 'set_default_confluence_field_set'];
      configTools.forEach(name => {
        expect(TOOLS.find(t => t.name === name)).toBeDefined();
      });
    });

    it('should have all OKR Board tools', () => {
      const okrTools = [
        'set_okrboard_token', 'set_okrboard_base_url', 'get_okrboard_connection',
        'list_okr_workspaces', 'list_okr_intervals', 'list_okr_groups',
        'list_okr_users', 'list_okr_objectives', 'create_okr_objective',
        'update_okr_objective', 'update_okr_key_result', 'delete_okr_key_result'
      ];
      okrTools.forEach(name => {
        expect(TOOLS.find(t => t.name === name)).toBeDefined();
      });
    });

    it('should have valid input schemas for all tools', () => {
      TOOLS.forEach(tool => {
        expect(tool.inputSchema).toBeDefined();
        expect(tool.inputSchema.type).toBe('object');
        expect(tool.inputSchema.properties).toBeDefined();
      });
    });
  });

  describe('Jira Read Tools', () => {
    describe('list_projects', () => {
      it('should return projects with count', async () => {
        jiraMock.listProjects.mockResolvedValue([
          { key: 'PROJ1', name: 'Project 1' },
          { key: 'PROJ2', name: 'Project 2' }
        ]);

        const result = await handleToolCall('list_projects', {});

        expect(result.projects).toHaveLength(2);
        expect(result.count).toBe(2);
      });

      it('should cap maxResults at 200', async () => {
        jiraMock.listProjects.mockResolvedValue([]);

        await handleToolCall('list_projects', { maxResults: 500 });

        expect(jiraMock.listProjects).toHaveBeenCalledWith(200);
      });
    });

    describe('get_project', () => {
      it('should return project details', async () => {
        jiraMock.getProject.mockResolvedValue({ key: 'PROJ', name: 'Project' });

        const result = await handleToolCall('get_project', { projectKey: 'PROJ' });

        expect(result.key).toBe('PROJ');
      });
    });

    describe('search_issues', () => {
      it('should search with JQL and return results with fieldSet', async () => {
        jiraMock.searchIssues.mockResolvedValue({
          issues: [{ key: 'PROJ-1' }],
          total: 1,
          isLast: true
        });

        const result = await handleToolCall('search_issues', { jql: 'project = PROJ' });

        expect(result.issues).toHaveLength(1);
        expect(result.fieldSet).toBeDefined();
      });

      it('should use user default field set', async () => {
        fileStore.getConfig.mockResolvedValue('standard');
        jiraMock.searchIssues.mockResolvedValue({ issues: [], total: 0 });

        const result = await handleToolCall('search_issues', { jql: 'project = PROJ' });

        expect(result.fieldSet).toBe('standard');
      });

      it('should cap maxResults at 100', async () => {
        jiraMock.searchIssues.mockResolvedValue({ issues: [], total: 0 });

        await handleToolCall('search_issues', { jql: 'project = PROJ', maxResults: 500 });

        expect(jiraMock.searchIssues).toHaveBeenCalledWith(
          'project = PROJ',
          expect.objectContaining({ maxResults: 100 })
        );
      });
    });

    describe('get_issue', () => {
      it('should return issue details', async () => {
        jiraMock.getIssue.mockResolvedValue({ key: 'PROJ-1', summary: 'Test' });

        const result = await handleToolCall('get_issue', { issueKey: 'PROJ-1' });

        expect(result.key).toBe('PROJ-1');
      });
    });

    describe('add_comment', () => {
      it('should add comment to issue', async () => {
        jiraMock.addComment.mockResolvedValue({ id: '1', body: 'Comment' });

        const result = await handleToolCall('add_comment', { issueKey: 'PROJ-1', body: 'Comment' });

        expect(result.id).toBe('1');
        expect(jiraMock.addComment).toHaveBeenCalledWith('PROJ-1', 'Comment');
      });
    });
  });

  describe('Jira Project Management Tools', () => {
    describe('create_project', () => {
      it('should create project with required fields', async () => {
        jiraMock.createProject.mockResolvedValue({ id: '1', key: 'NEW' });

        const result = await handleToolCall('create_project', { key: 'NEW', name: 'New Project' });

        expect(result.key).toBe('NEW');
        expect(jiraMock.createProject).toHaveBeenCalledWith(
          expect.objectContaining({
            key: 'NEW',
            name: 'New Project',
            projectTypeKey: 'software'
          })
        );
      });
    });

    describe('delete_project', () => {
      it('should delete project', async () => {
        jiraMock.deleteProject.mockResolvedValue({ deleted: true });

        const result = await handleToolCall('delete_project', { projectKey: 'PROJ' });

        expect(result.deleted).toBe(true);
      });
    });
  });

  describe('Jira Field Management Tools', () => {
    describe('list_fields', () => {
      it('should return fields with count', async () => {
        jiraMock.listFields.mockResolvedValue([{ id: 'summary', name: 'Summary' }]);

        const result = await handleToolCall('list_fields', {});

        expect(result.fields).toHaveLength(1);
        expect(result.count).toBe(1);
      });
    });

    describe('trash_field', () => {
      it('should trash field', async () => {
        jiraMock.trashField.mockResolvedValue({ trashed: true });

        const result = await handleToolCall('trash_field', { fieldId: 'customfield_10001' });

        expect(result.trashed).toBe(true);
      });
    });
  });

  describe('Jira Status Management Tools', () => {
    describe('create_statuses', () => {
      it('should create statuses with scope', async () => {
        jiraMock.createStatuses.mockResolvedValue([{ id: '1', name: 'New' }]);

        const result = await handleToolCall('create_statuses', {
          statuses: [{ name: 'New', statusCategory: 'TODO' }],
          scope: { type: 'GLOBAL' }
        });

        expect(result).toHaveLength(1);
      });
    });

    describe('delete_statuses', () => {
      it('should delete statuses', async () => {
        jiraMock.deleteStatuses.mockResolvedValue({ deleted: true, ids: ['1', '2'] });

        const result = await handleToolCall('delete_statuses', { ids: ['1', '2'] });

        expect(result.deleted).toBe(true);
      });
    });
  });

  describe('Confluence Tools', () => {
    describe('list_spaces', () => {
      it('should return spaces with count', async () => {
        confluenceMock.listSpaces.mockResolvedValue({
          spaces: [{ id: '1', key: 'SPACE' }],
          hasMore: false
        });

        const result = await handleToolCall('list_spaces', {});

        expect(result.spaces).toHaveLength(1);
        expect(result.count).toBe(1);
      });
    });

    describe('get_space', () => {
      it('should get space by numeric ID', async () => {
        confluenceMock.getSpace.mockResolvedValue({ id: '123', key: 'SPACE' });

        const result = await handleToolCall('get_space', { spaceIdOrKey: '123' });

        expect(confluenceMock.getSpace).toHaveBeenCalledWith('123');
        expect(result.id).toBe('123');
      });

      it('should search space by key', async () => {
        confluenceMock.getSpaceByKey.mockResolvedValue({ id: '123', key: 'SPACE' });

        const result = await handleToolCall('get_space', { spaceIdOrKey: 'SPACE' });

        expect(confluenceMock.getSpaceByKey).toHaveBeenCalledWith('SPACE');
        expect(result.key).toBe('SPACE');
      });
    });

    describe('list_pages', () => {
      it('should return pages with fieldSet', async () => {
        confluenceMock.listPages.mockResolvedValue({
          pages: [{ id: '1', title: 'Page' }],
          hasMore: false
        });

        const result = await handleToolCall('list_pages', { spaceId: '100' });

        expect(result.pages).toHaveLength(1);
        expect(result.fieldSet).toBeDefined();
      });
    });

    describe('search_confluence', () => {
      it('should search with query and return count', async () => {
        confluenceMock.searchContent.mockResolvedValue({
          results: [{ id: '1', title: 'Found' }],
          totalSize: 1
        });

        const result = await handleToolCall('search_confluence', { query: 'test' });

        expect(result.results).toHaveLength(1);
        expect(result.count).toBe(1);
      });
    });

    describe('watch_content', () => {
      it('should start watching content', async () => {
        confluenceMock.watchContent.mockResolvedValue({ contentId: '123', watching: true });

        const result = await handleToolCall('watch_content', { contentId: '123' });

        expect(result.watching).toBe(true);
      });
    });
  });

  describe('Config Tools', () => {
    describe('get_config', () => {
      it('should return config value', async () => {
        fileStore.getConfig.mockResolvedValue('standard');

        const result = await handleToolCall('get_config', { key: 'default_field_set' });

        expect(result.value).toBe('standard');
      });

      it('should throw error if no user set', async () => {
        auth.getCurrentUser.mockReturnValue(null);

        await expect(handleToolCall('get_config', { key: 'test' }))
          .rejects.toThrow('No user set');
      });
    });

    describe('set_config', () => {
      it('should set config value', async () => {
        fileStore.setConfig.mockResolvedValue();

        const result = await handleToolCall('set_config', { key: 'test', value: 'value' });

        expect(result.updated).toBe(true);
        expect(fileStore.setConfig).toHaveBeenCalledWith('test@example.com', 'test', 'value');
      });
    });

    describe('set_default_field_set', () => {
      it('should set valid field set', async () => {
        fileStore.setConfig.mockResolvedValue();

        const result = await handleToolCall('set_default_field_set', { fieldSet: 'standard' });

        expect(result.default_field_set).toBe('standard');
        expect(result.updated).toBe(true);
      });

      it('should throw error for invalid field set', async () => {
        await expect(handleToolCall('set_default_field_set', { fieldSet: 'invalid' }))
          .rejects.toThrow('Invalid field set: invalid');
      });
    });

    describe('set_default_confluence_field_set', () => {
      it('should set valid Confluence field set', async () => {
        fileStore.setConfig.mockResolvedValue();

        const result = await handleToolCall('set_default_confluence_field_set', { fieldSet: 'full' });

        expect(result.default_confluence_field_set).toBe('full');
        expect(result.updated).toBe(true);
      });
    });
  });

  describe('OKR Board Tools', () => {
    describe('set_okrboard_token', () => {
      it('should store token for current user', async () => {
        fileStore.setConfig.mockResolvedValue();

        const result = await handleToolCall('set_okrboard_token', { token: 'my-api-token' });

        expect(result.okrboard_api_token).toBe('configured');
        expect(result.updated).toBe(true);
        expect(fileStore.setConfig).toHaveBeenCalledWith('test@example.com', 'okrboard_api_token', 'my-api-token');
      });
    });

    describe('get_okrboard_connection', () => {
      it('should return configured status from stored config', async () => {
        fileStore.getConfig
          .mockResolvedValueOnce('my-token')
          .mockResolvedValueOnce('https://custom.api.com');

        const result = await handleToolCall('get_okrboard_connection', {});

        expect(result.email).toBe('test@example.com');
        expect(result.configured).toBe(true);
        expect(result.baseUrl).toBe('https://custom.api.com');
      });

      it('should fall back to env values', async () => {
        process.env.OKRBOARD_API_TOKEN = 'env-token';
        process.env.OKRBOARD_BASE_URL = 'https://env.api/v1';
        fileStore.getConfig
          .mockResolvedValueOnce(null)
          .mockResolvedValueOnce(null);

        const result = await handleToolCall('get_okrboard_connection', {});

        expect(result.configured).toBe(true);
        expect(result.baseUrl).toBe('https://env.api/v1');
      });
    });

    describe('list_okr_workspaces', () => {
      it('should return workspaces with count', async () => {
        okrboardMock.listWorkspaces.mockResolvedValue([{ id: 'ws1', name: 'Workspace 1' }]);

        const result = await handleToolCall('list_okr_workspaces', {});

        expect(result.workspaces).toHaveLength(1);
        expect(result.count).toBe(1);
      });
    });

    describe('list_okr_objectives', () => {
      it('should map objective elements with progress', async () => {
        okrboardMock.listObjectives.mockResolvedValue([
          {
            id: 'obj1',
            displayId: 'O-1',
            name: 'Increase Revenue',
            levelName: 'objective',
            parentId: null,
            intervalId: 'int1',
            intervalName: 'Q1 2026',
            gradeToUse: 75,
            users: [{ accountId: 'u1', email: 'alice@test.com', displayName: 'Alice' }],
            groups: [{ id: 'g1', name: 'Engineering' }]
          }
        ]);

        const result = await handleToolCall('list_okr_objectives', {
          workspaceId: 'ws1',
          intervalId: 'int1'
        });

        expect(result.workspaceId).toBe('ws1');
        expect(result.intervalId).toBe('int1');
        expect(result.progressField).toBe('progressPercent');
        expect(result.elements[0].progressPercent).toBe(75);
        expect(result.count).toBe(1);
      });
    });
  });

  describe('Unknown tool', () => {
    it('should throw error for unknown tool', async () => {
      await expect(handleToolCall('unknown_tool', {}))
        .rejects.toThrow('Unknown tool: unknown_tool');
    });
  });
});
