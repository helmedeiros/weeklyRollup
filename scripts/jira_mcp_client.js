#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');

const originalLog = console.log;
console.log = (...args) => {
  if (String(args[0] || '').startsWith('[dotenv')) return;
  originalLog.apply(console, args);
};

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => {
      data += chunk;
    });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

function defaultMcpDir() {
  return path.resolve(__dirname, '../../../../..', 'tools/omio-mcp-servers/omio-jira-mcp');
}

async function main() {
  const input = JSON.parse(await readStdin());
  const mcpDir = input.mcpDir || process.env.JIRA_MCP_DIR || defaultMcpDir();
  const jiraModulePath = path.join(mcpDir, 'src', 'jira.js');
  if (!fs.existsSync(jiraModulePath)) {
    throw new Error(`Jira MCP module not found at ${jiraModulePath}`);
  }

  const { JiraAPI } = require(jiraModulePath);
  const jira = new JiraAPI();

  if (input.operation === 'search') {
    const body = {
      jql: input.jql,
      maxResults: input.maxResults || 100,
      fields: input.fields || ['summary', 'status', 'assignee', 'labels', 'duedate', 'issuetype', 'project'],
    };
    if (input.nextPageToken) {
      body.nextPageToken = input.nextPageToken;
    }
    const result = await jira.request('POST', '/search/jql', body);
    console.log(JSON.stringify(result));
    return;
  }

  if (input.operation === 'comments') {
    const result = await jira.request(
      'GET',
      `/issue/${encodeURIComponent(input.issueKey)}/comment`,
      null,
      {
        startAt: input.startAt || 0,
        maxResults: input.maxResults || 100,
        orderBy: 'created',
      },
    );
    console.log(JSON.stringify(result));
    return;
  }

  if (input.operation === 'issueProperty') {
    const result = await jira.request(
      'GET',
      `/issue/${encodeURIComponent(input.issueKey)}/properties/${encodeURIComponent(input.propertyKey)}`,
    );
    console.log(JSON.stringify(result));
    return;
  }

  throw new Error(`Unsupported operation: ${input.operation}`);
}

main().catch(error => {
  if (error.response?.status === 404) {
    console.log(JSON.stringify({ missing: true, status: 404 }));
    return;
  }
  console.error(error.stack || error.message);
  process.exit(1);
});
