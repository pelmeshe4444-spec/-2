import { z } from 'zod'
import { HttpError } from './auth.ts'
import { addDays, audit, body, bounded, type Context, date, id, normal, one, owner, type Router, type Row, rows, scope, stamp, weekday } from './core.ts'
import { flushNotices, notice } from './telegram.ts'

const clock = z.string().regex(/^(?:[01]\d|2[0-3]):[0-5]\d$/)
const slotInput = z.object({ lesson_number: z.number().int().min(1).max(20), start_time: clock, end_time: clock })
const lessonInput = slotInput.extend({ weekday: z.number().int().min(0).max(6), subject_id: z.number().int().positive(),
  teacher_name: z.string().max(100).nullish(), classroom: z.string().max(40).nullish(), comment: z.string().max(250).nullish() }).strict()
const planInput = z.object({ name: z.string().min(1).max(80), cycle: z.enum(['A', 'B']), active: z.boolean().default(true),
  effective_from: z.string(), effective_to: z.string().nullish().transform(value => value ?? null), lessons: z.array(lessonInput).max(140), revision: z.number().int().min(0), notify: z.boolean().default(false) }).strict()
const exceptionInput = z.object({ action: z.enum(['regular', 'replace', 'closed']), lessons: z.array(lessonInput).max(20),
  comment: z.string().max(250).nullish(), revision: z.number().int().min(0), notify: z.boolean().default(false) }).strict()
const lessonFields = ['weekday', 'lesson_number', 'subject_id', 'start_time', 'end_time', 'teacher_name', 'classroom', 'comment']
const lessonView = (row: Row): Row => Object.fromEntries(lessonFields.map(key => [key, row[key] ?? null]))
const subjectView = (row: Row) => ({ id: row.id, name: row.name, color: row.color, icon: row.icon, active: row.is_active })
export function validateLessons(input: Row[]): Row[] {
  const occupied = new Set<string>()
  const result = input.map((row): Row => {
    const key = `${row.weekday ?? 0}:${row.lesson_number}`
    if (occupied.has(key) || row.start_time >= row.end_time) throw new HttpError(400, 'Проверьте уникальные номера уроков и время окончания.')
    occupied.add(key)
    return { ...row, teacher_name: row.teacher_name?.trim() ? bounded(row.teacher_name, 100) : null,
      classroom: row.classroom?.trim() ? bounded(row.classroom, 40) : null, comment: row.comment?.trim() ? bounded(row.comment, 250) : null }
  }).sort((a, b) => (a.weekday ?? 0) - (b.weekday ?? 0) || a.lesson_number - b.lesson_number)
  for (let index = 1; index < result.length; index++) {
    const previous = result[index - 1], next = result[index]
    if ((previous.weekday ?? 0) === (next.weekday ?? 0) && previous.end_time > next.start_time) throw new HttpError(400, 'Время уроков пересекается или нарушает порядок.')
  }
  return result
}
async function subjects(context: Context): Promise<Row[]> { return (await rows(context.db, 'SELECT * FROM subjects ORDER BY name_key')).map(subjectView) }
async function snapshot(context: Context, classId: number, cycle: string, start?: string): Promise<Row> {
  const plan = await one(context.db, `SELECT * FROM class_timetables WHERE class_id=$1 AND cycle=$2 AND ($3::date IS NULL OR effective_from=$3) ORDER BY effective_from DESC LIMIT 1`, [classId, cycle, start ?? null])
  if (!plan) return { name: 'Расписание', cycle, effective_from: start ?? '2000-01-03', effective_to: null, active: true, lessons: [], revision: 0 }
  return { name: plan.name, cycle: plan.cycle, effective_from: plan.effective_from, effective_to: plan.effective_to, active: plan.is_active,
    lessons: (await rows(context.db, 'SELECT * FROM timetable_lessons WHERE timetable_id=$1 ORDER BY weekday,lesson_number', [plan.id])).map(lessonView), revision: plan.revision }
}
async function effective(context: Context, classId: number, day: string): Promise<Row> {
  let cycle = Math.floor((Date.parse(day) - Date.parse('2026-01-05')) / (7 * 86400000)) % 2 === 0 ? 'A' : 'B'
  let plan = await one(context.db, `SELECT * FROM class_timetables WHERE class_id=$1 AND cycle=$2 AND is_active
    AND effective_from<=$3 AND (effective_to IS NULL OR effective_to>=$3) ORDER BY effective_from DESC LIMIT 1`, [classId, cycle, day])
  if (!plan && cycle === 'B') {
    cycle = 'A'
    plan = await one(context.db, `SELECT * FROM class_timetables WHERE class_id=$1 AND cycle='A' AND is_active
      AND effective_from<=$2 AND (effective_to IS NULL OR effective_to>=$2) ORDER BY effective_from DESC LIMIT 1`, [classId, day])
  }
  const regular = plan ? (await rows(context.db, 'SELECT * FROM timetable_lessons WHERE timetable_id=$1 AND weekday=$2 ORDER BY lesson_number', [plan.id, weekday(day)])).map(lessonView) : []
  const exception = await one(context.db, 'SELECT * FROM timetable_exceptions WHERE class_id=$1 AND date=$2', [classId, day])
  return { day, cycle, lessons: exception && exception.action !== 'regular' ? exception.lessons : regular, regular,
    action: exception?.action ?? 'regular', comment: exception?.comment ?? null, revision: exception?.revision ?? 0 }
}
async function bells(context: Context, classId: number): Promise<Row[]> {
  const result = await rows(context.db, 'SELECT shift,lesson_number,start_time,end_time FROM lesson_time_slots WHERE class_id=$1 ORDER BY shift,lesson_number', [classId])
  const start = context.preferences.lesson_start
  const minutes = Number(start.slice(0, 2)) * 60 + Number(start.slice(3)) + context.preferences.lesson_minutes
  return result.length ? result : [{ shift: 'Стандартные звонки', lesson_number: 1, start_time: start,
    end_time: `${Math.floor(minutes / 60).toString().padStart(2, '0')}:${(minutes % 60).toString().padStart(2, '0')}` }]
}
async function validateSubjects(context: Context, lessons: Row[]): Promise<void> {
  const selected = new Set(lessons.map(row => row.subject_id))
  const available = new Set((await rows(context.db, 'SELECT id FROM subjects WHERE id=ANY($1::int[])', [[...selected]])).map(row => row.id))
  if ([...selected].some(value => !available.has(value))) throw new HttpError(400, 'В расписании указан неизвестный предмет.')
}
async function change(context: Context, school: Row, target: string, key: string, before: Row, after: Row, send: boolean): Promise<void> {
  await rows(context.db, 'INSERT INTO timetable_change_history(class_id,actor_id,target,plan_key,"before","after") VALUES($1,$2,$3,$4,$5::json,$6::json)',
    [school.id, context.user.id, target, key, before, after])
  await audit(context.db, context.user, 'timetable.published', 'class', school.id, key)
  if (send) {
    const subjectMap = new Map((await subjects(context)).map(row => [row.id, row.name]))
    const beforeSlots = new Map(before.lessons.map((row: Row) => [`${row.weekday}:${row.lesson_number}`, row]))
    const afterSlots = new Map(after.lessons.map((row: Row) => [`${row.weekday}:${row.lesson_number}`, row]))
    const details = []
    for (const slot of new Set([...beforeSlots.keys(), ...afterSlots.keys()])) {
      const previous = beforeSlots.get(slot) as Row | undefined, next = afterSlots.get(slot) as Row | undefined
      if (JSON.stringify(previous) === JSON.stringify(next)) continue
      const value = next ?? previous!
      details.push(`${['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'][value.weekday]}, урок ${value.lesson_number}: ${previous ? subjectMap.get(previous.subject_id) : '—'} → ${next ? `${subjectMap.get(next.subject_id)} ${next.start_time}–${next.end_time}` : 'отменён'}`)
    }
    const message = `📚 Расписание изменено. Класс ${school.name}. ${key}.\n${details.slice(0, 3).join('\n')}${details.length > 3 ? '\nДругих изменений: ' + (details.length - 3) : ''}`
    for (const user of await rows(context.db, 'SELECT user_id FROM class_memberships WHERE class_id=$1 AND notify_schedule', [school.id])) await notice(context.db, user.user_id, 'timetable', message, school.id)
    context.effects.push(() => flushNotices(context.sql, context.config, 20))
  }
}
async function publish(context: Context, classId: number, input: z.infer<typeof planInput>): Promise<Row> {
  const school = await scope(context, classId, 'timetable_edit'), start = date(input.effective_from), end = input.effective_to ? date(input.effective_to) : null
  if (end && end < start) throw new HttpError(400, 'Конец периода должен быть не раньше начала.')
  const before = await snapshot(context, classId, input.cycle, start)
  if (input.revision !== before.revision) throw new HttpError(409, 'Расписание уже изменилось. Обновите его перед сохранением.')
  const lessons = validateLessons(input.lessons); await validateSubjects(context, lessons)
  if (input.active && await one(context.db, `SELECT 1 FROM class_timetables WHERE class_id=$1 AND cycle=$2 AND is_active AND effective_from<>$3
    AND (effective_to IS NULL OR effective_to>=$3) AND ($4::date IS NULL OR effective_from<=$4) LIMIT 1`, [classId, input.cycle, start, end])) throw new HttpError(409, 'Периоды этой недели пересекаются. Сначала завершите предыдущий период.')
  const plan = (await one(context.db, `INSERT INTO class_timetables(class_id,cycle,effective_from,effective_to,name,is_active,revision)
    VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(class_id,cycle,effective_from) DO UPDATE SET effective_to=excluded.effective_to,
    name=excluded.name,is_active=excluded.is_active,revision=excluded.revision,updated_at=timezone('UTC',now()) RETURNING *`,
    [classId, input.cycle, start, end, bounded(input.name, 80), input.active, before.revision + 1]))!
  await rows(context.db, 'DELETE FROM timetable_lessons WHERE timetable_id=$1', [plan.id])
  for (const row of lessons) await rows(context.db, `INSERT INTO timetable_lessons(timetable_id,weekday,lesson_number,subject_id,start_time,end_time,teacher_name,classroom,comment)
    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)`, [plan.id, row.weekday, row.lesson_number, row.subject_id, row.start_time, row.end_time, row.teacher_name, row.classroom, row.comment])
  const after = await snapshot(context, classId, input.cycle, start)
  await change(context, school, 'week', `${input.cycle}:${start}`, before, after, input.notify)
  return after
}
async function exception(context: Context, classId: number, day: string, input: z.infer<typeof exceptionInput>): Promise<Row> {
  const school = await scope(context, classId, 'timetable_edit'), before = await effective(context, classId, day)
  if (input.revision !== before.revision) throw new HttpError(409, 'Исключение уже изменилось. Обновите расписание.')
  const lessons = input.action === 'replace' ? validateLessons(input.lessons.map(row => ({ ...row, weekday: weekday(day) }))) : []
  await validateSubjects(context, lessons)
  await rows(context.db, `INSERT INTO timetable_exceptions(class_id,date,action,lessons,comment,revision,created_by)
    VALUES($1,$2,$3,$4::json,$5,$6,$7) ON CONFLICT(class_id,date) DO UPDATE SET action=excluded.action,lessons=excluded.lessons,
    comment=excluded.comment,revision=excluded.revision`, [classId, day, input.action, lessons,
    input.action === 'regular' ? null : input.comment?.trim() || null, before.revision + 1, context.user.id])
  const after = await effective(context, classId, day)
  await change(context, school, 'exception', day, before, after, input.notify)
  return after
}
export function timetableRoutes(router: Router): void {
  router.add('GET', '/subjects', async context => { owner(context); return await subjects(context) })
  for (const editing of [false, true]) router.add(editing ? 'PUT' : 'POST', '/subjects' + (editing ? '/:subjectId' : ''), async context => {
    owner(context)
    const input = await body(context, z.object({ name: z.string().min(1).max(80), color: z.string().regex(/^#[0-9a-fA-F]{6}$/),
      icon: z.enum(['book', 'calculator', 'globe', 'flask', 'music', 'monitor', 'dumbbell', 'palette', 'languages', 'atom']), active: z.boolean().default(true) }).strict())
    const name = bounded(input.name, 80), values = [name, normal(name), input.color.toLowerCase(), input.icon, input.active]
    const subject = editing ? await one(context.db, 'UPDATE subjects SET name=$1,name_key=$2,color=$3,icon=$4,is_active=$5 WHERE id=$6 RETURNING *', [...values, id(context.params.subjectId)]) :
      await one(context.db, 'INSERT INTO subjects(name,name_key,color,icon,is_active) VALUES($1,$2,$3,$4,$5) RETURNING *', values)
    if (!subject) throw new HttpError(404, 'Предмет недоступен.')
    await audit(context.db, context.user, 'timetable.subject', 'subject', subject.id)
    return Response.json(subjectView(subject), { status: editing ? 200 : 201 })
  })
  router.add('GET', '/classes/:classId/timetable', async context => {
    const classId = id(context.params.classId), school = await scope(context, classId, 'timetable'), day = date(context.url.searchParams.get('day') || context.today)
    const days = context.url.searchParams.get('week') === 'true' ? Array.from({ length: 7 }, (_, index) => addDays(day, index - weekday(day))) : [day]
    const plans = []
    for (const selected of days) plans.push(await effective(context, classId, selected))
    const used = new Set(plans.flatMap(plan => [...plan.lessons, ...plan.regular].map((row: Row) => row.subject_id)))
    const editor = await one(context.db, 'SELECT can_edit_timetable FROM manager_assignments WHERE user_id=$1 AND class_id=$2', [context.user.id, classId])
    return { class_name: school.name, days: plans, editable: context.identity.id === context.config.ownerId || !!editor?.can_edit_timetable, subjects: (await subjects(context)).filter(row => used.has(row.id)) }
  })
  router.add('GET', '/classes/:classId/timetable/editor', async context => {
    const classId = id(context.params.classId); await scope(context, classId, 'timetable_edit')
    const cycle = z.enum(['A', 'B']).parse(context.url.searchParams.get('cycle') || 'A'), start = context.url.searchParams.get('starts')
    return { plan: await snapshot(context, classId, cycle, start ? date(start) : undefined),
      periods: (await rows(context.db, 'SELECT effective_from FROM class_timetables WHERE class_id=$1 AND cycle=$2 ORDER BY effective_from DESC', [classId, cycle])).map(row => row.effective_from),
      subjects: await subjects(context), slots: await bells(context, classId) }
  })
  router.add('PUT', '/classes/:classId/timetable', async context => publish(context, id(context.params.classId), await body(context, planInput)))
  router.add('PUT', '/classes/:classId/timetable/bells', async context => {
    owner(context); const classId = id(context.params.classId); await scope(context, classId)
    const input = await body(context, z.object({ shift: z.string().min(1).max(32), slots: z.array(slotInput.strict()).max(20) }).strict())
    const shift = bounded(input.shift, 32), slots = validateLessons(input.slots)
    await rows(context.db, 'DELETE FROM lesson_time_slots WHERE class_id=$1 AND shift=$2', [classId, shift])
    for (const row of slots) await rows(context.db, 'INSERT INTO lesson_time_slots(class_id,shift,lesson_number,start_time,end_time) VALUES($1,$2,$3,$4,$5)', [classId, shift, row.lesson_number, row.start_time, row.end_time])
    await audit(context.db, context.user, 'timetable.bells', 'class', classId)
    return await bells(context, classId)
  })
  router.add('PUT', '/classes/:classId/timetable/exceptions/:day', async context => exception(context, id(context.params.classId), date(context.params.day), await body(context, exceptionInput)))
  router.add('GET', '/classes/:classId/timetable/history', async context => {
    owner(context); const classId = id(context.params.classId); await scope(context, classId, 'manage', true)
    return (await rows(context.db, `SELECT h.*,u.full_name AS actor FROM timetable_change_history h JOIN users u ON u.id=h.actor_id
      WHERE h.class_id=$1 ORDER BY h.id DESC LIMIT 100`, [classId])).map(row => ({ id: row.id, target: row.target, key: row.plan_key, before: row.before, after: row.after, changed_at: stamp(row.changed_at), actor: row.actor }))
  })
  router.add('POST', '/classes/:classId/timetable/history/:changeId/restore', async context => {
    owner(context); const classId = id(context.params.classId)
    const history = await one(context.db, 'SELECT * FROM timetable_change_history WHERE id=$1 AND class_id=$2', [id(context.params.changeId), classId])
    if (!history) throw new HttpError(400, 'Версия расписания недоступна.')
    if (history.target === 'week') {
      const current = await snapshot(context, classId, history.before.cycle, history.before.effective_from)
      return publish(context, classId, planInput.parse({ ...history.before, revision: current.revision }))
    }
    const current = await effective(context, classId, history.plan_key)
    return exception(context, classId, history.plan_key, exceptionInput.parse({ action: history.before.action, lessons: history.before.lessons,
      comment: history.before.comment, revision: current.revision }))
  })
  router.add('PUT', '/users/:target/classes/:classId/timetable-access', async context => {
    owner(context); const classId = id(context.params.classId); await scope(context, classId)
    const input = await body(context, z.object({ enabled: z.boolean() }).strict())
    const changed = await rows(context.db, 'UPDATE manager_assignments SET can_edit_timetable=$1 WHERE user_id=(SELECT id FROM users WHERE telegram_id=$2) AND class_id=$3 RETURNING user_id', [input.enabled, id(context.params.target), classId])
    if (!changed.length) throw new HttpError(400, 'Сначала назначьте ответственного за класс.')
    await audit(context.db, context.user, 'timetable.permission', 'user', changed[0].user_id, `class=${classId}`)
    return input
  })
}
