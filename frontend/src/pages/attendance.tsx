import { ArrowDownToLine, ArrowRight, Check, ClipboardCheck, ClipboardList,
  FileText, GraduationCap, MessageSquare, Search, UsersRound } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, download } from '../api'
import { attendanceRate, colors, formatDay, formatTime, initials, statuses, statusOrder, sum, toDay } from '../domain'
import type { Attendance, Entry, SchoolClass } from '../types'
import { DayLessons, type Timetable } from './timetable'
import { Button, ClassSelect, Confirm, Empty, Failure, Modal, PageTitle, Panel, Pending, StatusBadge,
  useAction, useClass, useData, useSession } from '../ui'

const zero = [0, 0, 0, 0, 0]

function Counts({ counts, period = false }: { counts: number[]; period?: boolean }) {
  const cards = [{ title: period ? 'Записей за период' : 'Всего учеников', amount: sum(counts), icon: UsersRound, color: 'indigo' },
    ...statusOrder.map(i => ({ title: statuses[i].group, amount: counts[i], icon: statuses[i].icon, color: statuses[i].color }))]
  return <div className="metrics">{cards.map(({ title, amount, icon: Icon, color }) => <div className="metric" key={title}>
    <span className={`metric-icon badge-${color}`}><Icon size={18} /></span><strong>{amount}</strong><span>{title}</span>
  </div>)}</div>
}

function Donut({ counts }: { counts: number[] }) {
  const total = sum(counts)
  const chart = total ? statusOrder.map(status => ({ name: statuses[status].group, value: counts[status], color: colors[status] })).filter(item => item.value)
    : [{ name: 'Нет данных', value: 1, color: 'var(--line)' }]
  return <div className="donut-section"><div className="donut">
    <ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={chart} dataKey="value" nameKey="name" innerRadius="71%" outerRadius="93%" paddingAngle={chart.length > 1 ? 3 : 0} stroke="none" startAngle={90} endAngle={-270} isAnimationActive={false}>
      {chart.map(item => <Cell key={item.name} fill={item.color} />)}</Pie></PieChart></ResponsiveContainer>
    <div className="donut-caption"><strong>{attendanceRate(counts)}%</strong><span>присутствуют</span></div>
  </div><ul className="legend">{statusOrder.map(i => <li key={i}><span style={{ background: colors[i] }} /><span>{statuses[i].group}</span><strong>{counts[i]}</strong></li>)}</ul></div>
}

export function ManagerDashboard() {
  const me = useSession()
  const selected = useClass(me.managed)
  const current = me.managed.find(item => item.id === selected.value)
  const daily = useData<Attendance>(current ? `/classes/${current.id}/attendance` : null, 12000)
  const counts = daily.data?.counts ?? zero
  const total = sum(counts)
  const marked = total - counts[0]
  return <>
    <PageTitle title="Мой класс" subtitle={formatDay(me.today, true)}>
      <ClassSelect items={me.managed} {...selected} />
    </PageTitle>
    {!current ? <Panel><Empty title="Нет назначенных классов" /></Panel> : <>
      <section className="hero"><div className="hero-copy"><div className="hero-meta"><GraduationCap size={17} /> {me.school} <span /> {current.name}</div><h2>Посещаемость сегодня</h2>
        <p>{daily.data ? <>Отмечено <b>{marked} из {total}</b> учеников</> : 'Сводка по выбранному классу'}</p>
        <div className="hero-progress" role="progressbar" aria-label="Ученики с отметкой" aria-valuenow={total ? Math.round(marked / total * 100) : 0}><span style={{ width: `${total ? marked / total * 100 : 0}%` }} /></div>
      </div><Button className="hero-button" asChild><Link to={`/attendance?class=${current.id}`}><ClipboardCheck size={19} />Начать отметку<ArrowRight size={18} /></Link></Button></section>
      {daily.isPending ? <Panel><Pending /></Panel> : daily.error ? <Failure error={daily.error} retry={() => daily.refetch()} /> : <Counts counts={counts} />}
      <div className="dashboard-grid single">
        <Panel title="Распределение отметок" subtitle="Сегодня, выбранный класс"><Donut counts={counts} /></Panel>
      </div>
    </>}
  </>
}

export function AttendancePage() { return <AttendanceView /> }
export function HistoryPage() { return <AttendanceView history /> }

function AttendanceView({ history = false }: { history?: boolean }) {
  const me = useSession()
  const owner = me.roles.includes('OWNER')
  const archived = useData<SchoolClass[]>(owner && history ? '/classes' : null)
  const classes = history ? (owner ? (archived.data ?? me.managed) : me.managed.filter(item => item.can_history)) : me.managed
  const selected = useClass(classes)
  const [day, setDay] = useState(history ? toDay(me.today, -1) : me.today)
  const current = classes.find(item => item.id === selected.value)
  const weekday = owner || current?.can_history ? day || me.today : me.today
  const base = current ? `/classes/${current.id}/attendance` : ''
  const query = useData<Attendance>(base ? `${base}?day=${weekday}` : null, 12000)
  const timetable = useData<Timetable>(current?.active ? `/classes/${current.id}/timetable?day=${weekday}` : null, 15000)
  const [showChanges, setShowChanges] = useState(false)
  const changes = useData<{ id: number; student_id: number; actor: string; time: string; before_status: number; after_status: number; before_reason: string | null; after_reason: string | null }[]>(
    base && showChanges ? `${base}/history?day=${weekday}` : null)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')
  const [confirm, setConfirm] = useState<'all' | null>(null)
  const [reason, setReason] = useState<{ entry: Entry; status: number; text: string } | null>(null)
  const [saving, setSaving] = useState<number>()
  const action = useAction()
  const navigate = useNavigate()
  const marked = query.data ? query.data.entries.length - query.data.counts[0] : 0
  const writable = !!query.data?.writable
  const entries = query.data?.entries.filter(item => item.name.toLocaleLowerCase('ru').includes(search.trim().toLocaleLowerCase('ru'))
    && (filter === 'all' || item.status === Number(filter))) ?? []

  async function save(entry: Entry, status: number, text: string | null = null) {
    setSaving(entry.id)
    const result = await action.run(() => api<Entry>(`${base}/${entry.id}?day=${weekday}`, 'PUT', { status, version: entry.version, reason: text }), 'Отметка сохранена')
    setSaving(undefined)
    if (result) setReason(null)
    else setReason(previous => previous?.entry.id === entry.id ? null : previous)
  }

  return <>
    <PageTitle title={history ? 'История посещаемости' : 'Посещаемость'} subtitle="Отметки по ученикам и классам">
      <ClassSelect items={classes} {...selected} />{(owner || current?.can_history) && <label className="inline-field"><span>Дата</span><input aria-label="Дата отметок" type="date" required value={day} max={me.today} onChange={event => setDay(event.target.value)} /></label>}
      {owner && current && <Button asChild variant="outline"><Link to={`/reports?class=${current.id}&day=${weekday}`}><FileText size={17}/> Отчёт за этот день</Link></Button>}
    </PageTitle>
    {timetable.data && <Panel title="Уроки выбранного дня"><DayLessons plan={timetable.data.days[0]} subjects={timetable.data.subjects} compact/></Panel>}
    {!current ? <Panel><Empty title="Нет доступных классов" /></Panel> : query.isPending ? <Panel><Pending /></Panel> : query.error ? <Failure error={query.error} retry={() => query.refetch()} /> : <>
      <section className="progress-panel"><span className="metric-icon badge-green"><ClipboardList size={21} /></span><div><strong>Отмечено {marked} из {query.data.entries.length}</strong><div className="progress"><span style={{ width: `${query.data.entries.length ? marked / query.data.entries.length * 100 : 0}%` }} /></div></div>
        {writable && <div className="progress-buttons"><Button variant="outline" onClick={() => setConfirm('all')} disabled={action.busy || query.data.counts[0] === 0}><Check size={17} /> Отметить всех присутствующими</Button>
          <Button disabled={action.busy || query.data.entries.length === 0} onClick={async () => {
            const saved = await action.run(() => api(`${base}/finish?day=${weekday}`, 'POST'), 'Отметка завершена')
            if (saved) navigate(`/?class=${selected.value}`)
          }}><ClipboardCheck size={17} /> Сохранить и завершить</Button></div>}
      </section>
      <Panel title="Ученики" subtitle={writable ? 'Изменения сохраняются автоматически' : 'Просмотр отметок'}
        actions={<Button variant="outline" size="small" onClick={() => setShowChanges(!showChanges)}>История исправлений</Button>}>
        <div className="toolbar"><label className="search"><Search size={17}/><input aria-label="Поиск по ученикам" placeholder="Поиск по имени" value={search} onChange={event => setSearch(event.target.value)} /></label>
          <select aria-label="Фильтр по статусу" value={filter} onChange={event => setFilter(event.target.value)}><option value="all">Все статусы</option>{statuses.map((status, i) => <option key={i} value={i}>{status.name}</option>)}</select></div>
        {!entries.length ? <Empty title="Ученики не найдены" /> : <div className="attendance-rows">{entries.map(item => <div className="attendance-row" key={item.id}>
          <div className="student-identity"><span aria-hidden="true" className="avatar avatar-soft">{initials(item.name)}</span><div><strong>{item.name}</strong><small>{item.updated_at ? `${formatTime(item.updated_at, me.timezone)} · ${item.author ?? 'Пользователь Telegram'}` : 'Отметки ещё нет'}</small>{item.reason && <p>{item.reason}</p>}</div></div>
          <div className="mark-controls">{!writable ? <StatusBadge status={item.status} /> : <>
            <div className="status-pick" aria-label={`Статус · ${item.name}`}>{statusOrder.map(status => { const s = statuses[status]; const Icon = s.icon; return <button type="button" key={status} className={`status-button ${item.status === status ? `badge-${s.color} picked` : ''}`}
              title={s.name} aria-label={`${s.name} · ${item.name}`} aria-pressed={item.status === status} disabled={action.busy} onClick={() => status === 3 ? setReason({ entry: item, status, text: item.reason ?? '' }) : save(item, status)}><Icon size={17} /><span>{s.short}</span></button> })}</div>
            {item.status >= 2 && <Button size="icon" variant="ghost" title="Изменить комментарий" aria-label={`Комментарий · ${item.name}`} onClick={() => setReason({ entry: item, status: item.status, text: item.reason ?? '' })}><MessageSquare size={17}/></Button>}
          </>}{saving === item.id && <span className="saving">Сохраняем…</span>}</div>
        </div>)}</div>}
      </Panel>
      {showChanges && <Panel title="История исправлений">{changes.isPending ? <Pending/> : changes.error ? <Failure error={changes.error}/> : changes.data.length ? <ul className="history-list">{changes.data.map(item => <li key={item.id}><div><strong>{query.data.entries.find(entry => entry.id === item.student_id)?.name ?? `Ученик ${item.student_id}`}</strong>
        <small>{statuses[item.before_status].name} → {statuses[item.after_status].name}{item.after_reason && ` · ${item.after_reason}`}</small></div><small>{formatTime(item.time, me.timezone)} · {item.actor}</small></li>)}</ul> : <Empty title="Отметки ещё не исправлялись"/>}</Panel>}
    </>}
    {confirm && <Confirm title="Отметить всех присутствующими" text="Отметку получат только ученики со статусом «Не отмечен»." label="Подтвердить" onClose={() => setConfirm(null)} busy={action.busy} onConfirm={async () => {
      const result = await action.run(() => api<{ changed: number }>(`${base}/mark-all?day=${weekday}`, 'POST'), ({ changed }) => `Отмечено учеников: ${changed}`)
      if (result) setConfirm(null)
    }} />}
    {reason && <Modal open onOpenChange={open => !open && setReason(null)} title={statuses[reason.status].name} description={reason.entry.name}>
      <form onSubmit={(event: FormEvent) => { event.preventDefault(); save(reason.entry, reason.status, reason.text.trim() || null) }}>
        <label className="field">Комментарий, необязательно<textarea maxLength={300} rows={3} value={reason.text} onChange={event => setReason({ ...reason, text: event.target.value })} /></label>
        <div className="dialog-actions"><Button variant="outline" type="button" onClick={() => setReason(null)}>Отмена</Button><Button disabled={action.busy}>Сохранить отметку</Button></div>
      </form>
    </Modal>}
  </>
}

interface Stats { counts: number[]; timeline: { day: string; counts: number[] }[] }
export function Statistics() {
  const me = useSession()
  const owner = me.roles.includes('OWNER')
  const classes = useData<SchoolClass[]>(owner ? '/classes' : null)
  const available = owner ? (classes.data ?? me.managed) : me.managed.filter(item => item.can_view_statistics)
  const selected = useClass(available)
  const [range, setRange] = useState({ start: toDay(me.today, -(me.statistics_days ?? 7) + 1), end: me.today })
  const [preset, setPreset] = useState(me.statistics_days === 1 ? 'day' : me.statistics_days === 30 ? 'month' : 'week')
  const [showComparison, setShowComparison] = useState(false)
  const valid = range.start && range.end && range.start <= range.end
  const params = `start=${range.start}&end=${range.end}`
  const data = useData<Stats>(selected.value && valid ? `/classes/${selected.value}/stats?${params}` : null)
  const comparison = useData<{ class: SchoolClass; counts: number[] }[]>(owner && showComparison && valid ? `/admin/stats/comparison?${params}` : null)
  const action = useAction()
  const series = data.data?.timeline.map(item => ({ date: formatDay(item.day), rate: attendanceRate(item.counts) })) ?? []
  const rangeButtons = [['day', 'День'], ['week', 'Неделя'], ['month', 'Месяц']]
  function choose(type: string) {
    setPreset(type)
    setRange({ start: toDay(me.today, type === 'day' ? 0 : type === 'week' ? -6 : -29), end: me.today })
  }
  return <>
    <PageTitle title="Статистика" subtitle="Посещаемость по дням и классам"><ClassSelect items={available} {...selected} />
      {owner && <><Button variant="outline" onClick={() => setShowComparison(!showComparison)} aria-pressed={showComparison}>Сравнить классы</Button>
        <Button variant="outline" disabled={!data.data || action.busy} onClick={() => action.run(() => download(`/classes/${selected.value}/export?${params}`, 'attendance.xlsx'), 'Отчёт Excel подготовлен')}><ArrowDownToLine size={17} /> Excel</Button></>}
    </PageTitle>
    <div className="toolbar filter-bar"><div className="segmented">{rangeButtons.map(([key, label]) => <button key={key} aria-pressed={preset === key} onClick={() => choose(key)}>{label}</button>)}</div>
      <label className="inline-field"><span>С</span><input type="date" max={me.today} value={range.start} onChange={e => { setPreset(''); setRange({ ...range, start: e.target.value }) }} /></label>
      <label className="inline-field"><span>По</span><input type="date" max={me.today} value={range.end} onChange={e => { setPreset(''); setRange({ ...range, end: e.target.value }) }} /></label></div>
    {!selected.value ? <Panel><Empty title="Нет классов" /></Panel> : !valid ? <Panel><Empty title="Укажите корректный период" /></Panel> : data.isPending ? <Panel><Pending /></Panel> : data.error ? <Failure error={data.error}/> : <>
      <Counts counts={data.data.counts} period={range.start !== range.end} />
      <div className="dashboard-grid"><Panel title="Процент посещаемости" subtitle="Доля присутствующих среди всех учеников за день">
        <div className="line-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={series} margin={{ left: -18, right: 18, top: 8, bottom: 2 }}>
          <CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="4 4" />
          <XAxis dataKey="date" tickLine={false} axisLine={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} minTickGap={32} />
          <YAxis tickLine={false} axisLine={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} domain={[0, 100]} tickFormatter={value => `${value}%`} />
          <Tooltip formatter={value => [`${value}%`, 'Посещаемость']} /><Area type="monotone" dataKey="rate" stroke="#1aaa82" fill="#1aaa82" fillOpacity={0.14} strokeWidth={2.5} isAnimationActive={false} />
        </AreaChart></ResponsiveContainer></div>
      </Panel><Panel title="Итог за период"><Donut counts={data.data.counts} /></Panel></div>
    </>}
    {showComparison && valid && <Panel title="Сравнение активных классов">{comparison.isPending ? <Pending/> : comparison.error ? <Failure error={comparison.error}/> :
      <div className="table-wrap"><table><thead><tr><th>Класс</th><th>Присутствовали</th><th>Всего записей</th><th>Посещаемость</th></tr></thead><tbody>
        {comparison.data.map(item => <tr key={item.class.id}><td>{item.class.name}</td><td>{item.counts[1]}</td><td>{sum(item.counts)}</td><td>{attendanceRate(item.counts)}%</td></tr>)}
      </tbody></table></div>}</Panel>}
  </>
}
