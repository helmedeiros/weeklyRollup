/**
 * File-Based Token Store
 * Encrypted JSON file storage for users, tokens, and config
 * Replaces PostgreSQL with simpler local file storage
 */

const fs = require('fs');
const path = require('path');
const { encrypt, decrypt } = require('./crypto');

const DATA_DIR = path.join(__dirname, '..', '.data');
const STORE_PATH = path.join(DATA_DIR, 'store.enc');

/**
 * Initialize the file store
 * Creates .data directory and empty store if needed
 */
function init() {
  // Create .data directory if it doesn't exist
  if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
    console.error('Created .data directory');
  }

  // Create empty store if it doesn't exist
  if (!fs.existsSync(STORE_PATH)) {
    const emptyStore = {
      users: {},
      tokens: {},
      config: {}
    };
    save(emptyStore);
    console.error('Created empty encrypted store');
  }

  console.error('File store initialized');
}

/**
 * Load and decrypt the store from disk
 */
function load() {
  if (!fs.existsSync(STORE_PATH)) {
    return { users: {}, tokens: {}, config: {} };
  }

  const encrypted = fs.readFileSync(STORE_PATH, 'utf8');
  const decrypted = decrypt(encrypted);
  return JSON.parse(decrypted);
}

/**
 * Encrypt and save the store to disk (atomic write)
 */
function save(data) {
  const json = JSON.stringify(data, null, 2);
  const encrypted = encrypt(json);

  // Atomic write: temp file -> rename
  const tempPath = `${STORE_PATH}.tmp`;
  fs.writeFileSync(tempPath, encrypted, 'utf8');
  fs.renameSync(tempPath, STORE_PATH);
}

// ============= User Management =============

/**
 * Get user by email
 */
function getUserByEmail(email) {
  const store = load();
  const user = store.users[email];
  if (!user) return null;

  return {
    email,
    name: user.name,
    enabled: user.enabled,
    created_at: user.created_at,
    updated_at: user.updated_at
  };
}

/**
 * Create or update user
 */
function saveUser(userData) {
  const store = load();
  const now = new Date().toISOString();

  const existing = store.users[userData.email];
  store.users[userData.email] = {
    name: userData.name || userData.email.split('@')[0],
    enabled: userData.enabled ?? existing?.enabled ?? true,
    created_at: existing?.created_at || now,
    updated_at: now
  };

  save(store);
  console.error(`User saved: ${userData.email}`);

  return {
    email: userData.email,
    ...store.users[userData.email]
  };
}

/**
 * List all users
 */
function listUsers() {
  const store = load();

  return Object.entries(store.users).map(([email, user]) => {
    const tokens = store.tokens[email];
    return {
      email,
      name: user.name,
      enabled: user.enabled,
      created_at: user.created_at,
      updated_at: user.updated_at,
      site_name: tokens?.site_name || null,
      cloud_id: tokens?.cloud_id || null
    };
  }).sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
}

/**
 * Enable/disable user
 */
function setUserEnabled(email, enabled) {
  const store = load();

  if (!store.users[email]) {
    throw new Error(`User ${email} not found`);
  }

  store.users[email].enabled = enabled;
  store.users[email].updated_at = new Date().toISOString();
  save(store);

  console.error(`User ${email} ${enabled ? 'enabled' : 'disabled'}`);
}

// ============= Jira OAuth Tokens =============

/**
 * Get Jira OAuth tokens for user
 */
function getJiraTokens(email) {
  const store = load();
  const tokens = store.tokens[email];

  if (!tokens) return null;

  return {
    access_token: tokens.access_token,
    refresh_token: tokens.refresh_token,
    expires_at: tokens.expires_at,
    scope: tokens.scope,
    cloud_id: tokens.cloud_id,
    site_url: tokens.site_url,
    site_name: tokens.site_name
  };
}

/**
 * Save Jira OAuth tokens for user
 */
function saveJiraTokens(email, tokenData) {
  const store = load();

  store.tokens[email] = {
    access_token: tokenData.access_token,
    refresh_token: tokenData.refresh_token,
    expires_at: tokenData.expires_at,
    scope: tokenData.scope,
    cloud_id: tokenData.cloud_id,
    site_url: tokenData.site_url,
    site_name: tokenData.site_name
  };

  save(store);
  console.error(`Jira tokens saved for ${email}`);
}

/**
 * Update Jira tokens after refresh
 */
function updateJiraTokens(email, accessToken, refreshToken, expiresAt) {
  const store = load();

  if (!store.tokens[email]) {
    throw new Error(`No existing tokens for ${email}`);
  }

  store.tokens[email].access_token = accessToken;
  store.tokens[email].refresh_token = refreshToken;
  store.tokens[email].expires_at = expiresAt;

  save(store);
  console.error(`Jira tokens refreshed for ${email}`);
}

/**
 * Delete Jira OAuth tokens for user
 */
function deleteJiraTokens(email) {
  const store = load();

  if (store.tokens[email]) {
    delete store.tokens[email];
    save(store);
    console.error(`Jira tokens deleted for ${email}`);
  }
}

// ============= User Config =============

/**
 * Get user config value
 */
function getConfig(email, key) {
  const store = load();
  const userConfig = store.config[email];
  return userConfig?.[key] || null;
}

/**
 * Set user config value
 */
function setConfig(email, key, value) {
  const store = load();

  if (!store.config[email]) {
    store.config[email] = {};
  }

  store.config[email][key] = value;
  save(store);

  return { email, key, value };
}

/**
 * Get all config for user
 */
function getUserConfig(email) {
  const store = load();
  const userConfig = store.config[email] || {};

  return Object.entries(userConfig).map(([key, value]) => ({
    key,
    value
  }));
}

/**
 * Set default config for new user
 */
function setDefaultConfig(email) {
  const store = load();

  if (!store.config[email]) {
    store.config[email] = {};
  }

  if (!store.config[email].default_field_set) {
    store.config[email].default_field_set = 'minimal';
  }

  save(store);
}

module.exports = {
  // Core
  init,
  load,
  save,
  // Users
  getUserByEmail,
  saveUser,
  listUsers,
  setUserEnabled,
  // Tokens
  getJiraTokens,
  saveJiraTokens,
  updateJiraTokens,
  deleteJiraTokens,
  // Config
  getConfig,
  setConfig,
  getUserConfig,
  setDefaultConfig
};
