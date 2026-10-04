process.env.AGENT_CITY_UI_EXTRA_BOOTSTRAP ||= require('node:crypto').randomBytes(32).toString('base64url');
process.env.AGENT_CITY_UI_OWNER_HOST ||= 'agent-city-'+require('node:crypto').randomBytes(16).toString('hex')+'.localhost';
process.env.AGENT_CITY_UI_BOOTSTRAP ||= require('node:crypto').randomBytes(32).toString('base64url');
const { defineConfig } = require('@playwright/test');
const port=Number(process.env.AGENT_CITY_TEST_PORT||47833);
module.exports = defineConfig({
  testDir: './tests', testMatch: '*.spec.cjs', workers: 1, retries: 0,
  use: {baseURL: `http://${process.env.AGENT_CITY_UI_OWNER_HOST}:${port}`, channel: process.env.PW_CHANNEL || 'chrome', viewport: {width: 1280, height: 900}, trace: 'off'},
  webServer: {command: `${process.platform === 'win32' ? 'python' : 'python3'} tests/fixture_server.py`, url: `http://127.0.0.1:${port}/api/health`, reuseExistingServer: false, timeout: 15000},
});
