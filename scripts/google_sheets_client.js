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

// Exact tool names exposed by the remote MCP. Pinned so we don't guess and
// so a tool rename on the remote side surfaces a clear error immediately.
const TOOLS = {
  searchFilesByName: 'search_by_name',
  listFilesQuery: 'list_files',
  createSpreadsheet: 'create_google_sheet',
  moveFile: 'move_file',
  listSheets: 'sheet_list_sheets',
  getSheetContent: 'sheet_get_content',
  updateValues: 'sheet_update_values',
  clearValues: 'sheet_clear_values',
  addSheet: 'sheet_add_sheet',
  setBasicFilter: 'sheet_set_basic_filter',
  clearBasicFilter: 'sheet_clear_basic_filter',
  freezeRows: 'sheet_freeze_rows',
  autoResizeColumns: 'sheet_auto_resize_columns',
};

function ensureTool(tools, name) {
  if (!tools.find((tool) => tool.name === name)) {
    throw new Error(`Remote MCP does not expose expected tool: ${name}`);
  }
  return name;
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

  ensureTool(tools, TOOLS.listFilesQuery);
  const found = await findExistingSpreadsheet(client, folderId, fileName);
  if (found) return found;

  if (!createIfMissing) return { spreadsheetId: '', name: '', url: '', created: false };

  ensureTool(tools, TOOLS.createSpreadsheet);
  ensureTool(tools, TOOLS.moveFile);
  const created = await callTool(client, TOOLS.createSpreadsheet, { title: fileName });
  const nested = created.spreadsheet || created.data?.spreadsheet || {};
  const spreadsheetId =
    nested.id ||
    nested.spreadsheetId ||
    nested.spreadsheet_id ||
    created.spreadsheetId ||
    created.spreadsheet_id ||
    created.id ||
    created.data?.spreadsheetId ||
    '';
  if (!spreadsheetId) {
    throw new Error(`create_google_sheet returned no spreadsheetId: ${JSON.stringify(created)}`);
  }
  await callTool(client, TOOLS.moveFile, {
    file_id: spreadsheetId,
    new_parent_folder_id: folderId,
  });
  return {
    spreadsheetId,
    name: fileName,
    url:
      nested.url ||
      nested.spreadsheetUrl ||
      nested.webViewLink ||
      created.spreadsheetUrl ||
      created.webViewLink ||
      '',
    created: true,
  };
}

async function findExistingSpreadsheet(client, folderId, fileName) {
  const query =
    `name = '${fileName.replace(/'/g, "\\'")}' ` +
    `and mimeType = 'application/vnd.google-apps.spreadsheet'`;
  const resp = await callTool(client, TOOLS.listFilesQuery, {
    folder_id: folderId,
    query,
    page_size: 5,
    include_trashed: false,
  });
  const files = resp.files || resp.data?.files || [];
  const spreadsheet = files.find(
    (file) => (file.mimeType || file.mime_type || '').includes('spreadsheet')
  ) || files[0];
  if (!spreadsheet) return null;
  return {
    spreadsheetId: spreadsheet.id || spreadsheet.file_id || '',
    name: spreadsheet.name || fileName,
    url: spreadsheet.webViewLink || spreadsheet.web_view_link || '',
    created: false,
  };
}

async function listSheets(client, tools, { spreadsheetId }) {
  ensureTool(tools, TOOLS.listSheets);
  const resp = await callTool(client, TOOLS.listSheets, { spreadsheet_id: spreadsheetId });
  const sheets = resp.sheets || resp.data?.sheets || [];
  return {
    sheets: sheets.map((sheet) => {
      const props = sheet.properties || sheet;
      return {
        sheetId: props.sheetId ?? props.sheet_id ?? props.id ?? null,
        title: props.title || props.name || '',
        index: props.index ?? null,
      };
    }),
  };
}

async function replaceTab(client, tools, opts) {
  const {
    spreadsheetId,
    tabName,
    values,
    createIfMissing = true,
    freezeHeader = true,
    addBasicFilter = true,
    autoResize = true,
  } = opts;
  if (!spreadsheetId) throw new Error('replaceTab: spreadsheetId required');
  if (!tabName) throw new Error('replaceTab: tabName required');

  const existing = await listSheets(client, tools, { spreadsheetId });
  const found = existing.sheets.find((sheet) => sheet.title === tabName);
  let sheetId = found?.sheetId;

  if (!found) {
    if (!createIfMissing) throw new Error(`replaceTab: tab "${tabName}" missing and createIfMissing=false`);
    ensureTool(tools, TOOLS.addSheet);
    const added = await callTool(client, TOOLS.addSheet, {
      spreadsheet_id: spreadsheetId,
      title: tabName,
    });
    sheetId =
      added.sheetId ||
      added.sheet_id ||
      added.properties?.sheetId ||
      added.properties?.sheet_id ||
      added.replies?.[0]?.addSheet?.properties?.sheetId;
  } else {
    ensureTool(tools, TOOLS.clearValues);
    await callTool(client, TOOLS.clearValues, {
      spreadsheet_id: spreadsheetId,
      range: `${tabName}!A:ZZ`,
    });
  }

  const rows = values || [];
  if (rows.length) {
    const endColumn = columnLetter(rows[0].length);
    ensureTool(tools, TOOLS.updateValues);
    await callTool(client, TOOLS.updateValues, {
      spreadsheet_id: spreadsheetId,
      range: `${tabName}!A1:${endColumn}${rows.length}`,
      values: rows.map((row) => row.map((cell) => (cell === null || cell === undefined ? '' : String(cell)))),
    });

    // Best-effort formatting; individual failures are non-fatal.
    if (freezeHeader && tools.find((tool) => tool.name === TOOLS.freezeRows)) {
      await callTool(client, TOOLS.freezeRows, {
        spreadsheet_id: spreadsheetId,
        sheet: tabName,
        rows: 1,
      }).catch(() => {});
    }
    if (addBasicFilter && tools.find((tool) => tool.name === TOOLS.setBasicFilter)) {
      if (tools.find((tool) => tool.name === TOOLS.clearBasicFilter)) {
        await callTool(client, TOOLS.clearBasicFilter, {
          spreadsheet_id: spreadsheetId,
          sheet: tabName,
        }).catch(() => {});
      }
      await callTool(client, TOOLS.setBasicFilter, {
        spreadsheet_id: spreadsheetId,
        sheet: tabName,
        range: `${tabName}!A1:${endColumn}${rows.length}`,
      }).catch(() => {});
    }
    if (autoResize && tools.find((tool) => tool.name === TOOLS.autoResizeColumns)) {
      await callTool(client, TOOLS.autoResizeColumns, {
        spreadsheet_id: spreadsheetId,
        sheet: tabName,
        start_index: 0,
        end_index: rows[0].length,
      }).catch(() => {});
    }
  }

  return { sheetId, tabName, rowsWritten: rows.length };
}

function columnLetter(index) {
  let value = index;
  let letters = '';
  while (value > 0) {
    const remainder = (value - 1) % 26;
    letters = String.fromCharCode(65 + remainder) + letters;
    value = Math.floor((value - 1) / 26);
  }
  return letters || 'A';
}

async function readTab(client, tools, { spreadsheetId, tabName, range }) {
  const meta = await listSheets(client, tools, { spreadsheetId });
  if (!meta.sheets.some((sheet) => sheet.title === tabName)) {
    return { values: [], missing: true };
  }
  ensureTool(tools, TOOLS.getSheetContent);
  const params = {
    spreadsheet_id: spreadsheetId,
    sheet: tabName,
    format: 'raw',
  };
  if (range) params.range = range;
  const resp = await callTool(client, TOOLS.getSheetContent, params);
  return {
    values: resp.values || resp.data?.values || resp.rows || [],
    missing: false,
  };
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
