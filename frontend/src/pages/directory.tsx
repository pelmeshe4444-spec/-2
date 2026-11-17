import { Archive, ArrowDownToLine, ArrowRight, BookOpen, ClipboardList, FolderArchive, History, Pencil, Plus, RotateCcw, Search, ShieldCheck, UsersRound } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { api, download } from '../api'
import { formatDay, formatTime, initials, roles, statuses, toDay } from '../domain'
import type { Person, SchoolClass, Student, StudentHistory, Team } from '../types'
import { Button, ClassSelect, Confirm, Empty, Failure, Modal, PageTitle, Pagination, Panel, Pending, StatusBadge,
  useAction, useClass, useData, useSession } from '../ui'

interface NamesResult { added: string[]; duplicates: string[] }
type StudentDialog = { kind: 'add' | 'bulk' } | { kind: 'edit' | 'history' | 'archive' | 'restore'; student: Student }

export function StudentsPage() {
  const me = useSession()
  const classes = useData<SchoolClass[]>('/classes')
  const available = classes.data ?? me.managed
  const selected = useClass(available)
  const current = available.find(item => item.id === selected.value)
  const list = useData<Student[]>(current ? `/classes/${current.id}/students` : null)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('active')
  const [status, setStatus] = useState('all')
  const [sort, setSort] = useState('name')
  const [page, setPage] = useState(0)
  const [dialog, setDialog] = useState<StudentDialog>()
  const action = useAction()
  const pageSize = 12
  const items = (list.data ?? []).filter(item => (filter === 'all' || item.active === (filter === 'active'))
    && (status === 'all' || item.status === Number(status))
    && item.name.toLocaleLowerCase('ru').includes(search.trim().toLocaleLowerCase('ru')))
    .sort((a, b) => sort === 'recent' ? (b.marked_at ?? b.updated_at).localeCompare(a.marked_at ?? a.updated_at) : a.name.localeCompare(b.name, 'ru'))
  const visiblePage = Math.min(page, Math.max(0, Math.ceil(items.length / pageSize) - 1))
  return <>
    <PageTitle title="Ученики" subtitle="Списки классов и личная история"><ClassSelect items={available} value={selected.value} change={id => { selected.change(id); setPage(0) }} />
      <Button variant="outline" disabled={!current?.active} onClick={() => setDialog({ kind: 'bulk' })}><ClipboardList size={17}/> Массовый ввод</Button>
      <Button disabled={!current?.active} onClick={() => setDialog({ kind: 'add' })}><Plus size={18}/> Добавить ученика</Button></PageTitle>
    <Panel><div className="toolbar"><label className="search"><Search size={17}/><input aria-label="Поиск ученика" placeholder="Поиск по имени" value={search} onChange={e => { setSearch(e.target.value); setPage(0) }} /></label>
      <select aria-label="Включение в список" value={filter} onChange={e => { setFilter(e.target.value); setPage(0) }}><option value="active">Активные</option><option value="archived">В архиве</option><option value="all">Все ученики</option></select>
      <select aria-label="Фильтр по отметке" value={status} onChange={e => { setStatus(e.target.value); setPage(0) }}><option value="all">Все статусы</option>{statuses.map((item, i) => <option value={i} key={i}>{item.name}</option>)}</select>
      <select aria-label="Сортировка учеников" value={sort} onChange={e => setSort(e.target.value)}><option value="name">По имени</option><option value="recent">По изменению</option></select></div>
      {!current ? <Empty title="Сначала добавьте класс" /> : list.isPending ? <Pending /> : list.error ? <Failure error={list.error} retry={() => list.refetch()} /> : !items.length ? <Empty title="Ученики не найдены" /> : <>
        <div className="table-wrap"><table><thead><tr><th>Ученик</th><th>Класс</th><th>Статус сегодня</th><th>Изменено</th><th>Действия</th></tr></thead><tbody>
          {items.slice(visiblePage * pageSize, (visiblePage + 1) * pageSize).map(item => <tr key={item.id}><td><button className="text-button student-link" onClick={() => setDialog({ kind: 'history', student: item })}><span aria-hidden="true" className="avatar avatar-soft">{initials(item.name)}</span>{item.name}</button></td><td>{current.name}</td><td>{item.active ? <StatusBadge status={item.status} /> : <span className="badge badge-slate">В архиве</span>}</td><td>{formatTime(item.marked_at ?? item.updated_at, me.timezone, true)}</td>
            <td><div className="table-actions">{current.active && (item.active ? <>
              <Button size="icon" variant="ghost" aria-label={`Редактировать · ${item.name}`} onClick={() => setDialog({ kind: 'edit', student: item })}><Pencil size={16}/></Button>
              <Button size="icon" variant="ghost" aria-label={`Архивировать · ${item.name}`} onClick={() => setDialog({ kind: 'archive', student: item })}><Archive size={17}/></Button></> :
              <Button size="icon" variant="ghost" aria-label={`Восстановить · ${item.name}`} onClick={() => setDialog({ kind: 'restore', student: item })}><RotateCcw size={17}/></Button>)}</div></td></tr>)}
        </tbody></table></div><Pagination page={visiblePage} size={pageSize} count={items.length} change={setPage} />
      </>}
    </Panel>
    {dialog && (dialog.kind === 'add' || dialog.kind === 'bulk') && <AddStudent classId={selected.value} bulk={dialog.kind === 'bulk'} close={() => setDialog(undefined)} />}
    {dialog?.kind === 'edit' && <EditStudent student={dialog.student} classes={me.managed} close={() => setDialog(undefined)} />}
    {dialog?.kind === 'history' && <PupilHistory student={dialog.student} close={() => setDialog(undefined)} />}
    {dialog && (dialog.kind === 'archive' || dialog.kind === 'restore') && <Confirm title={dialog.kind === 'archive' ? 'Архивировать ученика?' : 'Восстановить ученика?'}
      text={`${dialog.student.name} · ${dialog.kind === 'archive' ? 'История посещаемости сохранится.' : 'Ученик снова появится в ежедневном списке.'}`}
      label={dialog.kind === 'archive' ? 'Архивировать' : 'Восстановить'} busy={action.busy} onClose={() => setDialog(undefined)} onConfirm={async () => {
        const success = await action.run(() => api(`/students/${dialog.student.id}${dialog.kind === 'restore' ? '/restore' : ''}`, dialog.kind === 'restore' ? 'POST' : 'DELETE'), 'Список обновлён')
        if (success) setDialog(undefined)
      }} />}
  </>
}

function AddStudent({ classId, bulk, close }: { classId: number; bulk: boolean; close(): void }) {
  const [names, setNames] = useState('')
  const [preview, setPreview] = useState<NamesResult>()
  const action = useAction()
  const path = `/classes/${classId}/students`
  return <Modal open onOpenChange={open => !open && close()} title={bulk ? 'Массовое добавление' : 'Новый ученик'} description={bulk ? 'До 100 строк. Укажите фамилию и имя в каждой строке.' : 'Укажите фамилию и имя через пробел.'}>
    <form onSubmit={async e => {
      e.preventDefault()
      if (bulk && !preview) {
        setPreview(await action.run(() => api<NamesResult>(path, 'POST', { names, bulk, preview: true })))
        return
      }
      const result = await action.run(() => api<NamesResult>(path, 'POST', { names, bulk }), value => `Добавлено: ${value.added.length}. Дубликатов: ${value.duplicates.length}.`)
      if (result) close()
    }}>
      {!preview ? <label className="field">{bulk ? 'Список учеников' : 'Фамилия и имя'}{bulk ? <textarea required maxLength={10000} rows={8} value={names} onChange={e => setNames(e.target.value)}/> : <input required maxLength={97} value={names} onChange={e => setNames(e.target.value)}/>}</label> :
        <div className="preview-list"><strong>Будут добавлены · {preview.added.length}</strong><ol>{preview.added.map(name => <li key={name}>{name}</li>)}</ol>{preview.duplicates.length > 0 && <><strong>Дубликаты · {preview.duplicates.length}</strong><ul>{preview.duplicates.map((name, index) => <li key={`${name}-${index}`}>{name}</li>)}</ul></>}</div>}
      <div className="dialog-actions"><Button type="button" variant="outline" onClick={() => preview ? setPreview(undefined) : close()}>{preview ? 'Исправить список' : 'Отмена'}</Button>
        <Button disabled={action.busy || Boolean(preview && preview.added.length === 0)}>{bulk && !preview ? 'Предпросмотр' : 'Добавить'}</Button></div>
    </form>
  </Modal>
}

function EditStudent({ student, classes, close }: { student: Student; classes: SchoolClass[]; close(): void }) {
  const [name, setName] = useState(student.name)
  const [classId, setClassId] = useState(student.class_id)
  const action = useAction()
  return <Modal open onOpenChange={open => !open && close()} title="Данные ученика" description="Перевод в другой класс вступает в силу завтра.">
    <form onSubmit={async e => { e.preventDefault(); if (await action.run(() => api(`/students/${student.id}`, 'PATCH', { name, class_id: classId }), 'Карточка сохранена')) close() }}>
      <label className="field">Фамилия и имя<input required maxLength={97} value={name} onChange={e => setName(e.target.value)}/></label>
      <label className="field">Класс<select value={classId} onChange={e => setClassId(Number(e.target.value))}>{classes.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
      <div className="dialog-actions"><Button type="button" variant="outline" onClick={close}>Отмена</Button><Button disabled={action.busy}>Сохранить</Button></div>
    </form>
  </Modal>
}

function PupilHistory({ student, close }: { student: Student; close(): void }) {
  const { today } = useSession()
  const [period, setPeriod] = useState({ start: toDay(today, -29), end: today })
  const query = useData<StudentHistory>(period.start && period.end && period.start <= period.end ? `/students/${student.id}?start=${period.start}&end=${period.end}` : null)
  return <Modal open onOpenChange={open => !open && close()} title={student.name} description="История посещаемости ученика">
    <div className="toolbar"><label className="field">Начало<input type="date" value={period.start} max={today} onChange={e => setPeriod({ ...period, start: e.target.value })}/></label><label className="field">Конец<input type="date" value={period.end} max={today} onChange={e => setPeriod({ ...period, end: e.target.value })}/></label></div>
    {!period.start || !period.end || period.start > period.end ? <Empty title="Укажите корректный период"/> : query.isPending ? <Pending/> : query.error ? <Failure error={query.error}/> : query.data.history.length ?
      <ul className="history-list">{query.data.history.map(item => <li key={item.day}><div><strong>{formatDay(item.day)} · {item.class_name}</strong>{item.reason && <p>{item.reason}</p>}</div><StatusBadge status={item.status}/></li>)}</ul> : <Empty title="За этот период отметок нет"/>}
  </Modal>
}

export function ClassPage() {
  const data = useData<SchoolClass[]>('/classes')
  const [edit, setEdit] = useState<{ id?: number; name: string }>()
  const [archive, setArchive] = useState<SchoolClass>()
  const action = useAction()
  return <>
    <PageTitle title="Классы" subtitle="Состав и параметры учёта по классам"><Button onClick={() => setEdit({ name: '' })}><Plus size={18}/> Добавить класс</Button></PageTitle>
    {data.isPending ? <Panel><Pending/></Panel> : data.error ? <Failure error={data.error}/> : data.data.length ? <div className="class-grid">{data.data.map(item =>
      <Panel key={item.id}><div className="class-card"><div className="class-head"><span className="metric-icon badge-indigo"><BookOpen size={22}/></span><div><h2>{item.name}</h2><span className={`badge ${item.active ? 'badge-green' : 'badge-slate'}`}>{item.active ? 'Активен' : 'В архиве'}</span></div></div>
        <div className="class-links"><Button asChild variant="outline" size="small"><Link to={`/students?class=${item.id}`}>Ученики</Link></Button><Button asChild variant="outline" size="small"><Link to={`/statistics?class=${item.id}`}>Статистика</Link></Button>
          {item.active && <><Button asChild variant="outline" size="small"><Link to={`/access?class=${item.id}`}>Доступ</Link></Button><Button asChild variant="outline" size="small"><Link to={`/lessons?class=${item.id}`}>Уроки</Link></Button><Button asChild variant="outline" size="small"><Link to={`/schedule?class=${item.id}`}>Рассылка</Link></Button></>}</div>
        {item.active && <div className="class-actions"><Button variant="ghost" size="small" onClick={() => setEdit(item)}><Pencil size={15}/> Переименовать</Button><Button variant="ghost" size="small" onClick={() => setArchive(item)}><FolderArchive size={16}/> В архив</Button></div>}
      </div></Panel>)}</div> : <Panel><Empty title="Классы ещё не добавлены"/></Panel>}
    {edit && <Modal open onOpenChange={open => !open && setEdit(undefined)} title={edit.id ? 'Переименовать класс' : 'Новый класс'}>
      <form onSubmit={async e => { e.preventDefault(); if (await action.run(() => api(`/classes${edit.id ? `/${edit.id}` : ''}`, edit.id ? 'PATCH' : 'POST', { name: edit.name }), 'Класс сохранён')) setEdit(undefined) }}>
        <label className="field">Название<input required maxLength={32} value={edit.name} onChange={e => setEdit({ ...edit, name: e.target.value })} /></label><div className="dialog-actions"><Button disabled={action.busy}>Сохранить</Button></div>
      </form></Modal>}
    {archive && <Confirm title={`Архивировать ${archive.name}?`} text="Рассылка остановится. Историю класса можно будет посмотреть в статистике." label="Архивировать" busy={action.busy} onClose={() => setArchive(undefined)} onConfirm={async () => {
      if (await action.run(() => api(`/classes/${archive.id}`, 'DELETE'), 'Класс архивирован')) setArchive(undefined)
    }} />}
  </>
}

interface UserRow extends Person { roles: string[]; classes: string[] }
interface UserList { users: UserRow[]; total: number; page: number }
interface UserDetails extends Person { managed: SchoolClass[]; received: SchoolClass[] }

export function UsersPage() {
  const me = useSession()
  const [page, setPage] = useState(0)
  const data = useData<UserList>(`/users?page=${page}`)
  const [adding, setAdding] = useState(false)
  const [telegramId, setTelegramId] = useState('')
  const [target, setTarget] = useState<number>()
  const action = useAction()
  return <>
    <PageTitle title="Пользователи" subtitle="Профили Telegram, роли и доступ к классам"><Button onClick={() => setAdding(true)}><Plus size={17}/> Добавить по Telegram ID</Button></PageTitle>
    <Panel>{data.isPending ? <Pending/> : data.error ? <Failure error={data.error}/> : <>
      <div className="table-wrap"><table><thead><tr><th>Пользователь</th><th>Telegram ID</th><th>Роли</th><th>Классы</th><th>Доступ</th></tr></thead><tbody>{data.data.users.map(item => <tr key={item.id}>
        <td><button className="text-button" onClick={() => setTarget(item.id)}><strong>{item.name}</strong></button>{item.username && <small className="block muted">@{item.username}</small>}</td><td>{item.id}</td><td>{item.roles.map(role => roles[role]).join(', ')}</td><td>{item.classes.join(', ') || '—'}</td>
        <td><span className={`badge ${item.blocked ? 'badge-rose' : item.started ? 'badge-green' : 'badge-slate'}`}>{item.blocked ? 'Заблокирован' : item.started ? 'Запустил бота' : 'Ожидает /start'}</span></td></tr>)}</tbody></table></div>
      <Pagination page={data.data.page} count={data.data.total} size={50} change={setPage}/>
    </>}</Panel>
    {adding && <Modal open onOpenChange={open => !open && setAdding(false)} title="Добавить пользователя" description="Введите числовой ID. Для получения отчётов пользователь должен запустить бота.">
      <form onSubmit={async e => {
        e.preventDefault()
        const user = await action.run(() => api<Person>('/users', 'POST', { telegram_id: Number(telegramId) }), 'Пользователь добавлен')
        if (user) { setAdding(false); setTelegramId(''); setTarget(user.id) }
      }}><label className="field">Telegram ID<input required maxLength={16} pattern="[0-9]+" inputMode="numeric" value={telegramId} onChange={e => setTelegramId(e.target.value)}/></label>
        <div className="dialog-actions"><Button disabled={action.busy}>Добавить</Button></div></form>
    </Modal>}
    {target && <AccessDialog target={target} classes={me.managed} close={() => setTarget(undefined)}/>}
  </>
}

export function AccessPage() {
  const me = useSession()
  const selected = useClass(me.managed)
  const data = useData<Team>(selected.value ? `/classes/${selected.value}/access` : null)
  const [target, setTarget] = useState<number>()
  return <>
    <PageTitle title="Права доступа" subtitle="Ответственные и получатели по классам"><ClassSelect items={me.managed} {...selected}/><Button asChild variant="outline"><Link to="/users"><UsersRound size={17}/> Выбрать пользователя</Link></Button></PageTitle>
    {!selected.value ? <Panel><Empty title="Нет активных классов"/></Panel> : data.isPending ? <Panel><Pending/></Panel> : data.error ? <Failure error={data.error}/> :
      <div className="dashboard-grid">{(['managers', 'recipients'] as const).map(group => <Panel title={group === 'managers' ? 'Ответственные' : 'Получатели отчётов'} key={group}>
        {data.data[group].length ? <div className="list-stack">{data.data[group].map(({ user, history }) => <button className="list-link" onClick={() => setTarget(user.id)} key={user.id}><span className="avatar avatar-soft">{initials(user.name)}</span><span><strong>{user.name}</strong><small>{user.blocked ? 'Заблокирован' : group === 'managers' ? history ? 'История доступна' : 'Только текущий день' : `Telegram ID ${user.id}`}</small></span><ArrowRight size={16}/></button>)}</div> : <Empty title="Назначений пока нет"/>}
      </Panel>)}</div>}
    {target && <AccessDialog target={target} classes={me.managed} initialClass={selected.value} close={() => setTarget(undefined)}/>}
  </>
}

function AccessDialog({ target, classes, initialClass, close }: { target: number; classes: SchoolClass[]; initialClass?: number; close(): void }) {
  const me = useSession()
  const query = useData<UserDetails>(`/users/${target}`)
  const [classId, setClassId] = useState(initialClass ?? classes[0]?.id ?? 0)
  const [confirm, setConfirm] = useState<{ text: string; operation: string }>()
  const action = useAction()
  const manager = query.data?.managed.find(item => item.id === classId)
  const recipient = query.data?.received.some(item => item.id === classId)
  async function change(operation: string) {
    const result = await action.run(() => operation === 'block' || operation === 'unblock'
      ? api(`/users/${target}`, 'PATCH', { blocked: operation === 'block' })
      : api(`/users/${target}/access`, 'POST', { class_id: classId, operation }), 'Доступ обновлён')
    if (result) setConfirm(undefined)
  }
  return <Modal open onOpenChange={open => !open && close()} title={query.data?.name ?? 'Настройка доступа'} description={`Telegram ID · ${target}`}>
    {query.isPending ? <Pending/> : query.error ? <Failure error={query.error}/> : target === me.user.id ? <p className="muted">Владелец Attendance</p> : <>
      <ClassSelect items={classes} value={classId} change={id => { setClassId(id); setConfirm(undefined) }}/>
      {classId > 0 && <div className="permission-list">
        <div><span>Ответственный</span><Button size="small" variant={manager ? 'outline' : 'primary'} disabled={action.busy} onClick={() => manager ? setConfirm({ text: 'Отозвать права ответственного в выбранном классе?', operation: 'manager_remove' }) : change('manager_add')}>{manager ? 'Отозвать' : 'Назначить'}</Button></div>
        {manager && <div><span>Просмотр истории</span><Button size="small" variant="outline" disabled={action.busy} onClick={() => change(manager.can_history ? 'history_off' : 'history_on')}>{manager.can_history ? 'Запретить' : 'Разрешить'}</Button></div>}
        {manager && <div><span>Редактирование уроков</span><Button size="small" variant="outline" disabled={action.busy} onClick={() => action.run(
          () => api(`/users/${target}/classes/${classId}/timetable-access`, 'PUT', { enabled: !manager.can_edit_timetable }), 'Доступ обновлён')}>{manager.can_edit_timetable ? 'Запретить' : 'Разрешить'}</Button></div>}
        <div><span>Получатель отчётов</span><Button size="small" variant={recipient ? 'outline' : 'primary'} disabled={action.busy || !query.data.started} onClick={() => recipient ? setConfirm({ text: 'Отключить отчёты для этого пользователя?', operation: 'recipient_remove' }) : change('recipient_add')}>{recipient ? 'Удалить' : 'Добавить'}</Button></div>
        {!query.data.started && <p className="muted">Для получения отчётов требуется /start в боте.</p>}
      </div>}
      {confirm ? <div className="confirm-inline"><p>{confirm.text}</p><Button variant="outline" size="small" onClick={() => setConfirm(undefined)}>Отмена</Button><Button size="small" disabled={action.busy} onClick={() => change(confirm.operation)}>Подтвердить</Button></div> :
        <Button size="small" variant={query.data.blocked ? 'outline' : 'danger'} disabled={action.busy} onClick={() => query.data.blocked ? change('unblock') : setConfirm({ text: 'Закрыть пользователю вход в приложение и остановить рассылку?', operation: 'block' })}>
          <ShieldCheck size={16}/>{query.data.blocked ? 'Восстановить доступ' : 'Заблокировать доступ'}</Button>}
    </>}
  </Modal>
}

export function SettingsPage({ mode, setMode }: { mode: 'auto' | 'light' | 'dark'; setMode(value: 'auto' | 'light' | 'dark'): void }) {
  const me = useSession()
  const [school, setSchool] = useState(me.school)
  const [confirm, setConfirm] = useState(false)
  const action = useAction()
  return <>
    <PageTitle title="Настройки" subtitle="Профиль школы, внешний вид и данные" />
    <div className="dashboard-grid"><Panel title="Школа"><form className="panel-form" onSubmit={e => { e.preventDefault(); action.run(() => api('/settings', 'PUT', { school }), 'Настройки сохранены') }}>
      <label className="field">Название школы<input required maxLength={120} value={school} onChange={e => setSchool(e.target.value)} /></label><Button disabled={action.busy}>Сохранить</Button></form></Panel>
      <Panel title="Внешний вид"><div className="panel-form"><label className="field">Цветовая схема<select value={mode} onChange={e => setMode(e.target.value as typeof mode)}><option value="auto">Как в Telegram</option><option value="light">Светлая</option><option value="dark">Тёмная</option></select></label></div></Panel></div>
    <Panel title="Администрирование"><div className="quick-links">{me.sqlite && <button onClick={() => setConfirm(true)}><ArrowDownToLine size={19}/><span>Резервная копия SQLite</span><ArrowRight size={16}/></button>}<Link to="/audit"><History size={19}/><span>Журнал действий</span><ArrowRight size={16}/></Link></div></Panel>
    {confirm && <Confirm title="Скачать резервную копию?" text="Файл содержит данные школы. Храните его в месте с ограниченным доступом." label="Скачать" busy={action.busy} onClose={() => setConfirm(false)} onConfirm={async () => {
      const result = await action.run(async () => { await download('/backup', 'attendance.sqlite3'); return true }, 'Резервная копия подготовлена')
      if (result) setConfirm(false)
    }} />}
  </>
}
