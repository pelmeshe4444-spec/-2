import { createHmac } from 'node:crypto'
import { expect, test, type Page } from '@playwright/test'

const testToken = '123456:playwright-test'

function credential(id: number) {
  const fields = new URLSearchParams({ auth_date: String(Math.floor(Date.now() / 1000)), user: JSON.stringify({ id, first_name: 'Проверка' }) })
  fields.sort()
  const payload = [...fields].map(([key, value]) => `${key}=${value}`).join('\n')
  const secret = createHmac('sha256', 'WebAppData').update(testToken).digest()
  fields.set('hash', createHmac('sha256', secret).update(payload).digest('hex'))
  return fields.toString()
}

async function launch(page: Page, id: number, dark = false) {
  await page.route('https://telegram.org/js/telegram-web-app.js', route => route.fulfill({ contentType: 'application/javascript', body: '// Telegram bridge mock is set before loading.' }))
  await page.addInitScript(({ initData, dark }) => {
    window.Telegram = { WebApp: {
      initData, colorScheme: dark ? 'dark' : 'light', ready() {}, expand() {}, onEvent() {}, offEvent() {},
      isVersionAtLeast: () => true, contentSafeAreaInset: { top: 0, left: 0, right: 0, bottom: 16 },
      BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} }, HapticFeedback: { notificationOccurred() {} },
    } }
  }, { initData: credential(id), dark })
}

test('owner dashboard, bulk creation, statuses, and report scheduling use the REST API', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 980 })
  await launch(page, 101)
  await page.goto('/?class=1')
  await expect(page.getByRole('heading', { name: 'Обзор посещаемости' })).toBeVisible()
  await expect(page.getByText('Отмечено 3 из 4 учеников')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('desktop-dashboard.png') })
  const nav = page.getByRole('navigation', { name: 'Основная навигация' })
  await nav.getByRole('link', { name: 'Ученики', exact: true }).click()
  await page.getByLabel('Класс', { exact: true }).selectOption('1')
  await page.getByRole('button', { name: 'Массовый ввод' }).click()
  await page.getByLabel('Список учеников').fill('Данилов Егор\nЕгорова Анна')
  await page.getByRole('button', { name: 'Предпросмотр' }).click()
  await expect(page.getByText('Будут добавлены · 2')).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Добавить', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Данилов Егор', exact: true })).toBeVisible()
  await nav.getByRole('link', { name: 'Посещаемость' }).click()
  await page.getByRole('button', { name: 'По уважительной причине · Данилов Егор' }).click()
  await page.getByLabel('Комментарий, необязательно').fill('Семейные обстоятельства')
  await page.getByRole('button', { name: 'Сохранить отметку' }).click()
  await expect(page.getByText('Семейные обстоятельства')).toBeVisible()
  await nav.getByRole('link', { name: 'Автоматические отчёты' }).click()
  await page.getByLabel('Время отправки').fill('08:45')
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(page.getByText('Расписание сохранено')).toBeVisible()
  await page.getByRole('button', { name: 'Отправить сейчас' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Отправить', exact: true }).click()
  await expect(page.getByText('Отчёт доставлен: 1 из 1')).toBeVisible()
})

test('manager mobile view has no administrative navigation and saves a mark', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await launch(page, 102, true)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Мой класс' })).toBeVisible()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await expect(page.getByRole('navigation', { name: 'Навигация на телефоне' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Настройки' })).toHaveCount(0)
  await page.getByRole('link', { name: 'Начать отметку' }).click()
  await page.getByRole('button', { name: 'Присутствует · Громова Елена' }).click()
  await expect(page.getByRole('button', { name: 'Присутствует · Громова Елена' })).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  await page.screenshot({ path: testInfo.outputPath('mobile-attendance.png') })
  await page.goto('/users')
  await expect(page.getByText('Раздел недоступен')).toBeVisible()
})

test('recipient has access only to deliveries', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await launch(page, 103)
  await page.goto('/')
  await expect(page).toHaveURL(/\/reports$/)
  await expect(page.getByRole('heading', { name: 'Отчёты', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Посещаемость' })).toHaveCount(0)
})

test('unknown verified Telegram user can apply without access to attendance', async ({ page }) => {
  await launch(page, 1234)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Добро пожаловать в Attendance!' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Отправить заявку' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Посещаемость' })).toHaveCount(0)
})
