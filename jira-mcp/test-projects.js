#!/usr/bin/env node
require('dotenv').config();
const { JiraAPI } = require('./src/jira');

async function main() {
  const jira = new JiraAPI();

  console.log('=== Fetching last 3 projects ===\n');

  const projects = await jira.listProjects(200);

  // Filter out deprecated projects (contain "zzz", "deprecated", "RIP", "OLD")
  const activeProjects = projects.filter(p => {
    const name = p.name.toLowerCase();
    return !name.includes('zzz') &&
           !name.includes('deprecated') &&
           !name.includes('[rip]') &&
           !name.includes('- old');
  });

  const firstThree = activeProjects.slice(0, 3);

  console.log(`Found ${projects.length} projects total, ${activeProjects.length} active. Showing first 3 active:\n`);

  for (const project of firstThree) {
    console.log(`\n📁 ${project.key} - ${project.name}`);
    console.log(`   Type: ${project.projectTypeKey}`);
    console.log('   ---');

    try {
      const jql = `project = "${project.key}" ORDER BY created DESC`;
      const result = await jira.searchIssues(jql, {
        maxResults: 5,
        fieldSet: 'standard'
      });

      if (result.issues.length === 0) {
        console.log('   No issues found');
      } else {
        console.log(`   Last 5 issues (${result.issues.length} found):`);
        for (const issue of result.issues) {
          const assignee = issue.assignee || 'Unassigned';
          console.log(`   • ${issue.key}: ${issue.summary}`);
          console.log(`     Status: ${issue.status} | Assignee: ${assignee}`);
        }
      }
    } catch (err) {
      console.log(`   ❌ Error fetching issues: ${err.message}`);
    }
  }

  console.log('\n=== Done ===');
}

main().catch(err => {
  console.error('Error:', err.message);
  process.exit(1);
});
