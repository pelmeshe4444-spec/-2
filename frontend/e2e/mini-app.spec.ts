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
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.setViewportSize({ width: 390, height: 844 })
  await launch(page, 102, true)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Мой класс' })).toBeVisible()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await expect(page.getByRole('navigation', { name: 'Навигация на телефоне' })).toBeVisible()
  const watermark = page.getByText('made by @Pelmeshe4444', { exact: true })
  await expect(watermark).toBeVisible()
  await expect(page.locator('html')).toHaveCSS('--safe-bottom', '16px')
  const mark = await watermark.boundingBox()
  const navigation = await page.getByRole('navigation', { name: 'Навигация на телефоне' }).boundingBox()
  expect(mark!.x).toBeLessThan(30)
  expect(mark!.y).toBeGreaterThan(730)
  expect(mark!.y + mark!.height).toBeLessThanOrEqual(navigation!.y + 6)
  await expect(page.getByRole('link', { name: 'Настройки' })).toHaveCount(0)
  await page.getByRole('link', { name: 'Начать отметку' }).click()
  await page.getByRole('button', { name: 'Присутствует · Громова Елена' }).click()
  await expect(page.getByRole('button', { name: 'Присутствует · Громова Елена' })).toHaveAttribute('aria-pressed', 'true')
  await page.reload()
  await expect(page.getByRole('button', { name: 'Присутствует · Громова Елена' })).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  await page.screenshot({ path: testInfo.outputPath('mobile-attendance.png') })
  await page.goto('/users')
  await expect(page.getByText('Раздел недоступен')).toBeVisible()
  expect(errors).toEqual([])
})

test('recipient has access only to deliveries', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await launch(page, 103)
  await page.goto('/')
  await expect(page).toHaveURL(/\/reports$/)
  await expect(page.getByRole('heading', { name: 'Отчёты', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Посещаемость' })).toHaveCount(0)
})

test('new Telegram user applies, owner approves, and member can view only the class timetable', async ({ page, browser }) => {
  await launch(page, 1234)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Добро пожаловать в Attendance!' })).toBeVisible()
  await expect(page.locator('html')).not.toHaveClass(/dark/)
  await page.getByLabel('Класс', { exact: true }).selectOption('1')
  await page.getByRole('button', { name: 'Отправить заявку' }).click()
  await expect(page.getByText('Заявка ожидает подтверждения')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Посещаемость' })).toHaveCount(0)
  const admin = await browser.newPage()
  try {
    await launch(admin, 101)
    await admin.goto('/requests')
    await admin.getByRole('button', { name: 'Одобрить' }).click()
    await admin.getByRole('dialog').getByRole('button', { name: 'Подтвердить' }).click()
    await expect(admin.getByText('Заявка обновлена')).toBeVisible()
  } finally {
    await admin.close()
  }
  await page.reload()
  await page.getByRole('link', { name: 'Моё расписание', exact: true }).first().click()
  await expect(page.getByRole('heading', { name: 'Моё расписание' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Редактор недели' })).toHaveCount(0)
})

test('weekly editor copies a day and a week without changing the source class', async ({ page }) => {
  await launch(page, 101)
  await page.goto('/lessons?class=1')
  await page.getByRole('button', { name: 'Предметы', exact: true }).click()
  await page.getByRole('button', { name: 'Добавить предмет' }).click()
  await page.getByLabel('Название предмета').fill('Физика')
  await page.getByRole('button', { name: 'Сохранить предмет' }).click()
  await expect(page.getByText('Предмет сохранён')).toBeVisible()
  await page.getByRole('button', { name: 'Редактор недели' }).click()
  await page.getByRole('button', { name: 'Добавить урок · Понедельник' }).click()
  await page.getByLabel('Начало', { exact: true }).fill('08:30')
  await page.getByLabel('Окончание', { exact: true }).fill('09:15')
  await page.getByRole('button', { name: 'Сохранить в черновик' }).click()
  await page.getByRole('button', { name: 'Копировать день' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Копировать', exact: true }).click()
  const lessons = page.locator('.week-lesson')
  await expect(lessons).toHaveCount(2)
  await page.getByRole('button', { name: 'Предварительный просмотр' }).click()
  await page.getByRole('button', { name: 'Сохранить всю неделю' }).click()
  await expect(page.getByText('Расписание опубликовано')).toBeVisible()

  await page.getByLabel('Класс', { exact: true }).selectOption('2')
  await page.getByRole('button', { name: 'Редактор недели' }).click()
  await expect(lessons).toHaveCount(0)
  await page.getByRole('button', { name: 'Копировать неделю из класса' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Копировать', exact: true }).click()
  await expect(lessons).toHaveCount(2)
  await lessons.last().getByRole('button', { name: 'Удалить урок из черновика' }).click()
  await page.getByRole('button', { name: 'Предварительный просмотр' }).click()
  await page.getByRole('button', { name: 'Сохранить всю неделю' }).click()
  await expect(lessons).toHaveCount(1)
  await page.getByLabel('Класс', { exact: true }).selectOption('1')
  await page.getByRole('button', { name: 'Редактор недели' }).click()
  await expect(lessons).toHaveCount(2)
})
