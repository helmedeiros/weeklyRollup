/**
 * Token loader for downstream scripts.
 *
 * Reads .data/google_token.json, hands back an OAuth2 client that
 * transparently refreshes the access token on 401, and writes the refreshed
 * token back to disk so future runs start with a valid access token.
 */

import { google } from 'googleapis';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import 'dotenv/config';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const TOKEN_PATH = path.join(ROOT, '.data', 'google_token.json');

export function readTokenSync() {
  if (!fs.existsSync(TOKEN_PATH)) {
    throw new Error(
      `No Google token at ${TOKEN_PATH}. Run "cd google-drive-mcp && npm run auth" first.`
    );
  }
  return JSON.parse(fs.readFileSync(TOKEN_PATH, 'utf8'));
}

export function writeTokenSync(token) {
  const dir = path.dirname(TOKEN_PATH);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(TOKEN_PATH, JSON.stringify(token, null, 2), { mode: 0o600 });
}

export function authClientFromEnv() {
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  if (!clientId || !clientSecret) {
    throw new Error(
      'GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET missing. Copy google-drive-mcp/.env.example to .env and fill it in.'
    );
  }

  const stored = readTokenSync();
  const client = new google.auth.OAuth2(clientId, clientSecret);
  client.setCredentials({
    refresh_token: stored.refresh_token,
    access_token: stored.access_token,
    expiry_date: stored.expiry_date,
    token_type: stored.token_type,
    scope: stored.scope,
  });

  // Persist refreshed tokens so the next run doesn't have to refresh again.
  client.on('tokens', (tokens) => {
    const next = { ...stored };
    if (tokens.refresh_token) next.refresh_token = tokens.refresh_token;
    if (tokens.access_token) next.access_token = tokens.access_token;
    if (tokens.expiry_date) next.expiry_date = tokens.expiry_date;
    if (tokens.token_type) next.token_type = tokens.token_type;
    if (tokens.scope) next.scope = tokens.scope;
    try {
      writeTokenSync(next);
    } catch {
      // Non-fatal: refresh still succeeded in memory
    }
  });

  return client;
}
