#!/usr/bin/env node
/**
 * Bridge script that speaks the MCP protocol to a remote hosted Google Drive
 * MCP through the `mcp-remote` npm proxy. Mirrors the shape of
 * scripts/jira_mcp_client.js: one JSON operation on stdin, one JSON payload
 * on stdout.
 *
 * The remote MCP URL is expected in the env var GOOGLE_SHEETS_MCP_URL (or
 * a similarly-named override) and never hard-coded in tracked source.
 *
 * mcp-remote handles the whole OAuth ceremony against the remote MCP. On the
 * first run it opens a browser for consent; tokens then live under
 * ~/.mcp-auth/ and every subsequent invocation is silent.
 *
 * Supported top-level operations (this script maps them to the MCP tools the
 * hosted server exposes; the tool names may vary between server versions and
 * are looked up dynamically from tools/list, so this script only depends on
 * the shape of the response):
 *
 *   - resolveSpreadsheet { folderId, fileName, createIfMissing }
 *   - listSheets         { spreadsheetId }
 *   - replaceTab         { spreadsheetId, tabName, values, freezeHeader,
 *                          addBasicFilter, autoResize, createIfMissing }
 *   - readTab            { spreadsheetId, tabName, range? }
 */

import { spawn } from 'node:child_process';

function requireEnv(name) {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required env var: ${name}`);
  return value;
}

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => { data += chunk; });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

class JsonRpcClient {
  constructor(child) {
    this.child = child;
    this.nextId = 1;
    this.pending = new Map();
    this.buffer = '';
    this.child.stdout.setEncoding('utf8');
    this.child.stdout.on('data', (chunk) => this._onChunk(chunk));
    this.child.stderr.setEncoding('utf8');
    this.child.stderr.on('data', () => { /* swallow; mcp-remote is chatty */ });
    this.child.on('exit', (code) => {
      const error = new Error(`mcp-remote exited with code ${code}`);
      for (const { reject } of this.pending.values()) reject(error);
      this.pending.clear();
    });
  }

  _onChunk(chunk) {
    this.buffer += chunk;
    while (true) {
      const newlineIndex = this.buffer.indexOf('\n');
      if (newlineIndex < 0) break;
      const line = this.buffer.slice(0, newlineIndex);
      this.buffer = this.buffer.slice(newlineIndex + 1);
      if (!line.trim()) continue;
      let message;
      try { message = JSON.parse(line); } catch { continue; }
      if (message.id !== undefined && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(message.error.message || 'MCP error'));
        else resolve(message.result);
      }
    }
  }

  call(method, params = {}) {
    const id = this.nextId++;
    const payload = { jsonrpc: '2.0', id, method, params };
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.child.stdin.write(`${JSON.stringify(payload)}\n`);
    });
  }

  notify(method, params = {}) {
    const payload = { jsonrpc: '2.0', method, params };
    this.child.stdin.write(`${JSON.stringify(payload)}\n`);
  }

  shutdown() {
    try { this.child.stdin.end(); } catch { /* ignored */ }
    try { this.child.kill('SIGTERM'); } catch { /* ignored */ }
  }
}

async function connect() {
  const url = requireEnv('GOOGLE_SHEETS_MCP_URL');
  const child = spawn('npx', ['-y', 'mcp-remote', url], {
    env: process.env,
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  const client = new JsonRpcClient(child);
  await client.call('initialize', {
    protocolVersion: '2024-11-05',
    capabilities: { tools: {} },
    clientInfo: { name: 'weekly-rollup-sheets-client', version: '1.0.0' },
  });
  client.notify('notifications/initialized');
  return client;
}

async function listTools(client) {
  const tools = [];
  let cursor;
  while (true) {
    const params = cursor ? { cursor } : {};
    const page = await client.call('tools/list', params);
    for (const tool of page.tools || []) tools.push(tool);
    if (!page.nextCursor) break;
    cursor = page.nextCursor;
  }
  return tools;
}

function pickTool(tools, patterns) {
  for (const pattern of patterns) {
    const found = tools.find((tool) => pattern.test(tool.name));
    if (found) return found.name;
  }
  const names = tools.map((tool) => tool.name).join(', ');
  throw new Error(`No matching tool found. Available: ${names}`);
}

async function callTool(client, name, args) {
  const result = await client.call('tools/call', { name, arguments: args });
  if (!result || !Array.isArray(result.content)) {
    return { raw: result };
  }
  // Prefer structured content when the server returns it; otherwise unwrap
  // a text/plain payload that carries JSON.
  const textEntries = result.content.filter((entry) => entry.type === 'text');
  const combined = textEntries.map((entry) => entry.text).join('');
  if (combined.trim().startsWith('{') || combined.trim().startsWith('[')) {
    try { return JSON.parse(combined); } catch { /* fall through */ }
  }
  return { raw: result, text: combined };
}

async function resolveSpreadsheet(client, tools, { folderId, fileName, createIfMissing }) {
  if (!folderId) throw new Error('resolveSpreadsheet: folderId required');
  if (!fileName) throw new Error('resolveSpreadsheet: fileName required');
  const findTool = pickTool(tools, [/drive.?(list|find|search).?files/i, /files.?(list|find|search)/i]);
  const query = [
    `name = '${fileName.replace(/'/g, "\\'")}'`,
    `'${folderId}' in parents`,
    `mimeType = 'application/vnd.google-apps.spreadsheet'`,
    'trashed = false',
  ].join(' and ');
  const listed = await callTool(client, findTool, { q: query, pageSize: 5 });
  const files = listed.files || listed.data?.files || [];
  const found = files[0];
  if (found) {
    return {
      spreadsheetId: found.id || found.fileId || '',
      name: found.name || fileName,
      url: found.webViewLink || '',
      created: false,
    };
  }
  if (!createIfMissing) return { spreadsheetId: '', name: '', url: '', created: false };
  const createTool = pickTool(tools, [/sheet.?create|create.?spreadsheet|spreadsheet.?create/i]);
  const created = await callTool(client, createTool, { title: fileName });
  const spreadsheetId = created.spreadsheetId || created.data?.spreadsheetId || '';
  if (!spreadsheetId) throw new Error(`Sheet create returned no spreadsheetId: ${JSON.stringify(created)}`);
  const moveTool = pickTool(tools, [/drive.?(move|update)?.?file|files.?update|file.?move/i]);
  await callTool(client, moveTool, { fileId: spreadsheetId, addParents: folderId });
  return {
    spreadsheetId,
    name: fileName,
    url: created.spreadsheetUrl || '',
    created: true,
  };
}

async function listSheets(client, tools, { spreadsheetId }) {
  const tool = pickTool(tools, [/sheet.?(list|get).?sheets|sheets.?list|spreadsheet.?get/i]);
  const resp = await callTool(client, tool, { spreadsheetId });
  const sheets = resp.sheets || resp.data?.sheets || [];
  return {
    sheets: sheets.map((sheet) => {
      const props = sheet.properties || sheet;
      return {
        sheetId: props.sheetId,
        title: props.title,
        index: props.index,
      };
    }),
  };
}

async function replaceTab(client, tools, opts) {
  const { spreadsheetId, tabName, values, createIfMissing = true } = opts;
  if (!spreadsheetId) throw new Error('replaceTab: spreadsheetId required');
  if (!tabName) throw new Error('replaceTab: tabName required');
  const existing = await listSheets(client, tools, { spreadsheetId });
  const found = existing.sheets.find((sheet) => sheet.title === tabName);
  let sheetId = found?.sheetId;
  if (!found) {
    if (!createIfMissing) throw new Error(`replaceTab: tab "${tabName}" missing and createIfMissing=false`);
    const addTool = pickTool(tools, [/sheet.?add.?sheet|add.?sheet|sheet.?create.?tab/i]);
    const added = await callTool(client, addTool, { spreadsheetId, title: tabName });
    sheetId = added.sheetId || added.properties?.sheetId || added.replies?.[0]?.addSheet?.properties?.sheetId;
  } else {
    const clearTool = pickTool(tools, [/sheet.?clear.?values|clear.?values|values.?clear/i]);
    await callTool(client, clearTool, { spreadsheetId, range: `${tabName}!A1:ZZ` });
  }
  const rows = values || [];
  if (rows.length) {
    const updateTool = pickTool(tools, [/sheet.?update.?values|values.?update|sheet.?write.?values/i]);
    await callTool(client, updateTool, {
      spreadsheetId,
      range: `${tabName}!A1`,
      valueInputOption: 'USER_ENTERED',
      values: rows,
    });
  }
  return { sheetId, tabName, rowsWritten: rows.length };
}

async function readTab(client, tools, { spreadsheetId, tabName, range }) {
  const meta = await listSheets(client, tools, { spreadsheetId });
  if (!meta.sheets.some((sheet) => sheet.title === tabName)) {
    return { values: [], missing: true };
  }
  const tool = pickTool(tools, [/sheet.?get.?values|sheet.?read.?values|values.?get/i]);
  const fullRange = range ? `${tabName}!${range}` : `${tabName}`;
  const resp = await callTool(client, tool, { spreadsheetId, range: fullRange });
  return { values: resp.values || resp.data?.values || [], missing: false };
}

async function main() {
  const input = JSON.parse(await readStdin());
  const client = await connect();
  try {
    const tools = await listTools(client);
    let result;
    switch (input.operation) {
      case 'resolveSpreadsheet':
        result = await resolveSpreadsheet(client, tools, input);
        break;
      case 'listSheets':
        result = await listSheets(client, tools, input);
        break;
      case 'replaceTab':
        result = await replaceTab(client, tools, input);
        break;
      case 'readTab':
        result = await readTab(client, tools, input);
        break;
      default:
        throw new Error(`Unsupported operation: ${input.operation}`);
    }
    process.stdout.write(JSON.stringify(result));
  } finally {
    client.shutdown();
  }
}

main().catch((error) => {
  process.stderr.write(error.stack || String(error));
  process.exit(1);
});
