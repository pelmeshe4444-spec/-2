import { z } from 'zod'
import { HttpError } from './auth.ts'
import { AfterCommit, addDays, audit, body, type Configuration, type Context, date, id, localDay, one, owner,
  type Router, type Row, rows, scope, stamp, type Sql, weekday } from './core.ts'
import { counts, roster } from './attendance.ts'
import { telegram, TelegramError } from './telegram.ts'

export const reportKinds = [1, 2, 3, 4, 0]
export const reportLabels = ['Не отмечены', 'Присутствуют', 'Болеют', 'По уважительной причине', 'Отсутствуют без причины']
export const statusLabels = ['Не отмечен', 'Присутствует', 'Болеет', 'По уважительной причине', 'Отсутствует без причины']
const icons = ['⏳', '✅', '🤒', '📝', '❌']
const escape = (text: string): string => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
export function reportParts(className: string, day: string, entries: Row[], zone: string, now = new Date()): string[] {
  const header = `🏫 <b>ОТЧЁТ О ПОСЕЩАЕМОСТИ</b>\n\n📅 Дата: ${day.split('-').reverse().join('.')}\n🏷 Класс: ${escape(className)}`
  const totals = counts(entries), parts: string[] = []
  let current = header
  for (const status of reportKinds) {
    const students = entries.filter(row => row.status === status)
    const heading = status === 1 ? `${icons[status]} <b>${reportLabels[status].toUpperCase()}: ${students.length}</b>` :
      `${icons[status]} <b>${reportLabels[status].toUpperCase()} (${students.length}):</b>`
    const lines = status === 1 ? [] : students.length ? students.map((row, index) => `${index + 1}. ${escape(row.full_name)}`) : ['Нет']
    if ((current + '\n\n' + heading + '\n' + (lines[0] ?? '')).length > 3900) { parts.push(current); current = header + '\n<i>Продолжение</i>' }
    current += '\n\n' + heading
    for (const line of lines) {
      if ((current + '\n' + line).length > 3900) { parts.push(current); current = header + '\n<i>Продолжение</i>\n\n' + heading }
      current += '\n' + line
    }
  }
  const footer = `━━━━━━━━━━━━\n📊 <b>ИТОГО</b>\n👥 Всего учеников: ${entries.length}\n${reportKinds.map(status => `${icons[status]} ${reportLabels[status]}: ${totals[status]}`).join('\n')}\n🕒 Отчёт сформирован: ${new Intl.DateTimeFormat('en-GB', { timeZone: zone, hour: '2-digit', minute: '2-digit' }).format(now)}`
  if ((current + '\n' + footer).length > 3900) { parts.push(current); current = header + '\n<i>Продолжение</i>' }
  return [...parts, current + '\n' + footer]
}
export function safeParts(parts: string[]): string[] {
  return parts.map(part => {
    let present = false, names = false
    return part.split('\n').flatMap(line => {
      if (/<b>.*(?:Присутствуют|ПРИСУТСТВУЮТ)/.test(line)) { present = true; names = true }
      else if (/<b>.*(?:Болеют|БОЛЕЮТ|По уважительной|ПО УВАЖИТЕЛЬНОЙ|Отсутствуют|ОТСУТСТВУЮТ|Не отмечены|НЕ ОТМЕЧЕНЫ)/.test(line)) { present = false; names = true }
      if (names && /^\d+\. /.test(line)) return present ? [] : [line.split(' — ')[0]]
      return [line]
    }).join('\n')
  })
}
export const plainParts = (parts: string[]): string[] => safeParts(parts).map(part => part.replace(/<\/?(?:b|i)>/g, '').replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&amp;', '&'))
export function due(schedule: Row, key: string, day: string, now: Date): boolean {
  if (!schedule.is_enabled || schedule.deleted || !schedule.weekdays.includes(String(weekday(day)))) return false
  const today = localDay(schedule.timezone, now)
  const time = new Intl.DateTimeFormat('en-GB', { timeZone: schedule.timezone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(now)
  const difference = (Date.parse(today) - Date.parse(day)) / 60000 + Number(time.slice(0, 2)) * 60 + Number(time.slice(3)) - Number(schedule.time.slice(0, 2)) * 60 - Number(schedule.time.slice(3))
  if (key === 'scheduled') return difference >= 0 && difference <= 18 * 60
  const at = schedule[key]
  const later = [schedule.reminder_one, schedule.reminder_two, schedule.time].filter(value => value && value > at).sort()[0] ?? schedule.time
  return day === today && !!at && time >= at && time < later
}
function viewSchedule(row: Row): Row {
  return { time: row.time, timezone: row.timezone, weekdays: [...row.weekdays].map(Number), enabled: row.is_enabled,
    reminder_one: row.reminder_one, reminder_two: row.reminder_two, deleted: row.deleted }
}
async function deliver(sql: Sql, config: Configuration, deliveryId: number, deadline: number): Promise<void> {
  const delivery = await one(sql, `SELECT d.*,s.class_id FROM report_deliveries d JOIN report_schedules s ON s.id=d.schedule_id WHERE d.id=$1`, [deliveryId])
  if (!delivery || delivery.status !== 'sending' || !delivery.body) return
  const parts = safeParts(JSON.parse(delivery.body))
  let sent = delivery.parts_sent, status = 'sent', error: string | null = null, retrySeconds = 0, messageId: number | null = delivery.telegram_message_id
  for (const part of parts.slice(sent)) {
    if (Date.now() > deadline) { status = 'retry'; error = 'Отправка продолжится планировщиком.'; retrySeconds = 60; break }
    const target = await one(sql, `SELECT u.*,c.is_active AS active_class FROM users u JOIN classes c ON c.id=$2
      JOIN ${delivery.dispatch_key.startsWith('reminder_') ? 'manager_assignments' : 'report_recipients'} a ON a.user_id=u.id AND a.class_id=c.id WHERE u.id=$1`, [delivery.recipient_id, delivery.class_id])
    if (!target || target.blocked || !target.started_at || !target.active_class) { status = 'cancelled'; error = 'Права получателя отозваны.'; break }
    if (delivery.initiated_by) {
      const actor = await one(sql, `SELECT u.*,m.can_send_reports FROM users u LEFT JOIN manager_assignments m ON m.user_id=u.id AND m.class_id=$2 WHERE u.id=$1`, [delivery.initiated_by, delivery.class_id])
      if (!actor || (actor.telegram_id !== config.ownerId && (actor.blocked || !actor.can_send_reports))) { status = 'cancelled'; error = 'Право на ручную отправку отозвано.'; break }
    }
    try {
      const message = await telegram(config, 'sendMessage', { chat_id: target.telegram_id, text: part, parse_mode: 'HTML', protect_content: true })
      if (!Number.isSafeInteger(message.message_id) || message.message_id <= 0) { status = 'uncertain'; error = 'Telegram не вернул идентификатор сообщения.'; break }
      messageId = message.message_id; sent++
      await rows(sql, 'UPDATE report_deliveries SET parts_sent=$1,telegram_message_id=$2 WHERE id=$3', [sent, messageId, deliveryId])
    } catch (failure) {
      if (failure instanceof TelegramError && failure.uncertain) { status = 'uncertain'; error = 'Telegram не подтвердил приём запроса.' }
      else if (failure instanceof TelegramError && failure.code === 429) { status = 'retry'; error = 'Превышен лимит Telegram.'; retrySeconds = Math.max(120, failure.retryAfter) }
      else { status = 'failed'; error = failure instanceof TelegramError && failure.code === 403 ? 'Бот заблокирован или чат недоступен.' : 'Telegram отклонил запрос.' }
      break
    }
  }
  if (status === 'retry' && error !== 'Отправка продолжится планировщиком.' && (delivery.attempts >= 3 || retrySeconds > 7200)) status = 'failed'
  await sql.begin(async db => {
    await rows(db, `UPDATE report_deliveries SET status=$1::text,error_message=$2,parts_sent=$3,telegram_message_id=$4,
      sent_at=CASE WHEN $1='sent' THEN timezone('UTC',now()) ELSE sent_at END,
      retry_at=CASE WHEN $1='retry' THEN timezone('UTC',now())+$5::int*interval '1 second' END,
      body=CASE WHEN $1 IN ('sent','retry') THEN body END WHERE id=$6`, [status, error, sent, messageId, retrySeconds, deliveryId])
    await audit(db, null, 'delivery.' + status, 'delivery', deliveryId, `parts=${sent}/${parts.length}`)
    if (status === 'sent') await rows(db, `UPDATE report_deliveries old SET body=null WHERE old.schedule_id=$1 AND old.recipient_id=$2 AND old.status='sent' AND old.body IS NOT NULL
      AND (old.report_date<$3::date-89 OR EXISTS(SELECT 1 FROM report_deliveries newer WHERE newer.schedule_id=old.schedule_id AND newer.recipient_id=old.recipient_id
      AND newer.status='sent' AND newer.report_date=old.report_date AND newer.id>old.id))`, [delivery.schedule_id, delivery.recipient_id, delivery.report_date])
  })
  console.info('report_delivery completed', { status, parts_sent: sent, parts_total: parts.length })
}
export async function dispatch(sql: Sql, config: Configuration, scheduleId: number, day: string, key: string, initiator?: number, deadline = Date.now() + 90000): Promise<Row> {
  const claimed = await sql.begin(async db => {
    await db`SELECT pg_advisory_xact_lock(1724810925)`
    const schedule = await one(db, 'SELECT s.*,c.name,c.is_active AS active_class FROM report_schedules s JOIN classes c ON c.id=s.class_id WHERE s.id=$1', [scheduleId])
    if (!schedule?.active_class) return []
    let actor
    if (initiator != null) {
      actor = await one(db, `SELECT u.*,m.can_send_reports FROM users u LEFT JOIN manager_assignments m ON m.user_id=u.id AND m.class_id=$2 WHERE u.telegram_id=$1`, [initiator, schedule.class_id])
      if (!actor || (initiator !== config.ownerId && (actor.blocked || !actor.can_send_reports || day !== localDay(schedule.timezone)))) throw new HttpError(403, 'Доступ ограничен.')
      if (await one(db, 'SELECT 1 FROM report_deliveries WHERE schedule_id=$1 AND dispatch_key=$2 LIMIT 1', [scheduleId, key])) return []
    } else if (!due(schedule, key, day, new Date())) return []
    const reminder = key.startsWith('reminder_')
    const entries = await roster(db, schedule.class_id, day)
    if (reminder && !counts(entries)[0]) return []
    const time = new Intl.DateTimeFormat('en-GB', { timeZone: schedule.timezone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date())
    const remaining = Math.max(1, Number(schedule.time.slice(0, 2)) * 60 + Number(schedule.time.slice(3)) - Number(time.slice(0, 2)) * 60 - Number(time.slice(3)))
    const parts = reminder ? [`🔔 <b>Напоминание</b>\n🏷 Класс: ${escape(schedule.name)}\nДо отправки отчёта: ${remaining} мин.\nОсталось отметить: ${counts(entries)[0]}.`] : reportParts(schedule.name, day, entries, schedule.timezone)
    const claims = await rows(db, `INSERT INTO report_deliveries(schedule_id,recipient_id,initiated_by,report_date,dispatch_key,status,parts_sent,parts_total,body,attempts)
      SELECT $1,u.id,$2,$3,$4,'sending',0,$5,$6,1 FROM users u
      JOIN ${reminder ? 'manager_assignments' : 'report_recipients'} a ON a.user_id=u.id
      WHERE a.class_id=$7 AND u.started_at IS NOT NULL AND NOT u.blocked
      ON CONFLICT(schedule_id,recipient_id,report_date,dispatch_key) DO NOTHING RETURNING id`,
      [scheduleId, actor?.id ?? null, day, key, parts.length, JSON.stringify(parts), schedule.class_id])
    return claims.map(row => row.id as number)
  })
  for (let index = 0; index < claimed.length; index++) {
    if (Date.now() > deadline) {
      await rows(sql, `UPDATE report_deliveries SET status='retry',retry_at=timezone('UTC',now())+interval '1 minute',
        error_message='Отправка продолжится планировщиком.' WHERE id=ANY($1::int[]) AND status='sending' AND parts_sent=0`, [claimed.slice(index)])
      break
    }
    await deliver(sql, config, claimed[index], deadline)
  }
  const states = await rows(sql, 'SELECT status,count(*) AS n FROM report_deliveries WHERE schedule_id=$1 AND dispatch_key=$2 AND report_date=$3 GROUP BY status', [scheduleId, key, day])
  return { sent: states.find(row => row.status === 'sent')?.n ?? 0, total: states.reduce((total, row) => total + row.n, 0),
    pending: states.filter(row => ['sending', 'retry'].includes(row.status)).reduce((total, row) => total + row.n, 0) }
}
export async function scheduler(sql: Sql, config: Configuration): Promise<void> {
  const deadline = Date.now() + 90000
  await rows(sql, `UPDATE report_deliveries SET status='uncertain',body=null,error_message='Отправка была прервана, доставка не подтверждена.'
    WHERE status='sending' AND coalesce(retry_at,created_at)<timezone('UTC',now())-interval '15 minutes'`)
  const retry = await rows(sql, `SELECT d.*,s.class_id,s.is_enabled,s.deleted FROM report_deliveries d JOIN report_schedules s ON s.id=d.schedule_id
    WHERE d.status='retry' AND d.retry_at<=timezone('UTC',now()) ORDER BY d.retry_at LIMIT 30`)
  for (const row of retry) {
    const fresh = new Date(row.created_at + 'Z').getTime() > Date.now() - 18 * 3600000
    if ((!row.dispatch_key.startsWith('manual_') && (!row.is_enabled || row.deleted)) || !fresh || !row.body) {
      await rows(sql, "UPDATE report_deliveries SET status='cancelled',body=null,error_message='Срок отправки истёк или расписание отключено.' WHERE id=$1 AND status='retry'", [row.id]); continue
    }
    if (row.dispatch_key.startsWith('reminder_')) {
      const plan = (await one(sql, 'SELECT * FROM report_schedules WHERE id=$1', [row.schedule_id]))!
      if (!due(plan, row.dispatch_key, row.report_date, new Date())) {
        await rows(sql, "UPDATE report_deliveries SET status='cancelled',body=null WHERE id=$1 AND status='retry'", [row.id]); continue
      }
    }
    const claim = await one(sql, `UPDATE report_deliveries SET status='sending',attempts=attempts+CASE WHEN error_message='Отправка продолжится планировщиком.' THEN 0 ELSE 1 END,
      retry_at=timezone('UTC',now()) WHERE id=$1 AND status='retry' RETURNING id`, [row.id])
    if (claim) await deliver(sql, config, row.id, deadline)
    if (Date.now() > deadline) break
  }
  for (const plan of await rows(sql, 'SELECT * FROM report_schedules WHERE is_enabled AND NOT deleted ORDER BY id')) {
    if (Date.now() > deadline) break
    const today = localDay(plan.timezone)
    for (const key of ['reminder_one', 'reminder_two', 'scheduled']) {
      if (due(plan, key, today, new Date())) await dispatch(sql, config, plan.id, today, key, undefined, deadline)
    }
    const previous = addDays(today, -1)
    if (due(plan, 'scheduled', previous, new Date())) await dispatch(sql, config, plan.id, previous, 'scheduled', undefined, deadline)
  }
  await rows(sql, "INSERT INTO system_events(operation,success) VALUES('scheduler',true)")
  await rows(sql, 'DELETE FROM api_rate_limits WHERE expires_at<now()')
  await rows(sql, 'DELETE FROM download_tickets WHERE expires_at<now()')
}
export function reportRoutes(router: Router): void {
  router.add('GET', '/classes/:classId/schedule', async context => {
    owner(context); const classId = id(context.params.classId); await scope(context, classId)
    return viewSchedule((await one(context.db, 'SELECT * FROM report_schedules WHERE class_id=$1', [classId]))!)
  })
  router.add('PUT', '/classes/:classId/schedule', async context => {
    owner(context); const classId = id(context.params.classId); await scope(context, classId)
    const clock = z.string().regex(/^(?:[01]\d|2[0-3]):[0-5]\d$/)
    const input = await body(context, z.object({ time: clock, timezone: z.string().min(1).max(64), weekdays: z.array(z.number().int().min(0).max(6)).min(1).max(7),
      enabled: z.boolean(), reminder_one: clock.nullish(), reminder_two: clock.nullish() }).strict())
    try { localDay(input.timezone) } catch { throw new HttpError(400, 'Укажите часовой пояс IANA.') }
    const reminders = [input.reminder_one, input.reminder_two].filter(Boolean) as string[]
    if (new Set(reminders).size !== reminders.length || reminders.some(value => value >= input.time)) throw new HttpError(400, 'Напоминания должны быть в разное время и раньше отчёта.')
    const schedule = (await one(context.db, `UPDATE report_schedules SET time=$1,timezone=$2,weekdays=$3,is_enabled=$4,reminder_one=$5,reminder_two=$6,deleted=false WHERE class_id=$7 RETURNING *`,
      [input.time, input.timezone, [...new Set(input.weekdays)].sort().join(''), input.enabled, input.reminder_one ?? null, input.reminder_two ?? null, classId]))!
    await audit(context.db, context.user, 'schedule.updated', 'schedule', schedule.id)
    return viewSchedule(schedule)
  })
  router.add('DELETE', '/classes/:classId/schedule', async context => {
    owner(context); const classId = id(context.params.classId); await scope(context, classId)
    const row = (await one(context.db, "UPDATE report_schedules SET deleted=true,is_enabled=false,time='08:30',weekdays='01234',timezone=$1,reminder_one=null,reminder_two=null WHERE class_id=$2 RETURNING *", [context.preferences.timezone, classId]))!
    await audit(context.db, context.user, 'schedule.deleted', 'schedule', row.id)
    return viewSchedule(row)
  })
  for (const current of [false, true]) router.add('POST', current ? '/reports/send-now' : '/classes/:classId/send', async context => {
    const requestId = z.string().regex(/^[a-f0-9]{32}$/)
    const input = current ? await body(context, z.object({ class_id: z.number().int().positive(), request_id: requestId }).strict()) :
      await body(context, z.object({ request_id: requestId, day: z.string().nullable().optional() }).strict())
    const classId = current ? id('class_id' in input ? input.class_id : undefined) : id(context.params.classId)
    if (!current) owner(context)
    await scope(context, classId, 'send')
    const day = 'day' in input && input.day ? date(input.day) : context.today
    if (day > context.today || (context.identity.id !== context.config.ownerId && day !== context.today)) throw new HttpError(400, 'Нельзя отправить отчёт за выбранную дату.')
    const schedule = (await one(context.db, 'SELECT id FROM report_schedules WHERE class_id=$1', [classId]))!
    return new AfterCommit(() => dispatch(context.sql, context.config, schedule.id, day, 'manual_' + input.request_id, context.identity.id))
  })
  router.add('GET', '/classes/:classId/reports/last-manual', async context => {
    const classId = id(context.params.classId); await scope(context, classId, 'send')
    const latest = await one(context.db, `SELECT max(d.sent_at) AS stamp FROM report_deliveries d JOIN report_schedules s ON s.id=d.schedule_id WHERE s.class_id=$1 AND d.status='sent' AND d.dispatch_key LIKE 'manual_%'`, [classId])
    return { sent_at: stamp(latest?.stamp) }
  })
  router.add('GET', '/classes/:classId/deliveries', async context => {
    owner(context); const classId = id(context.params.classId); await scope(context, classId, 'manage', true)
    const total = Number((await one(context.db, 'SELECT count(*) AS n FROM report_deliveries d JOIN report_schedules s ON s.id=d.schedule_id WHERE s.class_id=$1', [classId]))!.n)
    const page = Math.min(Math.max(0, Number(context.url.searchParams.get('page')) || 0), Math.max(0, Math.ceil(total / 20) - 1))
    const items = await rows(context.db, `SELECT d.*,u.telegram_id,a.telegram_id AS sender_id,a.full_name AS sender_name FROM report_deliveries d
      JOIN report_schedules s ON s.id=d.schedule_id JOIN users u ON u.id=d.recipient_id LEFT JOIN users a ON a.id=d.initiated_by
      WHERE s.class_id=$1 ORDER BY d.id DESC OFFSET $2 LIMIT 20`, [classId, page * 20])
    return { page, total, items: items.map(row => ({ id: row.id, day: row.report_date, telegram_id: row.telegram_id, status: row.status,
      time: stamp(row.sent_at ?? row.created_at), error: row.error_message, sent_at: stamp(row.sent_at), initiated_by: row.sender_id,
      initiated_by_name: row.sender_name, telegram_message_id: row.telegram_message_id, parts_sent: row.parts_sent, parts_total: row.parts_total,
      kind: row.dispatch_key.startsWith('manual_') ? 'manual' : row.dispatch_key.startsWith('reminder_') ? 'reminder' : 'scheduled' })) }
  })
  router.add('GET', '/classes/:classId/report', async context => {
    const classId = id(context.params.classId); const school = await scope(context, classId, 'report', context.identity.id === context.config.ownerId)
    const manager = await one(context.db, 'SELECT can_view_reports FROM manager_assignments WHERE user_id=$1 AND class_id=$2', [context.user.id, classId])
    if (context.identity.id === context.config.ownerId || manager?.can_view_reports) {
      const day = date(context.url.searchParams.get('day') || context.today)
      if (day > context.today) throw new HttpError(400, 'Дата ещё не наступила.')
      const entries = school.archived_on && day > school.archived_on ? [] : await roster(context.db, classId, day)
      return { day, dates: [], parts: plainParts(reportParts(school.name, day, entries, context.preferences.timezone)) }
    }
    const available = await rows(context.db, `SELECT d.report_date,d.body FROM report_deliveries d JOIN report_schedules s ON s.id=d.schedule_id
      WHERE s.class_id=$1 AND d.recipient_id=$2 AND d.status='sent' AND d.body IS NOT NULL AND d.dispatch_key NOT LIKE 'reminder_%'
      ORDER BY d.report_date DESC,d.id DESC LIMIT 90`, [classId, context.user.id])
    const dates = [...new Set(available.map(row => row.report_date))], day = context.url.searchParams.get('day') || dates[0] || null
    const selected = available.find(row => row.report_date === day)
    return { day, dates, parts: selected ? plainParts(JSON.parse(selected.body)) : [] }
  })
}
