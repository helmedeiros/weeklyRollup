const axios = require('axios');

const RELINK_MESSAGE = 'Atlassian authentication expired. Run `npm run auth` to re-link your Atlassian account.';

function getConfig() {
  const clientId = process.env.ATLASSIAN_CLIENT_ID;
  const clientSecret = process.env.ATLASSIAN_CLIENT_SECRET;
  const redirectUri = process.env.ATLASSIAN_REDIRECT_URI;
  const authUrl = process.env.ATLASSIAN_AUTH_URL;
  const tokenUrl = process.env.ATLASSIAN_TOKEN_URL;
  const resourcesUrl = process.env.ATLASSIAN_RESOURCES_URL;
  const scopes = process.env.ATLASSIAN_SCOPES;

  return {
    clientId,
    clientSecret,
    redirectUri,
    authUrl,
    tokenUrl,
    resourcesUrl,
    scopes
  };
}

function getAuthorizationUrl() {
  const config = getConfig();
  const params = new URLSearchParams({
    audience: 'api.atlassian.com',
    client_id: config.clientId,
    scope: config.scopes,
    redirect_uri: config.redirectUri,
    response_type: 'code',
    prompt: 'consent'
  });
  return `${config.authUrl}?${params.toString()}`;
}

async function exchangeCodeForTokens(code) {
  const config = getConfig();
  const response = await axios.post(config.tokenUrl, {
    grant_type: 'authorization_code',
    client_id: config.clientId,
    client_secret: config.clientSecret,
    code,
    redirect_uri: config.redirectUri
  });
  return response.data;
}

async function getAccessibleResources(accessToken) {
  const config = getConfig();
  const response = await axios.get(config.resourcesUrl, {
    headers: { Authorization: `Bearer ${accessToken}` }
  });
  return response.data;
}

async function getUserInfo(accessToken) {
  const response = await axios.get('https://api.atlassian.com/me', {
    headers: { Authorization: `Bearer ${accessToken}` }
  });
  return response.data;
}

async function refreshAccessToken(refreshToken) {
  const config = getConfig();
  const response = await axios.post(config.tokenUrl, {
    grant_type: 'refresh_token',
    client_id: config.clientId,
    client_secret: config.clientSecret,
    refresh_token: refreshToken
  });
  return response.data;
}

function isAuthError(error) {
  return error?.response?.status === 401 ||
    error?.response?.status === 400 ||
    error?.message?.includes('invalid_grant') ||
    error?.message?.includes('Invalid Credentials');
}

module.exports = {
  RELINK_MESSAGE,
  getAuthorizationUrl,
  exchangeCodeForTokens,
  getAccessibleResources,
  getUserInfo,
  refreshAccessToken,
  isAuthError
};
