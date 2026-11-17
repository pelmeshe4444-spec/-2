import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Atom, BookOpen, Calculator, CalendarDays, ClipboardCopy,
  Dumbbell, FlaskConical, Globe2, GripVertical, Languages, Monitor, Music, Palette, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import { formatDay, formatTime, toDay } from '../domain'
import type { SchoolClass } from '../types'
import { Button, ClassSelect, Confirm, Empty, Failure, Modal, PageTitle, Panel, Pending, useAction, useClass, useData, useSession } from '../ui'

const days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
const icons = { book: BookOpen, calculator: Calculator, globe: Globe2, flask: FlaskConical, music: Music,
  monitor: Monitor, dumbbell: Dumbbell, palette: Palette, languages: Languages, atom: Atom }
const iconNames: Record<keyof typeof icons, string> = { book: 'Книга', calculator: 'Калькулятор', globe: 'Глобус', flask: 'Колба', music: 'Нота',
  monitor: 'Монитор', dumbbell: 'Спорт', palette: 'Палитра', languages: 'Языки', atom: 'Атом' }
export interface Subject { id: number; name: string; color: string; icon: keyof typeof icons; active: boolean }
interface Slot { lesson_number: number; start_time: string; end_time: string }
interface BellSlot extends Slot { shift: string }
interface Lesson extends Slot { weekday: number; subject_id: number; teacher_name: string | null; classroom: string | null; comment: string | null }
interface Plan { name: string; cycle: 'A' | 'B'; active: boolean; effective_from: string; effective_to: string | null; lessons: Lesson[]; revision: number }
interface EditorData { plan: Plan; periods: string[]; subjects: Subject[]; slots: BellSlot[] }
interface DayPlan { day: string; cycle: string; lessons: Lesson[]; regular: Lesson[]; action: 'regular' | 'replace' | 'closed'; comment: string | null; revision: number }
export interface Timetable { class_name: string; days: DayPlan[]; subjects: Subject[]; editable: boolean }
interface Change { id: number; key: string; target: string; before: { lessons: Lesson[] }; after: { lessons: Lesson[] }; changed_at: string; actor: string | null }

const dayIndex = (day: string) => (new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7
const sorted = (list: Lesson[]) => [...list].sort((a, b) => a.weekday - b.weekday || a.lesson_number - b.lesson_number)
const key = (lesson: Lesson) => `${lesson.weekday}:${lesson.lesson_number}`
const minutes = (time: string) => Number(time.slice(0, 2)) * 60 + Number(time.slice(3))

function LessonBadge({ subject }: { subject?: Subject }) {
  const Icon = icons[subject?.icon ?? 'book'] ?? BookOpen
  return <span className="lesson-glyph" style={{ color: subject?.color, backgroundColor: `${subject?.color ?? '#64748b'}23` }}><Icon size={17}/></span>
}

export function DayLessons({ plan, subjects, compact = false }: { plan: DayPlan; subjects: Subject[]; compact?: boolean }) {
  if (!plan.lessons.length) return <Empty title={plan.action === 'closed' ? 'Выходной день' : 'Нет уроков'} description={plan.comment ?? undefined}/>
  return <div className="lesson-list">{plan.action !== 'regular' && <p className="lesson-change badge badge-amber">Изменено на эту дату{plan.comment ? ` · ${plan.comment}` : ''}</p>}
    {plan.lessons.map((lesson, index) => {
      const subject = subjects.find(item => item.id === lesson.subject_id)
      const gap = index > 0 ? minutes(lesson.start_time) - minutes(plan.lessons[index - 1].end_time) : 0
      return <div key={key(lesson)}>{gap > 0 && !compact && <p className="lesson-break">Перемена · {gap} мин</p>}
        <div className="lesson-line"><span className="lesson-number">{lesson.lesson_number}</span><LessonBadge subject={subject}/><div className="lesson-details">
          <strong>{subject?.name ?? 'Предмет'}</strong>{!compact && <><small>{[lesson.teacher_name, lesson.classroom && `каб. ${lesson.classroom}`].filter(Boolean).join(' · ')}</small>{lesson.comment && <small>{lesson.comment}</small>}</>}</div><time>{lesson.start_time}–{lesson.end_time}</time></div></div>
    })}</div>
}

export function TimetablePage() {
  const me = useSession()
  const owner = me.roles.includes('OWNER')
  const choices = me.member && !me.managed.some(item => item.id === me.member?.id) ? [...me.managed, me.member] : me.managed
  const selected = useClass(choices)
  const [day, setDay] = useState(me.today)
  const [view, setView] = useState<'day' | 'week'>('day')
  const [tab, setTab] = useState<'view' | 'editor' | 'subjects' | 'bells' | 'history'>('view')
  const base = `/classes/${selected.value}/timetable`
  const query = useData<Timetable>(selected.value ? `${base}?day=${day}&week=${view === 'week'}` : null, 15000)
  const editable = owner || query.data?.editable
  return <>
    <PageTitle title={me.managed.length || owner ? 'Расписание уроков' : 'Моё расписание'} subtitle="Уроки, звонки и изменения по датам">
      <ClassSelect items={choices} value={selected.value} change={id => { selected.change(id); setTab('view') }}/>
    </PageTitle>
    {!selected.value ? <Panel><Empty title="Нет доступных классов"/></Panel> : <>
      {editable && <div className="segmented timetable-tabs">{([['view','Просмотр'],['editor','Редактор недели'], ...(owner ? [['subjects','Предметы'],['bells','Звонки'],['history','История']] : [])] as const).map(([id, label]) =>
        <button key={id} aria-pressed={tab === id} onClick={() => setTab(id as typeof tab)}>{label}</button>)}</div>}
      {tab === 'view' && <><div className="toolbar filter-bar"><div className="segmented">
        <button aria-pressed={view === 'day' && day === me.today} onClick={() => { setDay(me.today); setView('day') }}>Сегодня</button>
        <button aria-pressed={view === 'day' && day === toDay(me.today, 1)} onClick={() => { setDay(toDay(me.today, 1)); setView('day') }}>Завтра</button>
        <button aria-pressed={view === 'week'} onClick={() => setView('week')}>Неделя</button></div>
        <Button variant="outline" size="icon" aria-label="Предыдущий период" onClick={() => setDay(toDay(day, view === 'week' ? -7 : -1))}><ArrowLeft size={17}/></Button>
        <label className="inline-field">Дата<input aria-label="Дата расписания" type="date" value={day} onChange={e => e.target.value && setDay(e.target.value)}/></label>
        <Button variant="outline" size="icon" aria-label="Следующий период" onClick={() => setDay(toDay(day, view === 'week' ? 7 : 1))}><ArrowRight size={17}/></Button></div>
        {query.isPending ? <Pending/> : query.error ? <Failure error={query.error} retry={() => query.refetch()}/> : <div className="lesson-days">
          {query.data.days.map(plan => <Panel key={plan.day} title={`${days[dayIndex(plan.day)]} · ${formatDay(plan.day)}`}
            subtitle={`${query.data.class_name} · неделя ${plan.cycle}`} actions={editable ? <DateEditor classId={selected.value} plan={plan}/> : undefined}>
            <DayLessons plan={plan} subjects={query.data.subjects}/></Panel>)}
        </div>}</>}
      {tab === 'editor' && editable && <WeekPage key={selected.value} classId={selected.value} classes={choices}/>}
      {tab === 'subjects' && owner && <Subjects/>}
      {tab === 'bells' && owner && <Bells key={selected.value} classId={selected.value}/>}
      {tab === 'history' && owner && <ChangeHistory key={selected.value} classId={selected.value}/>}
    </>}
  </>
}

function Blank(weekday: number, lesson_number: number, subject: Subject | undefined, slot?: Slot): Lesson {
  return { weekday, lesson_number, subject_id: subject?.id ?? 0, start_time: slot?.start_time ?? '', end_time: slot?.end_time ?? '',
    teacher_name: null, classroom: null, comment: null }
}

function LessonForm({ value, subjects, slots, fixedDay, close, save }: { value: Lesson; subjects: Subject[]; slots: Slot[]; fixedDay?: boolean; close(): void; save(value: Lesson): void }) {
  const [lesson, setLesson] = useState(value)
  function setNumber(lesson_number: number) {
    const interval = slots.find(slot => slot.lesson_number === lesson_number)
    setLesson({ ...lesson, lesson_number, ...(interval ? { start_time: interval.start_time, end_time: interval.end_time } : {}) })
  }
  return <Modal open title="Урок" onOpenChange={open => !open && close()}>
    <form onSubmit={event => { event.preventDefault(); save(lesson) }}>
      <label className="field">Предмет<select value={lesson.subject_id || ''} required onChange={e => setLesson({ ...lesson, subject_id: Number(e.target.value) })}>
        <option value="">Выберите предмет</option>{subjects.filter(item => item.active || item.id === lesson.subject_id).map(item => <option value={item.id} key={item.id}>{item.name}{item.active ? '' : ' (архив)'}</option>)}</select></label>
      <div className="form-grid"><label className="field">День недели<select value={lesson.weekday} disabled={fixedDay} onChange={e => setLesson({ ...lesson, weekday: Number(e.target.value) })}>
        {days.map((day, index) => <option value={index} key={day}>{day}</option>)}</select></label>
        <label className="field">Номер урока<input required type="number" min={1} max={20} value={lesson.lesson_number} onChange={e => setNumber(Number(e.target.value))}/></label></div>
      <div className="form-grid"><label className="field">Начало<input type="time" required value={lesson.start_time} onChange={e => setLesson({ ...lesson, start_time: e.target.value })}/></label>
        <label className="field">Окончание<input type="time" required value={lesson.end_time} onChange={e => setLesson({ ...lesson, end_time: e.target.value })}/></label></div>
      <label className="field">Преподаватель<input maxLength={100} value={lesson.teacher_name ?? ''} onChange={e => setLesson({ ...lesson, teacher_name: e.target.value })}/></label>
      <label className="field">Кабинет<input maxLength={40} value={lesson.classroom ?? ''} onChange={e => setLesson({ ...lesson, classroom: e.target.value })}/></label>
      <label className="field">Комментарий<textarea maxLength={250} rows={2} value={lesson.comment ?? ''} onChange={e => setLesson({ ...lesson, comment: e.target.value })}/></label>
      <div className="dialog-actions"><Button type="button" variant="outline" onClick={close}>Отмена</Button><Button disabled={!lesson.subject_id || lesson.start_time >= lesson.end_time}>Сохранить в черновик</Button></div>
    </form>
  </Modal>
}

function WeekPage({ classId, classes }: { classId: number; classes: SchoolClass[] }) {
  const { today } = useSession()
  const [cycle, setCycle] = useState<Plan['cycle']>('A')
  const [start, setStart] = useState('')
  const base = `/classes/${classId}/timetable`
  const query = useData<EditorData>(`${base}/editor?cycle=${cycle}${start ? `&starts=${start}` : ''}`)
  return <>
    <div className="toolbar"><div className="segmented">{(['A', 'B'] as const).map(value => <button key={value} aria-pressed={cycle === value} onClick={() => { setCycle(value); setStart('') }}>Неделя {value}</button>)}</div>
      <label className="inline-field">Период<select value={start} onChange={e => setStart(e.target.value)}><option value="">Последний период</option>{query.data?.periods.map(period => <option key={period} value={period}>{formatDay(period, true)}</option>)}
        {start && !query.data?.periods.includes(start as string) && <option value={start}>Новый с {formatDay(start)}</option>}</select></label>
      <label className="inline-field">Новый период с<input type="date" value={start} min="2000-01-01" onChange={e => setStart(e.target.value || today)}/></label>
    </div>
    {query.isPending ? <Pending/> : query.error ? <Failure error={query.error}/> : <WeekEditor key={`${cycle}:${start}`} classes={classes} classId={classId} query={query.data} />}
  </>
}

function conflict(rows: Lesson[]) {
  const ordered = sorted(rows)
  return ordered.some((row, index) => row.start_time >= row.end_time || (index > 0 && ordered[index - 1].weekday === row.weekday &&
    (ordered[index - 1].lesson_number === row.lesson_number || ordered[index - 1].end_time > row.start_time)))
}

function WeekEditor({ query, classId, classes }: { query: EditorData; classId: number; classes: SchoolClass[] }) {
  const { plan: original, subjects } = query
  const [plan, setPlan] = useState(original)
  const [notify, setNotify] = useState(false)
  const [shift, setShift] = useState(query.slots[0]?.shift ?? '')
  const [selectedDay, setSelectedDay] = useState(-1)
  const [edit, setEdit] = useState<{ lesson: Lesson; old?: string }>()
  const [preview, setPreview] = useState(false)
  const [copies, setCopies] = useState<'day' | 'week' | null>(null)
  const [source, setSource] = useState(0)
  const [target, setTarget] = useState(1)
  const [confirmClear, setConfirmClear] = useState<number>()
  const [dragging, setDragging] = useState<string>()
  const [duplicate, setDuplicate] = useState(false)
  const mutation = useAction()
  const base = `/classes/${classId}/timetable`
  const allShifts = [...new Set(query.slots.map(item => item.shift))]
  const slots = query.slots.filter(item => item.shift === shift)
  const dirty = JSON.stringify(plan) !== JSON.stringify(original)
  function save(lesson: Lesson) {
    const rest = plan.lessons.filter(item => key(item) !== edit?.old)
    if (rest.some(item => key(item) === key(lesson))) { setDuplicate(true); return }
    setPlan({ ...plan, lessons: sorted([...rest, lesson]) }); setEdit(undefined); setDuplicate(false)
  }
  function add(day: number, copy?: Lesson) {
    const used = new Set(plan.lessons.filter(row => row.weekday === day).map(row => row.lesson_number))
    const slot = slots.find(row => !used.has(row.lesson_number))
    const number = slot?.lesson_number ?? Array.from({ length: 20 }, (_, index) => index + 1).find(number => !used.has(number))
    if (!number) return
    const lesson = Blank(day, number, subjects.find(item => item.active), slot)
    setEdit({ lesson: copy ? { ...copy, weekday: day, lesson_number: number, start_time: lesson.start_time, end_time: lesson.end_time } : lesson })
  }
  function exchange(origin: string, destination: string) {
    const from = plan.lessons.find(item => key(item) === origin)
    const to = plan.lessons.find(item => key(item) === destination)
    if (!from || !to || from === to) return
    const placed = (content: Lesson, slot: Lesson) => ({ ...content, weekday: slot.weekday, lesson_number: slot.lesson_number,
      start_time: slot.start_time, end_time: slot.end_time })
    setPlan({ ...plan, lessons: sorted(plan.lessons.map(item => item === from ? placed(to, from) : item === to ? placed(from, to) : item)) })
  }
  const changes = plan.lessons.filter(lesson => !original.lessons.some(old => JSON.stringify(old) === JSON.stringify(lesson))).length
  const removed = original.lessons.filter(lesson => !plan.lessons.some(now => key(now) === key(lesson))).length
  return <>
    <Panel title="Редактор недели" subtitle="Изменения действуют после сохранения всей недели"><div className="panel-form">
      <div className="toolbar"><label className="inline-field">Название<input maxLength={80} value={plan.name} onChange={e => setPlan({ ...plan, name: e.target.value })}/></label>
        <label className="inline-field">Действует с <strong>{formatDay(plan.effective_from, true)}</strong></label>
        <label className="inline-field">Действует по<input aria-label="Конец действия" type="date" min={plan.effective_from} value={plan.effective_to ?? ''} onChange={e => setPlan({ ...plan, effective_to: e.target.value || null })}/></label>
        <label className="inline-field"><input type="checkbox" checked={plan.active} onChange={e => setPlan({ ...plan, active: e.target.checked })}/> Действует</label></div>
      {allShifts.length > 0 && <label className="inline-field">Шаблон звонков<select value={shift} onChange={e => setShift(e.target.value)}>{allShifts.map(item => <option key={item}>{item}</option>)}</select></label>}
      <div className="toolbar"><label className="inline-field">Дни<select value={selectedDay} onChange={e => setSelectedDay(Number(e.target.value))}><option value={-1}>Вся неделя</option>{days.map((day, index) => <option value={index} key={day}>{day}</option>)}</select></label>
        <Button variant="outline" onClick={() => { setCopies('day'); setSource(0); setTarget(1) }}><ClipboardCopy size={16}/> Копировать день</Button>
        <Button variant="outline" onClick={() => { setCopies('week'); setSource(classes.find(item => item.id !== classId)?.id ?? 0) }} disabled={classes.length < 2}>Копировать неделю из класса</Button>
        <Button variant="ghost" disabled={!plan.lessons.length} onClick={() => setConfirmClear(selectedDay)}><Trash2 size={16}/> {selectedDay < 0 ? 'Очистить неделю' : 'Очистить день'}</Button></div>
      {conflict(plan.lessons) && <p className="failure" role="alert">Время уроков пересекается или нарушает порядок. Проверьте интервалы перед публикацией.</p>}
      {!subjects.some(item => item.active) && <p className="muted">Сначала добавьте предмет во вкладке «Предметы».</p>}
    </div></Panel>
    <div className="week-board">{days.map((day, index) => {
      const rows = plan.lessons.filter(item => item.weekday === index)
      if (selectedDay !== -1 && selectedDay !== index) return null
      return <Panel title={day} key={day} actions={<Button variant="ghost" size="icon" aria-label={`Добавить урок · ${day}`} disabled={rows.length === 20 || !subjects.some(item => item.active)} onClick={() => add(index)}><Plus size={18}/></Button>}>
        {!rows.length && <p className="empty-day muted">Нет уроков</p>}
        <div className="week-lessons">{rows.map((lesson, order) => {
          const subject = subjects.find(item => item.id === lesson.subject_id)
          return <article className="week-lesson" key={key(lesson)} draggable onDragStart={event => { setDragging(key(lesson)); event.dataTransfer.setData('text/plain', key(lesson)) }}
            onDragEnd={() => setDragging(undefined)} onDragOver={event => event.preventDefault()}
            onDrop={event => { event.preventDefault(); if (dragging) exchange(dragging, key(lesson)); setDragging(undefined) }}>
            <div className="lesson-line"><GripVertical className="drag-cue" size={15}/><span className="lesson-number">{lesson.lesson_number}</span><LessonBadge subject={subject}/><div className="lesson-details"><strong>{subject?.name ?? 'Предмет'}</strong><small>{lesson.start_time}–{lesson.end_time}{lesson.classroom && ` · ${lesson.classroom}`}</small></div></div>
            <div className="table-actions"><Button variant="ghost" size="icon" aria-label="Урок выше" disabled={order === 0} onClick={() => exchange(key(lesson), key(rows[order - 1]))}><ArrowUp size={15}/></Button>
              <Button variant="ghost" size="icon" aria-label="Урок ниже" disabled={order === rows.length - 1} onClick={() => exchange(key(lesson), key(rows[order + 1]))}><ArrowDown size={15}/></Button>
              <Button variant="ghost" size="icon" aria-label="Редактировать урок" onClick={() => setEdit({ lesson, old: key(lesson) })}><Pencil size={15}/></Button>
              <Button variant="ghost" size="icon" aria-label="Дублировать урок" disabled={rows.length === 20} onClick={() => add(index, lesson)}><ClipboardCopy size={15}/></Button>
              <Button variant="ghost" size="icon" aria-label="Удалить урок из черновика" onClick={() => setPlan({ ...plan, lessons: plan.lessons.filter(item => key(item) !== key(lesson)) })}><Trash2 size={15}/></Button></div>
          </article>
        })}</div></Panel>
    })}</div>
    <Panel><div className="panel-form"><label className="switch"><input type="checkbox" checked={notify} onChange={e => setNotify(e.target.checked)}/><span/> Уведомить участников класса</label>
      <div className="toolbar"><Button disabled={!dirty || !plan.name.trim() || conflict(plan.lessons)} onClick={() => setPreview(true)}>Предварительный просмотр</Button>
        <Button variant="outline" onClick={() => setPlan(original)} disabled={!dirty}>Отменить изменения</Button></div></div></Panel>
    {edit && <LessonForm key={key(edit.lesson)} value={edit.lesson} subjects={subjects} slots={slots} close={() => setEdit(undefined)} save={save}/>}
    {duplicate && <Confirm title="Номер занят" text="Выберите свободный номер урока для этого дня." label="Понятно" onClose={() => setDuplicate(false)} onConfirm={() => setDuplicate(false)}/>}
    {preview && <Modal open title="Опубликовать расписание" onOpenChange={open => !open && setPreview(false)} description={`Добавлено или изменено: ${changes}. Удалено: ${removed}.`}>
      <div className="preview-list">{days.map((day, index) => <p key={day}><strong>{day}.</strong> {plan.lessons.filter(row => row.weekday === index).map(row => `${row.start_time} ${subjects.find(item => item.id === row.subject_id)?.name ?? ''}`).join(', ') || 'Нет уроков'}</p>)}</div>
      <div className="dialog-actions"><Button variant="outline" onClick={() => setPreview(false)}>Назад</Button><Button disabled={mutation.busy} onClick={async () => {
        const result = await mutation.run(() => api<Plan>(base, 'PUT', { ...plan, notify }), 'Расписание опубликовано')
        if (result) { setPlan(result); setPreview(false) }
      }}>Сохранить всю неделю</Button></div>
    </Modal>}
    {confirmClear !== undefined && <Confirm title={confirmClear < 0 ? 'Очистить неделю?' : `Очистить день «${days[confirmClear]}»?`} text="В опубликованном расписании изменения появятся после сохранения." label="Очистить черновик" onClose={() => setConfirmClear(undefined)} onConfirm={() => {
      setPlan({ ...plan, lessons: confirmClear < 0 ? [] : plan.lessons.filter(item => item.weekday !== confirmClear) }); setConfirmClear(undefined)
    }}/>}
    {copies && <Modal open title={copies === 'day' ? 'Копировать день' : 'Копировать неделю из другого класса'} description="Копия заменит соответствующую часть черновика." onOpenChange={open => !open && setCopies(null)}>
      {copies === 'day' ? <div className="toolbar">{[['Откуда', source, setSource], ['Куда', target, setTarget]].map(([label, value, setter]) => <label key={String(label)} className="field">{String(label)}<select value={Number(value)} onChange={e => (setter as (value: number) => void)(Number(e.target.value))}>{days.map((day, i) => <option key={day} value={i}>{day}</option>)}</select></label>)}</div> :
        <ClassSelect items={classes.filter(item => item.id !== classId)} value={source} change={setSource}/>}
      <div className="dialog-actions"><Button disabled={mutation.busy || (copies === 'day' ? source === target : !source)} onClick={async () => {
        if (copies === 'day') setPlan({ ...plan, lessons: sorted([...plan.lessons.filter(item => item.weekday !== target),
          ...plan.lessons.filter(item => item.weekday === source).map(item => ({ ...item, weekday: target }))]) })
        else {
          const data = await mutation.run(() => api<EditorData>(`/classes/${source}/timetable/editor?cycle=${plan.cycle}`))
          if (!data) return
          setPlan({ ...plan, lessons: data.plan.lessons })
        }
        setCopies(null)
      }}>Копировать</Button></div>
    </Modal>}
  </>
}

function DateEditor({ classId, plan }: { classId: number; plan: DayPlan }) {
  const [open, setOpen] = useState(false)
  return <><Button variant="outline" size="small" onClick={() => setOpen(true)}><Pencil size={15}/> Изменить дату</Button>
    {open && <ExceptionForm classId={classId} plan={plan} close={() => setOpen(false)}/>}</>
}

function ExceptionForm({ classId, plan, close }: { classId: number; plan: DayPlan; close(): void }) {
  const [kind, setKind] = useState<DayPlan['action']>(plan.action === 'regular' ? 'replace' : plan.action)
  const [rows, setRows] = useState(plan.action === 'closed' ? plan.regular : plan.lessons)
  const [comment, setComment] = useState(plan.comment ?? '')
  const [notify, setNotify] = useState(false)
  const [edit, setEdit] = useState<{ lesson: Lesson; old?: number }>()
  const action = useAction()
  const base = `/classes/${classId}/timetable`
  const query = useData<EditorData>(`${base}/editor`)
  const { subjects = [], slots = [] } = query.data ?? {}
  const index = dayIndex(plan.day)
  const taken = new Set(rows.map(row => row.lesson_number))
  const nextNumber = Array.from({ length: 20 }, (_, index) => index + 1).find(number => !taken.has(number))
  if (edit) return <LessonForm value={edit.lesson} subjects={subjects} fixedDay={true} slots={slots.filter(item => item.shift === slots[0]?.shift)} close={() => setEdit(undefined)} save={lesson => {
    setRows(sorted([...rows.filter(row => row.lesson_number !== edit.old), lesson])); setEdit(undefined)
  }}/>
  return <Modal open title={`Изменение · ${formatDay(plan.day, true)}`} description="Изменения действуют только на эту дату." onOpenChange={open => !open && close()}>
    <label className="field">Режим<select value={kind} onChange={e => setKind(e.target.value as DayPlan['action'])}><option value="replace">Заменить уроки дня</option><option value="closed">Выходной день</option><option value="regular">Восстановить обычное расписание</option></select></label>
    {kind !== 'regular' && <label className="field">Комментарий<input maxLength={250} value={comment} onChange={e => setComment(e.target.value)}/></label>}
    {kind === 'replace' && <>
      <div className="history-list">{rows.map((row, i) => <div className="exception-row" key={`${key(row)}:${i}`}><strong>{row.lesson_number}. {subjects.find(item => item.id === row.subject_id)?.name ?? 'Предмет'}</strong><time>{row.start_time}–{row.end_time}</time>
        <Button variant="ghost" size="icon" aria-label="Изменить урок даты" onClick={() => setEdit({ lesson: row, old: row.lesson_number })} disabled={!query.data}><Pencil size={15}/></Button>
        <Button variant="ghost" size="icon" aria-label="Отменить урок даты" onClick={() => setRows(rows.filter((_, index) => index !== i))}><Trash2 size={15}/></Button></div>)}</div>
      <Button variant="outline" size="small" disabled={!subjects.length || !nextNumber} onClick={() => {
        if (nextNumber) setEdit({ lesson: Blank(index, nextNumber, subjects.find(item => item.active), slots.find(item => item.lesson_number === nextNumber)) })
      }}><Plus size={15}/> Добавить урок</Button>
      {conflict(rows) && <p className="failure" role="alert">Проверьте номера и пересечение времени уроков.</p>}
    </>}
    <label className="switch"><input type="checkbox" checked={notify} onChange={e => setNotify(e.target.checked)}/><span/> Уведомить участников класса</label>
    <div className="dialog-actions"><Button variant="outline" onClick={close}>Отмена</Button><Button disabled={action.busy || (kind === 'replace' && conflict(rows))} onClick={async () => {
      const result = await action.run(() => api(`${base}/exceptions/${plan.day}`, 'PUT', { action: kind, lessons: rows, comment, notify, revision: plan.revision }), 'Изменение опубликовано')
      if (result) close()
    }}>Опубликовать</Button></div>
  </Modal>
}

function Subjects() {
  const query = useData<Subject[]>('/subjects')
  const [subject, setSubject] = useState<Subject>()
  const mutation = useAction()
  return <Panel title="Предметы" actions={<Button size="small" onClick={() => setSubject({ id: 0, name: '', icon: 'book', color: '#0f9278', active: true })}><Plus size={16}/> Добавить предмет</Button>}>
    {query.isPending ? <Pending/> : query.error ? <Failure error={query.error}/> : !query.data.length ? <Empty title="В справочнике пока нет предметов"/> :
      <ul className="history-list">{query.data.map(item => <li key={item.id}><div className="lesson-line"><LessonBadge subject={item}/><strong>{item.name}</strong>{!item.active && <span className="badge badge-slate">В архиве</span>}</div>
        <Button variant="ghost" size="icon" aria-label={`Изменить предмет ${item.name}`} onClick={() => setSubject(item)}><Pencil size={17}/></Button></li>)}</ul>}
    {subject && <Modal open title={subject.id ? 'Изменить предмет' : 'Добавить предмет'} onOpenChange={open => !open && setSubject(undefined)}>
      <form onSubmit={async event => {
        event.preventDefault()
        const { id, ...body } = subject
        if (await mutation.run(() => api(id ? `/subjects/${id}` : '/subjects', id ? 'PUT' : 'POST', body), 'Предмет сохранён')) setSubject(undefined)
      }}>
        <label className="field">Название предмета<input required maxLength={80} value={subject.name} onChange={e => setSubject({ ...subject, name: e.target.value })}/></label>
        <div className="form-grid"><label className="field">Цвет<input type="color" value={subject.color} onChange={e => setSubject({ ...subject, color: e.target.value })}/></label>
          <label className="field">Значок<select value={subject.icon} onChange={e => setSubject({ ...subject, icon: e.target.value as Subject['icon'] })}>
            {Object.entries(iconNames).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></label></div>
        <label className="switch"><input type="checkbox" checked={!subject.active} onChange={e => setSubject({ ...subject, active: !e.target.checked })}/><span/> В архиве</label>
        <div className="dialog-actions"><Button type="button" variant="outline" onClick={() => setSubject(undefined)}>Отмена</Button><Button disabled={mutation.busy}>Сохранить предмет</Button></div>
      </form>
    </Modal>}
  </Panel>
}

function Bells({ classId }: { classId: number }) {
  const query = useData<EditorData>(`/classes/${classId}/timetable/editor`)
  const [preset, setPreset] = useState<{ shift: string; slots: Slot[] }>()
  const shifts = [...new Set(query.data?.slots.map(item => item.shift))]
  const action = useAction()
  const start = (shift: string) => setPreset({ shift, slots: (query.data?.slots ?? []).filter(item => item.shift === shift).map(({ shift: _, ...slot }) => slot) })
  const last = preset?.slots.at(-1)
  return <Panel title="Расписание звонков" subtitle="Интервалы привязаны к классу. При добавлении урока можно использовать шаблон смены."
    actions={<Button size="small" onClick={() => start('')}><Plus size={16}/> Добавить смену</Button>}>
    {query.isPending ? <Pending/> : query.error ? <Failure error={query.error}/> : shifts.length ? <ul className="history-list">{shifts.map(shift => <li key={shift}>
      <div><strong>{shift}</strong><small className="muted">Интервалов: {query.data.slots.filter(slot => slot.shift === shift).length}</small></div><Button variant="outline" size="small" onClick={() => start(shift)}>Редактировать</Button></li>)}</ul> : <Empty title="Шаблонов звонков пока нет"/>}
    {preset && <Modal open title="Интервалы уроков" onOpenChange={open => !open && setPreset(undefined)}>
      <form onSubmit={async event => {
        event.preventDefault()
        if (await action.run(() => api(`/classes/${classId}/timetable/bells`, 'PUT', preset), 'Интервалы сохранены')) setPreset(undefined)
      }}>
        <label className="field">Название смены<input required maxLength={32} value={preset.shift} onChange={e => setPreset({ ...preset, shift: e.target.value })}/></label>
        {preset.slots.map((row, index) => <div className="bell-row" key={index}>
          {(['lesson_number','start_time','end_time'] as const).map((field,i) => <label className="field" key={field}>{['Урок','Начало','Конец'][i]}<input required type={i ? 'time' : 'number'} min={i ? undefined : 1} max={i ? undefined : 20} value={row[field]} onChange={e => setPreset({ ...preset,
            slots: preset.slots.map((slot,n) => n === index ? { ...slot, [field]: i ? e.target.value : Number(e.target.value) } : slot) })}/></label>)}
          <Button type="button" variant="ghost" size="icon" aria-label="Удалить интервал" onClick={() => setPreset({ ...preset, slots: preset.slots.filter((_, i) => i !== index) })}><Trash2 size={15}/></Button>
        </div>)}
        <Button type="button" variant="outline" size="small" disabled={preset.slots.length >= 20} onClick={() => setPreset({ ...preset,
          slots: [...preset.slots, { lesson_number: Math.min(20, (last?.lesson_number ?? 0) + 1), start_time: '', end_time: '' }] })}><Plus size={15}/> Добавить интервал</Button>
        <div className="dialog-actions"><Button disabled={action.busy}>Сохранить интервалы</Button></div>
      </form>
    </Modal>}
  </Panel>
}

function ChangeHistory({ classId }: { classId: number }) {
  const { timezone } = useSession()
  const path = `/classes/${classId}/timetable/history`
  const query = useData<Change[]>(path)
  const subjects = useData<Subject[]>('/subjects')
  const [detail, setDetail] = useState<Change>()
  const [restore, setRestore] = useState<Change>()
  const mutation = useAction()
  return <Panel title="История расписания">{query.isPending ? <Pending/> : query.error ? <Failure error={query.error}/> : !query.data.length ? <Empty title="Опубликованных изменений ещё нет"/> :
    <ul className="history-list">{query.data.map(row => <li key={row.id}><div><strong>{row.target === 'week' ? 'Недельное расписание' : 'Исключение по дате'} · {row.key}</strong><small className="muted">{formatTime(row.changed_at, timezone, true)} · {row.actor ?? 'Владелец'}</small></div>
      <div className="toolbar"><Button variant="ghost" size="small" onClick={() => setDetail(row)}>Сравнить</Button><Button variant="outline" size="small" onClick={() => setRestore(row)}>Восстановить</Button></div></li>)}</ul>}
    {detail && <Modal open title="Изменения расписания" onOpenChange={open => !open && setDetail(undefined)}><div className="form-grid">{([[detail.before,'Было'], [detail.after,'Стало']] as const).map(([value, label]) =>
      <section className="preview-list" key={label}><strong>{label}</strong>{value.lessons.length ? <ul>{value.lessons.map(lesson => <li key={key(lesson)}>{days[lesson.weekday]}, {lesson.lesson_number}. {subjects.data?.find(subject => subject.id === lesson.subject_id)?.name ?? 'Предмет'} · {lesson.start_time}–{lesson.end_time}</li>)}</ul> : <p>Нет уроков</p>}</section>)}</div></Modal>}
    {restore && <Confirm title="Восстановить предыдущую версию?" text={`Изменение ${restore.key}. Восстановление будет записано в историю.`} label="Восстановить" busy={mutation.busy} onClose={() => setRestore(undefined)} onConfirm={async () => {
      if (await mutation.run(() => api(`${path}/${restore.id}/restore`, 'POST'), 'Предыдущая версия восстановлена')) setRestore(undefined)
    }}/>}
  </Panel>
}
