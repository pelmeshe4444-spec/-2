import { z } from 'zod'
import { hex, hmac, HttpError } from './auth.ts'
import { AfterCommit, addDays, audit, body, bounded, type Context, id, localDay, one, owner, profile,
  type Router, type Row, rows, stamp } from './core.ts'
import { flushNotices, telegram } from './telegram.ts'

async function auditPage(context: Context, userId?: number, size = 20): Promise<Row> {
  owner(context)
  const predicate = userId == null ? 'true' : "a.entity_type='user' AND a.entity_id=$1"
  const values = userId == null ? [] : [userId]
  const total = Number((await one(context.db, `SELECT count(*) AS n FROM audit_logs a WHERE ${predicate}`, values))!.n)
  const page = Math.min(Math.max(0, Number(context.url.searchParams.get('page')) || 0), Math.max(0, Math.ceil(total / size) - 1))
  const result = await rows(context.db, `SELECT a.*,u.telegram_id FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id WHERE ${predicate}
    ORDER BY a.id DESC OFFSET $${values.length + 1} LIMIT $${values.length + 2}`, [...values, page * size, size])
  return { page, total, items: result.map(row => ({ id: row.id, action: row.action, by: row.telegram_id, time: stamp(row.timestamp),
    entity: row.entity_type, entity_id: row.entity_id, details: row.details })) }
}
async function dailyCounts(context: Context, day: string): Promise<number[]> {
  const grouped = await rows(context.db, `SELECT coalesce(a.status,0) AS status,count(*) AS n FROM enrollments e
    JOIN classes c ON c.id=e.class_id AND c.is_active LEFT JOIN attendance a ON a.student_id=e.student_id AND a.date=$1
    WHERE e.starts_on<=$1 AND (e.ends_before IS NULL OR e.ends_before>$1) GROUP BY coalesce(a.status,0)`, [day])
  return [0, 1, 2, 3, 4].map(index => grouped.find(row => row.status === index)?.n ?? 0)
}
async function announcementAudience(context: Context, classIds: number[], message: string): Promise<Row> {
  const classes = [...new Set(classIds)].sort((a, b) => a - b)
  const available = await rows(context.db, 'SELECT id FROM classes WHERE is_active AND id=ANY($1::int[])', [classes])
  if (available.length !== classes.length) throw new HttpError(400, 'Выберите действующие классы.')
  const recipients = (await rows(context.db, `SELECT u.id FROM users u WHERE u.started_at IS NOT NULL AND NOT u.blocked AND u.id IN
    (SELECT user_id FROM class_memberships WHERE class_id=ANY($1::int[]) UNION SELECT user_id FROM manager_assignments WHERE class_id=ANY($1::int[])
    UNION SELECT user_id FROM report_recipients WHERE class_id=ANY($1::int[])) ORDER BY u.id`, [classes])).map(row => row.id)
  const confirmation = hex(await hmac(new TextEncoder().encode(context.config.token), JSON.stringify([classes, message, recipients])))
  return { classes, recipients, confirmation }
}

export function adminRoutes(router: Router): void {
  for (const path of ['/audit', '/admin/audit-logs']) router.add('GET', path, context => auditPage(context))
  router.add('GET', '/admin/users/:target/audit-logs', async context => {
    owner(context); const user = await one(context.db, 'SELECT id FROM users WHERE telegram_id=$1', [id(context.params.target)])
    if (!user) throw new HttpError(404, 'Пользователь недоступен.')
    return auditPage(context, user.id)
  })
  router.add('GET', '/admin/dashboard', async context => {
    owner(context)
    const metrics = (await one(context.db, `SELECT (SELECT count(*) FROM students s JOIN classes c ON c.id=s.class_id WHERE c.is_active AND s.is_active) AS students,
      (SELECT count(*) FROM classes WHERE is_active) AS classes,(SELECT count(*) FROM class_join_requests WHERE status='PENDING') AS pending_requests,
      (SELECT count(DISTINCT a.user_id) FROM manager_assignments a JOIN users u ON u.id=a.user_id JOIN classes c ON c.id=a.class_id WHERE NOT u.blocked AND c.is_active) AS managers,
      (SELECT count(*) FROM report_deliveries WHERE status='sent' AND dispatch_key NOT LIKE 'reminder_%' AND
      (sent_at AT TIME ZONE 'UTC' AT TIME ZONE $1)::date=$2) AS sent_reports`, [context.preferences.timezone, context.today]))!
    const trend = []
    if (context.preferences.dashboard_chart) for (let offset = 6; offset >= 0; offset--) {
      const day = addDays(context.today, -offset); trend.push({ day, counts: await dailyCounts(context, day) })
    }
    return { ...metrics, school: context.preferences.school, system_name: context.preferences.system_name, today: context.today, backend: 'ok',
      attendance: await dailyCounts(context, context.today), trend, recent_actions: (await auditPage(context, undefined, 6)).items }
  })
  router.add('GET', '/admin/system-health', async context => {
    owner(context)
    const checked = new Date().toISOString()
    const success = await one(context.db, "SELECT occurred_at FROM system_events WHERE operation='scheduler' AND success ORDER BY id DESC LIMIT 1")
    const latest = await one(context.db, "SELECT * FROM report_deliveries WHERE dispatch_key NOT LIKE 'reminder_%' ORDER BY id DESC LIMIT 1")
    const errors = await rows(context.db, 'SELECT * FROM system_events WHERE NOT success ORDER BY id DESC LIMIT 10')
    return new AfterCommit(async () => {
      let webhook: Row
      try {
        const info = await telegram(context.config, 'getWebhookInfo')
        webhook = { state: !info.url ? 'not_registered' : info.url !== context.config.projectUrl + '/functions/v1/telegram-webhook' ? 'unexpected' : info.last_error_date ? 'error' : 'ok',
          checked_at: checked, pending: info.pending_update_count, last_error_at: info.last_error_date ? new Date(info.last_error_date * 1000).toISOString() : null }
      } catch { webhook = { state: 'unavailable', checked_at: checked } }
      return { backend: 'ok', checked_at: checked, database: { engine: 'postgresql', state: 'ok' }, webhook,
        last_scheduler_success: stamp(success?.occurred_at), last_report: latest ? { status: latest.status, time: stamp(latest.sent_at ?? latest.created_at) } : null,
        recent_errors: errors.map(row => ({ source: row.operation, time: stamp(row.occurred_at) })) }
    })
  })
  router.add('GET', '/settings', async context => { owner(context); return context.preferences })
  router.add('PUT', '/settings', async context => {
    owner(context)
    const clock = z.string().regex(/^(?:[01]\d|2[0-3]):[0-5]\d$/)
    const input = await body(context, z.object({ school: z.string().min(1).max(120), system_name: z.string().min(1).max(40).optional(), timezone: z.string().min(1).max(64).optional(),
      school_days: z.array(z.number().int().min(0).max(6)).min(1).max(7).optional(), join_open: z.boolean().optional(), join_retry_days: z.number().int().min(0).max(90).optional(),
      notify_owner: z.boolean().optional(), notify_schedule: z.boolean().optional(), lesson_start: clock.optional(), lesson_minutes: z.number().int().min(15).max(120).optional(),
      report_time: clock.optional(), dashboard_chart: z.boolean().optional(), statistics_days: z.union([z.literal(1), z.literal(7), z.literal(30)]).optional() }).strict())
    if (input.timezone) try { localDay(input.timezone) } catch { throw new HttpError(400, 'Укажите часовой пояс IANA.') }
    const preferences: Row = { ...context.preferences, ...input }
    if (input.school_days) preferences.school_days = [...new Set(input.school_days)].sort()
    if (Number(preferences.lesson_start.slice(0, 2)) * 60 + Number(preferences.lesson_start.slice(3)) + preferences.lesson_minutes >= 1440) throw new HttpError(400, 'Урок должен закончиться в тот же календарный день.')
    const name = bounded(input.school, 120)
    delete preferences.school
    await rows(context.db, 'INSERT INTO school_settings(id,name,preferences) VALUES(1,$1,$2::json) ON CONFLICT(id) DO UPDATE SET name=excluded.name,preferences=excluded.preferences', [name, preferences])
    await audit(context.db, context.user, 'settings.updated', 'school')
    return { ...preferences, school: name }
  })
  const announcement = z.object({ class_ids: z.array(z.number().int().positive()).min(1).max(100), message: z.string().min(1).max(500) }).strict()
  router.add('GET', '/admin/announcements', async context => {
    owner(context)
    const result = []
    for (const row of await rows(context.db, 'SELECT * FROM announcements ORDER BY id DESC LIMIT 30')) {
      const statuses = await rows(context.db, 'SELECT status,count(*) AS n FROM notifications WHERE announcement_id=$1 GROUP BY status', [row.id])
      result.push({ id: row.id, message: row.message, class_ids: row.class_ids, time: stamp(row.created_at), statuses: Object.fromEntries(statuses.map(value => [value.status, value.n])) })
    }
    return result
  })
  router.add('POST', '/admin/announcements/preview', async context => {
    owner(context); const input = await body(context, announcement)
    const audience = await announcementAudience(context, input.class_ids, bounded(input.message, 500))
    return { recipients: audience.recipients.length, confirmation: audience.confirmation }
  })
  router.add('POST', '/admin/announcements', async context => {
    owner(context)
    const input = await body(context, announcement.extend({ confirmation: z.string().regex(/^[a-f0-9]{64}$/), request_id: z.string().regex(/^[a-f0-9]{32}$/) }).strict())
    const message = bounded(input.message, 500), classIds = [...new Set(input.class_ids)].sort((a, b) => a - b)
    const previous = await one(context.db, 'SELECT * FROM announcements WHERE request_id=$1', [input.request_id])
    if (previous) {
      if (JSON.stringify(previous.class_ids) !== JSON.stringify(classIds) || previous.message !== message) throw new HttpError(409, 'Этот запрос уже использован для другого объявления.')
      return Response.json({ id: previous.id }, { status: 202 })
    }
    const audience = await announcementAudience(context, classIds, message)
    if (audience.confirmation !== input.confirmation) throw new HttpError(409, 'Состав получателей или текст изменился. Выполните новый предпросмотр.')
    if (!audience.recipients.length || audience.recipients.length > 2000) throw new HttpError(400, 'Для одной отправки выберите от 1 до 2000 зарегистрированных получателей.')
    const row = (await one(context.db, 'INSERT INTO announcements(request_id,class_ids,message) VALUES($1,$2::json,$3) RETURNING id', [input.request_id, classIds, message]))!
    await rows(context.db, `INSERT INTO notifications(announcement_id,recipient_id,category,message,status)
      SELECT $1,recipient,'announcement',$2,'pending' FROM unnest($3::int[]) recipient`, [row.id, message, audience.recipients])
    await audit(context.db, context.user, 'announcement.queued', 'announcement', row.id, `recipients=${audience.recipients.length}`)
    context.effects.push(() => flushNotices(context.sql, context.config, 30))
    return Response.json({ id: row.id }, { status: 202 })
  })
}
