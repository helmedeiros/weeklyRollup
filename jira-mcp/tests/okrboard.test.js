/**
 * Unit tests for okrboard.js
 */

jest.mock('axios');
jest.mock('../src/file-store', () => ({
  init: jest.fn(),
  getConfig: jest.fn()
}));
jest.mock('../src/auth', () => ({
  getCurrentUser: jest.fn()
}));

const axios = require('axios');
const fileStore = require('../src/file-store');
const auth = require('../src/auth');
const { OkrBoardAPI, DEFAULT_BASE_URL } = require('../src/okrboard');

describe('OkrBoardAPI', () => {
  let api;

  beforeEach(() => {
    jest.clearAllMocks();
    delete process.env.OKRBOARD_API_TOKEN;
    delete process.env.OKRBOARD_BASE_URL;
    api = new OkrBoardAPI();
    auth.getCurrentUser.mockReturnValue('test@example.com');
  });

  describe('DEFAULT_BASE_URL', () => {
    it('should export the default base URL', () => {
      expect(DEFAULT_BASE_URL).toBe('https://backend.okr-api.com/api/v1');
    });
  });

  describe('init()', () => {
    it('should initialize file store on first call', () => {
      api.init();
      expect(fileStore.init).toHaveBeenCalledTimes(1);
    });

    it('should only initialize once', () => {
      api.init();
      api.init();
      expect(fileStore.init).toHaveBeenCalledTimes(1);
    });
  });

  describe('getConnection()', () => {
    it('should throw if no user is set', () => {
      auth.getCurrentUser.mockReturnValue(null);

      expect(() => api.getConnection())
        .toThrow('No user set. Configure JIRA_USER_EMAIL or run authentication first.');
    });

    it('should throw if no token is configured', () => {
      fileStore.getConfig.mockReturnValue(null);

      expect(() => api.getConnection())
        .toThrow('OKR Board token is not configured. Use set_okrboard_token first or set OKRBOARD_API_TOKEN in .env.');
    });

    it('should return connection with default base URL', () => {
      fileStore.getConfig
        .mockReturnValueOnce('my-api-token')
        .mockReturnValueOnce(null);

      const conn = api.getConnection();

      expect(conn.email).toBe('test@example.com');
      expect(conn.token).toBe('my-api-token');
      expect(conn.baseUrl).toBe(DEFAULT_BASE_URL);
    });

    it('should fall back to env token and base URL', () => {
      process.env.OKRBOARD_API_TOKEN = 'env-token';
      process.env.OKRBOARD_BASE_URL = 'https://env.okr.example/api/v1/';
      fileStore.getConfig.mockReturnValue(null);

      const conn = api.getConnection();

      expect(conn.token).toBe('env-token');
      expect(conn.baseUrl).toBe('https://env.okr.example/api/v1');
    });

    it('should return connection with configured base URL', () => {
      fileStore.getConfig
        .mockReturnValueOnce('my-api-token')
        .mockReturnValueOnce('https://custom.okr.com/api/v1/');

      const conn = api.getConnection();

      expect(conn.baseUrl).toBe('https://custom.okr.com/api/v1');
    });
  });

  describe('request()', () => {
    beforeEach(() => {
      fileStore.getConfig
        .mockReturnValueOnce('my-token')
        .mockReturnValueOnce(null);
    });

    it('should make request with correct headers and URL', async () => {
      axios.mockResolvedValue({ data: { result: 'ok' } });

      const result = await api.request('GET', '/workspaces');

      expect(axios).toHaveBeenCalledWith({
        method: 'GET',
        url: `${DEFAULT_BASE_URL}/workspaces`,
        headers: {
          'API-Token': 'my-token',
          'Content-Type': 'application/json'
        },
        data: null,
        params: null
      });
      expect(result).toEqual({ result: 'ok' });
    });
  });

  describe('API methods', () => {
    beforeEach(() => {
      fileStore.getConfig.mockReturnValue('my-token');
      axios.mockResolvedValue({ data: [] });
    });

    it('should call GET /workspaces', async () => {
      await api.listWorkspaces();

      expect(axios).toHaveBeenCalledWith(
        expect.objectContaining({
          method: 'GET',
          url: expect.stringContaining('/workspaces')
        })
      );
    });

    it('should call GET /intervals with workspaceId param', async () => {
      await api.listIntervals('ws1');

      expect(axios).toHaveBeenCalledWith(
        expect.objectContaining({
          method: 'GET',
          url: expect.stringContaining('/intervals'),
          params: { workspaceId: 'ws1' }
        })
      );
    });

    it('should call GET /elements with default pagination', async () => {
      await api.listObjectives('ws1');

      expect(axios).toHaveBeenCalledWith(
        expect.objectContaining({
          method: 'GET',
          url: expect.stringContaining('/elements'),
          params: {
            workspaceIds: 'ws1',
            startAt: 0,
            maxResults: 200
          }
        })
      );
    });

    it('should call POST /objectives with payload', async () => {
      const payload = { workspaceId: 'ws1', name: 'New OKR' };
      await api.createObjective(payload);

      expect(axios).toHaveBeenCalledWith(
        expect.objectContaining({
          method: 'POST',
          url: expect.stringContaining('/objectives'),
          data: payload
        })
      );
    });
  });
});
