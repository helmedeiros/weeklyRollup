/**
 * Unit tests for jira.js
 */

// Create a mock function that also has method properties
const mockAxios = jest.fn();
mockAxios.post = jest.fn();
mockAxios.get = jest.fn();
mockAxios.put = jest.fn();
mockAxios.delete = jest.fn();

jest.mock('axios', () => mockAxios);
jest.mock('../src/auth', () => ({
  getValidAccessToken: jest.fn(),
  getCurrentUser: jest.fn()
}));
jest.mock('../src/file-store', () => ({
  init: jest.fn()
}));

const axios = require('axios');

describe('jira module', () => {
  let JiraAPI;
  let FIELD_SETS;
  let jira;
  let auth;

  const mockToken = {
    cloud_id: 'test-cloud-id',
    access_token: 'test-access-token'
  };

  beforeEach(() => {
    jest.resetModules();
    jest.clearAllMocks();

    const jiraModule = require('../src/jira');
    JiraAPI = jiraModule.JiraAPI;
    FIELD_SETS = jiraModule.FIELD_SETS;
    jira = new JiraAPI();

    auth = require('../src/auth');
    auth.getValidAccessToken.mockResolvedValue(mockToken);
    auth.getCurrentUser.mockReturnValue('test@example.com');
  });

  describe('FIELD_SETS', () => {
    it('should have minimal field set', () => {
      expect(FIELD_SETS.minimal).toEqual(['key', 'summary', 'status', 'priority', 'issuetype']);
    });

    it('should have standard field set', () => {
      expect(FIELD_SETS.standard).toContain('assignee');
      expect(FIELD_SETS.standard).toContain('reporter');
      expect(FIELD_SETS.standard).toContain('created');
      expect(FIELD_SETS.standard).toContain('updated');
    });

    it('should have extended field set', () => {
      expect(FIELD_SETS.extended).toContain('labels');
      expect(FIELD_SETS.extended).toContain('components');
      expect(FIELD_SETS.extended).toContain('fixVersions');
    });

    it('should have full field set', () => {
      expect(FIELD_SETS.full).toEqual(['*all']);
    });
  });

  describe('getFields', () => {
    it('should return minimal fields by default', () => {
      expect(jira.getFields()).toEqual(FIELD_SETS.minimal);
    });

    it('should return requested field set', () => {
      expect(jira.getFields('standard')).toEqual(FIELD_SETS.standard);
      expect(jira.getFields('extended')).toEqual(FIELD_SETS.extended);
      expect(jira.getFields('full')).toEqual(FIELD_SETS.full);
    });

    it('should fallback to minimal for invalid field set', () => {
      expect(jira.getFields('invalid')).toEqual(FIELD_SETS.minimal);
    });
  });

  describe('init', () => {
    it('should initialize and return baseUrl and accessToken', async () => {
      const result = await jira.init();

      expect(result.baseUrl).toBe('https://api.atlassian.com/ex/jira/test-cloud-id/rest/api/3');
      expect(result.accessToken).toBe('test-access-token');
    });

    it('should call getValidAccessToken', async () => {
      await jira.init();

      expect(auth.getValidAccessToken).toHaveBeenCalled();
    });
  });

  describe('request', () => {
    it('should force refresh and retry once after a 401 response', async () => {
      mockAxios
        .mockRejectedValueOnce({ response: { status: 401 } })
        .mockResolvedValueOnce({ data: [] });

      await jira.listProjects(10);

      expect(auth.getValidAccessToken).toHaveBeenNthCalledWith(1, 'test@example.com', { forceRefresh: false });
      expect(auth.getValidAccessToken).toHaveBeenNthCalledWith(2, 'test@example.com', { forceRefresh: true });
      expect(mockAxios).toHaveBeenCalledTimes(2);
    });
  });

  describe('Projects', () => {
    describe('listProjects', () => {
      it('should return formatted projects', async () => {
        mockAxios.mockResolvedValueOnce({
          data: [
            { key: 'PROJ1', name: 'Project 1', projectTypeKey: 'software' },
            { key: 'PROJ2', name: 'Project 2', projectTypeKey: 'business' }
          ]
        });

        const result = await jira.listProjects(50);

        expect(result).toHaveLength(2);
        expect(result[0]).toEqual({
          key: 'PROJ1',
          name: 'Project 1',
          projectTypeKey: 'software'
        });
      });

      it('should pass maxResults to API', async () => {
        mockAxios.mockResolvedValueOnce({ data: [] });

        await jira.listProjects(100);

        expect(mockAxios).toHaveBeenCalledWith(
          expect.objectContaining({
            params: { maxResults: 100 }
          })
        );
      });
    });

    describe('getProject', () => {
      it('should return formatted project details', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            key: 'PROJ',
            name: 'Project',
            description: 'A project',
            lead: { displayName: 'John Doe' },
            projectTypeKey: 'software',
            self: 'https://api.atlassian.com/project/123'
          }
        });

        const result = await jira.getProject('PROJ');

        expect(result).toEqual({
          key: 'PROJ',
          name: 'Project',
          description: 'A project',
          lead: 'John Doe',
          projectTypeKey: 'software',
          url: 'https://api.atlassian.com/project/123'
        });
      });
    });

    describe('createProject', () => {
      it('should create project and return result', async () => {
        mockAxios.mockResolvedValueOnce({
          data: { id: '123', key: 'NEW', self: 'https://...' }
        });

        const result = await jira.createProject({
          key: 'NEW',
          name: 'New Project',
          projectTypeKey: 'software'
        });

        expect(result).toEqual({
          id: '123',
          key: 'NEW',
          name: 'New Project',
          self: 'https://...'
        });
      });
    });

    describe('updateProject', () => {
      it('should update project', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            key: 'PROJ',
            name: 'Updated',
            description: 'New desc',
            lead: { displayName: 'Jane' },
            projectTypeKey: 'software'
          }
        });

        const result = await jira.updateProject('PROJ', { name: 'Updated' });

        expect(result.name).toBe('Updated');
      });
    });

    describe('deleteProject', () => {
      it('should delete project', async () => {
        mockAxios.mockResolvedValueOnce({ data: null });

        const result = await jira.deleteProject('PROJ');

        expect(result).toEqual({ deleted: true, projectKeyOrId: 'PROJ' });
      });
    });

    describe('getProjectStatuses', () => {
      it('should return statuses per issue type', async () => {
        mockAxios.mockResolvedValueOnce({
          data: [
            {
              name: 'Bug',
              statuses: [
                { id: '1', name: 'Open', statusCategory: { name: 'To Do' } },
                { id: '2', name: 'Done', statusCategory: { name: 'Done' } }
              ]
            }
          ]
        });

        const result = await jira.getProjectStatuses('PROJ');

        expect(result).toHaveLength(1);
        expect(result[0].issueType).toBe('Bug');
        expect(result[0].statuses).toHaveLength(2);
      });
    });
  });

  describe('Fields', () => {
    describe('listFields', () => {
      it('should return formatted fields', async () => {
        mockAxios.mockResolvedValueOnce({
          data: [
            { id: 'summary', name: 'Summary', custom: false, schema: { type: 'string' }, searchable: true },
            { id: 'customfield_10001', name: 'Custom', custom: true, schema: { type: 'string' }, searchable: true }
          ]
        });

        const result = await jira.listFields();

        expect(result).toHaveLength(2);
        expect(result[0]).toEqual({
          id: 'summary',
          name: 'Summary',
          custom: false,
          schema: 'string',
          searchable: true
        });
      });
    });

    describe('createField', () => {
      it('should create custom field', async () => {
        mockAxios.mockResolvedValueOnce({
          data: { id: 'customfield_10002', name: 'New Field', custom: true, schema: { type: 'string' } }
        });

        const result = await jira.createField({ name: 'New Field', type: 'string' });

        expect(result.id).toBe('customfield_10002');
      });
    });

    describe('trashField', () => {
      it('should trash field', async () => {
        mockAxios.mockResolvedValueOnce({ data: null });

        const result = await jira.trashField('customfield_10001');

        expect(result).toEqual({ trashed: true, fieldId: 'customfield_10001' });
      });
    });

    describe('restoreField', () => {
      it('should restore field', async () => {
        mockAxios.mockResolvedValueOnce({ data: null });

        const result = await jira.restoreField('customfield_10001');

        expect(result).toEqual({ restored: true, fieldId: 'customfield_10001' });
      });
    });

    describe('listTrashedFields', () => {
      it('should return trashed fields', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            total: 1,
            values: [{ id: 'customfield_10001', name: 'Trashed', schema: { type: 'string' }, lastUsed: '2024-01-01' }]
          }
        });

        const result = await jira.listTrashedFields();

        expect(result.total).toBe(1);
        expect(result.fields).toHaveLength(1);
      });
    });
  });

  describe('Statuses', () => {
    describe('listStatuses', () => {
      it('should return paginated statuses', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            total: 10,
            values: [
              { id: '1', name: 'Open', statusCategory: 'TODO', scope: { type: 'PROJECT', project: { id: '100' } } }
            ],
            isLast: false
          }
        });

        const result = await jira.listStatuses({ projectId: '100', maxResults: 50 });

        expect(result.total).toBe(10);
        expect(result.statuses).toHaveLength(1);
        expect(result.isLast).toBe(false);
      });
    });

    describe('createStatuses', () => {
      it('should create statuses', async () => {
        mockAxios.mockResolvedValueOnce({
          data: [{ id: '1', name: 'New Status', statusCategory: 'TODO' }]
        });

        const result = await jira.createStatuses({
          statuses: [{ name: 'New Status', statusCategory: 'TODO' }],
          scope: { type: 'GLOBAL' }
        });

        expect(result).toHaveLength(1);
        expect(result[0].name).toBe('New Status');
      });
    });

    describe('deleteStatuses', () => {
      it('should delete statuses', async () => {
        mockAxios.mockResolvedValueOnce({ data: null });

        const result = await jira.deleteStatuses(['1', '2']);

        expect(result).toEqual({ deleted: true, ids: ['1', '2'] });
      });
    });
  });

  describe('Workflows', () => {
    describe('listWorkflows', () => {
      it('should return paginated workflows', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            total: 5,
            values: [
              {
                id: { name: 'Default' },
                description: 'Default workflow',
                created: '2024-01-01',
                updated: '2024-01-02',
                statuses: [{ name: 'Open' }, { name: 'Done' }],
                isDefault: true
              }
            ],
            isLast: true
          }
        });

        const result = await jira.listWorkflows();

        expect(result.total).toBe(5);
        expect(result.workflows[0].name).toBe('Default');
        expect(result.workflows[0].statuses).toEqual(['Open', 'Done']);
      });
    });
  });

  describe('Issues', () => {
    describe('searchIssues', () => {
      it('should search issues with JQL', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            issues: [
              {
                key: 'PROJ-1',
                fields: {
                  summary: 'Test issue',
                  status: { name: 'Open', statusCategory: { name: 'To Do' } },
                  priority: { name: 'High' },
                  issuetype: { name: 'Bug' }
                }
              }
            ],
            nextPageToken: null
          }
        });

        const result = await jira.searchIssues('project = PROJ');

        expect(result.issues).toHaveLength(1);
        expect(result.issues[0].key).toBe('PROJ-1');
        expect(result.issues[0].summary).toBe('Test issue');
        expect(result.isLast).toBe(true);
      });

      it('should handle pagination token', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            issues: [],
            nextPageToken: 'token123'
          }
        });

        const result = await jira.searchIssues('project = PROJ', { nextPageToken: 'prevToken' });

        expect(mockAxios).toHaveBeenCalledWith(
          expect.objectContaining({
            data: expect.objectContaining({
              nextPageToken: 'prevToken'
            })
          })
        );
        expect(result.nextPageToken).toBe('token123');
      });
    });

    describe('getIssue', () => {
      it('should get issue details', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            key: 'PROJ-1',
            fields: {
              summary: 'Test',
              status: { name: 'Open', statusCategory: { name: 'To Do' } },
              priority: { name: 'High' },
              issuetype: { name: 'Bug' },
              assignee: { displayName: 'John' },
              description: {
                type: 'doc',
                content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Description text' }] }]
              }
            }
          }
        });

        const result = await jira.getIssue('PROJ-1', 'standard');

        expect(result.key).toBe('PROJ-1');
        expect(result.assignee).toBe('John');
        expect(result.description).toBe('Description text');
      });
    });

    describe('getIssueComments', () => {
      it('should return formatted comments', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            total: 1,
            comments: [
              {
                id: '1',
                author: { displayName: 'John' },
                body: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Comment text' }] }] },
                created: '2024-01-01',
                updated: '2024-01-02'
              }
            ]
          }
        });

        const result = await jira.getIssueComments('PROJ-1');

        expect(result.total).toBe(1);
        expect(result.comments[0].author).toBe('John');
        expect(result.comments[0].body).toBe('Comment text');
      });
    });

    describe('addComment', () => {
      it('should add comment with ADF format', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            id: '1',
            author: { displayName: 'John' },
            body: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'New comment' }] }] },
            created: '2024-01-01'
          }
        });

        const result = await jira.addComment('PROJ-1', 'New comment');

        expect(result.id).toBe('1');
        expect(result.body).toBe('New comment');
        expect(mockAxios).toHaveBeenCalledWith(
          expect.objectContaining({
            data: expect.objectContaining({
              body: expect.objectContaining({
                type: 'doc',
                version: 1
              })
            })
          })
        );
      });
    });
  });

  describe('Formatting', () => {
    describe('extractTextFromAdf', () => {
      it('should extract text from ADF document', () => {
        const adf = {
          type: 'doc',
          content: [
            {
              type: 'paragraph',
              content: [
                { type: 'text', text: 'Hello ' },
                { type: 'text', text: 'World' }
              ]
            }
          ]
        };

        expect(jira.extractTextFromAdf(adf)).toBe('Hello World');
      });

      it('should return empty string for null', () => {
        expect(jira.extractTextFromAdf(null)).toBe('');
      });

      it('should return string as-is', () => {
        expect(jira.extractTextFromAdf('plain text')).toBe('plain text');
      });

      it('should truncate to 2000 characters', () => {
        const longText = 'x'.repeat(3000);
        const adf = {
          type: 'doc',
          content: [{ type: 'paragraph', content: [{ type: 'text', text: longText }] }]
        };

        expect(jira.extractTextFromAdf(adf)).toHaveLength(2000);
      });
    });

    describe('formatIssue', () => {
      it('should format issue with basic fields', () => {
        const issue = {
          key: 'PROJ-1',
          fields: {
            summary: 'Test',
            status: { name: 'Open', statusCategory: { name: 'To Do' } },
            priority: { name: 'High' },
            issuetype: { name: 'Bug' }
          }
        };

        const result = jira.formatIssue(issue);

        expect(result).toEqual({
          key: 'PROJ-1',
          summary: 'Test',
          status: 'Open',
          statusCategory: 'To Do',
          priority: 'High',
          type: 'Bug'
        });
      });

      it('should include optional fields when present', () => {
        const issue = {
          key: 'PROJ-1',
          fields: {
            summary: 'Test',
            status: { name: 'Open', statusCategory: { name: 'To Do' } },
            priority: { name: 'High' },
            issuetype: { name: 'Bug' },
            assignee: { displayName: 'John' },
            labels: ['bug', 'critical'],
            components: [{ name: 'API' }],
            fixVersions: [{ name: 'v1.0' }]
          }
        };

        const result = jira.formatIssue(issue);

        expect(result.assignee).toBe('John');
        expect(result.labels).toEqual(['bug', 'critical']);
        expect(result.components).toEqual(['API']);
        expect(result.fixVersions).toEqual(['v1.0']);
      });
    });
  });
});
