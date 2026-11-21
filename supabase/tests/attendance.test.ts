import { strict as assert } from 'node:assert'
import { createHmac } from 'node:crypto'
import postgres from 'postgres'
import { authenticate, HttpError } from '../functions/_shared/auth.ts'
import { normal, studentNames, type Row } from '../functions/_shared/core.ts'
import { reportParts, due } from '../functions/_shared/reports.ts'
import { validateLessons } from '../functions/_shared/timetable.ts'
import { apiHandler } from '../functions/_shared/runtime.ts'
import { webhookHandler } from '../functions/_shared/webhook.ts'
import { schedulerHandler } from '../functions/_shared/scheduler-http.ts'
import { fixtures, testConfiguration, testToken, testUrl } from './fixtures.ts'

function signed(userId: number, timestamp = Math.floor(Date.now() / 1000)): string {
  const fields = new URLSearchParams({ auth_date: String(timestamp), user: JSON.stringify({ id: userId, first_name: 'QA' }) })
  fields.sort()
  const secret = createHmac('sha256', 'WebAppData').update(testToken).digest()
  fields.set('hash', createHmac('sha256', secret).update([...fields].map(([key, value]) => `${key}=${value}`).join('\n')).digest('hex'))
  return fields.toString()
}
Deno.test('Telegram HMAC rejects expiry, duplicated fields, wrong signatures, and forged identities', async () => {
  assert.equal((await authenticate(signed(9_876_543_210, 1000), testToken, 3600, 1100)).id, 9_876_543_210)
  for (const raw of [signed(101, 1000) + '&auth_date=1000', signed(101, 1000).replace(/hash=./, 'hash=z'), 'user=invalid']) {
    await assert.rejects(() => authenticate(raw, testToken, 3600, 1100), HttpError)
  }
  await assert.rejects(() => authenticate(signed(101, 1000), testToken, 60, 1100), HttpError)
  await assert.rejects(() => authenticate(signed(-101, 1000), testToken, 3600, 1100), HttpError)
})
Deno.test('full names preserve one, two, three, five, ten words, Unicode, hyphens and apostrophes', () => {
  for (const name of ['Али', 'Иванов Иван', 'Иванов Иван Иванович', 'Мухаммад Али Абдулла ибн Хасан',
    'Абдуллаев Мухаммад Али Абдуллаевич ибн Хасан Каримов Отабеков Ибрагимов Шарифов', "Oʻtkir D'Артаньян Анна-Мария"]) assert.deepEqual(studentNames(name, false), [name])
  assert.equal(studentNames('Али\nИванов Иван Иванович\nАбдуллаев Мухаммад Али ибн Хасан', true).length, 3)
  assert.equal(normal('  STRAẞE  Ёлкин  '), 'strasse ёлкин')
  assert.throws(() => studentNames('А'.repeat(256), false), HttpError)
  assert.throws(() => studentNames('Али 123', false), HttpError)
})
Deno.test('shared manual and automatic report format omits present names and medical reasons and respects Telegram size', () => {
  const entries = [{ full_name: 'Присутствующий Скрытый', status: 1 }, ...Array.from({ length: 100 }, (_, index) => ({
    full_name: 'Длинное Полное Имя Ученика '.repeat(8) + index, status: index % 4 + 2 > 4 ? 0 : index % 4 + 2, reason: 'PRIVATE_MEDICAL_REASON' }))]
  const parts = reportParts('9-А <класс>', '2026-11-20', entries, 'Asia/Tashkent')
  assert(parts.length > 1)
  assert(parts.every(part => part.length <= 3900))
  assert(!parts.join('').includes('Присутствующий Скрытый'))
  assert(!parts.join('').includes('PRIVATE_MEDICAL_REASON'))
  assert(parts.join('').includes('ПРИСУТСТВУЮТ: 1'))
  assert(parts.join('').includes(entries[1].full_name))
})
Deno.test('report schedules use local dates, 18-hour catch-up and separate reminder windows', () => {
  const schedule = { is_enabled: true, deleted: false, weekdays: '0123456', timezone: 'Asia/Tashkent', time: '08:30', reminder_one: '08:00', reminder_two: '08:20' }
  assert(due(schedule, 'reminder_one', '2026-11-20', new Date('2026-11-20T03:10:00Z')))
  assert(!due(schedule, 'reminder_one', '2026-11-20', new Date('2026-11-20T03:21:00Z')))
  assert(due(schedule, 'scheduled', '2026-11-20', new Date('2026-11-20T04:00:00Z')))
  assert(!due(schedule, 'scheduled', '2026-11-20', new Date('2026-11-21T04:00:00Z')))
})
Deno.test('lesson editor prevents duplicate numbers, reversed times, and overlap', () => {
  const lesson = { weekday: 0, lesson_number: 1, subject_id: 1, start_time: '08:00', end_time: '08:45' }
  assert.throws(() => validateLessons([lesson, lesson]), HttpError)
  assert.throws(() => validateLessons([{ ...lesson, end_time: '07:59' }]), HttpError)
  assert.throws(() => validateLessons([lesson, { ...lesson, lesson_number: 2, start_time: '08:40', end_time: '09:20' }]), HttpError)
})

Deno.test({ name: 'PostgreSQL integration verifies every application workflow through the TypeScript API',
  ignore: !Deno.env.get('ATTENDANCE_TEST_DATABASE_URL'), async fn(test) {
    await fixtures()
    const api = apiHandler(testConfiguration), webhook = webhookHandler(testConfiguration), cron = schedulerHandler(testConfiguration)
    const sql = postgres(testUrl, { prepare: false, max: 1, onnotice: () => {} })
    const send = async (path: string, user = 101, method = 'GET', data?: Row, expected = 200): Promise<Response> => {
      const response = await api(new Request('http://127.0.0.1:8109/api/v1' + path, { method,
        headers: { ...(user ? { Authorization: 'tma ' + signed(user) } : {}), ...(data ? { 'Content-Type': 'application/json' } : {}) },
        body: data ? JSON.stringify(data) : undefined }))
      assert.equal(response.status, expected, path + ' ' + await response.clone().text())
      return response
    }
    const json = async (path: string, user = 101, method = 'GET', data?: Row, expected = 200): Promise<Row> => (await send(path, user, method, data, expected)).json()
    const userId = 8_123_456_789
    try {
      await test.step('authorization and CORS guard administrative data', async () => {
        await send('/admin/dashboard', 0, 'GET', undefined, 401)
        await send('/admin/dashboard', 102, 'GET', undefined, 403)
        const origin = await api(new Request('http://127.0.0.1:8109/api/v1/me', { method: 'OPTIONS', headers: { Origin: 'https://wrong.example' } }))
        assert.equal(origin.status, 403)
        assert.equal((await json('/me')).roles[0], 'OWNER')
      })
      await test.step('/start inserts and updates a numeric Telegram user and exposes an eligible class-independent recipient', async () => {
        assert.equal((await json('/me', userId)).user.started, false)
        const query = '/admin/recipient-candidates?class_id=2&q=' + userId
        assert.equal((await json(query)).total, 0)
        const update: Row = { update_id: 901, message: { message_id: 901, date: 1800000000, text: '/start',
          chat: { id: userId, type: 'private' }, from: { id: userId, is_bot: false, first_name: 'Тестовый Родитель' } } }
        assert.equal((await webhook(new Request('http://127.0.0.1/webhook', { method: 'POST', body: JSON.stringify(update) }))).status, 403)
        for (const number of [901, 901, 902]) {
          update.update_id = number
          update.message.from.first_name = 'Тестовый Родитель Обновлённый'
          const response = await webhook(new Request('http://127.0.0.1/webhook', { method: 'POST', headers: {
            'X-Telegram-Bot-Api-Secret-Token': testConfiguration.webhookSecret }, body: JSON.stringify(update) }))
          assert.equal(response.status, 200)
        }
        const candidates = await json(query)
        assert.equal(candidates.users[0].id, userId)
        assert.equal(candidates.users[0].name, 'Тестовый Родитель Обновлённый')
        assert.equal(candidates.total, 1)
        for (const changed of [true, false]) assert.equal((await json('/users/' + userId + '/access', 101, 'POST', { class_id: 2, operation: 'recipient_add' })).changed, changed)
        assert.equal((await json('/users/' + userId)).member, null)
        assert.equal((await json(query)).total, 0)
        assert.equal(Number((await sql`SELECT count(*) AS n FROM users WHERE telegram_id=${userId}`)[0].n), 1)
      })
      let pupilId = 0
      const longName = 'Абдуллаев Мухаммад Али Абдуллаевич ибн Хасан Каримов Отабеков Ибрагимов Шарифов'
      await test.step('bulk preview, full-name storage, edit, search, archived restore and enrollment', async () => {
        const path = '/classes/2/students', input = { names: longName + '\nТестовый Присутствующий\nТестовый Отсутствующий', bulk: true, preview: true }
        assert.equal((await json(path, 101, 'POST', input)).added.length, 3)
        assert.equal((await json(path)).length, 0)
        assert.equal((await json(path, 101, 'POST', { ...input, preview: false })).added.length, 3)
        const pupils = await json(path)
        pupilId = pupils.find((row: Row) => row.full_name === longName).id
        await json('/students/' + pupilId, 101, 'PATCH', { full_name: longName + ' Oʻtkir' })
        assert.equal((await json(path + '?q=' + encodeURIComponent('Хасан Каримов')))[0].full_name, longName + ' Oʻtkir')
        assert.equal((await json('/students/' + pupilId)).history.length, 1)
        await json('/students/' + pupilId, 101, 'DELETE')
        await json('/students/' + pupilId + '/restore', 101, 'POST')
        assert((await json(path)).find((row: Row) => row.id === pupilId).active)
      })
      const today = (await json('/me')).today
      await test.step('attendance enforces optimistic versions, preserves history and calculates statistics', async () => {
        const path = '/classes/2/attendance/' + pupilId + '?day=' + today
        const marked = await json(path, 101, 'PUT', { status: 2, version: '', reason: 'PRIVATE_MEDICAL_REASON' })
        assert.equal(marked.status, 2)
        await json(path, 101, 'PUT', { status: 3, version: '', reason: 'Причина' }, 409)
        await json(path, 101, 'PUT', { status: 2, version: marked.version, reason: 'PRIVATE_MEDICAL_REASON' })
        assert.equal((await json('/classes/2/attendance/history?day=' + today)).length, 1)
        assert.equal((await json('/classes/2/attendance/mark-all?day=' + today, 101, 'POST')).changed, 2)
        const stats = await json('/classes/2/stats?start=' + today + '&end=' + today)
        assert.equal(stats.counts[1], 2)
        assert.equal(stats.counts[2], 1)
        assert.equal((await json('/classes/2/attendance/finish?day=' + today, 101, 'POST')).counts[1], 2)
      })
      await test.step('manual reports allow later operations, suppress concurrent replay, and enforce manager permission', async () => {
        const request = { class_id: 1, request_id: 'a'.repeat(32) }
        await Promise.all([json('/reports/send-now', 102, 'POST', request), json('/reports/send-now', 102, 'POST', request)])
        assert.equal((await json('/classes/1/deliveries')).total, 1)
        assert.equal((await json('/classes/1/deliveries')).items[0].telegram_message_id, 1)
        assert((await json('/classes/1/reports/last-manual', 102)).sent_at)
        await json('/reports/send-now', 102, 'POST', { ...request, request_id: 'b'.repeat(32) })
        assert.equal((await json('/classes/1/deliveries')).total, 2)
        await json('/admin/users/102/roles', 101, 'PATCH', { class_id: 1, operation: 'report_send_off' })
        await json('/reports/send-now', 102, 'POST', { ...request, request_id: 'c'.repeat(32) }, 403)
        await json('/reports/send-now', 103, 'POST', { ...request, request_id: 'd'.repeat(32) }, 403)
        await json('/reports/send-now', 101, 'POST', { ...request, recipient_id: userId }, 422)
        await json('/admin/users/102/roles', 101, 'PATCH', { class_id: 1, operation: 'report_send_on' })
        const preview = (await json('/classes/2/report')).parts.join('\n')
        assert(preview.includes(longName))
        assert(!preview.includes('Тестовый Присутствующий'))
        assert(!preview.includes('PRIVATE_MEDICAL_REASON'))
      })
      await test.step('Cron authenticates calls and persists a single scheduled delivery across repeated runs', async () => {
        const time = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Tashkent', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date())
        await json('/classes/1/schedule', 101, 'PUT', { time, timezone: 'Asia/Tashkent', weekdays: [0, 1, 2, 3, 4, 5, 6], enabled: true })
        assert.equal((await cron(new Request('http://127.0.0.1/scheduler', { method: 'POST' }))).status, 403)
        for (let index = 0; index < 2; index++) assert.equal((await cron(new Request('http://127.0.0.1/scheduler', { method: 'POST', headers: { Authorization: 'Bearer ' + testConfiguration.schedulerSecret } }))).status, 200)
        const deliveries = (await json('/classes/1/deliveries')).items.filter((row: Row) => row.kind === 'scheduled')
        assert.equal(deliveries.length, 1)
        assert.equal(deliveries[0].status, 'sent')
        await json('/classes/1/schedule', 101, 'DELETE')
      })
      await test.step('signed Cron invocations accept one nonce and reject forged or expired signatures', async () => {
        const timestamp = String(Math.floor(Date.now() / 1000)), nonce = crypto.randomUUID()
        const signature = createHmac('sha256', testConfiguration.schedulerSecret).update(`attendance-scheduler\n${timestamp}\n${nonce}`).digest('hex')
        const headers = { 'X-Attendance-Time': timestamp, 'X-Attendance-Nonce': nonce, 'X-Attendance-Signature': signature }
        const invoke = (values: Record<string, string>) => cron(new Request('http://127.0.0.1/scheduler', { method: 'POST', headers: values }))
        assert.equal((await invoke({ ...headers, 'X-Attendance-Signature': '0'.repeat(64) })).status, 403)
        assert.equal((await invoke({ ...headers, 'X-Attendance-Time': '1000' })).status, 403)
        assert.equal((await invoke(headers)).status, 200)
        assert.equal((await (await invoke(headers)).json()).duplicate, true)
      })
      await test.step('class application approval and notifications work without exposing attendance to a member', async () => {
        const applicant = 901_901
        await json('/me', applicant)
        const application = await json('/join-requests', applicant, 'POST', { class_id: 2 }, 201)
        await json('/admin/join-requests/' + application.id + '/approve', applicant, 'POST', undefined, 403)
        await json('/admin/join-requests/' + application.id + '/approve', 101, 'POST')
        assert.equal((await json('/me', applicant)).member.id, 2)
        await json('/classes/2/attendance', applicant, 'GET', undefined, 403)
        await json('/classes/2/timetable', applicant)
        await json('/me/lesson-notifications', applicant, 'PUT', { enabled: true })
        assert((await json('/notifications', applicant)).length > 0)
        await json('/notifications/read', applicant, 'POST')
        assert((await json('/notifications', applicant)).every((row: Row) => row.read))
      })
      await test.step('subject editor, weekly plans, revisions, exceptions, bells and historical restore persist', async () => {
        const subject = await json('/subjects', 101, 'POST', { name: 'Физика', color: '#123456', icon: 'atom' }, 201)
        const editor = await json('/classes/2/timetable/editor')
        const lesson = { weekday: 0, lesson_number: 1, subject_id: subject.id, start_time: '08:00', end_time: '08:45', teacher_name: null, classroom: '101', comment: null }
        const plan = { ...editor.plan, lessons: [lesson] }
        const published = await json('/classes/2/timetable', 101, 'PUT', plan)
        assert.equal(published.revision, 1)
        await json('/classes/2/timetable', 101, 'PUT', plan, 409)
        await json('/classes/2/timetable/bells', 101, 'PUT', { shift: 'Первая', slots: [{ lesson_number: 1, start_time: '08:00', end_time: '08:45' }] })
        await json('/classes/2/timetable/exceptions/' + today, 101, 'PUT', { action: 'closed', lessons: [], revision: 0 })
        assert.equal((await json('/classes/2/timetable?day=' + today)).days[0].action, 'closed')
        const history = await json('/classes/2/timetable/history')
        await json('/classes/2/timetable/history/' + history[0].id + '/restore', 101, 'POST')
        assert.equal((await json('/classes/2/timetable?day=' + today)).days[0].action, 'regular')
        assert((await json('/classes/2/timetable/editor')).slots.length > 0)
      })
      await test.step('settings, audit, system health and announcement confirmation remain functional', async () => {
        await json('/settings', 101, 'PUT', { school: 'Тестовая школа', timezone: 'Asia/Tashkent', system_name: 'Attendance' })
        assert.equal((await json('/settings')).school, 'Тестовая школа')
        assert((await json('/admin/audit-logs')).total > 0)
        assert((await json('/admin/users/' + userId + '/audit-logs')).total > 0)
        assert.equal((await json('/admin/system-health')).database.engine, 'postgresql')
        const announcement = { class_ids: [1], message: 'Тестовое объявление' }, preview = await json('/admin/announcements/preview', 101, 'POST', announcement)
        assert(preview.recipients > 0)
        await json('/admin/announcements', 101, 'POST', { ...announcement, confirmation: preview.confirmation, request_id: 'f'.repeat(32) }, 202)
        assert.equal((await json('/admin/announcements')).length, 1)
      })
      await test.step('Excel and protected download tickets preserve complete names while hiding present names', async () => {
        const path = '/classes/2/export?start=' + today + '&end=' + today
        const file = await send(path)
        const buffer = new Uint8Array(await file.arrayBuffer())
        const { default: ExcelJS } = await import('exceljs')
        const book = new ExcelJS.Workbook()
        await book.xlsx.load(buffer.buffer)
        const details = book.getWorksheet('Посещаемость')!
        const values: unknown[] = []
        details.eachRow(row => { values.push(row.values) })
        assert(JSON.stringify(values).includes(longName))
        assert(!JSON.stringify(values).includes('Тестовый Присутствующий'))
        const ticket = await json(path + '&ticket=true')
        const response = await api(new Request(ticket.path))
        assert.equal(response.status, 200)
        assert(response.headers.get('Content-Type')?.includes('spreadsheetml'))
        assert((await response.arrayBuffer()).byteLength > 1000)
        const backup = await json('/backup')
        assert.equal(backup.format, 'attendance-postgresql-json-v1')
        assert(backup.tables.users.some((row: Row) => row.telegram_id === userId))
      })
      await test.step('RLS and SQL privileges deny direct anonymous access to all Attendance data', async () => {
        const [permission] = await sql`SELECT has_table_privilege('anon','public.users','SELECT') AS allowed,
          (SELECT relrowsecurity FROM pg_class WHERE oid='public.users'::regclass) AS rls`
        assert.equal(permission.allowed, false)
        assert.equal(permission.rls, true)
      })
      await test.step('Telegram rate limits resume safely, unconfirmed sends stay uncertain, and revoked recipients stop multipart delivery', async () => {
        const failingApi = apiHandler({ ...testConfiguration, test: false }), failingCron = schedulerHandler({ ...testConfiguration, test: false })
        const originalFetch = globalThis.fetch
        let behavior = 'rate-limit', calls = 0
        globalThis.fetch = async input => {
          assert(String(input).startsWith('https://api.telegram.org/bot' + testToken + '/'))
          calls++
          if (behavior === 'rate-limit') { behavior = 'accepted'; return Response.json({ ok: false, error_code: 429, parameters: { retry_after: 1 } }, { status: 429 }) }
          if (behavior === 'timeout') throw new DOMException('Synthetic timeout', 'TimeoutError')
          if (behavior === 'revoke') await sql`UPDATE users SET blocked=true WHERE telegram_id=${userId}`
          return Response.json({ ok: true, result: { message_id: 700 + calls } })
        }
        const invoke = (classId: number, key: string) => failingApi(new Request('http://127.0.0.1:8109/api/v1/reports/send-now', {
          method: 'POST', headers: { Authorization: 'tma ' + signed(101), 'Content-Type': 'application/json' }, body: JSON.stringify({ class_id: classId, request_id: key }) }))
        const tick = () => failingCron(new Request('http://127.0.0.1/scheduler', { method: 'POST', headers: { Authorization: 'Bearer ' + testConfiguration.schedulerSecret } }))
        try {
          assert.equal((await (await invoke(1, '1'.repeat(32))).json()).pending, 1)
          await sql`UPDATE report_deliveries SET retry_at=timezone('UTC',now())-interval '1 second' WHERE dispatch_key=${'manual_' + '1'.repeat(32)}`
          assert.equal((await tick()).status, 200)
          const [resumed] = await sql`SELECT * FROM report_deliveries WHERE dispatch_key=${'manual_' + '1'.repeat(32)}`
          assert.equal(resumed.status, 'sent'); assert.equal(resumed.attempts, 2)
          behavior = 'timeout'
          assert.equal((await (await invoke(1, '2'.repeat(32))).json()).sent, 0)
          const before = calls
          assert.equal((await tick()).status, 200)
          assert.equal(calls, before)
          const [uncertain] = await sql`SELECT * FROM report_deliveries WHERE dispatch_key=${'manual_' + '2'.repeat(32)}`
          assert.equal(uncertain.status, 'uncertain'); assert.equal(uncertain.telegram_message_id, null)
          const longNames = Array.from({ length: 24 }, (_, index) => 'Тестовый ' + 'А'.repeat(230) + String.fromCharCode(0x410 + index))
          await json('/classes/2/students', 101, 'POST', { names: longNames.join('\n'), bulk: true })
          behavior = 'revoke'
          await invoke(2, '3'.repeat(32))
          const [cancelled] = await sql`SELECT * FROM report_deliveries WHERE dispatch_key=${'manual_' + '3'.repeat(32)}`
          assert.equal(cancelled.status, 'cancelled'); assert.equal(cancelled.parts_sent, 1); assert(cancelled.parts_total > 1)
        } finally {
          globalThis.fetch = originalFetch
          await sql`UPDATE users SET blocked=false WHERE telegram_id=${userId}`
          await Promise.all([failingApi.close(), failingCron.close()])
        }
      })
    } finally {
      await Promise.all([api.close(), webhook.close(), cron.close(), sql.end()])
    }
  },
})
