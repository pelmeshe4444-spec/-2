import { Activity, ArrowRight, CalendarClock, ClipboardList, GraduationCap, HeartPulse, School, ShieldCheck, UserCheck, UsersRound } from 'lucide-react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { type FormEvent, useState } from 'react'
import { Link } from 'react-router'
import { api } from '../api'
import { activities, attendanceRate, deliveryLabels, formatDay, formatTime } from '../domain'
import type { AuditItem } from '../types'
import { Button, Confirm, Empty, Failure, PageTitle, Panel, Pending, useAction, useData, useSession } from '../ui'

interface Overview {
  school: string; today: string; backend: 'ok'; students: number; classes: number; attendance: number[]
  pending_requests: number; managers: number; sent_reports: number
  trend: { day: string; counts: number[] }[]; recent_actions: AuditItem[]
}

export function OwnerDashboard() {
  const { timezone, system_name } = useSession()
  const query = useData<Overview>('/admin/dashboard', 60000)
  const data = query.data
  return <>
    <PageTitle title="Панель владельца" subtitle={data ? `${system_name} · ${data.school} · ${formatDay(data.today, true)}` : undefined}>
      {data && <Link className="badge badge-green" to="/admin/system"><Activity size={15}/> Backend на связи</Link>}
    </PageTitle>
    {query.isPending ? <Panel><Pending/></Panel> : query.error ? <Failure error={query.error} retry={() => query.refetch()}/> : <>
      <div className="owner-metrics">{[
        { label: 'Ученики', value: data!.students, icon: GraduationCap, to: '/students' },
        { label: 'Классы', value: data!.classes, icon: School, to: '/classes' },
        { label: 'Присутствуют', value: data!.attendance[1], icon: ClipboardList, to: '/attendance' },
        { label: 'Болеют', value: data!.attendance[2], icon: HeartPulse, to: '/attendance' },
        { label: 'По уважительной причине', value: data!.attendance[3], icon: ClipboardList, to: '/attendance' },
        { label: 'Без уважительной причины', value: data!.attendance[4], icon: ClipboardList, to: '/attendance' },
        { label: 'Ожидают отметки', value: data!.attendance[0], icon: ClipboardList, to: '/attendance' },
        { label: 'Новые заявки', value: data!.pending_requests, icon: UserCheck, to: '/requests' },
        { label: 'Активные ответственные', value: data!.managers, icon: ShieldCheck, to: '/access' },
        { label: 'Отчёты отправлены сегодня', value: data!.sent_reports, icon: CalendarClock, to: '/schedule' },
      ].map(({ label, value, icon: Icon, to }) => <Link to={to} className="owner-metric" key={label}>
        <span className="metric-icon badge-indigo"><Icon size={19}/></span><span><strong>{value}</strong><small>{label}</small></span><ArrowRight size={15}/>
      </Link>)}</div>
      <div className="dashboard-grid">
        {data!.trend.length > 0 && <Panel title="Посещаемость за семь дней"><div className="line-chart">
          <ResponsiveContainer width="100%" height="100%"><AreaChart data={data!.trend.map(({ day, counts }) => ({ day: formatDay(day), value: attendanceRate(counts) }))}>
            <CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="4 4"/>
            <XAxis dataKey="day" tick={{ fontSize: 11, fill: 'var(--muted)' }} minTickGap={14}/>
            <YAxis domain={[0, 100]} tickFormatter={value => `${value}%`} width={44}/>
            <Tooltip formatter={value => [`${value}%`, 'Присутствовали']}/>
            <Area dataKey="value" type="monotone" stroke="#1aaa82" fill="#1aaa82" fillOpacity={0.16} isAnimationActive={false}/>
          </AreaChart></ResponsiveContainer>
        </div></Panel>}
        <Panel title="Последние действия" actions={<Button asChild size="small" variant="ghost"><Link to="/audit">Журнал</Link></Button>}>
          {data!.recent_actions.length ? <ul className="history-list">{data!.recent_actions.map(item => <li key={item.id}>
            <span>{activities[item.action] ?? item.action}</span><small className="muted">{formatTime(item.time, timezone, true)}</small>
          </li>)}</ul> : <Empty title="Действий пока нет"/>}
        </Panel>
      </div>
    </>}
  </>
}

interface Health {
  backend: string; checked_at: string; database: { engine: string; state: string }
  webhook: { state: string; checked_at: string; pending?: number; last_error_at?: string | null }
  last_scheduler_success: string | null; last_report: { time: string; status: string } | null
  recent_errors: { source: string; time: string }[]
}

const webhookStatus: Record<string, string> = {
  ok: 'Подключён', error: 'Telegram сообщил об ошибке доставки', not_configured: 'Настройки webhook отсутствуют',
  not_registered: 'Webhook не зарегистрирован в Telegram', unexpected: 'Указан другой адрес webhook', unavailable: 'Telegram API не ответил',
}
const errorSources: Record<string, string> = { webhook: 'Webhook Telegram', scheduler: 'Планировщик', backend: 'Backend' }

export function SystemHealthPage() {
  const { timezone } = useSession()
  const query = useData<Health>('/admin/system-health')
  const data = query.data
  const time = (value?: string | null) => value ? formatTime(value, timezone, true) : 'Пока нет данных'
  return <>
    <PageTitle title="Состояние системы" subtitle={data ? `Проверено ${time(data.checked_at)}` : undefined}>
      <Button variant="outline" disabled={query.isFetching} onClick={() => query.refetch()}>Проверить снова</Button>
    </PageTitle>
    {query.isPending ? <Pending/> : query.error ? <Failure error={query.error} retry={() => query.refetch()}/> : <>
      <div className="dashboard-grid">
        <Panel title="Backend и база данных"><ul className="history-list">
          <li><strong>Backend</strong><span>{data!.backend === 'ok' ? 'Доступен' : 'Недоступен'}</span></li>
          <li><strong>{data!.database.engine === 'postgresql' ? 'PostgreSQL' : 'SQLite'}</strong><span>{data!.database.state === 'ok' ? 'Соединение проверено' : 'Нет соединения'}</span></li>
        </ul></Panel>
        <Panel title="Telegram webhook"><ul className="history-list">
          <li><strong>{webhookStatus[data!.webhook.state] ?? data!.webhook.state}</strong></li>
          {data!.webhook.pending !== undefined && <li><span>В очереди</span><strong>{data!.webhook.pending}</strong></li>}
          {data!.webhook.last_error_at && <li><span>Последняя ошибка Telegram</span><strong>{time(data!.webhook.last_error_at)}</strong></li>}
        </ul></Panel>
        <Panel title="Планировщик и отчёты"><ul className="history-list">
          <li><span>Последний успешный запуск</span><strong>{time(data!.last_scheduler_success)}</strong></li>
          <li><span>Последний отчёт</span><strong>{data!.last_report ? `${deliveryLabels[data!.last_report.status] ?? data!.last_report.status} · ${time(data!.last_report.time)}` : 'Пока нет отчётов'}</strong></li>
        </ul></Panel>
        <Panel title="Последние ошибки">{data!.recent_errors.length ? <ul className="history-list">
          {data!.recent_errors.map((error, index) => <li key={`${error.time}:${index}`}><span>{errorSources[error.source] ?? error.source}</span><strong>{time(error.time)}</strong></li>)}
        </ul> : <Empty title="Ошибки пока не зарегистрированы"/>}</Panel>
      </div>
    </>}
  </>
}

interface Announcement { id: number; message: string; class_ids: number[]; time: string; statuses: Record<string, number> }
interface Preview { recipients: number; confirmation: string }

export function AnnouncementsPanel() {
  const { managed, timezone } = useSession()
  const data = useData<Announcement[]>('/admin/announcements', 30000)
  const [classIds, setClassIds] = useState<number[]>([])
  const [message, setMessage] = useState('')
  const [preview, setPreview] = useState<Preview & { request_id: string }>()
  const action = useAction()
  async function review(event: FormEvent) {
    event.preventDefault()
    const result = await action.run(() => api<Preview>('/admin/announcements/preview', 'POST', { class_ids: classIds, message }))
    if (result) setPreview({ ...result, request_id: crypto.randomUUID().replaceAll('-', '') })
  }
  async function send() {
    if (!preview?.recipients) return
    const result = await action.run(() => api('/admin/announcements', 'POST', {
      class_ids: classIds, message, confirmation: preview.confirmation, request_id: preview.request_id,
    }), 'Объявление поставлено в очередь')
    if (result) { setPreview(undefined); setMessage('') }
  }
  return <div className="dashboard-grid">
    <Panel title="Объявление" subtitle="Сообщение получат пользователи выбранных классов, которые запустили бота.">
      <form className="panel-form" onSubmit={review}>
        <fieldset className="choice-list"><legend>Классы получателей</legend>{managed.map(item => <label key={item.id}>
          <input type="checkbox" checked={classIds.includes(item.id)} onChange={e => setClassIds(e.target.checked ? [...classIds, item.id] : classIds.filter(id => id !== item.id))}/> {item.name}
        </label>)}</fieldset>
        <label className="field">Текст объявления<textarea required rows={4} maxLength={500} value={message} onChange={e => setMessage(e.target.value)}/></label>
        <Button disabled={!classIds.length || !message.trim() || action.busy}><UsersRound size={17}/> Проверить получателей</Button>
        {preview?.recipients === 0 && <p role="status">Подходящих получателей нет.</p>}
      </form>
    </Panel>
    <Panel title="Доставка объявлений">{data.isPending ? <Pending/> : data.error ? <Failure error={data.error}/> : data.data.length ? <ul className="history-list">
      {data.data.map(item => <li key={item.id}><div><strong>{item.message}</strong><small className="block muted">{formatTime(item.time, timezone, true)} · {item.class_ids.map(id => managed.find(group => group.id === id)?.name ?? `Класс ${id}`).join(', ')}</small>
        <div className="toolbar">{Object.entries(item.statuses).map(([status, count]) => <span className="badge badge-slate" key={status}>{status === 'in_app' ? 'Только в приложении' : deliveryLabels[status] ?? status} · {count}</span>)}</div></div></li>)}
    </ul> : <Empty title="Объявлений пока нет"/>}</Panel>
    {!!preview?.recipients && <Confirm title="Отправить объявление?" text={`Получателей: ${preview.recipients}.`} label="Отправить" onClose={() => setPreview(undefined)} onConfirm={send} busy={action.busy}/>}
  </div>
}
