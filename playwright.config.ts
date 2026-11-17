import { defineConfig } from '@playwright/test'

// 浏览器端到端测试（tests/e2e/）。
// - Vite 开发服务器由 Playwright 自动启动（VITE_PORT 固定 5174 并绑定 127.0.0.1，
//   可用 E2E_NO_SERVER=1 复用外部已启动的服务）。
// - 纯前端用例（未登录跳转等）无需后端；需要真实登录的用例在设置
//   E2E_BACKEND_URL 后才执行，且会把 Vite 代理指向该后端。永不连接生产服务。
const backendUrl = process.env.E2E_BACKEND_URL

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5174',
    // 优先使用系统浏览器（Windows 自带 Edge），避免下载 Chromium；
    // 已执行 playwright install chromium 的环境可改回默认浏览器。
    channel: process.env.E2E_BROWSER ?? 'msedge',
  },
  webServer: process.env.E2E_NO_SERVER
    ? undefined
    : {
        command: 'pnpm --dir frontend dev',
        url: 'http://127.0.0.1:5174',
        reuseExistingServer: true,
        timeout: 60_000,
        env: { VITE_PORT: '5174', ...(backendUrl ? { VITE_API_TARGET: backendUrl } : {}) },
      },
})
