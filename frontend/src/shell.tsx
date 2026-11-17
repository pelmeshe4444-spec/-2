import { Activity, Bell, BookOpen, CalendarClock, ChartNoAxesCombined, ChevronRight, ClipboardCheck, ClipboardList, FileText,
  GraduationCap, History, LayoutDashboard, ListChecks, LogIn, Menu, Settings, ShieldCheck, UserCheck, UsersRound } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router'
import { formatDay, initials, roles } from './domain'
import { ApiError } from './api'
import { applyTelegramTheme, telegram } from './telegram'
import type { Me } from './types'
import { Button, Empty, Notice, Pending, Session, Toast, useData } from './ui'
import { AttendancePage, HistoryPage, ManagerDashboard, Statistics } from './pages/attendance'
import { AccessPage, ClassPage, SettingsPage, StudentsPage, UsersPage } from './pages/directory'
import { AuditPage, ReportsPage, SchedulePage } from './pages/reports'
import { JoinPage, NotificationsPage, RequestsPage } from './pages/memberships'
import { TimetablePage } from './pages/timetable'
import { Watermark } from './components/Watermark'
import { OwnerDashboard, SystemHealthPage } from './pages/admin'

const links = [
  { href: '/admin', label: 'Главная', icon: LayoutDashboard }, { href: '/manager', label: 'Главная', icon: LayoutDashboard },
  { href: '/attendance', label: 'Посещаемость', icon: ClipboardList },
  { href: '/statistics', label: 'Статистика', icon: ChartNoAxesCombined }, { href: '/history', label: 'История', icon: History },
  { href: '/students', label: 'Ученики', icon: GraduationCap }, { href: '/classes', label: 'Классы', icon: ListChecks },
  { href: '/users', label: 'Пользователи', icon: UsersRound }, { href: '/access', label: 'Права доступа', icon: ShieldCheck },
  { href: '/reports', label: 'Отчёты', icon: FileText }, { href: '/schedule', label: 'Автоматические отчёты', icon: CalendarClock },
  { href: '/settings', label: 'Настройки', icon: Settings }, { href: '/audit', label: 'Журнал действий', icon: History },
  { href: '/lessons', label: 'Расписание уроков', icon: BookOpen }, { href: '/requests', label: 'Заявки', icon: UserCheck },
  { href: '/notifications', label: 'Уведомления', icon: Bell }, { href: '/student', label: 'Мой класс', icon: GraduationCap },
  { href: '/register', label: 'Вступление в класс', icon: GraduationCap },
  { href: '/admin/system', label: 'Состояние системы', icon: Activity }, { href: '/admin/sections', label: 'Разделы', icon: Menu },
]
const ownerGroups = [['/admin', '/attendance', '/lessons', '/statistics', '/history'],
  ['/students', '/classes', '/users', '/requests', '/access', '/reports', '/schedule'],
  ['/notifications', '/settings', '/audit', '/admin/system']]
const groupTitles = ['Обзор', 'Управление', 'Система']
const linkSet = (paths: string[]) => paths.map(path => links.find(link => link.href === path)!)
type Mode = 'auto' | 'light' | 'dark'

export function Brand({ name = 'Attendance' }: { name?: string }) { return <div className="brand"><span><ClipboardCheck size={21} strokeWidth={2.2} /></span><strong>{name}</strong></div> }

export function App() {
  const me = useData<Me>('/me', 20000)
  const [mode, setMode] = useState<Mode>(() => {
    const saved = localStorage.getItem('attendance-theme')
    return saved === 'dark' || saved === 'light' ? saved : 'auto'
  })
  const [toast, setToast] = useState<{ text: string; error: boolean; key: number }>()
  useEffect(() => {
    const app = telegram()
    app?.ready()
    app?.expand()
  }, [])
  useEffect(() => {
    const update = () => applyTelegramTheme(mode)
    update()
    localStorage.setItem('attendance-theme', mode)
    const app = telegram()
    const events = ['themeChanged', 'safeAreaChanged', 'contentSafeAreaChanged']
    events.forEach(event => app?.onEvent(event, update))
    const preference = window.matchMedia('(prefers-color-scheme: dark)')
    preference.addEventListener('change', update)
    return () => { events.forEach(event => app?.offEvent(event, update)); preference.removeEventListener('change', update) }
  }, [mode])
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(undefined), 4100)
    return () => clearTimeout(timer)
  }, [toast])

  if (me.isPending) return <main className="gate"><Brand /><Pending /><Watermark/></main>
  if (!telegram()?.initData && me.error instanceof ApiError && me.error.status === 401) {
    return <Gate title="Откройте приложение в Telegram" text="Отправьте /start боту Attendance и нажмите «Открыть Attendance»." />
  }
  if (me.isError) return <Gate title="Не удалось войти" text={me.error.message}><Button variant="outline" onClick={() => me.refetch()}>Повторить</Button></Gate>
  if (me.data.user.blocked) return <Gate title="Доступ ограничен" text="Обратитесь к владельцу школы, чтобы он восстановил ваш доступ." />
  return <Session.Provider value={me.data}><Toast.Provider value={(text, error = false) => setToast({ text, error, key: Date.now() })}>
    <Layout me={me.data} mode={mode} setMode={setMode} />{toast && <Notice key={toast.key} text={toast.text} error={toast.error} />}
  </Toast.Provider></Session.Provider>
}

function Gate({ title, text, children }: { title: string; text: string; children?: ReactNode }) {
  return <main className="gate"><Brand /><section className="panel"><div className="gate-icon"><LogIn size={27} /></div><h1>{title}</h1><p>{text}</p>{children}</section><Watermark/></main>
}

function Layout({ me, mode, setMode }: { me: Me; mode: Mode; setMode(mode: Mode): void }) {
  const location = useLocation()
  const navigate = useNavigate()
  const owner = me.roles.includes('OWNER')
  const manager = me.roles.includes('MANAGER')
  const history = owner || me.managed.some(item => item.can_history)
  const stats = owner || me.managed.some(item => item.can_view_statistics)
  const reports = owner || me.reports.length > 0
  const member = me.roles.includes('CLASS_MEMBER')
  const studentHome = member ? '/student' : '/register'
  const home = owner ? '/admin' : manager ? '/manager' : member || !reports ? studentHome : '/reports'
  const primary = owner ? ['/admin', '/attendance', '/requests', '/admin/sections']
    : manager ? ['/manager', '/attendance', '/lessons', ...(reports ? ['/reports'] : []), ...(stats ? ['/statistics'] : [])]
    : member ? ['/student', '/lessons', ...(reports ? ['/reports'] : [])] : reports ? ['/reports', '/register'] : ['/register']
  const groups = owner ? ownerGroups.map(linkSet)
    : [linkSet([...primary, ...(history ? ['/history'] : []), ...(manager ? [studentHome] : []), '/notifications'])]
  const [popover, setPopover] = useState<'profile' | null>(null)
  const selected = links.find(link => link.href === location.pathname)
  const backTo = () => navigate(home)

  useEffect(() => {
    const sdk = telegram()
    const button = sdk?.isVersionAtLeast?.('6.1') ? sdk.BackButton : undefined
    if (!button) return
    if (location.pathname === home) button.hide()
    else button.show()
    const callback = () => navigate(home)
    button.onClick(callback)
    return () => { button.offClick(callback); button.hide() }
  }, [home, location.pathname, navigate])

  return <div className="app-shell">
    <aside className="sidebar"><Brand name={me.system_name}/><nav aria-label="Основная навигация">
      {groups.map((group, i) => <div className="nav-group" key={i}>
        {owner && <div className="nav-caption">{groupTitles[i]}</div>}
        {group.map(({ href, label, icon: Icon }) => <NavLink key={href} to={href} end onClick={() => setPopover(null)}><Icon size={18} />{label}</NavLink>)}
      </div>)}
    </nav></aside>
    <div className="work-area">
      <header className="topbar"><div className="top-title"><span className="mobile-logo"><ClipboardCheck size={20}/></span><span>{me.system_name}</span><ChevronRight size={15}/><strong>{selected?.label ?? 'Главная'}</strong></div>
        <div className="top-actions"><span className="top-date">{formatDay(me.today, true)}</span>
          <Button variant="ghost" size="icon" aria-label="Уведомления" onClick={() => { setPopover(null); navigate('/notifications') }}><Bell size={19} /></Button>
          <button className="profile-button" aria-label="Профиль" aria-expanded={popover === 'profile'} onClick={() => setPopover(popover === 'profile' ? null : 'profile')}><span className="avatar">{initials(me.user.name)}</span><span><strong>{me.user.name}</strong><small>{roles[me.roles[0]]}</small></span></button>
        </div>
        {popover === 'profile' && <div className="popover"><strong>{me.user.name}</strong><p className="muted">Telegram ID · {me.user.id}</p><label className="field">Тема<select value={mode} onChange={event => setMode(event.target.value as Mode)}><option value="auto">Как в Telegram</option><option value="light">Светлая</option><option value="dark">Тёмная</option></select></label></div>}
      </header>
      <main className="content" key={location.pathname}>
        <Routes>
          <Route path="/" element={<Navigate to={{ pathname: home, search: location.search }} replace />} />
          {owner && <Route path="/admin" element={<OwnerDashboard/>}/>}
          {manager && <Route path="/manager" element={<ManagerDashboard/>}/>}
          {(owner || manager) && <Route path="/attendance" element={<AttendancePage />} />}
          {(owner || manager || member) && <Route path="/lessons" element={<TimetablePage/>}/>}
          {!owner && <Route path="/join" element={<Navigate to={studentHome} replace/>}/>}
          {!owner && <Route path="/register" element={member ? <Navigate to="/student" replace/> : <JoinPage/>}/>}
          {!owner && <Route path="/student" element={member ? <JoinPage/> : <Navigate to="/register" replace/>}/>}
          <Route path="/notifications" element={<NotificationsPage/>}/>
          {history && <Route path="/history" element={<HistoryPage />} />}
          {reports && <Route path="/reports" element={<ReportsPage />} />}
          {stats && <Route path="/statistics" element={<Statistics />}/>}
          {owner && <><Route path="/students" element={<StudentsPage />}/>
            <Route path="/classes" element={<ClassPage />}/><Route path="/users" element={<UsersPage />}/><Route path="/access" element={<AccessPage />}/><Route path="/requests" element={<RequestsPage/>}/>
            <Route path="/schedule" element={<SchedulePage />}/><Route path="/settings" element={<SettingsPage mode={mode} setMode={setMode} />}/><Route path="/audit" element={<AuditPage />}/>
            <Route path="/admin/system" element={<SystemHealthPage/>}/><Route path="/admin/sections" element={<AdminSections/>}/></>}
          <Route path="*" element={<><Empty title="Раздел недоступен" /><Button onClick={backTo}>Вернуться</Button></>} />
        </Routes>
      </main>
    </div>
    <nav className="bottom-nav" aria-label="Навигация на телефоне">{primary.map(href => {
      const { label, icon: Icon } = links.find(link => link.href === href)!
      return <NavLink to={href} key={href} end onClick={() => setPopover(null)}><Icon size={21} /><span>{label}</span></NavLink>
    })}</nav><Watermark/>
  </div>
}

function AdminSections() {
  return <><h1>Все разделы</h1><nav className="dashboard-grid owner-sections" aria-label="Разделы администрирования">
    {ownerGroups.map((paths, index) => <section className="panel" key={groupTitles[index]}><h2>{groupTitles[index]}</h2>
      <div className="quick-links">{linkSet(paths).map(({ href, label, icon: Icon }) => <NavLink key={href} to={href}>
        <Icon size={18}/><span>{label}</span><ChevronRight size={16}/>
      </NavLink>)}</div>
    </section>)}
  </nav></>
}
