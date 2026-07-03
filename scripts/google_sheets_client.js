#!/usr/bin/env node
/**
 * Bridge script from the Python rollup runner to the vendored Sheets + Drive
 * wrappers. Mirrors the shape of scripts/jira_mcp_client.js: one JSON
 * operation on stdin, one JSON payload on stdout.
 *
 * Supported operations:
 *   - resolveSpreadsheet  { folderId, fileName, createIfMissing }
 *   - listSheets          { spreadsheetId }
 *   - replaceTab          { spreadsheetId, tabName, values, freezeHeader,
 *                           addBasicFilter, autoResize, createIfMissing }
 *   - readTab             { spreadsheetId, tabName, range? }
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function defaultMcpDir() {
  return path.resolve(__dirname, '..', 'google-drive-mcp');
}

async function loadModules() {
  const mcpDir = process.env.GOOGLE_DRIVE_MCP_DIR || defaultMcpDir();
  const src = path.join(mcpDir, 'src');
  const sheetsPath = path.join(src, 'sheets.js');
  const drivePath = path.join(src, 'drive.js');
  const tokenPath = path.join(src, 'token.js');
  if (!fs.existsSync(sheetsPath) || !fs.existsSync(drivePath) || !fs.existsSync(tokenPath)) {
    throw new Error(`Google Drive MCP modules not found under ${src}`);
  }
  process.chdir(mcpDir); // dotenv in token.js reads mcpDir/.env
  const [{ SheetsAPI }, { DriveAPI }, { authClientFromEnv }] = await Promise.all([
    import(sheetsPath),
    import(drivePath),
    import(tokenPath),
  ]);
  return { SheetsAPI, DriveAPI, authClientFromEnv };
}

async function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => { data += chunk; });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

async function resolveSpreadsheet(driveApi, sheetsApi, { folderId, fileName, createIfMissing }) {
  if (!folderId) throw new Error('resolveSpreadsheet: folderId is required');
  if (!fileName) throw new Error('resolveSpreadsheet: fileName is required');
  const q = [
    `name = '${fileName.replace(/'/g, "\\'")}'`,
    `'${folderId}' in parents`,
    `mimeType = 'application/vnd.google-apps.spreadsheet'`,
    'trashed = false',
  ].join(' and ');
  const list = await driveApi.drive.files.list({
    q,
    fields: 'files(id,name,webViewLink)',
    supportsAllDrives: true,
    includeItemsFromAllDrives: true,
    pageSize: 5,
  });
  const found = (list.data.files || [])[0];
  if (found) {
    return { spreadsheetId: found.id, name: found.name, url: found.webViewLink, created: false };
  }
  if (!createIfMissing) {
    return { spreadsheetId: '', name: '', url: '', created: false };
  }
  // Create empty spreadsheet, then move it into the target folder.
  const created = await sheetsApi.sheets.spreadsheets.create({
    requestBody: { properties: { title: fileName } },
    fields: 'spreadsheetId,spreadsheetUrl',
  });
  const spreadsheetId = created.data.spreadsheetId;
  await driveApi.drive.files.update({
    fileId: spreadsheetId,
    addParents: folderId,
    fields: 'id,parents,webViewLink',
    supportsAllDrives: true,
  });
  return {
    spreadsheetId,
    name: fileName,
    url: created.data.spreadsheetUrl,
    created: true,
  };
}

async function listSheets(sheetsApi, { spreadsheetId }) {
  const meta = await sheetsApi.sheets.spreadsheets.get({
    spreadsheetId,
    fields: 'sheets(properties(sheetId,title,index,gridProperties))',
  });
  return {
    sheets: (meta.data.sheets || []).map((s) => ({
      sheetId: s.properties.sheetId,
      title: s.properties.title,
      index: s.properties.index,
      rowCount: s.properties.gridProperties?.rowCount,
      columnCount: s.properties.gridProperties?.columnCount,
    })),
  };
}

async function replaceTab(sheetsApi, opts) {
  const {
    spreadsheetId,
    tabName,
    values,
    freezeHeader = true,
    addBasicFilter = true,
    autoResize = true,
    createIfMissing = true,
  } = opts;
  if (!spreadsheetId) throw new Error('replaceTab: spreadsheetId required');
  if (!tabName) throw new Error('replaceTab: tabName required');

  const meta = await sheetsApi.sheets.spreadsheets.get({
    spreadsheetId,
    fields: 'sheets(properties(sheetId,title))',
  });
  const existing = (meta.data.sheets || []).find((s) => s.properties.title === tabName);
  let sheetId;
  if (existing) {
    sheetId = existing.properties.sheetId;
    // Clear existing content
    await sheetsApi.sheets.spreadsheets.values.clear({
      spreadsheetId,
      range: `${tabName}!A1:ZZ`,
    });
    // Remove any existing basic filter so we can re-add with new range.
    await sheetsApi.sheets.spreadsheets.batchUpdate({
      spreadsheetId,
      requestBody: {
        requests: [
          { clearBasicFilter: { sheetId } },
        ],
      },
    }).catch(() => { /* no filter existed */ });
  } else {
    if (!createIfMissing) throw new Error(`replaceTab: tab "${tabName}" missing and createIfMissing=false`);
    const created = await sheetsApi.sheets.spreadsheets.batchUpdate({
      spreadsheetId,
      requestBody: {
        requests: [{ addSheet: { properties: { title: tabName } } }],
      },
    });
    sheetId = created.data.replies[0].addSheet.properties.sheetId;
  }

  const rows = values || [];
  if (rows.length) {
    await sheetsApi.sheets.spreadsheets.values.update({
      spreadsheetId,
      range: `${tabName}!A1`,
      valueInputOption: 'USER_ENTERED',
      requestBody: { values: rows },
    });
  }

  const followUp = [];
  if (freezeHeader && rows.length) {
    followUp.push({
      updateSheetProperties: {
        properties: { sheetId, gridProperties: { frozenRowCount: 1 } },
        fields: 'gridProperties.frozenRowCount',
      },
    });
  }
  if (addBasicFilter && rows.length) {
    followUp.push({
      setBasicFilter: {
        filter: {
          range: {
            sheetId,
            startRowIndex: 0,
            endRowIndex: rows.length,
            startColumnIndex: 0,
            endColumnIndex: rows[0].length,
          },
        },
      },
    });
  }
  if (autoResize && rows.length) {
    followUp.push({
      autoResizeDimensions: {
        dimensions: {
          sheetId,
          dimension: 'COLUMNS',
          startIndex: 0,
          endIndex: rows[0].length,
        },
      },
    });
  }
  if (followUp.length) {
    await sheetsApi.sheets.spreadsheets.batchUpdate({
      spreadsheetId,
      requestBody: { requests: followUp },
    });
  }

  return { sheetId, tabName, rowsWritten: rows.length };
}

async function readTab(sheetsApi, { spreadsheetId, tabName, range }) {
  if (!spreadsheetId) throw new Error('readTab: spreadsheetId required');
  if (!tabName) throw new Error('readTab: tabName required');
  const meta = await sheetsApi.sheets.spreadsheets.get({
    spreadsheetId,
    fields: 'sheets(properties(title))',
  });
  const exists = (meta.data.sheets || []).some((s) => s.properties.title === tabName);
  if (!exists) return { values: [], missing: true };
  const fullRange = range ? `${tabName}!${range}` : `${tabName}`;
  const resp = await sheetsApi.sheets.spreadsheets.values.get({
    spreadsheetId,
    range: fullRange,
  });
  return { values: resp.data.values || [], missing: false };
}

async function main() {
  const input = JSON.parse(await readStdin());
  const { SheetsAPI, DriveAPI, authClientFromEnv } = await loadModules();
  const auth = authClientFromEnv();
  const sheetsApi = new SheetsAPI(auth);
  const driveApi = new DriveAPI(auth);

  let result;
  switch (input.operation) {
    case 'resolveSpreadsheet':
      result = await resolveSpreadsheet(driveApi, sheetsApi, input);
      break;
    case 'listSheets':
      result = await listSheets(sheetsApi, input);
      break;
    case 'replaceTab':
      result = await replaceTab(sheetsApi, input);
      break;
    case 'readTab':
      result = await readTab(sheetsApi, input);
      break;
    default:
      throw new Error(`Unsupported operation: ${input.operation}`);
  }
  process.stdout.write(JSON.stringify(result));
}

main().catch((error) => {
  process.stderr.write(error.stack || String(error));
  process.exit(1);
});
