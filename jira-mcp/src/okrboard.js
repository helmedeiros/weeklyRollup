const axios = require('axios');
const fileStore = require('./file-store');
const { getCurrentUser } = require('./auth');

const DEFAULT_BASE_URL = 'https://backend.okr-api.com/api/v1';

class OkrBoardAPI {
  constructor() {
    this.initialized = false;
  }

  init() {
    if (!this.initialized) {
      fileStore.init();
      this.initialized = true;
    }
  }

  getConnection() {
    this.init();

    const email = getCurrentUser();
    if (!email) {
      throw new Error('No user set. Configure JIRA_USER_EMAIL or run authentication first.');
    }

    const configuredToken = fileStore.getConfig(email, 'okrboard_api_token');
    const token = configuredToken || process.env.OKRBOARD_API_TOKEN;
    if (!token) {
      throw new Error('OKR Board token is not configured. Use set_okrboard_token first or set OKRBOARD_API_TOKEN in .env.');
    }

    const configuredBaseUrl = fileStore.getConfig(email, 'okrboard_base_url');
    const baseUrl = (configuredBaseUrl || process.env.OKRBOARD_BASE_URL || DEFAULT_BASE_URL).replace(/\/+$/, '');

    return { email, token, baseUrl };
  }

  async request(method, endpoint, options = {}) {
    const { token, baseUrl } = this.getConnection();
    const { data = null, params = null } = options;

    const response = await axios({
      method,
      url: `${baseUrl}${endpoint}`,
      headers: {
        'API-Token': token,
        'Content-Type': 'application/json'
      },
      data,
      params
    });

    return response.data;
  }

  async listWorkspaces() {
    return await this.request('GET', '/workspaces');
  }

  async listIntervals(workspaceId) {
    return await this.request('GET', '/intervals', { params: { workspaceId } });
  }

  async listGroups(workspaceId) {
    return await this.request('GET', '/groups', { params: { workspaceId } });
  }

  async listUsers(workspaceId) {
    return await this.request('GET', '/users', { params: { workspaceId } });
  }

  async listObjectives(workspaceId, options = {}) {
    const {
      intervalId = null,
      startAt = 0,
      maxResults = 200
    } = options;

    const params = {
      workspaceIds: String(workspaceId),
      startAt: Math.max(0, startAt),
      maxResults: Math.min(Math.max(1, maxResults), 500)
    };
    if (intervalId) params.intervalId = String(intervalId);

    return await this.request('GET', '/elements', { params });
  }

  async createObjective(payload) {
    return await this.request('POST', '/objectives', { data: payload });
  }

  async updateObjective(payload) {
    return await this.request('PUT', '/objectives', { data: payload });
  }

  async updateKeyResult(payload) {
    return await this.request('PUT', '/key-results', { data: payload });
  }

  async deleteKeyResult(payload) {
    return await this.request('DELETE', '/key-results', { data: payload });
  }
}

module.exports = {
  OkrBoardAPI,
  DEFAULT_BASE_URL
};
