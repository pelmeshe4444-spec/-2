import { hex, hmac, HttpError, internalSecret } from './auth.ts'
import { configuration, connection, type Configuration, one, rows } from './core.ts'
import { scheduler } from './reports.ts'
import { flushNotices } from './telegram.ts'

export function schedulerHandler(overrides: Partial<Configuration> = {}): ((request: Request) => Promise<Response>) & { close(): Promise<void> } {
  const config = configuration(overrides), sql = connection(config)
  const handler = async (request: Request): Promise<Response> => {
    try {
      if (request.method !== 'POST') return Response.json({ detail: 'Метод недоступен.' }, { status: 405 })
      if (!config.schedulerSecret) throw new HttpError(503, 'Планировщик ещё не подключён.')
      const authorization = request.headers.get('Authorization') ?? ''
      if (authorization.startsWith('Bearer ')) internalSecret(authorization.slice(7), config.schedulerSecret)
      else {
        const timestamp = request.headers.get('X-Attendance-Time') ?? '', nonce = request.headers.get('X-Attendance-Nonce') ?? ''
        const age = Date.now() / 1000 - Number(timestamp)
        if (!/^\d+$/.test(timestamp) || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(nonce) || !Number.isFinite(age) || age < -30 || age > 300) throw new HttpError(403, 'Доступ запрещён.')
        const expected = hex(await hmac(new TextEncoder().encode(config.schedulerSecret), `attendance-scheduler\n${timestamp}\n${nonce}`))
        internalSecret(request.headers.get('X-Attendance-Signature') ?? '', expected)
        const claim = await one(sql, `INSERT INTO background_leases(name,owner,expires_at) VALUES($1,$2,now()+interval '6 minutes')
          ON CONFLICT(name) DO NOTHING RETURNING name`, ['scheduler-invocation/' + nonce, nonce])
        if (!claim) return Response.json({ ok: true, duplicate: true })
      }
      if (config.readOnly) throw new HttpError(503, 'Attendance временно обслуживается.')
      const owner = crypto.randomUUID()
      const lease = await one(sql, `INSERT INTO background_leases(name,owner,expires_at) VALUES('scheduler',$1,now()+interval '3 minutes')
        ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at WHERE background_leases.expires_at<now() RETURNING name`, [owner])
      if (!lease) return Response.json({ ok: true, running: true })
      try {
        await rows(sql, 'DELETE FROM background_leases WHERE expires_at<now()')
        await scheduler(sql, config)
        await flushNotices(sql, config, 30)
      } finally { await rows(sql, "DELETE FROM background_leases WHERE name='scheduler' AND owner=$1", [owner]) }
      console.info('attendance_scheduler completed')
      return Response.json({ ok: true })
    } catch (error) {
      if (error instanceof HttpError) return Response.json({ detail: error.message }, { status: error.status })
      console.error('attendance_scheduler failed', { kind: error instanceof Error ? error.name : 'unknown' })
      try { await rows(sql, "INSERT INTO system_events(operation,success) VALUES('scheduler',false)") } catch { /* Keep the original failure status. */ }
      return Response.json({ detail: 'Планировщик временно недоступен.' }, { status: 503 })
    }
  }
  return Object.assign(handler, { close: () => sql.end({ timeout: 1 }) })
}
