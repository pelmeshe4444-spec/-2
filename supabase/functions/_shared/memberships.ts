import { z } from 'zod'
import { HttpError } from './auth.ts'
import { audit, body, type Context, id, one, owner, profile, type Router, type Row, rows, schoolView, scope, stamp } from './core.ts'
import { flushNotices, notice } from './telegram.ts'

const brief = (row: Row) => ({ id: row.id, class_id: row.class_id, class_name: row.class_name ?? null, status: row.status,
  requested_at: stamp(row.requested_at), decided_at: stamp(row.decided_at) })
async function assign(context: Context, user: Row, classId: number): Promise<void> {
  if (user.blocked) throw new HttpError(400, 'Сначала восстановите доступ пользователя.')
  await scope(context, classId)
  await rows(context.db, `INSERT INTO class_memberships(user_id,class_id,notify_schedule) VALUES($1,$2,$3)
    ON CONFLICT(user_id) DO UPDATE SET class_id=excluded.class_id,approved_at=timezone('UTC',now())`, [user.id, classId, context.preferences.notify_schedule])
}
function notify(context: Context): void { context.effects.push(() => flushNotices(context.sql, context.config, 20)) }
async function decide(context: Context, requestId: number, decision: string, targetClass?: number | null): Promise<Row> {
  owner(context)
  const row = await one(context.db, 'SELECT * FROM class_join_requests WHERE id=$1', [requestId])
  if (!row || row.status !== 'PENDING') throw new HttpError(409, 'Заявка уже рассмотрена или недоступна.')
  const user = (await one(context.db, 'SELECT * FROM users WHERE id=$1', [row.user_id]))!
  if (user.telegram_id === context.identity.id) throw new HttpError(403, 'Доступ ограничен.')
  const classId = targetClass ?? row.class_id
  if (decision === 'APPROVED' || targetClass != null) await scope(context, classId)
  if (decision === 'APPROVED') {
    await assign(context, user, classId)
    const school = (await one(context.db, 'SELECT * FROM classes WHERE id=$1', [classId]))!
    await notice(context.db, user.id, 'join_decision', `Заявка одобрена. Ваш класс — ${school.name}.`, classId)
  } else if (decision === 'BLOCKED') await rows(context.db, 'UPDATE users SET blocked=true WHERE id=$1', [user.id])
  else if (decision === 'REJECTED') await notice(context.db, user.id, 'join_decision', 'Владелец отклонил вашу заявку на вступление.', classId)
  const updated = (await one(context.db, `UPDATE class_join_requests SET status=$1::text,class_id=$2,
    pending_user_id=CASE WHEN $1='PENDING' THEN user_id END,decided_at=CASE WHEN $1<>'PENDING' THEN timezone('UTC',now()) END,
    decided_by=CASE WHEN $1<>'PENDING' THEN $3::int END WHERE id=$4 RETURNING *`, [decision, classId, context.user.id, requestId]))!
  await audit(context.db, context.user, 'membership.' + decision.toLowerCase(), 'join_request', row.id, `class=${classId}`)
  notify(context)
  return brief(updated)
}
export function membershipRoutes(router: Router): void {
  router.add('GET', '/join-requests/me', async context => {
    const schools = await rows(context.db, 'SELECT * FROM classes WHERE is_active ORDER BY name_key')
    const membership = await one(context.db, 'SELECT * FROM class_memberships WHERE user_id=$1', [context.user.id])
    const requests = await rows(context.db, `SELECT r.*,c.name AS class_name FROM class_join_requests r JOIN classes c ON c.id=r.class_id WHERE user_id=$1 ORDER BY r.id DESC LIMIT 30`, [context.user.id])
    return { classes: schools.map(row => schoolView(row, false)), member: membership?.class_id ?? null, notify_schedule: membership?.notify_schedule ?? false, requests: requests.map(brief) }
  })
  router.add('POST', '/join-requests', async context => {
    const { class_id: classId } = await body(context, z.object({ class_id: z.number().int().positive() }).strict())
    if (!context.preferences.join_open) throw new HttpError(400, 'Приём заявок временно закрыт.')
    const school = await one(context.db, 'SELECT * FROM classes WHERE id=$1 AND is_active', [classId])
    if (!school) throw new HttpError(400, 'Выберите активный класс.')
    if (await one(context.db, 'SELECT 1 FROM class_memberships WHERE user_id=$1 AND class_id=$2', [context.user.id, classId])) throw new HttpError(400, 'Вы уже участник этого класса.')
    const existing = await one(context.db, 'SELECT * FROM class_join_requests WHERE pending_user_id=$1', [context.user.id])
    if (existing) {
      if (existing.class_id === classId) return Response.json(brief(existing), { status: 201 })
      throw new HttpError(409, 'У вас уже есть заявка на рассмотрении.')
    }
    if (context.preferences.join_retry_days && await one(context.db, `SELECT 1 FROM class_join_requests WHERE user_id=$1 AND status='REJECTED'
      AND decided_at>timezone('UTC',now())-$2::int*interval '1 day' LIMIT 1`, [context.user.id, context.preferences.join_retry_days])) throw new HttpError(400, 'Срок повторной подачи заявки ещё не наступил.')
    const created = (await one(context.db, `INSERT INTO class_join_requests(user_id,class_id,pending_user_id,status) VALUES($1,$2,$1,'PENDING') RETURNING *`, [context.user.id, classId]))!
    const creator = await one(context.db, 'SELECT id FROM users WHERE telegram_id=$1', [context.config.ownerId])
    if (creator && context.preferences.notify_owner) await notice(context.db, creator.id, 'join_request', `Новая заявка в класс ${school.name}. Откройте раздел «Заявки».`, classId)
    await audit(context.db, context.user, 'membership.requested', 'join_request', created.id)
    notify(context)
    return Response.json(brief(created), { status: 201 })
  })
  for (const path of ['/join-requests', '/admin/join-requests']) router.add('GET', path, async context => {
    owner(context)
    const requests = await rows(context.db, `SELECT r.*,c.name AS class_name,row_to_json(u) AS applicant FROM class_join_requests r
      JOIN classes c ON c.id=r.class_id JOIN users u ON u.id=r.user_id WHERE ($1=false OR r.status='PENDING') ORDER BY r.id DESC LIMIT 200`, [context.url.searchParams.get('pending') === 'true'])
    return requests.map(row => ({ ...brief(row), user: profile(row.applicant) }))
  })
  router.add('PATCH', '/join-requests/:requestId', async context => {
    const input = await body(context, z.object({ decision: z.enum(['APPROVED', 'REJECTED', 'BLOCKED', 'PENDING']), class_id: z.number().int().positive().nullish() }).strict())
    return decide(context, id(context.params.requestId), input.decision, input.class_id)
  })
  for (const [action, decision] of [['approve', 'APPROVED'], ['reject', 'REJECTED']]) router.add('POST', '/admin/join-requests/:requestId/' + action, async context => {
    const raw = await context.request.text()
    const input = raw ? z.object({ class_id: z.number().int().positive().nullable() }).strict().parse(JSON.parse(raw)) : null
    return decide(context, id(context.params.requestId), decision, input?.class_id)
  })
  router.add('PUT', '/admin/users/:target/membership', async context => {
    owner(context); const target = id(context.params.target)
    const input = await body(context, z.object({ class_id: z.number().int().positive().nullable() }).strict())
    const user = await one(context.db, 'SELECT * FROM users WHERE telegram_id=$1', [target])
    if (!user || target === context.identity.id) throw new HttpError(400, 'Выберите другого пользователя.')
    if (input.class_id == null) {
      await rows(context.db, 'DELETE FROM class_memberships WHERE user_id=$1', [user.id])
      await notice(context.db, user.id, 'membership', 'Владелец отозвал доступ к вашему классу.')
    } else {
      await assign(context, user, input.class_id)
      const school = (await one(context.db, 'SELECT name FROM classes WHERE id=$1', [input.class_id]))!
      await notice(context.db, user.id, 'membership', `Ваш класс — ${school.name}.`, input.class_id)
    }
    await audit(context.db, context.user, input.class_id == null ? 'membership.revoked' : 'membership.assigned', 'user', user.id)
    notify(context)
    return input
  })
  router.add('PUT', '/me/lesson-notifications', async context => {
    const input = await body(context, z.object({ enabled: z.boolean() }).strict())
    if (!await one(context.db, 'UPDATE class_memberships SET notify_schedule=$1 WHERE user_id=$2 RETURNING user_id', [input.enabled, context.user.id])) throw new HttpError(403, 'Доступ ограничен.')
    return input
  })
  router.add('GET', '/notifications', async context => (await rows(context.db, 'SELECT * FROM notifications WHERE recipient_id=$1 ORDER BY id DESC LIMIT 100', [context.user.id]))
    .map(row => ({ id: row.id, message: row.message, category: row.category, status: row.status, created_at: stamp(row.created_at), read: row.read_at != null })))
  router.add('POST', '/notifications/read', async context => {
    await rows(context.db, `UPDATE notifications SET read_at=timezone('UTC',now()) WHERE id IN(SELECT id FROM notifications WHERE recipient_id=$1 ORDER BY id DESC LIMIT 100) AND read_at IS NULL`, [context.user.id])
    return { read: true }
  })
}
