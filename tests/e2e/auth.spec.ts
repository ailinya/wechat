/** 认证与导航：未登录守卫无需后端；真实登录用例需 E2E_BACKEND_URL。 */
import { expect, test } from '@playwright/test'

test('未登录访问受保护模块跳回登录页', async ({ page }) => {
  await page.goto('/#/dashboard')
  await expect(page).toHaveURL(/#\/login/)
})

test('登录页展示账号与密码输入', async ({ page }) => {
  await page.goto('/#/login')
  await expect(page.getByLabel('账号')).toBeVisible()
  await expect(page.getByLabel('密码')).toBeVisible()
})

const hasBackend = Boolean(process.env.E2E_BACKEND_URL)
// 需要真实后端的用例：未设置 E2E_BACKEND_URL 时整组跳过。
test.describe('真实登录（需 E2E_BACKEND_URL）', () => {
  test.skip(!hasBackend, '未设置 E2E_BACKEND_URL，跳过真实登录用例')
  const account = process.env.E2E_ADMIN_ACCOUNT ?? 'admin'
  const password = process.env.E2E_ADMIN_PASSWORD ?? ''

  test('管理员登录后看到八模块导航并可退出', async ({ page }) => {
    await page.goto('/#/login')
    await page.getByLabel('账号').fill(account)
    await page.getByLabel('密码').fill(password)
    await page.getByRole('button', { name: '登录' }).click()

    await expect(page).toHaveURL(/#\/dashboard/)
    const nav = page.getByRole('navigation', { name: '主导航' })
    for (const label of ['工作台', '采集管理', '智能创作', '内容管理', '素材库', '数据统计分析', '账号管理', '系统设置']) {
      await expect(nav.getByText(label)).toBeVisible()
    }

    await page.getByRole('button', { name: '退出登录' }).click()
    await expect(page).toHaveURL(/#\/login/)
  })

  test('登录失败提示来自后端错误响应', async ({ page }) => {
    await page.goto('/#/login')
    await page.getByLabel('账号').fill(account)
    await page.getByLabel('密码').fill('wrong-password')
    await page.getByRole('button', { name: '登录' }).click()
    await expect(page.locator('.form-error')).toBeVisible()
    await expect(page).toHaveURL(/#\/login/)
  })
})
