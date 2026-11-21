import { z } from 'zod'
import { authenticate, hex, hmac, HttpError } from './auth.ts'
import { AfterCommit, configuration, connection, type Configuration, type Context, localDay, one, register, Router, rows, settings } from './core.ts'
import { directoryRoutes } from './directory.ts'
import { attendanceRoutes } from './attendance.ts'
import { membershipRoutes } from './memberships.ts'
import { timetableRoutes } from './timetable.ts'
import { reportRoutes } from './reports.ts'
import { adminRoutes } from './admin.ts'
import { exportRoutes, ticketDownload } from './exports.ts'
import { webhookHandler } from './webhook.ts'
import { schedulerHandler } from './scheduler-http.ts'

export function apiHandler(overrides: Partial<Configuration> = {}): ((request: Request) => Promise<Response>) & { close(): Promise<void> } {
  const config = configuration(overrides), sql = connection(config), router = new Router()
  directoryRoutes(router)
  attendanceRoutes(router)
  membershipRoutes(router)
  timetableRoutes(router)
  reportRoutes(router)
  adminRoutes(router)
  exportRoutes(router)
  const origin = new URL(config.miniAppUrl).origin
  let webhook: ReturnType<typeof webhookHandler> | undefined
  let cron: ReturnType<typeof schedulerHandler> | undefined
  const handler = async (request: Request): Promise<Response> => {
    const url = new URL(request.url)
    const path = url.pathname.includes('/api/v1/') ? '/' + url.pathname.split('/api/v1/')[1] : url.pathname.replace(/^.*\/api(?=\/|$)/, '')
    const download = path.startsWith('/downloads/') && ['GET', 'HEAD'].includes(request.method)
    const responseHeaders = { 'Access-Control-Allow-Origin': download ? '*' : origin, Vary: 'Origin', 'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff', 'Access-Control-Expose-Headers': 'Content-Disposition',
      'Access-Control-Allow-Methods': 'GET,HEAD,POST,PUT,PATCH,DELETE,OPTIONS', 'Access-Control-Allow-Headers': 'Authorization,Content-Type' }
    try {
      if (!download && request.headers.has('Origin') && request.headers.get('Origin') !== origin) throw new HttpError(403, 'Источник запроса недоступен.')
      if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: responseHeaders })
      if (Number(request.headers.get('Content-Length') ?? 0) > 64000) throw new HttpError(413, 'Запрос слишком большой.')
      if (path === '/telegram/webhook') {
        webhook ??= webhookHandler(config)
        return await webhook(request)
      }
      if (path === '/internal/scheduler/run') {
        cron ??= schedulerHandler(config)
        return await cron(request)
      }
      if (path === '/health' && request.method === 'GET') {
        await sql`SELECT 1`
        return Response.json({ status: 'ok' }, { headers: responseHeaders })
      }
      if (config.readOnly && (request.method !== 'GET' && request.method !== 'HEAD' || path === '/me')) {
        throw new HttpError(503, 'Выполняется обслуживание Attendance. Повторите через несколько минут.')
      }
      if (download) {
        const response = await sql.begin('isolation level repeatable read', async db => {
          const preferences = await settings(db)
          return ticketDownload({ request, url, params: {}, db, sql, config, user: {}, identity: { id: 0, username: null, name: '' },
            preferences, today: localDay(preferences.timezone), effects: [] }, path.slice('/downloads/'.length))
        })
        for (const [name, value] of Object.entries(responseHeaders)) response.headers.set(name, value)
        return response
      }
      const authorization = request.headers.get('Authorization') ?? ''
      if (!authorization.startsWith('tma ')) throw new HttpError(401, 'Откройте приложение заново из Telegram.')
      const identity = await authenticate(authorization.slice(4), config.token)
      const bucket = hex(await hmac(new TextEncoder().encode(config.token), `api:${identity.id}:${Math.floor(Date.now() / 60000)}`))
      const limited = await one(sql, `INSERT INTO api_rate_limits(bucket,expires_at,hits) VALUES($1,now()+interval '3 minutes',1)
        ON CONFLICT(bucket) DO UPDATE SET hits=api_rate_limits.hits+1 RETURNING hits`, [bucket])
      if (limited!.hits > 180) throw new HttpError(429, 'Слишком много запросов. Подождите минуту.')
      const effects: (() => Promise<void>)[] = []
      const write = request.method !== 'GET' || path === '/me' ||
        (url.searchParams.get('ticket') === 'true' && (path === '/backup' || path.endsWith('/export')))
      const result = await sql.begin(write ? '' : 'isolation level repeatable read', async db => {
        await db.unsafe('SET LOCAL search_path TO ' + config.schema)
        if (write) await db`SELECT pg_advisory_xact_lock(1724810925)`
        let user = await one(db, 'SELECT * FROM users WHERE telegram_id=$1', [identity.id])
        if (path === '/me' && (!user || (!user.started_at && !user.full_name))) user = await register(db, identity, false)
        if (!user || (user.blocked && identity.id !== config.ownerId)) throw new HttpError(403, 'Доступ ограничен.')
        const preferences = await settings(db)
        const context: Context = { request, url, params: {}, db, sql, config, identity, user, preferences,
          today: localDay(preferences.timezone), effects }
        return await router.run(path, context)
      })
      const output = result instanceof AfterCommit ? await result.execute() : result
      for (const effect of effects) await effect()
      const response = output instanceof Response ? output : Response.json(output)
      for (const [name, value] of Object.entries(responseHeaders)) response.headers.set(name, value)
      return response
    } catch (error) {
      const invalid = error instanceof z.ZodError
      const code = error && typeof error === 'object' && 'code' in error ? String(error.code) : ''
      const status = error instanceof HttpError ? error.status : invalid ? 422 : code === '23505' ? 409 : code === '23503' ? 400 : 503
      const message = error instanceof HttpError ? error.message : invalid ? 'Проверьте заполненные поля.' : status === 409 ? 'Запись уже существует или была изменена.' : 'Сервер временно недоступен.'
      if (status === 503) console.error('attendance_api failed', { kind: error instanceof Error ? error.name : 'unknown', code })
      return Response.json({ detail: message }, { status, headers: responseHeaders })
    }
  }
  return Object.assign(handler, { close: async () => { await Promise.all([sql.end({ timeout: 1 }), webhook?.close(), cron?.close()]) } })
}
