import { Clock, Plus, Send, Trash2, UsersRound, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { api } from '../api'
import { activities, deliveryLabels, formatDay, formatTime } from '../domain'
import type { AuditItem, Delivery, Page, Person, Report, Schedule, SchoolClass, Team } from '../types'
import { Button, ClassSelect, Confirm, Empty, Failure, PageTitle, Pagination, Panel, Pending, useAction, useClass, useData, useSession } from '../ui'

export function ReportsPage() {
  const me = useSession()
  const owner = me.roles.includes('OWNER')
  const all = useData<SchoolClass[]>(owner ? '/classes' : null)
  const classes = owner ? (all.data ?? me.managed) : me.reports
  const selected = useClass(classes)
  const [params] = useSearchParams()
  const [day, setDay] = useState(() => owner && /^\d{4}-\d{2}-\d{2}$/.test(params.get('day') ?? '') ? params.get('day')! : '')
  const [tab, setTab] = useState<'report' | 'delivery'>('report')
  const [send, setSend] = useState<string>()
  const action = useAction()
  const current = classes.find(item => item.id === selected.value)
  const canBrowse = owner || current?.can_view_reports
  const query = useData<Report>(selected.value && tab === 'report' ? `/classes/${selected.value}/report?day=${day}` : null, 20000)
  return <>
    <PageTitle title="Отчёты" subtitle={canBrowse ? 'Сводки посещаемости' : 'Отчёты, доставленные вам в Telegram'}><ClassSelect items={classes} value={selected.value} change={value => { selected.change(value); setDay('') }} />
      {canBrowse && <label className="inline-field"><span>Дата</span><input type="date" value={day || me.today} max={me.today} onChange={e => setDay(e.target.value)}/></label>}
      {owner && <Button variant="outline" disabled={!current?.active || !query.data?.day || action.busy} onClick={() => setSend(crypto.randomUUID().replaceAll('-', ''))}><Send size={17}/> Отправить отчёт</Button>}</PageTitle>
    {owner && <div className="segmented"><button aria-pressed={tab === 'report'} onClick={() => setTab('report')}>Отчёт</button><button aria-pressed={tab === 'delivery'} onClick={() => setTab('delivery')}>История доставки</button></div>}
    {!selected.value ? <Panel><Empty title="Нет доступных классов"/></Panel> : tab === 'delivery' ? <DeliveryList classId={selected.value} key={selected.value}/> :
      query.isPending ? <Panel><Pending/></Panel> : query.error ? <Failure error={query.error} retry={() => query.refetch()}/> : <Panel title="Отчёт о посещаемости" subtitle={query.data.day ? formatDay(query.data.day, true) : undefined}
        actions={!owner && query.data.dates.length > 0 ? <label className="inline-field"><span>Дата</span><select value={day || query.data.day || ''} onChange={e => setDay(e.target.value)}>{query.data.dates.map(date => <option key={date} value={date}>{formatDay(date, true)}</option>)}</select></label> : undefined}>
        {query.data.parts.length ? <article className="report-sheet">{query.data.parts.map((part, index) => <div className="report-part" key={index}>{part.split('\n').map((line, n) => {
          if (!line) return <br key={n}/>
          if (/^(✅|🤒|📝|❌|⏳).*\([0-9]+\)|^📊/.test(line)) return <h3 key={n}>{line}</h3>
          return <div key={n}>{line}</div>
        })}</div>)}</article> : <Empty title="Пока нет доставленных отчётов" description="После первой доставки отчёт появится в этом разделе."/>}
      </Panel>}
    {send && <Confirm title="Отправить отчёт?" text={`Получатели класса ${current?.name} получат отчёт за ${formatDay(query.data?.day ?? me.today)}.`}
      label="Отправить" busy={action.busy} onClose={() => setSend(undefined)} onConfirm={async () => {
        const result = await action.run(() => api<{ sent: number; total: number }>(`/classes/${selected.value}/send`, 'POST', {
          request_id: send, day: query.data?.day ?? me.today,
        }), result => result.total ? `Отчёт доставлен: ${result.sent} из ${result.total}` : 'Нет доступных получателей')
        if (result) setSend(undefined)
      }}/>}
  </>
}

function DeliveryList({ classId }: { classId: number }) {
  const { timezone } = useSession()
  const [page, setPage] = useState(0)
  const data = useData<Page<Delivery>>(`/classes/${classId}/deliveries?page=${page}`, 12000)
  return <Panel title="История доставки">{data.isPending ? <Pending/> : data.error ? <Failure error={data.error}/> : data.data.items.length === 0 ? <Empty title="Отправок пока нет"/> : <>
    <div className="table-wrap"><table><thead><tr><th>Дата</th><th>Получатель</th><th>Тип</th><th>Результат</th><th>Части</th></tr></thead><tbody>{data.data.items.map(item => <tr key={item.id}>
      <td>{formatDay(item.day)}<small className="block muted">{formatTime(item.time, timezone)}</small></td><td>{item.telegram_id}</td><td>{deliveryLabels[item.kind] ?? item.kind}</td>
      <td><span className={`badge ${item.status === 'sent' ? 'badge-green' : item.error ? 'badge-rose' : 'badge-slate'}`}>{deliveryLabels[item.status] ?? item.status}</span>
        {item.error && <small className="block muted">{item.error}</small>}</td><td>{item.parts_sent}/{item.parts_total}</td></tr>)}</tbody></table></div>
    <Pagination page={data.data.page} count={data.data.total} size={20} change={setPage}/>
  </>}</Panel>
}

export function SchedulePage() {
  const me = useSession()
  const selected = useClass(me.managed)
  const data = useData<Schedule>(selected.value ? `/classes/${selected.value}/schedule` : null)
  return <>
    <PageTitle title="Расписание" subtitle="Автоматические отчёты и напоминания"><ClassSelect items={me.managed} {...selected}/></PageTitle>
    {!selected.value ? <Panel><Empty title="Нет активных классов"/></Panel> : data.isPending ? <Panel><Pending/></Panel> : data.error ? <Failure error={data.error}/> : <>
      <div className="dashboard-grid settings-grid"><ScheduleEditor classId={selected.value} initial={data.data} key={selected.value}/><Recipients classId={selected.value}/></div>
      <DeliveryList key={selected.value} classId={selected.value}/>
    </>}
  </>
}

function ScheduleEditor({ classId, initial }: { classId: number; initial: Schedule }) {
  const [values, setValues] = useState(initial)
  const [confirm, setConfirm] = useState<'send' | 'delete' | 'disable' | null>(null)
  const requestId = useRef('')
  const action = useAction()
  const base = `/classes/${classId}`
  const days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
  async function save(enabled: boolean) {
    const { deleted: _, ...body } = values
    const result = await action.run(() => api<Schedule>(`${base}/schedule`, 'PUT', { ...body, enabled }), 'Расписание сохранено')
    if (result) { setValues(result); setConfirm(null) }
  }
  async function execute() {
    if (confirm === 'disable') { await save(false); return }
    if (confirm === 'delete') {
      const result = await action.run(() => api<Schedule>(`${base}/schedule`, 'DELETE'), 'Расписание удалено')
      if (result) { setValues(result); setConfirm(null) }
      return
    }
    if (await action.run(() => api<{ sent: number; total: number }>(`${base}/send`, 'POST', { request_id: requestId.current }),
      result => result.total ? `Отчёт доставлен: ${result.sent} из ${result.total}` : 'Нет доступных получателей')) setConfirm(null)
  }
  return <Panel title="Правила отправки" subtitle={values.deleted ? 'Расписание удалено. Заполните поля, чтобы создать его заново.' : undefined}>
    <form className="panel-form schedule-form" onSubmit={e => { e.preventDefault(); save(values.enabled) }}>
      <label className="switch"><input type="checkbox" checked={values.enabled} onChange={e => setValues({ ...values, enabled: e.target.checked })}/><span/> Включить автоматическую рассылку</label>
      <div className="form-grid"><label className="field">Время отправки<input type="time" value={values.time} required onChange={e => setValues({ ...values, time: e.target.value })}/></label>
        <label className="field">Часовой пояс<input list="timezones" required maxLength={64} value={values.timezone} onChange={e => setValues({ ...values, timezone: e.target.value })}/>
          <datalist id="timezones">{['Asia/Tashkent','Asia/Almaty','Asia/Bishkek','Europe/Moscow','Europe/Berlin','UTC'].map(zone => <option key={zone} value={zone}/>)}</datalist></label></div>
      <fieldset><legend>Дни недели</legend><div className="weekdays">{days.map((day, i) => <button type="button" key={day} aria-pressed={values.weekdays.includes(i)} onClick={() => setValues({ ...values,
        weekdays: values.weekdays.includes(i) ? values.weekdays.filter(n => n !== i) : [...values.weekdays, i] })}>{day}</button>)}</div></fieldset>
      <div className="form-grid"><label className="field">Первое напоминание<input type="time" value={values.reminder_one ?? ''} onChange={e => setValues({ ...values, reminder_one: e.target.value || null })}/></label>
        <label className="field">Второе напоминание<input type="time" value={values.reminder_two ?? ''} onChange={e => setValues({ ...values, reminder_two: e.target.value || null })}/></label></div>
      <div className="toolbar schedule-actions"><Button disabled={action.busy || values.weekdays.length === 0}><Clock size={17}/> Сохранить</Button>
        <Button type="button" variant="outline" disabled={action.busy} onClick={() => {
          requestId.current = crypto.randomUUID().replaceAll('-', ''); setConfirm('send')
        }}><Send size={16}/> Отправить сейчас</Button>
        {initial.enabled && <Button type="button" variant="outline" disabled={action.busy} onClick={() => setConfirm('disable')}>Отключить</Button>}
        {!values.deleted && <Button type="button" variant="danger" disabled={action.busy} onClick={() => setConfirm('delete')}><Trash2 size={16}/> Удалить</Button>}</div>
    </form>
    {confirm && <Confirm title={{ send: 'Отправить отчёт сейчас?', delete: 'Удалить расписание?', disable: 'Отключить рассылку?' }[confirm]}
      text={{ send: 'Отчёт за сегодня получат все активные получатели класса.', delete: 'Автоматические отправки остановятся. История доставок сохранится.', disable: 'Отчёты и напоминания будут приостановлены.' }[confirm]}
      label={{ send: 'Отправить', delete: 'Удалить', disable: 'Отключить' }[confirm]} busy={action.busy} onClose={() => setConfirm(null)} onConfirm={execute}/>}
  </Panel>
}

function Recipients({ classId }: { classId: number }) {
  const data = useData<Team>(`/classes/${classId}/access`)
  const [target, setTarget] = useState('')
  const [remove, setRemove] = useState<Person>()
  const action = useAction()
  async function change(id: number, operation: 'recipient_add' | 'recipient_remove') {
    return action.run(() => api(`/users/${id}/access`, 'POST', { class_id: classId, operation }), 'Получатели обновлены')
  }
  return <Panel title="Получатели отчётов" subtitle="Чтобы получать сообщения, пользователь должен нажать /start в боте.">
    {data.isPending ? <Pending/> : data.error ? <Failure error={data.error}/> : data.data.recipients.length ? <ul className="history-list">{data.data.recipients.map(({ user }) => <li key={user.id}>
      <div><strong>{user.name}</strong><small className="block muted">{user.blocked ? 'Заблокирован' : user.id}</small></div><Button variant="ghost" size="icon" aria-label={`Удалить получателя ${user.name}`} onClick={() => setRemove(user)}><X size={17}/></Button></li>)}</ul> : <Empty title="Получателей пока нет"/>}
    <form className="panel-form" onSubmit={async e => { e.preventDefault(); if (await change(Number(target), 'recipient_add')) setTarget('') }}>
      <label className="field">Telegram ID получателя<input maxLength={16} pattern="[0-9]+" inputMode="numeric" required value={target} onChange={e => setTarget(e.target.value)}/></label>
      <div className="toolbar"><Button disabled={action.busy}><Plus size={17}/> Добавить</Button><Button asChild variant="ghost"><Link to="/users"><UsersRound size={17}/> Пользователи</Link></Button></div>
    </form>
    {remove && <Confirm title="Удалить получателя?" text={`Отчёты класса для ${remove.name} будут отключены.`} label="Удалить" busy={action.busy} onClose={() => setRemove(undefined)} onConfirm={async () => {
      if (await change(remove.id, 'recipient_remove')) setRemove(undefined)
    }}/>}
  </Panel>
}

export function AuditPage() {
  const { timezone } = useSession()
  const [page, setPage] = useState(0)
  const data = useData<Page<AuditItem>>(`/admin/audit-logs?page=${page}`, 30000)
  return <><PageTitle title="Журнал действий" subtitle="Изменения в школе, права доступа и отправка отчётов"/>
    <Panel>{data.isPending ? <Pending/> : data.error ? <Failure error={data.error}/> : data.data.items.length === 0 ? <Empty title="Нет записей"/> : <>
      <div className="table-wrap"><table><thead><tr><th>Дата и время</th><th>Действие</th><th>Кто</th><th>Подробности</th></tr></thead><tbody>{data.data.items.map(item => <tr key={item.id}>
        <td>{formatTime(item.time, timezone, true)}</td><td><strong>{activities[item.action] ?? item.action}</strong></td><td>{item.by ?? 'Система'}</td><td>{item.details || (item.entity_id ? `Запись ${item.entity_id}` : '—')}</td></tr>)}</tbody></table></div>
      <Pagination page={data.data.page} count={data.data.total} size={20} change={setPage}/>
    </>}</Panel>
  </>
}
