/**
 * Unit tests for auth.js
 */

// Setup mocks before requiring modules
const mockAxiosPost = jest.fn();
const mockAxiosGet = jest.fn();

jest.mock('axios', () => ({
  post: mockAxiosPost,
  get: mockAxiosGet
}));

const mockFileStore = {
  init: jest.fn(),
  getUserByEmail: jest.fn(),
  getJiraTokens: jest.fn(),
  updateJiraTokens: jest.fn(),
  deleteJiraTokens: jest.fn(),
  saveUser: jest.fn(),
  saveJiraTokens: jest.fn(),
  setDefaultConfig: jest.fn()
};

jest.mock('../src/file-store', () => mockFileStore);

describe('auth module', () => {
  let auth;

  beforeEach(() => {
    // Set up environment variables before requiring auth module
    process.env.ATLASSIAN_CLIENT_ID = 'test-client-id';
    process.env.ATLASSIAN_CLIENT_SECRET = 'test-client-secret';
    process.env.ATLASSIAN_REDIRECT_URI = 'http://localhost:3002/callback';
    process.env.ATLASSIAN_AUTH_URL = 'https://auth.atlassian.com/authorize';
    process.env.ATLASSIAN_TOKEN_URL = 'https://auth.atlassian.com/oauth/token';
    process.env.ATLASSIAN_RESOURCES_URL = 'https://api.atlassian.com/oauth/token/accessible-resources';
    process.env.ATLASSIAN_SCOPES = 'read:jira-work read:me offline_access';
    process.env.AUTH_PORT = '3002';
    process.env.JIRA_USER_EMAIL = 'default@example.com';

    // Reset modules to get fresh auth module with new env vars
    jest.resetModules();

    // Re-setup mocks after resetModules
    jest.doMock('axios', () => ({
      post: mockAxiosPost,
      get: mockAxiosGet
    }));
    jest.doMock('../src/file-store', () => mockFileStore);

    auth = require('../src/auth');

    // Clear all mock calls
    jest.clearAllMocks();
  });

  afterEach(() => {
    delete process.env.ATLASSIAN_CLIENT_ID;
    delete process.env.ATLASSIAN_CLIENT_SECRET;
    delete process.env.ATLASSIAN_REDIRECT_URI;
    delete process.env.ATLASSIAN_AUTH_URL;
    delete process.env.ATLASSIAN_TOKEN_URL;
    delete process.env.ATLASSIAN_RESOURCES_URL;
    delete process.env.ATLASSIAN_SCOPES;
    delete process.env.AUTH_PORT;
    delete process.env.JIRA_USER_EMAIL;
  });

  describe('setCurrentUser and getCurrentUser', () => {
    it('should set and get current user', () => {
      auth.setCurrentUser('test@example.com');
      expect(auth.getCurrentUser()).toBe('test@example.com');
    });

    it('should return default user from env if not set', () => {
      expect(auth.getCurrentUser()).toBe('default@example.com');
    });
  });

  describe('isTokenExpired', () => {
    it('should return true for null token', () => {
      expect(auth.isTokenExpired(null)).toBe(true);
    });

    it('should return true for token without expires_at', () => {
      expect(auth.isTokenExpired({})).toBe(true);
    });

    it('should return true for expired token', () => {
      const token = { expires_at: Date.now() - 1000 };
      expect(auth.isTokenExpired(token)).toBe(true);
    });

    it('should return true for token expiring within 1 minute', () => {
      const token = { expires_at: Date.now() + 30000 }; // 30 seconds
      expect(auth.isTokenExpired(token)).toBe(true);
    });

    it('should return false for valid token', () => {
      const token = { expires_at: Date.now() + 3600000 }; // 1 hour
      expect(auth.isTokenExpired(token)).toBe(false);
    });
  });

  describe('refreshAccessToken', () => {
    it('should call token endpoint with refresh token', async () => {
      mockAxiosPost.mockResolvedValueOnce({
        data: {
          access_token: 'new-access-token',
          refresh_token: 'new-refresh-token',
          expires_in: 3600
        }
      });

      const result = await auth.refreshAccessToken('old-refresh-token');

      expect(mockAxiosPost).toHaveBeenCalledWith(
        'https://auth.atlassian.com/oauth/token',
        {
          grant_type: 'refresh_token',
          client_id: 'test-client-id',
          client_secret: 'test-client-secret',
          refresh_token: 'old-refresh-token'
        }
      );
      expect(result.access_token).toBe('new-access-token');
    });
  });

  describe('getValidAccessToken', () => {
    it('should throw error if no user email set', async () => {
      auth.setCurrentUser(null);
      delete process.env.JIRA_USER_EMAIL;

      // Need to re-require to pick up deleted env var
      jest.resetModules();
      jest.doMock('axios', () => ({ post: mockAxiosPost, get: mockAxiosGet }));
      jest.doMock('../src/file-store', () => mockFileStore);
      const freshAuth = require('../src/auth');
      freshAuth.setCurrentUser(null);

      await expect(freshAuth.getValidAccessToken()).rejects.toThrow(
        'No user email set'
      );
    });

    it('should throw error if user not found', async () => {
      auth.setCurrentUser('notfound@example.com');
      mockFileStore.getUserByEmail.mockReturnValue(null);

      await expect(auth.getValidAccessToken()).rejects.toThrow(
        'User notfound@example.com not found'
      );
    });

    it('should throw error if user is disabled', async () => {
      auth.setCurrentUser('disabled@example.com');
      mockFileStore.getUserByEmail.mockReturnValue({ enabled: false });

      await expect(auth.getValidAccessToken()).rejects.toThrow(
        'User disabled@example.com is disabled'
      );
    });

    it('should throw error if no token found', async () => {
      auth.setCurrentUser('test@example.com');
      mockFileStore.getUserByEmail.mockReturnValue({ enabled: true });
      mockFileStore.getJiraTokens.mockReturnValue(null);

      await expect(auth.getValidAccessToken()).rejects.toThrow(
        'No token found for test@example.com'
      );
    });

    it('should return valid token without refresh if not expired', async () => {
      auth.setCurrentUser('test@example.com');
      const validToken = {
        access_token: 'valid-token',
        refresh_token: 'refresh-token',
        expires_at: Date.now() + 3600000
      };

      mockFileStore.getUserByEmail.mockReturnValue({ enabled: true });
      mockFileStore.getJiraTokens.mockReturnValue(validToken);

      const result = await auth.getValidAccessToken();

      expect(result.access_token).toBe('valid-token');
      expect(mockAxiosPost).not.toHaveBeenCalled();
    });

    it('should refresh expired token', async () => {
      auth.setCurrentUser('test@example.com');
      const expiredToken = {
        access_token: 'old-token',
        refresh_token: 'refresh-token',
        expires_at: Date.now() - 1000 // expired
      };

      mockFileStore.getUserByEmail.mockReturnValue({ enabled: true });
      mockFileStore.getJiraTokens.mockReturnValue(expiredToken);

      mockAxiosPost.mockResolvedValueOnce({
        data: {
          access_token: 'new-access-token',
          refresh_token: 'new-refresh-token',
          expires_in: 3600
        }
      });

      const result = await auth.getValidAccessToken();

      expect(result.access_token).toBe('new-access-token');
      expect(mockFileStore.updateJiraTokens).toHaveBeenCalledWith(
        'test@example.com',
        'new-access-token',
        'new-refresh-token',
        expect.any(Number)
      );
    });

    it('should force refresh a token even if it is not expired', async () => {
      auth.setCurrentUser('test@example.com');
      const validToken = {
        access_token: 'old-access-token',
        refresh_token: 'refresh-token',
        expires_at: Date.now() + 3600000
      };

      mockFileStore.getUserByEmail.mockReturnValue({ enabled: true });
      mockFileStore.getJiraTokens.mockReturnValue(validToken);
      mockAxiosPost.mockResolvedValueOnce({
        data: {
          access_token: 'forced-access-token',
          refresh_token: 'forced-refresh-token',
          expires_in: 3600
        }
      });

      const result = await auth.getValidAccessToken(null, { forceRefresh: true });

      expect(result.access_token).toBe('forced-access-token');
      expect(mockFileStore.updateJiraTokens).toHaveBeenCalledWith(
        'test@example.com',
        'forced-access-token',
        'forced-refresh-token',
        expect.any(Number)
      );
    });

    it('should delete stored tokens and throw re-link message when refresh token is invalid', async () => {
      auth.setCurrentUser('test@example.com');
      const expiredToken = {
        access_token: 'old-token',
        refresh_token: 'stale-refresh-token',
        expires_at: Date.now() - 1000
      };

      mockFileStore.getUserByEmail.mockReturnValue({ enabled: true });
      mockFileStore.getJiraTokens.mockReturnValue(expiredToken);
      mockAxiosPost.mockRejectedValueOnce({
        response: { status: 400 },
        message: 'invalid_grant'
      });

      await expect(auth.getValidAccessToken()).rejects.toThrow(
        'Atlassian authentication expired. Run `npm run auth` to re-link your Atlassian account.'
      );

      expect(mockFileStore.deleteJiraTokens).toHaveBeenCalledWith('test@example.com');
    });

    it('should use email parameter over current user', async () => {
      auth.setCurrentUser('default@example.com');

      mockFileStore.getUserByEmail.mockReturnValue({ enabled: true });
      mockFileStore.getJiraTokens.mockReturnValue({
        access_token: 'token',
        expires_at: Date.now() + 3600000
      });

      await auth.getValidAccessToken('specific@example.com');

      expect(mockFileStore.getUserByEmail).toHaveBeenCalledWith('specific@example.com');
    });
  });
});
