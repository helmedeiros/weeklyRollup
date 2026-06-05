/**
 * Unit tests for file-store.js
 */

const fs = require('fs');
const path = require('path');

// Mock crypto module before requiring file-store
jest.mock('../src/crypto', () => ({
  encrypt: jest.fn(data => `encrypted:${data}`),
  decrypt: jest.fn(data => data.replace('encrypted:', ''))
}));

describe('file-store module', () => {
  let fileStore;
  const DATA_DIR = path.join(__dirname, '..', '.data');
  const STORE_PATH = path.join(DATA_DIR, 'store.enc');
  let originalStoreContent = null;

  beforeAll(() => {
    // Backup existing store if present
    if (fs.existsSync(STORE_PATH)) {
      originalStoreContent = fs.readFileSync(STORE_PATH, 'utf8');
    }
  });

  afterAll(() => {
    // Restore original store if it existed
    if (originalStoreContent !== null) {
      fs.writeFileSync(STORE_PATH, originalStoreContent, 'utf8');
    }
  });

  beforeEach(() => {
    jest.resetModules();
    jest.clearAllMocks();

    // Suppress console output
    jest.spyOn(console, 'error').mockImplementation();

    // Remove store file for clean state
    if (fs.existsSync(STORE_PATH)) {
      fs.unlinkSync(STORE_PATH);
    }

    fileStore = require('../src/file-store');
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe('init', () => {
    it('should create .data directory if not exists', () => {
      // Remove the directory to test creation
      if (fs.existsSync(DATA_DIR)) {
        // Only remove if empty or only contains store.enc
        const files = fs.readdirSync(DATA_DIR);
        if (files.length === 0 || (files.length === 1 && files[0] === 'store.enc')) {
          if (fs.existsSync(STORE_PATH)) fs.unlinkSync(STORE_PATH);
          fs.rmdirSync(DATA_DIR);
        }
      }

      fileStore.init();

      expect(fs.existsSync(DATA_DIR)).toBe(true);
    });

    it('should create empty store if not exists', () => {
      if (fs.existsSync(STORE_PATH)) {
        fs.unlinkSync(STORE_PATH);
      }

      fileStore.init();

      expect(fs.existsSync(STORE_PATH)).toBe(true);
    });
  });

  describe('load and save', () => {
    it('should return empty store if file does not exist', () => {
      if (fs.existsSync(STORE_PATH)) {
        fs.unlinkSync(STORE_PATH);
      }

      const store = fileStore.load();

      expect(store).toEqual({ users: {}, tokens: {}, config: {} });
    });

    it('should save and load data correctly', () => {
      fileStore.init();

      const testData = {
        users: { 'test@example.com': { name: 'Test', enabled: true } },
        tokens: {},
        config: {}
      };

      fileStore.save(testData);
      const loaded = fileStore.load();

      expect(loaded).toEqual(testData);
    });
  });

  describe('User Management', () => {
    beforeEach(() => {
      fileStore.init();
    });

    describe('saveUser', () => {
      it('should save a new user', () => {
        const user = fileStore.saveUser({
          email: 'test@example.com',
          name: 'Test User',
          enabled: true
        });

        expect(user.email).toBe('test@example.com');
        expect(user.name).toBe('Test User');
        expect(user.enabled).toBe(true);
        expect(user.created_at).toBeDefined();
        expect(user.updated_at).toBeDefined();
      });

      it('should update existing user', () => {
        fileStore.saveUser({
          email: 'test@example.com',
          name: 'Test User',
          enabled: true
        });

        const updated = fileStore.saveUser({
          email: 'test@example.com',
          name: 'Updated User',
          enabled: false
        });

        expect(updated.name).toBe('Updated User');
        expect(updated.enabled).toBe(false);
      });

      it('should use email prefix as name if not provided', () => {
        const user = fileStore.saveUser({
          email: 'john.doe@example.com'
        });

        expect(user.name).toBe('john.doe');
      });
    });

    describe('getUserByEmail', () => {
      it('should return null for non-existent user', () => {
        const user = fileStore.getUserByEmail('nonexistent@example.com');

        expect(user).toBeNull();
      });

      it('should return user data for existing user', () => {
        fileStore.saveUser({
          email: 'test@example.com',
          name: 'Test User'
        });

        const user = fileStore.getUserByEmail('test@example.com');

        expect(user).not.toBeNull();
        expect(user.email).toBe('test@example.com');
        expect(user.name).toBe('Test User');
      });
    });

    describe('listUsers', () => {
      it('should return empty array when no users', () => {
        const users = fileStore.listUsers();

        expect(users).toEqual([]);
      });

      it('should return all users sorted by updated_at desc', () => {
        fileStore.saveUser({ email: 'user1@example.com', name: 'User 1' });
        fileStore.saveUser({ email: 'user2@example.com', name: 'User 2' });

        const users = fileStore.listUsers();

        expect(users).toHaveLength(2);
        // Both users should be present
        const emails = users.map(u => u.email);
        expect(emails).toContain('user1@example.com');
        expect(emails).toContain('user2@example.com');
        // Users should be sorted by updated_at (most recent first)
        // Since they're created almost instantly, just verify the sort is consistent
        const timestamps = users.map(u => new Date(u.updated_at).getTime());
        expect(timestamps[0]).toBeGreaterThanOrEqual(timestamps[1]);
      });
    });

    describe('setUserEnabled', () => {
      it('should enable/disable user', () => {
        fileStore.saveUser({ email: 'test@example.com', enabled: true });

        fileStore.setUserEnabled('test@example.com', false);
        let user = fileStore.getUserByEmail('test@example.com');
        expect(user.enabled).toBe(false);

        fileStore.setUserEnabled('test@example.com', true);
        user = fileStore.getUserByEmail('test@example.com');
        expect(user.enabled).toBe(true);
      });

      it('should throw error for non-existent user', () => {
        expect(() => fileStore.setUserEnabled('nonexistent@example.com', true))
          .toThrow('User nonexistent@example.com not found');
      });
    });
  });

  describe('Token Management', () => {
    beforeEach(() => {
      fileStore.init();
    });

    const mockTokenData = {
      access_token: 'access123',
      refresh_token: 'refresh456',
      expires_at: Date.now() + 3600000,
      scope: 'read:jira-work',
      cloud_id: 'cloud123',
      site_url: 'https://test.atlassian.net',
      site_name: 'Test Site'
    };

    describe('saveJiraTokens', () => {
      it('should save tokens for user', () => {
        fileStore.saveJiraTokens('test@example.com', mockTokenData);

        const tokens = fileStore.getJiraTokens('test@example.com');
        expect(tokens.access_token).toBe('access123');
        expect(tokens.refresh_token).toBe('refresh456');
        expect(tokens.cloud_id).toBe('cloud123');
      });
    });

    describe('getJiraTokens', () => {
      it('should return null for non-existent user', () => {
        const tokens = fileStore.getJiraTokens('nonexistent@example.com');

        expect(tokens).toBeNull();
      });

      it('should return tokens for existing user', () => {
        fileStore.saveJiraTokens('test@example.com', mockTokenData);

        const tokens = fileStore.getJiraTokens('test@example.com');

        expect(tokens).toMatchObject({
          access_token: 'access123',
          refresh_token: 'refresh456',
          cloud_id: 'cloud123',
          site_url: 'https://test.atlassian.net',
          site_name: 'Test Site'
        });
      });
    });

    describe('updateJiraTokens', () => {
      it('should update tokens after refresh', () => {
        fileStore.saveJiraTokens('test@example.com', mockTokenData);

        const newExpiry = Date.now() + 7200000;
        fileStore.updateJiraTokens('test@example.com', 'newAccess', 'newRefresh', newExpiry);

        const tokens = fileStore.getJiraTokens('test@example.com');
        expect(tokens.access_token).toBe('newAccess');
        expect(tokens.refresh_token).toBe('newRefresh');
        expect(tokens.expires_at).toBe(newExpiry);
      });

      it('should throw error for non-existent user tokens', () => {
        expect(() => fileStore.updateJiraTokens('nonexistent@example.com', 'a', 'b', 123))
          .toThrow('No existing tokens for nonexistent@example.com');
      });
    });

    describe('deleteJiraTokens', () => {
      it('should delete tokens for user', () => {
        fileStore.saveJiraTokens('test@example.com', mockTokenData);
        expect(fileStore.getJiraTokens('test@example.com')).not.toBeNull();

        fileStore.deleteJiraTokens('test@example.com');
        expect(fileStore.getJiraTokens('test@example.com')).toBeNull();
      });

      it('should not throw for non-existent user', () => {
        expect(() => fileStore.deleteJiraTokens('nonexistent@example.com')).not.toThrow();
      });
    });
  });

  describe('Config Management', () => {
    beforeEach(() => {
      fileStore.init();
    });

    describe('setConfig and getConfig', () => {
      it('should set and get config value', () => {
        fileStore.setConfig('test@example.com', 'default_field_set', 'standard');

        const value = fileStore.getConfig('test@example.com', 'default_field_set');
        expect(value).toBe('standard');
      });

      it('should return null for non-existent config', () => {
        const value = fileStore.getConfig('test@example.com', 'nonexistent');

        expect(value).toBeNull();
      });

      it('should overwrite existing config value', () => {
        fileStore.setConfig('test@example.com', 'key', 'value1');
        fileStore.setConfig('test@example.com', 'key', 'value2');

        const value = fileStore.getConfig('test@example.com', 'key');
        expect(value).toBe('value2');
      });
    });

    describe('getUserConfig', () => {
      it('should return empty array for user with no config', () => {
        const config = fileStore.getUserConfig('test@example.com');

        expect(config).toEqual([]);
      });

      it('should return all config for user', () => {
        fileStore.setConfig('test@example.com', 'key1', 'value1');
        fileStore.setConfig('test@example.com', 'key2', 'value2');

        const config = fileStore.getUserConfig('test@example.com');

        expect(config).toHaveLength(2);
        expect(config).toContainEqual({ key: 'key1', value: 'value1' });
        expect(config).toContainEqual({ key: 'key2', value: 'value2' });
      });
    });

    describe('setDefaultConfig', () => {
      it('should set default field set to minimal', () => {
        fileStore.setDefaultConfig('test@example.com');

        const value = fileStore.getConfig('test@example.com', 'default_field_set');
        expect(value).toBe('minimal');
      });

      it('should not overwrite existing default_field_set', () => {
        fileStore.setConfig('test@example.com', 'default_field_set', 'full');
        fileStore.setDefaultConfig('test@example.com');

        const value = fileStore.getConfig('test@example.com', 'default_field_set');
        expect(value).toBe('full');
      });
    });
  });
});
