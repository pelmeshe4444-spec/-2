import { hex, HttpError } from './auth.ts'
import { audit, type Context, date, id, one, owner, type Router, type Row, rows, scope, storage } from './core.ts'
import { counts, periodRoster } from './attendance.ts'
import { reportKinds, reportLabels, statusLabels } from './reports.ts'
import { workbook } from './xlsx.ts'

const backupTables = ['alembic_version', 'announcements', 'attendance', 'attendance_history', 'audit_logs', 'class_join_requests',
  'class_memberships', 'class_timetables', 'classes', 'enrollments', 'lesson_time_slots', 'manager_assignments', 'notifications',
  'report_deliveries', 'report_recipients', 'report_schedules', 'school_settings', 'students', 'subjects', 'system_events',
  'timetable_change_history', 'timetable_exceptions', 'timetable_lessons', 'user_roles', 'users',
  'api_rate_limits', 'download_tickets', 'telegram_updates', 'background_leases']
async function excel(context: Context, payload: Row): Promise<Response> {
  const school = await scope(context, payload.class_id, 'manage', true)
  const byDay = await periodRoster(context, payload.class_id, payload.start, payload.end)
  const details: (string | number | null)[][] = [['Дата', 'Класс', 'Ученик', 'Статус', 'Количество']]
  const summary: (string | number | null)[][] = [['Дата', 'Всего', ...reportKinds.map(kind => reportLabels[kind])]]
  for (const [day, entries] of byDay) {
    const totals = counts(entries)
    summary.push([day, entries.length, ...reportKinds.map(kind => totals[kind])])
    details.push([day, school.name, null, statusLabels[1], totals[1]])
    for (const entry of entries) if (entry.status !== 1) details.push([day, school.name, entry.full_name, statusLabels[entry.status], 1])
  }
  const data = workbook([{ name: 'Посещаемость', widths: [15, 22, 65, 33, 17], rows: details },
    { name: 'Сводка', widths: [15, 12, 20, 14, 32, 32, 18], rows: summary }])
  await audit(context.db, context.user, 'statistics.exported', 'class', payload.class_id)
  return new Response(new Uint8Array(data).buffer, { headers: { 'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'Content-Disposition': `attachment; filename="${payload.name}"` } })
}
async function backup(context: Context, name: string): Promise<Response> {
  const tables: Row = {}
  for (const table of backupTables) tables[table] = await rows(context.db, 'SELECT * FROM ' + table)
  const sequences: Row = {}
  for (const sequence of await rows(context.db, "SELECT sequencename FROM pg_sequences WHERE schemaname='public'")) {
    if (!/^[a-z_]+$/.test(sequence.sequencename)) throw new HttpError(503, 'Не удалось проверить структуру резервной копии.')
    sequences[sequence.sequencename] = await one(context.db, 'SELECT last_value,is_called FROM public.' + sequence.sequencename)
  }
  const data = JSON.stringify({ format: 'attendance-postgresql-json-v1', created_at: new Date().toISOString(), tables, sequences })
  if (!context.config.test) {
    const { error } = await storage(context.config).storage.from('attendance-backups').upload(
      `manual/${context.today}/${crypto.randomUUID()}.json`, new Blob([data], { type: 'application/json' }), { upsert: false })
    if (error) throw new HttpError(503, 'Не удалось сохранить защищённую резервную копию. Повторите загрузку.')
  }
  return new Response(data, {
    headers: { 'Content-Type': 'application/json', 'Content-Disposition': `attachment; filename="${name}"` } })
}
async function file(context: Context, payload: Row): Promise<Response | Row> {
  if (context.url.searchParams.get('ticket') === 'true') {
    const active = await one(context.db, 'SELECT count(*) AS n FROM download_tickets WHERE owner_id=$1 AND expires_at>now()', [context.user.id])
    if (Number(active!.n) >= 3) throw new HttpError(429, 'Подождите завершения предыдущих загрузок.')
    const key = hex(crypto.getRandomValues(new Uint8Array(24))), digest = hex(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(key))))
    await rows(context.db, `INSERT INTO download_tickets(key_hash,owner_id,expires_at,payload) VALUES($1,$2,now()+interval '90 seconds',$3::jsonb)`, [digest, context.user.id, payload])
    return { path: context.config.projectUrl + '/functions/v1/' + context.config.apiName + '/api/v1/downloads/' + key, name: payload.name }
  }
  return payload.format === 'xlsx' ? excel(context, payload) : backup(context, payload.name)
}
export async function ticketDownload(context: Context, key: string): Promise<Response> {
  if (!/^[a-f0-9]{48}$/.test(key)) throw new HttpError(404, 'Ссылка недоступна.')
  const digest = hex(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(key))))
  const ticket = await one(context.db, `SELECT t.*,row_to_json(u) AS actor FROM download_tickets t JOIN users u ON u.id=t.owner_id
    WHERE t.key_hash=$1 AND t.expires_at>now() AND u.telegram_id=$2`, [digest, context.config.ownerId])
  if (!ticket) throw new HttpError(404, 'Срок действия ссылки истёк.')
  context.user = ticket.actor
  context.identity = { id: ticket.actor.telegram_id, name: ticket.actor.full_name, username: ticket.actor.username }
  const response = ticket.payload.format === 'xlsx' ? await excel(context, ticket.payload) : await backup(context, ticket.payload.name)
  return context.request.method === 'HEAD' ? new Response(null, { headers: response.headers }) : response
}
export function exportRoutes(router: Router): void {
  router.add('GET', '/classes/:classId/export', async context => {
    owner(context); const classId = id(context.params.classId); await scope(context, classId, 'manage', true)
    return file(context, { format: 'xlsx', class_id: classId, start: date(context.url.searchParams.get('start') || ''),
      end: date(context.url.searchParams.get('end') || ''), name: 'attendance-' + classId + '.xlsx' })
  })
  router.add('GET', '/backup', async context => { owner(context); return file(context, { format: 'json', name: 'attendance-backup-' + context.today + '.json' }) })
}
