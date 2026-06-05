/**
 * Authentication Module
 * OAuth 2.0 (3LO) with SSO support for Atlassian/Jira
 */

const express = require('express');
const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '..', '.env') });

const fileStore = require('./file-store');
const {
  RELINK_MESSAGE,
  getAuthorizationUrl,
  exchangeCodeForTokens,
  getAccessibleResources,
  getUserInfo,
  refreshAccessToken,
  isAuthError
} = require('./atlassian-auth');

const config = {
  clientId: process.env.ATLASSIAN_CLIENT_ID,
  clientSecret: process.env.ATLASSIAN_CLIENT_SECRET,
  redirectUri: process.env.ATLASSIAN_REDIRECT_URI,
  port: parseInt(process.env.AUTH_PORT) || 3002
};

// Current user email (set after auth or from env)
let currentUserEmail = process.env.JIRA_USER_EMAIL || null;

function setCurrentUser(email) {
  currentUserEmail = email;
}

function getCurrentUser() {
  return currentUserEmail;
}

function isTokenExpired(token) {
  if (!token || !token.expires_at) return true;
  return Date.now() >= token.expires_at - 60000; // 1 min buffer
}

async function refreshStoredAccessToken(userEmail, token) {
  try {
    const newTokenData = await refreshAccessToken(token.refresh_token);
    const expiresAt = Date.now() + (newTokenData.expires_in * 1000);

    fileStore.updateJiraTokens(
      userEmail,
      newTokenData.access_token,
      newTokenData.refresh_token || token.refresh_token,
      expiresAt
    );

    return {
      ...token,
      access_token: newTokenData.access_token,
      refresh_token: newTokenData.refresh_token || token.refresh_token,
      expires_at: expiresAt,
      scope: newTokenData.scope || token.scope
    };
  } catch (error) {
    if (isAuthError(error)) {
      fileStore.deleteJiraTokens(userEmail);
      throw new Error(RELINK_MESSAGE);
    }
    throw error;
  }
}

/**
 * Get valid access token for user (auto-refresh if expired)
 */
async function getValidAccessToken(email = null, options = {}) {
  const userEmail = email || currentUserEmail;
  const { forceRefresh = false } = options;

  if (!userEmail) {
    throw new Error('No user email set. Run authentication first or set JIRA_USER_EMAIL.');
  }

  // Check if user is enabled
  const user = fileStore.getUserByEmail(userEmail);
  if (!user) {
    throw new Error(`User ${userEmail} not found. Run authentication first.`);
  }
  if (!user.enabled) {
    throw new Error(`User ${userEmail} is disabled.`);
  }

  let token = fileStore.getJiraTokens(userEmail);
  if (!token) {
    throw new Error(`No token found for ${userEmail}. Run authentication first.`);
  }

  if (forceRefresh || isTokenExpired(token)) {
    console.error(`Token expired for ${userEmail}, refreshing...`);
    token = await refreshStoredAccessToken(userEmail, token);
  }

  return token;
}

/**
 * Start OAuth authentication server
 */
async function startAuthServer() {
  fileStore.init();

  const app = express();

  return new Promise((resolve, reject) => {
    app.get('/callback', async (req, res) => {
      const { code, error } = req.query;

      if (error) {
        res.send(`<h1>Error</h1><p>${error}</p>`);
        reject(new Error(error));
        return;
      }

      if (!code) {
        res.send('<h1>Error</h1><p>No authorization code received</p>');
        reject(new Error('No authorization code'));
        return;
      }

      try {
        console.log('Exchanging code for tokens...');
        const tokenData = await exchangeCodeForTokens(code);

        console.log('Getting user info...');
        const userInfo = await getUserInfo(tokenData.access_token);
        const userEmail = userInfo.email;
        const displayName = userInfo.name;

        console.log('Getting accessible resources...');
        const resources = await getAccessibleResources(tokenData.access_token);

        if (resources.length === 0) {
          throw new Error('No accessible Jira sites found');
        }

        console.log('User:', userEmail);
        console.log('Accessible sites:', resources.map(r => r.name).join(', '));

        // Save user
        fileStore.saveUser({
          email: userEmail,
          name: displayName,
          enabled: true
        });

        // Save tokens (encrypted)
        const token = {
          access_token: tokenData.access_token,
          refresh_token: tokenData.refresh_token,
          expires_at: Date.now() + (tokenData.expires_in * 1000),
          scope: tokenData.scope,
          cloud_id: resources[0].id,
          site_url: resources[0].url,
          site_name: resources[0].name
        };

        fileStore.saveJiraTokens(userEmail, token);
        fileStore.setDefaultConfig(userEmail);

        // Set current user
        setCurrentUser(userEmail);

        res.send(`
          <h1>Authentication Successful!</h1>
          <p>User: <strong>${displayName}</strong> (${userEmail})</p>
          <p>Connected to: <strong>${resources[0].name}</strong></p>
          <p>Cloud ID: ${resources[0].id}</p>
          <p>Tokens encrypted and stored locally.</p>
          <p>You can close this window.</p>
        `);

        resolve({ email: userEmail, token });

        setTimeout(() => process.exit(0), 1000);
      } catch (err) {
        console.error('Error:', err.response?.data || err.message);
        res.send(`<h1>Error</h1><pre>${JSON.stringify(err.response?.data || err.message, null, 2)}</pre>`);
        reject(err);
      }
    });

    const server = app.listen(config.port, async () => {
      const authUrl = getAuthorizationUrl();
      console.log(`\nAuth server running on port ${config.port}`);
      console.log('\nOpening browser for authentication...');
      console.log('If browser does not open, visit:\n');
      console.log(authUrl);

      const open = (await import('open')).default;
      await open(authUrl);
    });
  });
}

// Run if called directly
if (require.main === module) {
  startAuthServer().catch(console.error);
}

module.exports = {
  RELINK_MESSAGE,
  getValidAccessToken,
  setCurrentUser,
  getCurrentUser,
  refreshAccessToken,
  isTokenExpired,
  refreshStoredAccessToken,
  startAuthServer
};
