import { useQueryClient } from '@tanstack/react-query'
import { LoaderCircle } from 'lucide-react'
import { useContext, useRef } from 'react'
import { api } from '../api'
import { formatTime } from '../domain'
import { Button, Toast, useAction, useData, useSession } from '../ui'

interface SendResult { sent: number; total: number; pending: number }

export function SendReportNow({ classId }: { classId: number }) {
  const action = useAction()
  const client = useQueryClient()
  const notify = useContext(Toast)
  const { timezone } = useSession()
  const path = `/classes/${classId}/reports/last-manual`
  const history = useData<{ sent_at: string | null }>(path, 20000)
  const pending = useRef(false)
  const requestId = useRef<string | undefined>(undefined)
  const lastClick = useRef(-Infinity)

  async function send() {
    if (pending.current || performance.now() - lastClick.current < 750) return
    pending.current = true
    lastClick.current = performance.now()
    requestId.current ??= crypto.randomUUID().replaceAll('-', '')
    try {
      const result = await action.run(() => api<SendResult>('/reports/send-now', 'POST', {
        class_id: classId, request_id: requestId.current,
      }))
      if (!result) return
      requestId.current = undefined
      await client.invalidateQueries({ queryKey: [path] })
      if (!result.total) notify('Владелец ещё не назначил доступных получателей.', true)
      else if (result.sent === result.total) notify('✅ Отчёт успешно отправлен')
      else if (result.pending) notify(`Telegram принял ${result.sent} из ${result.total}. Остальные отправки ещё выполняются.`)
      else notify(`Telegram принял ${result.sent} из ${result.total}. Проверьте ошибки доставки у владельца.`, true)
    } finally {
      pending.current = false
    }
  }

  return <div className="toolbar">
    <Button onClick={send} disabled={action.busy} aria-busy={action.busy}>
      {action.busy ? <LoaderCircle size={17} className="animate-spin"/> : <span aria-hidden="true">📨</span>}
      {action.busy ? 'Отправляем отчёт…' : 'Отправить отчёт сейчас'}
    </Button>
    {history.data && <small className="muted">{history.data.sent_at
      ? `Последняя отправка: ${formatTime(history.data.sent_at, timezone, true)}`
      : 'Последняя отправка: пока нет'}</small>}
  </div>
}
