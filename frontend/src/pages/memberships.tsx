import { Bell, Check, GraduationCap, Send, ShieldBan, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { api } from '../api'
import { formatTime } from '../domain'
import type { Person, SchoolClass } from '../types'
import { Button, ClassSelect, Confirm, Empty, Failure, PageTitle, Panel, Pending, useAction, useData, useSession } from '../ui'
import { AnnouncementsPanel } from './admin'

type Decision = 'PENDING' | 'APPROVED' | 'REJECTED' | 'BLOCKED'
interface JoinRequest { id: number; class_id: number; class_name: string; status: Decision; requested_at: string; decided_at: string | null }
interface AdminRequest extends JoinRequest { user: Person }
interface MembershipData { classes: SchoolClass[]; member: number | null; notify_schedule: boolean; requests: JoinRequest[] }
interface NoticeItem { id: number; message: string; category: string; status: string; created_at: string; read: boolean }
const states: Record<Decision, string> = { PENDING: 'На рассмотрении', APPROVED: 'Одобрена', REJECTED: 'Отклонена', BLOCKED: 'Доступ закрыт' }

export function JoinPage() {
  const { member, timezone, join_open } = useSession()
  const query = useData<MembershipData>('/join-requests/me', 15000)
  const action = useAction()
  const [selected, setSelected] = useState(0)
  if (query.isPending) return <Pending />
  if (query.error) return <Failure error={query.error} retry={() => query.refetch()}/>
  const { requests, notify_schedule } = query.data
  const classes = query.data.classes.filter(item => item.id !== member?.id)
  const value = classes.some(item => item.id === selected) ? selected : classes[0]?.id ?? 0
  return <>
    <PageTitle title={member ? 'Мой класс' : 'Добро пожаловать в Attendance!'} subtitle={member ? member.name : 'Выберите свой класс'} />
    {member && <Panel title={member.name}><div className="panel-form">
      <Button asChild><Link to={`/lessons?class=${member.id}`}><GraduationCap size={17}/> Моё расписание</Link></Button>
      <label className="switch"><input type="checkbox" checked={notify_schedule} disabled={action.busy} onChange={event => action.run(
        () => api('/me/lesson-notifications', 'PUT', { enabled: event.target.checked }), 'Настройки сохранены')}/><span /> Получать изменения расписания в Telegram</label>
    </div></Panel>}
    <Panel title={member ? 'Смена класса' : 'Заявка на вступление'}>
      {requests.some(item => item.status === 'PENDING') ? <Empty title="Заявка ожидает подтверждения" description="Результат появится здесь после решения владельца."/> : !join_open ? <Empty title="Приём заявок закрыт"/> : classes.length ?
        <form className="panel-form" onSubmit={event => { event.preventDefault(); action.run(() => api('/join-requests', 'POST', { class_id: value }), 'Заявка отправлена') }}>
          <ClassSelect items={classes} value={value} change={setSelected}/><Button disabled={action.busy}><Send size={17}/> Отправить заявку</Button>
        </form> : <Empty title="Доступных классов пока нет"/>}
    </Panel>
    {requests.length > 0 && <Panel title="Мои заявки"><ul className="history-list">{requests.map(item => <li key={item.id}><div><strong>{item.class_name}</strong><small className="muted">{formatTime(item.requested_at, timezone, true)}</small></div><span className={`badge ${item.status === 'APPROVED' ? 'badge-green' : item.status === 'PENDING' ? 'badge-amber' : 'badge-slate'}`}>{states[item.status]}</span></li>)}</ul></Panel>}
  </>
}

export function RequestsPage() {
  const me = useSession()
  const [pending, setPending] = useState(true)
  const [classes, setClasses] = useState<Record<number, number>>({})
  const [decision, setDecision] = useState<{ item: AdminRequest; status: Decision }>()
  const query = useData<AdminRequest[]>(`/admin/join-requests?pending=${pending}`, 30000)
  const pendingItems = useData<AdminRequest[]>('/admin/join-requests?pending=true', 30000)
  const action = useAction()
  async function resolve(item: AdminRequest, status: Decision) {
    const class_id = classes[item.id] ?? (me.managed.some(school => school.id === item.class_id) ? item.class_id : undefined)
    const result = await action.run(() => {
      if (status === 'APPROVED') return api(`/admin/join-requests/${item.id}/approve`, 'POST', class_id ? { class_id } : undefined)
      if (status === 'REJECTED') return api(`/admin/join-requests/${item.id}/reject`, 'POST')
      return api(`/join-requests/${item.id}`, 'PATCH', { decision: status, ...(class_id ? { class_id } : {}) })
    }, 'Заявка обновлена')
    if (result) setDecision(undefined)
  }
  return <><PageTitle title="Заявки" subtitle={pendingItems.data ? `На рассмотрении: ${pendingItems.data.length}` : undefined}/>
    <div className="segmented"><button aria-pressed={pending} onClick={() => setPending(true)}>На рассмотрении</button><button aria-pressed={!pending} onClick={() => setPending(false)}>История</button></div>
    <Panel>{query.isPending ? <Pending/> : query.error ? <Failure error={query.error}/> : !query.data.length ? <Empty title="Заявок пока нет"/> : <div className="table-wrap"><table><thead><tr><th>Пользователь</th><th>Класс</th><th>Статус</th><th>Действия</th></tr></thead><tbody>
      {query.data.map(item => <tr key={item.id}><td><Link className="text-button" to={`/users?user=${item.user.id}`}><strong>{item.user.name}</strong></Link><small className="block muted">{formatTime(item.requested_at, me.timezone, true)}</small></td><td>{item.status === 'PENDING' ? <ClassSelect label="Класс заявки" items={me.managed}
        value={classes[item.id] ?? item.class_id} change={value => setClasses({ ...classes, [item.id]: value })} /> : item.class_name}</td><td><span className="badge badge-slate">{states[item.status]}</span></td>
        <td>{item.status === 'PENDING' && <div className="toolbar"><Button size="small" disabled={action.busy} onClick={() => setDecision({ item, status: 'APPROVED' })}><Check size={15}/> Одобрить</Button>
          <Button variant="outline" size="small" onClick={() => resolve(item, 'PENDING')} disabled={action.busy || !classes[item.id] || classes[item.id] === item.class_id}>Сменить класс</Button>
          <Button variant="ghost" size="icon" aria-label="Отклонить заявку" onClick={() => setDecision({ item, status: 'REJECTED' })}><X size={17}/></Button>
          <Button variant="ghost" size="icon" aria-label="Заблокировать пользователя" onClick={() => setDecision({ item, status: 'BLOCKED' })}><ShieldBan size={17}/></Button></div>}</td></tr>)}
      </tbody></table></div>}</Panel>
    {decision && <Confirm title={{ APPROVED: 'Одобрить заявку?', REJECTED: 'Отклонить заявку?', BLOCKED: 'Заблокировать пользователя?', PENDING: 'Перенести заявку?' }[decision.status]}
      text={decision.item.user.name} label="Подтвердить" busy={action.busy} onClose={() => setDecision(undefined)} onConfirm={() => resolve(decision.item, decision.status)}/>}
  </>
}

export function NotificationsPage() {
  const { timezone, roles } = useSession()
  const query = useData<NoticeItem[]>('/notifications', 15000)
  const action = useAction()
  return <><PageTitle title="Уведомления"><Button variant="outline" disabled={action.busy || !query.data?.some(item => !item.read)}
    onClick={() => action.run(() => api('/notifications/read', 'POST'), 'Уведомления отмечены прочитанными')}><Bell size={16}/> Прочитать все</Button></PageTitle>
    <Panel>{query.isPending ? <Pending/> : query.error ? <Failure error={query.error}/> : !query.data.length ? <Empty title="Уведомлений пока нет"/> :
      <ul className="history-list">{query.data.map(item => <li key={item.id}><div><strong className="notice-message">{item.message}</strong>
        <small className="muted">{formatTime(item.created_at, timezone, true)}</small></div>{!item.read && <span className="badge badge-green">Новое</span>}</li>)}</ul>}</Panel>
    {roles.includes('OWNER') && <AnnouncementsPanel/>}
  </>
}
