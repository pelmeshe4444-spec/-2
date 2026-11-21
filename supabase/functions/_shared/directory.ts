import { z } from 'zod'
import { HttpError } from './auth.ts'
import { addDays, audit, body, bounded, type Context, id, normal, one, owner, profile, type Router, type Row,
  rows, schoolView, scope, stamp, studentNames, studentView } from './core.ts'
import { flushNotices } from './telegram.ts'

const classInput = z.object({ name: z.string().min(1).max(32) }).strict()
const permissions: Record<string, string> = { history: 'can_view_history', correction: 'can_edit_history', statistics: 'can_view_statistics',
  timetable: 'can_edit_timetable', report_view: 'can_view_reports', report_send: 'can_send_reports' }

async function team(context: Context, classId: number): Promise<Row> {
  owner(context); await scope(context, classId)
  const result: Row = {}
  for (const [key, table] of [['managers', 'manager_assignments'], ['recipients', 'report_recipients']]) {
    const assignments = await rows(context.db, `SELECT u.*, a.* FROM ${table} a JOIN users u ON u.id=a.user_id WHERE a.class_id=$1 ORDER BY u.id`, [classId])
    result[key] = assignments.map(user => ({ user: profile(user), history: user.can_view_history ?? false }))
  }
  return result
}
export async function userDetails(context: Context, target: number): Promise<Row> {
  owner(context)
  const user = await one(context.db, 'SELECT * FROM users WHERE telegram_id=$1', [target])
  if (!user) throw new HttpError(404, 'Пользователь недоступен.')
  const managed = await rows(context.db, 'SELECT c.*,a.* FROM classes c JOIN manager_assignments a ON a.class_id=c.id WHERE a.user_id=$1 ORDER BY c.name_key', [user.id])
  const received = await rows(context.db, 'SELECT c.* FROM classes c JOIN report_recipients a ON a.class_id=c.id WHERE a.user_id=$1 ORDER BY c.name_key', [user.id])
  const member = await one(context.db, 'SELECT c.* FROM classes c JOIN class_memberships m ON m.class_id=c.id WHERE m.user_id=$1', [user.id])
  return { ...profile(user), managed: managed.map(row => ({ ...schoolView(row, row.can_view_history), can_edit_history: row.can_edit_history,
    can_edit_timetable: row.can_edit_timetable, can_view_statistics: row.can_view_statistics, can_view_reports: row.can_view_reports,
    can_send_reports: row.can_send_reports })), received: received.map(row => schoolView(row)), member: member ? schoolView(member) : null }
}

export function directoryRoutes(router: Router): void {
  router.add('GET', '/me', async context => {
    const owned = context.identity.id === context.config.ownerId
    const managed = await rows(context.db, `SELECT c.*,m.can_view_history,m.can_edit_history,m.can_view_statistics,m.can_send_reports,m.can_view_reports
      FROM classes c LEFT JOIN manager_assignments m ON m.class_id=c.id AND m.user_id=$1
      WHERE c.is_active AND ($2 OR m.user_id IS NOT NULL) ORDER BY c.name_key`, [context.user.id, owned])
    const received = owned ? [] : await rows(context.db, 'SELECT c.* FROM classes c JOIN report_recipients r ON r.class_id=c.id WHERE c.is_active AND r.user_id=$1 ORDER BY c.name_key', [context.user.id])
    const member = await one(context.db, 'SELECT c.* FROM classes c JOIN class_memberships m ON m.class_id=c.id WHERE m.user_id=$1 AND c.is_active', [context.user.id])
    const roles = owned ? ['OWNER'] : [...(managed.length ? ['MANAGER'] : []), ...(received.length ? ['REPORT_RECIPIENT'] : []), ...(member ? ['CLASS_MEMBER'] : [])]
    const reports = new Map([...received, ...managed.filter(row => row.can_view_reports)].map(row => [row.id, row]))
    return { user: profile(context.user), roles: roles.length ? roles : ['USER'], school: context.preferences.school,
      system_name: context.preferences.system_name, join_open: context.preferences.join_open, statistics_days: context.preferences.statistics_days,
      timezone: context.preferences.timezone, today: context.today, sqlite: false,
      managed: managed.map(row => ({ ...schoolView(row, owned || row.can_view_history || row.can_edit_history),
        can_edit_history: owned || row.can_edit_history, can_view_statistics: owned || row.can_view_statistics, can_send_reports: owned || row.can_send_reports })),
      reports: [...reports.values()].map(row => ({ ...schoolView(row), can_view_reports: managed.some(item => item.id === row.id && item.can_view_reports) })),
      member: member ? schoolView(member, false) : null }
  })
  router.add('GET', '/classes', async context => {
    owner(context)
    return (await rows(context.db, 'SELECT * FROM classes ORDER BY is_active DESC,name_key')).map(row => schoolView(row))
  })
  router.add('POST', '/classes', async context => {
    owner(context)
    const input = await body(context, classInput), name = bounded(input.name, 32)
    const school = (await one(context.db, 'INSERT INTO classes(name,name_key,is_active) VALUES($1,$2,true) RETURNING *', [name, normal(name)]))!
    await rows(context.db, 'INSERT INTO report_schedules(class_id,timezone,time,weekdays) VALUES($1,$2,$3,$4)',
      [school.id, context.preferences.timezone, context.preferences.report_time, context.preferences.school_days.join('')])
    await audit(context.db, context.user, 'class.added', 'class', school.id)
    return Response.json(schoolView(school), { status: 201 })
  })
  router.add('PATCH', '/classes/:classId', async context => {
    owner(context); const classId = id(context.params.classId); await scope(context, classId)
    const name = bounded((await body(context, classInput)).name, 32)
    const school = (await one(context.db, 'UPDATE classes SET name=$1,name_key=$2 WHERE id=$3 RETURNING *', [name, normal(name), classId]))!
    await audit(context.db, context.user, 'class.updated', 'class', classId)
    return schoolView(school)
  })
  for (const restore of [false, true]) router.add(restore ? 'POST' : 'DELETE', '/classes/:classId' + (restore ? '/restore' : ''), async context => {
    owner(context); const classId = id(context.params.classId); await scope(context, classId, 'manage', restore)
    const school = (await one(context.db, 'UPDATE classes SET is_active=$1,archived_on=$2 WHERE id=$3 RETURNING *', [restore, restore ? null : context.today, classId]))!
    if (!restore) await rows(context.db, 'UPDATE report_schedules SET is_enabled=false WHERE class_id=$1', [classId])
    await audit(context.db, context.user, restore ? 'class.restored' : 'class.archived', 'class', classId)
    return schoolView(school)
  })
  router.add('GET', '/classes/:classId/access', context => team(context, id(context.params.classId)))
  router.add('GET', '/classes/:classId/students', async context => {
    owner(context); const classId = id(context.params.classId); await scope(context, classId, 'manage', true)
    const query = normal(context.url.searchParams.get('q') ?? '')
    const pupils = await rows(context.db, `SELECT s.*,coalesce(a.status,0) AS status,a.updated_at AS marked_at
      FROM students s LEFT JOIN attendance a ON a.student_id=s.id AND a.date=$2 WHERE s.class_id=$1`, [classId, context.today])
    return pupils.filter(row => normal(row.full_name).includes(query)).sort((a, b) => normal(a.full_name).replaceAll('ё', 'е').localeCompare(normal(b.full_name).replaceAll('ё', 'е'), 'ru') || a.id - b.id)
      .map(row => ({ ...studentView(row), status: row.status, marked_at: stamp(row.marked_at) }))
  })
  router.add('POST', '/classes/:classId/students', async context => {
    owner(context); const classId = id(context.params.classId); await scope(context, classId)
    const input = await body(context, z.object({ names: z.string().max(25600).optional(), full_name: z.string().max(25600).optional(), bulk: z.boolean().default(false), preview: z.boolean().default(false) }).strict())
    const names = studentNames(input.names ?? input.full_name ?? '', input.bulk)
    const existing = new Set((await rows(context.db, 'SELECT active_name_key FROM students WHERE class_id=$1 AND is_active', [classId])).map(row => row.active_name_key))
    const added: string[] = [], duplicates: string[] = []
    for (const name of names) {
      const key = normal(name)
      if (existing.has(key)) { duplicates.push(name); continue }
      existing.add(key); added.push(name)
      if (input.preview) continue
      const pupil = (await one(context.db, 'INSERT INTO students(full_name,class_id,active_name_key) VALUES($1,$2,$3) RETURNING id', [name, classId, key]))!
      await rows(context.db, 'INSERT INTO enrollments(student_id,class_id,starts_on) VALUES($1,$2,$3)', [pupil.id, classId, context.today])
      await audit(context.db, context.user, 'student.added', 'student', pupil.id, `class=${classId}`)
    }
    return { added, duplicates }
  })
  router.add('PATCH', '/students/:studentId', async context => {
    owner(context); const studentId = id(context.params.studentId)
    const input = await body(context, z.object({ full_name: z.string().optional(), name: z.string().optional(), class_id: z.number().int().positive().optional() }).strict())
    const pupil = await one(context.db, 'SELECT * FROM students WHERE id=$1 AND is_active', [studentId])
    if (!pupil) throw new HttpError(400, 'Ученик уже в архиве или недоступен.')
    const classId = input.class_id ?? pupil.class_id; await scope(context, classId)
    const name = input.full_name ?? input.name
    const fullName = name == null ? pupil.full_name : studentNames(name, false)[0]
    if (classId !== pupil.class_id) {
      const effective = addDays(context.today, 1)
      const latest = (await one(context.db, 'SELECT * FROM enrollments WHERE student_id=$1 ORDER BY starts_on DESC LIMIT 1', [studentId]))!
      if (latest.starts_on === effective) await rows(context.db, 'UPDATE enrollments SET class_id=$1 WHERE student_id=$2 AND starts_on=$3', [classId, studentId, effective])
      else {
        await rows(context.db, 'UPDATE enrollments SET ends_before=$1 WHERE student_id=$2 AND starts_on=$3', [effective, studentId, latest.starts_on])
        await rows(context.db, 'INSERT INTO enrollments(student_id,class_id,starts_on) VALUES($1,$2,$3)', [studentId, classId, effective])
      }
    }
    const updated = (await one(context.db, `UPDATE students SET full_name=$1,class_id=$2,active_name_key=$3,updated_at=timezone('UTC',now()) WHERE id=$4 RETURNING *`, [fullName, classId, normal(fullName), studentId]))!
    await audit(context.db, context.user, 'student.updated', 'student', studentId, `class=${classId}`)
    return studentView(updated)
  })
  for (const restore of [false, true]) router.add(restore ? 'POST' : 'DELETE', '/students/:studentId' + (restore ? '/restore' : ''), async context => {
    owner(context); const studentId = id(context.params.studentId)
    const pupil = await one(context.db, 'SELECT * FROM students WHERE id=$1', [studentId])
    if (!pupil) throw new HttpError(404, 'Ученик недоступен.')
    await scope(context, pupil.class_id)
    if (pupil.is_active === restore) return studentView(pupil)
    if (restore) {
      const latest = await one(context.db, 'SELECT * FROM enrollments WHERE student_id=$1 ORDER BY starts_on DESC LIMIT 1', [studentId])
      if (latest?.ends_before === context.today && latest.class_id === pupil.class_id) await rows(context.db, 'UPDATE enrollments SET ends_before=null WHERE student_id=$1 AND starts_on=$2', [studentId, latest.starts_on])
      else await rows(context.db, 'INSERT INTO enrollments(student_id,class_id,starts_on) VALUES($1,$2,$3)', [studentId, pupil.class_id, context.today])
    } else {
      await rows(context.db, 'DELETE FROM enrollments WHERE student_id=$1 AND starts_on>$2', [studentId, context.today])
      const latest = await one(context.db, 'SELECT * FROM enrollments WHERE student_id=$1 ORDER BY starts_on DESC LIMIT 1', [studentId])
      if (latest) {
        await rows(context.db, 'UPDATE enrollments SET ends_before=$1 WHERE student_id=$2 AND starts_on=$3', [context.today, studentId, latest.starts_on])
        pupil.class_id = latest.class_id
      }
    }
    const updated = (await one(context.db, `UPDATE students SET is_active=$1,active_name_key=$2,class_id=$3,updated_at=timezone('UTC',now()) WHERE id=$4 RETURNING *`, [restore, restore ? normal(pupil.full_name) : null, pupil.class_id, studentId]))!
    await audit(context.db, context.user, restore ? 'student.restored' : 'student.archived', 'student', studentId)
    return studentView(updated)
  })
  for (const path of ['/users', '/admin/users']) router.add('GET', path, async context => {
    owner(context)
    const total = Number((await one(context.db, 'SELECT count(*) AS n FROM users'))!.n)
    const page = Math.min(Math.max(0, Number(context.url.searchParams.get('page')) || 0), Math.max(0, Math.ceil(total / 50) - 1))
    const users = await rows(context.db, 'SELECT * FROM users ORDER BY id OFFSET $1 LIMIT 50', [page * 50])
    const result = []
    for (const user of users) {
      const roles = (await rows(context.db, 'SELECT role FROM user_roles WHERE user_id=$1', [user.id])).map(row => row.role)
      const assignments = await rows(context.db, `SELECT DISTINCT c.name FROM classes c WHERE c.is_active AND c.id IN
        (SELECT class_id FROM manager_assignments WHERE user_id=$1 UNION SELECT class_id FROM report_recipients WHERE user_id=$1 UNION SELECT class_id FROM class_memberships WHERE user_id=$1) ORDER BY c.name`, [user.id])
      if (await one(context.db, 'SELECT 1 FROM class_memberships m JOIN classes c ON c.id=m.class_id WHERE m.user_id=$1 AND c.is_active', [user.id])) roles.push('CLASS_MEMBER')
      result.push({ ...profile(user), roles: user.telegram_id === context.config.ownerId ? ['OWNER'] : roles.length ? roles : ['USER'], classes: assignments.map(row => row.name) })
    }
    return { users: result, total, page }
  })
  router.add('GET', '/admin/recipient-candidates', async context => {
    owner(context); const classId = id(context.url.searchParams.get('class_id')); await scope(context, classId)
    const term = normal(context.url.searchParams.get('q') ?? '').replace(/^@/, '')
    const escaped = term.replace(/[\\%_]/g, '\\$&')
    const users = await rows(context.db, `SELECT u.* FROM users u WHERE u.started_at IS NOT NULL AND NOT u.blocked
      AND NOT EXISTS(SELECT 1 FROM report_recipients r WHERE r.user_id=u.id AND r.class_id=$1)
      AND (lower(coalesce(u.full_name,'')) LIKE $2 ESCAPE '\\' OR lower(coalesce(u.username,'')) LIKE $2 ESCAPE '\\' OR u.telegram_id::text LIKE $2 ESCAPE '\\') ORDER BY u.id`, [classId, '%' + escaped + '%'])
    const page = Math.min(Math.max(0, Number(context.url.searchParams.get('page')) || 0), Math.max(0, Math.ceil(users.length / 50) - 1))
    return { users: users.slice(page * 50, page * 50 + 50).map(profile), total: users.length, page }
  })
  router.add('POST', '/users', async context => {
    owner(context); const { telegram_id: target } = await body(context, z.object({ telegram_id: z.number().int().positive().max(2 ** 52 - 1) }).strict())
    if (target === context.identity.id) throw new HttpError(400, 'Выберите другого пользователя.')
    const user = (await one(context.db, 'INSERT INTO users(telegram_id) VALUES($1) ON CONFLICT(telegram_id) DO UPDATE SET telegram_id=excluded.telegram_id RETURNING *', [target]))!
    await audit(context.db, context.user, 'user.added', 'user', user.id)
    return profile(user)
  })
  router.add('GET', '/users/:target', context => userDetails(context, id(context.params.target)))
  router.add('PATCH', '/users/:target', async context => {
    owner(context); const target = id(context.params.target)
    if (target === context.identity.id) throw new HttpError(400, 'Выберите другого пользователя.')
    const input = await body(context, z.object({ blocked: z.boolean() }).strict())
    const user = await one(context.db, 'UPDATE users SET blocked=$1 WHERE telegram_id=$2 RETURNING *', [input.blocked, target])
    if (!user) throw new HttpError(404, 'Пользователь недоступен.')
    await audit(context.db, context.user, input.blocked ? 'user.blocked' : 'user.unblocked', 'user', user.id)
    return profile(user)
  })
  for (const [method, path] of [['POST', '/users/:target/access'], ['PATCH', '/admin/users/:target/roles']]) router.add(method, path, async context => {
    owner(context); const target = id(context.params.target)
    const input = await body(context, z.object({ class_id: z.number().int().positive(), operation: z.enum(['manager_add', 'manager_remove', 'recipient_add', 'recipient_remove',
      ...Object.keys(permissions).flatMap(key => [key + '_on', key + '_off'])] as [string, ...string[]]) }).strict())
    await scope(context, input.class_id)
    const recipient = input.operation.startsWith('recipient_')
    if (target === context.config.ownerId && !recipient) throw new HttpError(400, 'Права владельца заданы в конфигурации сервера.')
    let user = await one(context.db, 'SELECT * FROM users WHERE telegram_id=$1', [target])
    if (input.operation === 'recipient_add' && (!user?.started_at || user.blocked)) throw new HttpError(400, 'Получатель должен запустить бота и иметь доступ к Attendance.')
    if (!user && input.operation === 'manager_add') user = await one(context.db, 'INSERT INTO users(telegram_id) VALUES($1) RETURNING *', [target])
    if (!user) throw new HttpError(400, 'Назначение не найдено.')
    const table = recipient ? 'report_recipients' : 'manager_assignments', role = recipient ? 'REPORT_RECIPIENT' : 'MANAGER'
    const previous = await one(context.db, `SELECT * FROM ${table} WHERE user_id=$1 AND class_id=$2`, [user.id, input.class_id])
    let changed = true
    if (input.operation.endsWith('_add')) {
      changed = !previous
      await rows(context.db, `INSERT INTO ${table}(user_id,class_id) VALUES($1,$2) ON CONFLICT DO NOTHING`, [user.id, input.class_id])
      await rows(context.db, 'INSERT INTO user_roles(user_id,role) VALUES($1,$2) ON CONFLICT DO NOTHING', [user.id, role])
    } else if (!previous) throw new HttpError(400, 'Назначение для этого класса не найдено.')
    else if (input.operation.endsWith('_remove')) {
      await rows(context.db, `DELETE FROM ${table} WHERE user_id=$1 AND class_id=$2`, [user.id, input.class_id])
      if (recipient) await rows(context.db, 'UPDATE report_deliveries SET body=null WHERE recipient_id=$1 AND schedule_id IN(SELECT id FROM report_schedules WHERE class_id=$2)', [user.id, input.class_id])
      if (!await one(context.db, `SELECT 1 FROM ${table} WHERE user_id=$1 LIMIT 1`, [user.id])) await rows(context.db, 'DELETE FROM user_roles WHERE user_id=$1 AND role=$2', [user.id, role])
    } else {
      const setting = input.operation.endsWith('_on'), key = input.operation.replace(/_(on|off)$/, ''), column = permissions[key]
      if (!column || recipient) throw new HttpError(400, 'Действие недоступно.')
      changed = previous[column] !== setting
      await rows(context.db, `UPDATE manager_assignments SET ${column}=$1 WHERE user_id=$2 AND class_id=$3`, [setting, user.id, input.class_id])
    }
    if (changed) await audit(context.db, context.user, 'access.' + input.operation, 'user', user.id, `class=${input.class_id}`)
    console.info('recipient_assignment committed', { changed, operation: input.operation })
    if (changed && target !== context.identity.id && input.operation.endsWith('_add') && user.started_at && !user.blocked) {
      await rows(context.db, `INSERT INTO notifications(recipient_id,class_id,category,message,status)
        VALUES($1,$2,'access','Вам предоставлен доступ к Attendance. Откройте приложение из меню бота.','pending')`, [user.id, input.class_id])
      context.effects.push(() => flushNotices(context.sql, context.config, 20))
    }
    return { changed }
  })
}
