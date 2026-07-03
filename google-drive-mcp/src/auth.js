/**
 * One-off Google OAuth Desktop-app flow.
 *
 * Opens the consent screen in the default browser, captures the auth code on a
 * loopback listener, exchanges it for a refresh token, and stores that token
 * plus the current access token in .data/google_token.json.
 *
 * Re-run `npm run reauth` to force a fresh consent flow (drops the stored
 * token first).
 */

import { google } from 'googleapis';
import http from 'node:http';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import open from 'open';
import 'dotenv/config';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const DATA_DIR = path.join(ROOT, '.data');
const TOKEN_PATH = path.join(DATA_DIR, 'google_token.json');

// Only what the rollup runner needs: read/write spreadsheets you create or
// explicitly open, and read/write files in a shared Drive folder.
const SCOPES = [
  'https://www.googleapis.com/auth/drive',
  'https://www.googleapis.com/auth/spreadsheets',
  'https://www.googleapis.com/auth/userinfo.email',
];

function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required env var: ${name}. Copy .env.example to .env and fill it in.`);
  }
  return value;
}

async function main() {
  const clientId = requireEnv('GOOGLE_CLIENT_ID');
  const clientSecret = requireEnv('GOOGLE_CLIENT_SECRET');
  const host = process.env.OAUTH_REDIRECT_HOST || '127.0.0.1';
  const port = parseInt(process.env.OAUTH_REDIRECT_PORT || '3003', 10);
  const redirectUri = `http://${host}:${port}/callback`;

  const oauth2Client = new google.auth.OAuth2(clientId, clientSecret, redirectUri);
  const state = crypto.randomBytes(24).toString('hex');
  const codeVerifier = crypto.randomBytes(32).toString('base64url');
  const codeChallenge = crypto.createHash('sha256').update(codeVerifier).digest('base64url');

  const authUrl = oauth2Client.generateAuthUrl({
    access_type: 'offline',
    prompt: 'consent',
    scope: SCOPES,
    state,
    code_challenge: codeChallenge,
    code_challenge_method: 'S256',
  });

  const server = http.createServer();
  const codePromise = new Promise((resolve, reject) => {
    server.on('request', (req, res) => {
      try {
        const url = new URL(req.url, redirectUri);
        if (url.pathname !== '/callback') {
          res.writeHead(404); res.end('Not found');
          return;
        }
        if (url.searchParams.get('state') !== state) {
          res.writeHead(400); res.end('State mismatch');
          reject(new Error('OAuth state mismatch'));
          return;
        }
        const err = url.searchParams.get('error');
        if (err) {
          res.writeHead(400); res.end(`OAuth error: ${err}`);
          reject(new Error(`OAuth error: ${err}`));
          return;
        }
        const code = url.searchParams.get('code');
        if (!code) {
          res.writeHead(400); res.end('No code');
          reject(new Error('No auth code returned'));
          return;
        }
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end(
          '<html><body style="font-family:system-ui;padding:24px">' +
            '<h2>Auth complete</h2><p>You can close this tab.</p></body></html>'
        );
        resolve(code);
      } catch (error) {
        res.writeHead(500); res.end('Internal error');
        reject(error);
      }
    });
    server.listen(port, host);
  });

  console.log(`Opening browser for Google OAuth consent...`);
  console.log(`If the browser does not open, visit:\n\n${authUrl}\n`);
  try {
    await open(authUrl);
  } catch {
    // ignored: user can open manually
  }

  const code = await codePromise;
  server.close();

  const { tokens } = await oauth2Client.getToken({ code, codeVerifier });
  oauth2Client.setCredentials(tokens);

  const oauth2 = google.oauth2({ version: 'v2', auth: oauth2Client });
  const { data: userInfo } = await oauth2.userinfo.get();

  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(
    TOKEN_PATH,
    JSON.stringify(
      {
        email: userInfo.email,
        refresh_token: tokens.refresh_token,
        access_token: tokens.access_token,
        expiry_date: tokens.expiry_date,
        scope: tokens.scope,
        token_type: tokens.token_type,
      },
      null,
      2
    ),
    { mode: 0o600 }
  );

  console.log(`Authenticated ${userInfo.email}. Token stored at ${TOKEN_PATH}.`);
}

main().catch((error) => {
  console.error('Auth failed:', error.message);
  process.exit(1);
});
