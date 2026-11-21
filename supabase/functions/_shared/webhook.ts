import { z } from 'zod'
import { HttpError, internalSecret } from './auth.ts'
import { configuration, connection, type Configuration, one, register, rows } from './core.ts'
import { telegram, TelegramError } from './telegram.ts'

const telegramUser = z.object({ id: z.number().int().positive().max(2 ** 52 - 1), is_bot: z.boolean().optional(),
  username: z.string().nullable().optional(), first_name: z.string(), last_name: z.string().optional() })
const updateInput = z.object({ update_id: z.number().int().nonnegative(), message: z.object({
  chat: z.object({ id: z.number().int(), type: z.string() }), from: telegramUser.optional(), text: z.string().optional(),
}).optional(), callback_query: z.object({ id: z.string() }).optional() })

export function webhookHandler(overrides: Partial<Configuration> = {}): ((request: Request) => Promise<Response>) & { close(): Promise<void> } {
  const config = configuration(overrides), sql = connection(config)
  const handler = async (request: Request): Promise<Response> => {
    try {
      if (request.method !== 'POST') return Response.json({ detail: 'Метод недоступен.' }, { status: 405 })
      internalSecret(request.headers.get('X-Telegram-Bot-Api-Secret-Token') ?? '', config.webhookSecret)
      if (config.readOnly) throw new HttpError(503, 'Attendance временно обслуживается.')
      const raw = await request.text()
      if (new TextEncoder().encode(raw).length > 64000) throw new HttpError(413, 'Запрос слишком большой.')
      const update = updateInput.parse(JSON.parse(raw))
      console.info('telegram_webhook received')
      const action = await sql.begin(async db => {
        await db`SELECT pg_advisory_xact_lock(1724810925)`
        const previous = await one(db, 'SELECT * FROM telegram_updates WHERE update_id=$1 FOR UPDATE', [update.update_id])
        if (previous && previous.status !== 'retry') return null
        await rows(db, `INSERT INTO telegram_updates(update_id,status) VALUES($1,'processing') ON CONFLICT(update_id) DO UPDATE SET status='processing'`, [update.update_id])
        const message = update.message, user = message?.from
        if (message?.chat.type === 'private' && user && !user.is_bot && message.chat.id === user.id) {
          if (/^\/start(?:@[A-Za-z0-9_]+)?(?:\s|$)/.test(message.text ?? '')) {
            await register(db, { id: user.id, username: user.username ?? null, name: [user.first_name, user.last_name].filter(Boolean).join(' ') }, true)
            return { method: 'sendMessage', payload: { chat_id: user.id, text: 'Откройте Attendance, чтобы работать с посещаемостью.',
              reply_markup: { inline_keyboard: [[{ text: 'Открыть Attendance', web_app: { url: config.miniAppUrl } }]] } } }
          }
          if (message.text?.startsWith('/')) return { method: 'sendMessage', payload: { chat_id: user.id, text: 'Команда не найдена. Отправьте /start, чтобы открыть Attendance.' } }
        }
        if (update.callback_query) return { method: 'answerCallbackQuery', payload: { callback_query_id: update.callback_query.id, text: 'Откройте Attendance через /start.', show_alert: true } }
        return null
      })
      if (action) {
        try { await telegram(config, action.method, action.payload) }
        catch (error) {
          const retry = error instanceof TelegramError && !error.uncertain && error.code === 429
          await rows(sql, 'UPDATE telegram_updates SET status=$1 WHERE update_id=$2', [retry ? 'retry' : 'uncertain', update.update_id])
          if (retry) return Response.json({ detail: 'Telegram временно ограничил отправку.' }, { status: 503 })
          console.warn('telegram_webhook reply_unconfirmed')
        }
      }
      await rows(sql, `UPDATE telegram_updates SET status=CASE WHEN status='processing' THEN 'processed' ELSE status END,completed_at=now() WHERE update_id=$1`, [update.update_id])
      console.info('telegram_webhook processed')
      return Response.json({ ok: true })
    } catch (error) {
      const status = error instanceof HttpError ? error.status : error instanceof z.ZodError || error instanceof SyntaxError ? 400 : 503
      if (status === 503) {
        console.error('telegram_webhook failed', { kind: error instanceof Error ? error.name : 'unknown' })
        try { await rows(sql, "INSERT INTO system_events(operation,success) VALUES('webhook',false)") } catch { /* A failed database connection cannot record its own error. */ }
      }
      return Response.json({ detail: status === 403 ? 'Доступ запрещён.' : 'Не удалось обработать обновление Telegram.' }, { status })
    }
  }
  return Object.assign(handler, { close: () => sql.end({ timeout: 1 }) })
}
