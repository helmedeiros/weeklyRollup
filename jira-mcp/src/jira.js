const axios = require('axios');
const { getValidAccessToken, getCurrentUser } = require('./auth');
const fileStore = require('./file-store');

// Field sets - minimal by default to reduce payload
const FIELD_SETS = {
  minimal: ['key', 'summary', 'status', 'priority', 'issuetype'],
  standard: ['key', 'summary', 'status', 'priority', 'issuetype', 'assignee', 'reporter', 'created', 'updated'],
  extended: ['key', 'summary', 'status', 'priority', 'issuetype', 'assignee', 'reporter', 'created', 'updated', 'labels', 'components', 'fixVersions', 'duedate'],
  full: ['*all']
};

class JiraAPI {
  constructor() {
    this.initialized = false;
  }

  async init() {
    if (!this.initialized) {
      fileStore.init();
      this.initialized = true;
    }
    const token = await getValidAccessToken();
    return {
      baseUrl: `https://api.atlassian.com/ex/jira/${token.cloud_id}/rest/api/3`,
      accessToken: token.access_token
    };
  }

  async request(method, endpoint, data = null, params = null) {
    const makeRequest = async (forceRefresh = false) => {
      if (forceRefresh) {
        this.initialized = false;
      }

      const token = await getValidAccessToken(getCurrentUser(), { forceRefresh });
      const config = {
        method,
        url: `https://api.atlassian.com/ex/jira/${token.cloud_id}/rest/api/3${endpoint}`,
        headers: {
          Authorization: `Bearer ${token.access_token}`,
          'Content-Type': 'application/json'
        }
      };
      if (data) config.data = data;
      if (params) config.params = params;

      const response = await axios(config);
      return response.data;
    };

    try {
      return await makeRequest(false);
    } catch (error) {
      if (error.response?.status !== 401) throw error;
      return await makeRequest(true);
    }
  }

  getFields(fieldSet = 'minimal') {
    return FIELD_SETS[fieldSet] || FIELD_SETS.minimal;
  }

  // === Projects ===

  async listProjects(maxResults = 50) {
    const data = await this.request('GET', '/project', null, { maxResults });
    return data.map(p => ({
      key: p.key,
      name: p.name,
      projectTypeKey: p.projectTypeKey
    }));
  }

  async getProject(projectKeyOrId) {
    const data = await this.request('GET', `/project/${projectKeyOrId}`);
    return {
      key: data.key,
      name: data.name,
      description: data.description,
      lead: data.lead?.displayName,
      projectTypeKey: data.projectTypeKey,
      url: data.self
    };
  }

  async createProject(data) {
    const result = await this.request('POST', '/project', data);
    return {
      id: result.id,
      key: result.key,
      name: data.name,
      self: result.self
    };
  }

  async updateProject(projectKeyOrId, data) {
    const result = await this.request('PUT', `/project/${projectKeyOrId}`, data);
    return {
      key: result.key,
      name: result.name,
      description: result.description,
      lead: result.lead?.displayName,
      projectTypeKey: result.projectTypeKey
    };
  }

  async deleteProject(projectKeyOrId) {
    await this.request('DELETE', `/project/${projectKeyOrId}`);
    return { deleted: true, projectKeyOrId };
  }

  async getProjectStatuses(projectKeyOrId) {
    const data = await this.request('GET', `/project/${projectKeyOrId}/statuses`);
    return data.map(issueType => ({
      issueType: issueType.name,
      statuses: issueType.statuses?.map(s => ({
        id: s.id,
        name: s.name,
        statusCategory: s.statusCategory?.name
      })) || []
    }));
  }

  // === Fields ===

  async listFields() {
    const data = await this.request('GET', '/field');
    return data.map(f => ({
      id: f.id,
      name: f.name,
      custom: f.custom,
      schema: f.schema?.type,
      searchable: f.searchable
    }));
  }

  async createField(data) {
    const result = await this.request('POST', '/field', data);
    return {
      id: result.id,
      name: result.name,
      custom: result.custom,
      schema: result.schema?.type
    };
  }

  async updateField(fieldId, data) {
    await this.request('PUT', `/field/${fieldId}`, data);
    return { updated: true, fieldId, ...data };
  }

  async deleteField(fieldId) {
    await this.request('DELETE', `/field/${fieldId}`);
    return { deleted: true, fieldId };
  }

  async trashField(fieldId) {
    await this.request('POST', `/field/${fieldId}/trash`);
    return { trashed: true, fieldId };
  }

  async restoreField(fieldId) {
    await this.request('POST', `/field/${fieldId}/restore`);
    return { restored: true, fieldId };
  }

  async listTrashedFields() {
    const data = await this.request('GET', '/field/search', null, {
      type: ['custom'],
      state: ['TRASHED']
    });
    return {
      total: data.total,
      fields: (data.values || []).map(f => ({
        id: f.id,
        name: f.name,
        schema: f.schema?.type,
        trashedDate: f.lastUsed
      }))
    };
  }

  // === Statuses ===

  async listStatuses(options = {}) {
    const { projectId, searchString, maxResults = 50, startAt = 0 } = options;
    const params = { maxResults, startAt };
    if (projectId) params.projectId = projectId;
    if (searchString) params.searchString = searchString;

    const data = await this.request('GET', '/statuses/search', null, params);
    return {
      total: data.total,
      statuses: (data.values || []).map(s => ({
        id: s.id,
        name: s.name,
        statusCategory: s.statusCategory,
        scope: s.scope?.type,
        projectId: s.scope?.project?.id
      })),
      isLast: data.isLast
    };
  }

  async createStatuses(statuses) {
    const data = await this.request('POST', '/statuses', statuses);
    return (data || []).map(s => ({
      id: s.id,
      name: s.name,
      statusCategory: s.statusCategory
    }));
  }

  async updateStatuses(statuses) {
    await this.request('PUT', '/statuses', statuses);
    return { updated: true, count: statuses.length };
  }

  async deleteStatuses(ids) {
    const params = { id: ids.join(',') };
    await this.request('DELETE', '/statuses', null, params);
    return { deleted: true, ids };
  }

  // === Workflows ===

  async listWorkflows(options = {}) {
    const { workflowName, projectId, maxResults = 50, startAt = 0 } = options;
    const params = { maxResults, startAt };
    if (workflowName) params.workflowName = workflowName;
    if (projectId) params.projectId = projectId;

    const data = await this.request('GET', '/workflow/search', null, params);
    return {
      total: data.total,
      workflows: (data.values || []).map(w => ({
        id: w.id?.name,
        name: w.id?.name,
        description: w.description,
        created: w.created,
        updated: w.updated,
        statuses: w.statuses?.map(s => s.name) || [],
        isDefault: w.isDefault
      })),
      isLast: data.isLast
    };
  }

  async createWorkflows(data) {
    const result = await this.request('POST', '/workflows/create', data);
    return {
      workflows: (result.workflows || []).map(w => ({
        id: w.id,
        name: w.name
      })),
      statuses: (result.statuses || []).map(s => ({
        id: s.id,
        name: s.name
      }))
    };
  }

  async updateWorkflows(data) {
    const result = await this.request('POST', '/workflows/update', data);
    return {
      updated: true,
      workflows: (result.workflows || []).map(w => ({
        id: w.id,
        name: w.name
      })),
      statuses: (result.statuses || []).map(s => ({
        id: s.id,
        name: s.name
      }))
    };
  }

  async getWorkflowSchemes(projectId) {
    const params = { projectId };
    const data = await this.request('GET', '/workflowscheme/project', null, params);
    return {
      schemes: (data.values || []).map(s => ({
        id: s.id,
        name: s.name,
        description: s.description,
        defaultWorkflow: s.defaultWorkflow,
        issueTypeMappings: s.issueTypeMappings
      }))
    };
  }

  // === Issues ===

  async searchIssues(jql, options = {}) {
    const {
      maxResults = 20,
      nextPageToken = null,
      fieldSet = 'minimal'
    } = options;

    const body = {
      jql,
      maxResults,
      fields: this.getFields(fieldSet)
    };

    if (nextPageToken) {
      body.nextPageToken = nextPageToken;
    }

    const data = await this.request('POST', '/search/jql', body);

    return {
      total: data.issues?.length || 0,
      issues: data.issues.map(i => this.formatIssue(i)),
      nextPageToken: data.nextPageToken,
      isLast: !data.nextPageToken
    };
  }

  async getIssue(issueKeyOrId, fieldSet = 'standard') {
    const fields = this.getFields(fieldSet);
    const params = fields[0] === '*all' ? {} : { fields: fields.join(',') };
    const data = await this.request('GET', `/issue/${issueKeyOrId}`, null, params);
    return this.formatIssue(data, true);
  }

  async getIssueComments(issueKeyOrId, maxResults = 10) {
    const data = await this.request('GET', `/issue/${issueKeyOrId}/comment`, null, { maxResults });
    return {
      total: data.total,
      comments: data.comments.map(c => ({
        id: c.id,
        author: c.author?.displayName,
        body: this.extractTextFromAdf(c.body),
        created: c.created,
        updated: c.updated
      }))
    };
  }

  async addComment(issueKeyOrId, body) {
    const data = await this.request('POST', `/issue/${issueKeyOrId}/comment`, {
      body: {
        type: 'doc',
        version: 1,
        content: [
          {
            type: 'paragraph',
            content: [
              {
                type: 'text',
                text: body
              }
            ]
          }
        ]
      }
    });
    return {
      id: data.id,
      author: data.author?.displayName,
      body: this.extractTextFromAdf(data.body),
      created: data.created
    };
  }

  // === Formatting ===

  formatIssue(issue, includeDescription = false) {
    const f = issue.fields || {};
    const result = {
      key: issue.key,
      summary: f.summary,
      status: f.status?.name,
      statusCategory: f.status?.statusCategory?.name,
      priority: f.priority?.name,
      type: f.issuetype?.name
    };

    if (f.assignee) result.assignee = f.assignee.displayName;
    if (f.reporter) result.reporter = f.reporter.displayName;
    if (f.created) result.created = f.created;
    if (f.updated) result.updated = f.updated;
    if (f.labels?.length) result.labels = f.labels;
    if (f.components?.length) result.components = f.components.map(c => c.name);
    if (f.fixVersions?.length) result.fixVersions = f.fixVersions.map(v => v.name);
    if (f.duedate) result.dueDate = f.duedate;

    if (includeDescription && f.description) {
      result.description = this.extractTextFromAdf(f.description);
    }

    return result;
  }

  extractTextFromAdf(adf) {
    if (!adf) return '';
    if (typeof adf === 'string') return adf;

    const extract = (node) => {
      if (!node) return '';
      if (node.type === 'text') return node.text || '';
      if (node.content) return node.content.map(extract).join('');
      return '';
    };

    const text = extract(adf);
    return text.slice(0, 2000); // Limit description length
  }
}

module.exports = { JiraAPI, FIELD_SETS };
