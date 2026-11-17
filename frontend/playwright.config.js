import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  globalTimeout: 120000,
  workers: 1,
  use: { baseURL: process.env.SIERRA_URL || 'http://127.0.0.1:8000', headless: true,
    ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}),
  },
  reporter: 'list',
})
