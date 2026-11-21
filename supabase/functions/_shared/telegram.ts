import { type Configuration, one, type Row, rows, type Sql, type Transaction } from './core.ts'

export class TelegramError extends Error {
  constructor(public code: number, public retryAfter = 0, public uncertain = false) { super('Telegram request failed') }
}
export async function telegram(config: Configuration, method: string, payload: Row = {}): Promise<Row> {
  if (config.test) return method === 'getWebhookInfo' ? { url: config.projectUrl + '/functions/v1/telegram-webhook', pending_update_count: 0 } : { message_id: 1 }
  let response: Response
  try {
    response = await fetch(`https://api.telegram.org/bot${config.token}/${method}`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: AbortSignal.timeout(15000) })
  } catch { throw new TelegramError(0, 0, true) }
  let result
  try { result = await response.json() } catch { throw new TelegramError(response.status, 0, true) }
  if (!response.ok || !result.ok) throw new TelegramError(result.error_code ?? response.status, result.parameters?.retry_after ?? 0)
  return result.result
}
export async function notice(db: Transaction, recipient: number, category: string, message: string, classId: number | null = null): Promise<void> {
  await rows(db, `INSERT INTO notifications(recipient_id,class_id,category,message,status) VALUES($1,$2,$3,$4,'pending')`, [recipient, classId, category, message.slice(0, 500)])
}
export async function flushNotices(sql: Sql, config: Configuration, limit = 30): Promise<void> {
  const started = Date.now()
  await rows(sql, `UPDATE notifications SET status='uncertain' WHERE status='sending' AND attempted_at<timezone('UTC',now())-interval '5 minutes'`)
  for (let index = 0; index < limit && Date.now() - started < 40000; index++) {
    const item = await sql.begin(async db => {
      const pending = await one(db, `SELECT n.*,u.telegram_id,u.blocked,u.started_at FROM notifications n JOIN users u ON u.id=n.recipient_id
        WHERE n.status='pending' AND (n.attempted_at IS NULL OR n.attempted_at<timezone('UTC',now())-interval '2 minutes') ORDER BY n.id FOR UPDATE OF n SKIP LOCKED LIMIT 1`)
      if (!pending) return null
      let allowed = !pending.blocked && pending.started_at && (pending.category !== 'timetable' || !!await one(db,
        'SELECT 1 FROM class_memberships WHERE user_id=$1 AND class_id=$2 AND notify_schedule', [pending.recipient_id, pending.class_id]))
      if (allowed && pending.announcement_id) allowed = !!await one(db, `SELECT 1 FROM announcements a WHERE a.id=$1 AND EXISTS
        (SELECT 1 FROM classes c WHERE c.is_active AND a.class_ids::jsonb @> to_jsonb(ARRAY[c.id]) AND c.id IN
        (SELECT class_id FROM class_memberships WHERE user_id=$2 UNION SELECT class_id FROM manager_assignments WHERE user_id=$2
        UNION SELECT class_id FROM report_recipients WHERE user_id=$2))`, [pending.announcement_id, pending.recipient_id])
      await rows(db, `UPDATE notifications SET status=$1,attempted_at=timezone('UTC',now()) WHERE id=$2`, [allowed ? 'sending' : 'cancelled', pending.id])
      return allowed ? pending : { ...pending, skipped: true }
    })
    if (!item) break
    if (item.skipped) continue
    let status = 'sent'
    try {
      const message = await telegram(config, 'sendMessage', { chat_id: item.telegram_id, text: item.message, protect_content: true })
      if (!Number.isSafeInteger(message.message_id) || message.message_id <= 0) status = 'uncertain'
    } catch (error) {
      status = error instanceof TelegramError && error.code === 429 && Date.now() - new Date(item.created_at + 'Z').getTime() < 86400000 ? 'pending' :
        error instanceof TelegramError && error.uncertain ? 'uncertain' : 'failed'
    }
    await rows(sql, 'UPDATE notifications SET status=$1 WHERE id=$2', [status, item.id])
  }
}
