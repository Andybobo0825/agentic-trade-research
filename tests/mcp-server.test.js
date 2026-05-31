import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';

function callMcp(message) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ['src/mcp-server.js'], { stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    const timeout = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error(`MCP call timed out. stderr=${stderr}`));
    }, 3000);
    child.stdout.on('data', (chunk) => {
      stdout += chunk;
      const line = stdout.split('\n').find(Boolean);
      if (!line) return;
      clearTimeout(timeout);
      child.kill('SIGTERM');
      try { resolve(JSON.parse(line)); } catch (error) { reject(error); }
    });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('error', (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    child.stdin.write(`${JSON.stringify(message)}\n`);
  });
}

test('MCP tools/list exposes low-token output controls', async () => {
  const response = await callMcp({ jsonrpc: '2.0', id: 1, method: 'tools/list' });
  const endpoints = response.result.tools.find((tool) => tool.name === 'endpoints');
  assert.ok(endpoints);
  assert.ok(endpoints.inputSchema.properties.format);
  assert.ok(endpoints.inputSchema.properties.outputFields);
  assert.ok(endpoints.inputSchema.properties.maxRows);
});

test('MCP tools/call defaults to compact JSON text', async () => {
  const response = await callMcp({ jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'endpoints', arguments: {} } });
  const text = response.result.content[0].text;
  assert.equal(text.includes('\n  '), false);
  assert.match(text, /^\{"endpoints":/);
});
