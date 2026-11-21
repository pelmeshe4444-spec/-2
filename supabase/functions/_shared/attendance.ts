import { z } from 'zod'
import { HttpError } from './auth.ts'
import { addDays, audit, body, type Context, date, id, one, owner, period, type Router, type Row, rows,
  schoolView, scope, stamp, studentView, type Transaction } from './core.ts'

export function counts(entries: Row[]): number[] {
  const result = [0, 0, 0, 0, 0]
  for (const row of entries) result[row.status ?? 0]++
  return result
}
function version(value: string | null): string {
  if (!value) return ''
  const text = value.replace(' ', 'T').replace(/Z$/, '')
  return text.includes('.') ? text.split('.')[0] + '.' + text.split('.')[1].padEnd(6, '0') : text
}
export const markView = (entry: Row) => ({ id: entry.id, name: entry.full_name, status: entry.status ?? 0, reason: entry.reason ?? null,
  version: version(entry.mark_updated_at), updated_at: stamp(entry.mark_updated_at), author: entry.author ?? null })
export async function roster(db: Transaction, classId: number, day: string): Promise<Row[]> {
  const result = await rows(db, `SELECT s.*,coalesce(a.status,0) AS status,a.reason,a.marked_by,a.updated_at AS mark_updated_at,u.full_name AS author
    FROM enrollments e JOIN students s ON s.id=e.student_id LEFT JOIN attendance a ON a.student_id=s.id AND a.date=$2
    LEFT JOIN users u ON u.id=a.marked_by WHERE e.class_id=$1 AND e.starts_on<=$2 AND (e.ends_before IS NULL OR e.ends_before>$2)`, [classId, day])
  return result.sort((a, b) => a.full_name.toLocaleLowerCase('ru').replaceAll('ё', 'е').localeCompare(b.full_name.toLocaleLowerCase('ru').replaceAll('ё', 'е'), 'ru') || a.id - b.id)
}
async function attendanceScope(context: Context, classId: number, day: string, writing = false): Promise<Row> {
  if (day > context.today) throw new HttpError(400, 'Дата ещё не наступила.')
  return await scope(context, classId, day < context.today ? writing ? 'correction' : 'history' : 'manage', !writing && context.identity.id === context.config.ownerId)
}
async function mark(context: Context, classId: number, studentId: number, day: string, status: number, reason: string | null, expected?: string): Promise<Row> {
  const entry = (await roster(context.db, classId, day)).find(row => row.id === studentId)
  if (!entry) throw new HttpError(400, 'Ученик не числится в этом классе на выбранную дату.')
  if (expected != null && expected !== version(entry.mark_updated_at)) throw new HttpError(409, 'Отметка уже изменилась. Проверьте новое значение.')
  if (entry.status === status && entry.reason === reason) return entry
  const updated = (await one(context.db, `INSERT INTO attendance(student_id,date,status,reason,marked_by,updated_at)
    VALUES($1,$2,$3,$4,$5,timezone('UTC',clock_timestamp())) ON CONFLICT(student_id,date)
    DO UPDATE SET status=excluded.status,reason=excluded.reason,marked_by=excluded.marked_by,updated_at=excluded.updated_at RETURNING *`,
    [studentId, day, status, reason, context.user.id]))!
  await rows(context.db, `INSERT INTO attendance_history(student_id,class_id,date,actor_id,before_status,after_status,before_reason,after_reason)
    VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, [studentId, classId, day, context.user.id, entry.status, status, entry.reason ?? null, reason])
  await audit(context.db, context.user, 'attendance.marked', 'student', studentId, `class=${classId} date=${day} status=${entry.status}→${status}`)
  return { ...entry, status, reason, mark_updated_at: updated.updated_at, marked_by: context.user.id, author: context.user.full_name }
}
export async function periodRoster(context: Context, classId: number, start: string, end: string): Promise<Map<string, Row[]>> {
  const days = period(start, end, context.today)
  const result = new Map<string, Row[]>(days.map(day => [day, []]))
  const records = await rows(context.db, `SELECT d::date AS day,s.*,coalesce(a.status,0) AS status,a.reason
    FROM generate_series($2::date,$3::date,interval '1 day') d
    JOIN enrollments e ON e.class_id=$1 AND e.starts_on<=d::date AND (e.ends_before IS NULL OR e.ends_before>d::date)
    JOIN classes c ON c.id=e.class_id AND (c.archived_on IS NULL OR d::date<=c.archived_on)
    JOIN students s ON s.id=e.student_id LEFT JOIN attendance a ON a.student_id=s.id AND a.date=d::date
    ORDER BY d,s.full_name,s.id`, [classId, start, end])
  for (const row of records) result.get(row.day)?.push(row)
  return result
}

export function attendanceRoutes(router: Router): void {
  router.add('GET', '/students/:studentId', async context => {
    owner(context); const studentId = id(context.params.studentId)
    const pupil = await one(context.db, 'SELECT * FROM students WHERE id=$1', [studentId])
    if (!pupil) throw new HttpError(404, 'Ученик недоступен.')
    const end = date(context.url.searchParams.get('end') || context.today)
    const start = date(context.url.searchParams.get('start') || addDays(end, -29))
    period(start, end, context.today)
    const history = await rows(context.db, `SELECT d::date AS day,c.name AS class_name,s.*,coalesce(a.status,0) AS status,a.reason,a.updated_at AS mark_updated_at
      FROM generate_series($2::date,$3::date,interval '1 day') d
      JOIN enrollments e ON e.student_id=$1 AND e.starts_on<=d::date AND (e.ends_before IS NULL OR e.ends_before>=d::date)
      JOIN classes c ON c.id=e.class_id JOIN students s ON s.id=e.student_id
      LEFT JOIN attendance a ON a.student_id=s.id AND a.date=d::date
      WHERE (e.ends_before IS NULL OR e.ends_before>d::date OR a.student_id IS NOT NULL) ORDER BY d DESC,e.starts_on DESC`, [studentId, start, end])
    const byDay = new Map(history.map(row => [row.day, row]))
    return { ...studentView(pupil), history: [...byDay.values()].map(row => ({ day: row.day, class_name: row.class_name, ...markView(row) })) }
  })
  router.add('GET', '/classes/:classId/attendance', async context => {
    const classId = id(context.params.classId), day = date(context.url.searchParams.get('day') || context.today)
    const school = await attendanceScope(context, classId, day)
    const entries = school.archived_on && day > school.archived_on ? [] : await roster(context.db, classId, day)
    const manager = await one(context.db, 'SELECT * FROM manager_assignments WHERE user_id=$1 AND class_id=$2', [context.user.id, classId])
    return { class: schoolView(school), day, counts: counts(entries), writable: school.is_active &&
      (day === context.today || context.identity.id === context.config.ownerId || !!manager?.can_edit_history), entries: entries.map(markView) }
  })
  router.add('GET', '/classes/:classId/attendance/history', async context => {
    const classId = id(context.params.classId), day = date(context.url.searchParams.get('day') || context.today)
    await attendanceScope(context, classId, day)
    return (await rows(context.db, `SELECT h.*,u.full_name AS actor FROM attendance_history h JOIN users u ON u.id=h.actor_id
      WHERE h.class_id=$1 AND h.date=$2 ORDER BY h.id DESC LIMIT 100`, [classId, day])).map(row => ({
      id: row.id, student_id: row.student_id, before_status: row.before_status, after_status: row.after_status,
      before_reason: row.before_reason, after_reason: row.after_reason, actor: row.actor, time: stamp(row.changed_at) }))
  })
  router.add('PUT', '/classes/:classId/attendance/:studentId', async context => {
    const classId = id(context.params.classId), studentId = id(context.params.studentId), day = date(context.url.searchParams.get('day') || '')
    await attendanceScope(context, classId, day, true)
    const input = await body(context, z.object({ status: z.number().int().min(0).max(4), version: z.string().max(32), reason: z.string().trim().min(1).max(300).nullable().optional() }).strict())
    if (input.reason && ![2, 3, 4].includes(input.status)) throw new HttpError(400, 'Комментарий доступен для статусов отсутствия.')
    return markView(await mark(context, classId, studentId, day, input.status, input.reason ?? null, input.version))
  })
  router.add('POST', '/classes/:classId/attendance/mark-all', async context => {
    const classId = id(context.params.classId), day = date(context.url.searchParams.get('day') || '')
    await attendanceScope(context, classId, day, true)
    let changed = 0
    for (const row of await roster(context.db, classId, day)) if (row.status === 0) { await mark(context, classId, row.id, day, 1, null); changed++ }
    if (changed) await audit(context.db, context.user, 'attendance.bulk', 'class', classId, `date=${day} count=${changed}`)
    return { changed }
  })
  router.add('POST', '/classes/:classId/attendance/finish', async context => {
    const classId = id(context.params.classId), day = date(context.url.searchParams.get('day') || '')
    await attendanceScope(context, classId, day, true)
    await audit(context.db, context.user, 'attendance.finished', 'class', classId, `date=${day}`)
    return { counts: counts(await roster(context.db, classId, day)) }
  })
  router.add('GET', '/classes/:classId/stats', async context => {
    const classId = id(context.params.classId); const school = await scope(context, classId, 'statistics', context.identity.id === context.config.ownerId)
    const timeline = [...await periodRoster(context, classId, date(context.url.searchParams.get('start') || ''), date(context.url.searchParams.get('end') || ''))]
      .map(([day, entries]) => ({ day, counts: counts(entries) }))
    return { class: schoolView(school), counts: [0, 1, 2, 3, 4].map(index => timeline.reduce((sum, point) => sum + point.counts[index], 0)), timeline }
  })
  router.add('GET', '/admin/stats/comparison', async context => {
    owner(context); const start = date(context.url.searchParams.get('start') || ''), end = date(context.url.searchParams.get('end') || '')
    period(start, end, context.today)
    const result = []
    for (const school of await rows(context.db, 'SELECT * FROM classes WHERE is_active ORDER BY name_key')) {
      const daily = [...await periodRoster(context, school.id, start, end)].map(([, entries]) => counts(entries))
      result.push({ class: schoolView(school), counts: [0, 1, 2, 3, 4].map(index => daily.reduce((sum, item) => sum + item[index], 0)) })
    }
    return result
  })
}
