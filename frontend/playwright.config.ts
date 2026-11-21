import { defineConfig } from '@playwright/test'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const defaultPython = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python'
const python = process.env.ATTENDANCE_TEST_PYTHON ?? resolve(root, defaultPython)
const baseURL = 'http://127.0.0.1:8109'
const edge = process.env.ATTENDANCE_TEST_EDGE !== '0'
const deno = process.env.ATTENDANCE_TEST_DENO ?? 'deno'

export default defineConfig({
  testDir: './e2e', workers: 1, timeout: 35000,
  use: { baseURL, channel: process.env.PLAYWRIGHT_CHANNEL, trace: 'retain-on-failure' },
  webServer: {
    command: edge ? `"${deno}" run -A --config supabase/functions/deno.json supabase/tests/browser-server.ts` : `"${python}" tests/browser_server.py`,
    cwd: root, env: { PYTHONPATH: root },
    url: `${baseURL}/api/health`, timeout: 20000,
  },
})
