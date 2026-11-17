import { Bell, BookOpen, CalendarClock, ChartNoAxesCombined, ChevronRight, ClipboardCheck, ClipboardList, FileText,
  GraduationCap, History, LayoutDashboard, ListChecks, LogIn, Settings, ShieldCheck, UserCheck, UsersRound } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router'
import { formatDay, initials, roles } from './domain'
import { ApiError } from './api'
import { applyTelegramTheme, telegram } from './telegram'
import type { Me } from './types'
import { Button, Empty, Notice, Pending, Session, Toast, useData } from './ui'
import { AttendancePage, Dashboard, HistoryPage, Statistics } from './pages/attendance'
import { AccessPage, ClassPage, SettingsPage, StudentsPage, UsersPage } from './pages/directory'
import { AuditPage, ReportsPage, SchedulePage } from './pages/reports'
import { JoinPage, NotificationsPage, RequestsPage } from './pages/memberships'
import { TimetablePage } from './pages/timetable'
import { Watermark } from './components/Watermark'

const links = [
  { href: '/', label: 'Главная', icon: LayoutDashboard }, { href: '/attendance', label: 'Посещаемость', icon: ClipboardList },
  { href: '/statistics', label: 'Статистика', icon: ChartNoAxesCombined }, { href: '/history', label: 'История', icon: History },
  { href: '/students', label: 'Ученики', icon: GraduationCap }, { href: '/classes', label: 'Классы', icon: ListChecks },
  { href: '/users', label: 'Пользователи', icon: UsersRound }, { href: '/access', label: 'Права доступа', icon: ShieldCheck },
  { href: '/reports', label: 'Отчёты', icon: FileText }, { href: '/schedule', label: 'Автоматические отчёты', icon: CalendarClock },
  { href: '/settings', label: 'Настройки', icon: Settings }, { href: '/audit', label: 'Журнал действий', icon: History },
  { href: '/lessons', label: 'Расписание уроков', icon: BookOpen }, { href: '/requests', label: 'Заявки', icon: UserCheck },
  { href: '/notifications', label: 'Уведомления', icon: Bell }, { href: '/join', label: 'Мой класс', icon: GraduationCap },
]
type Mode = 'auto' | 'light' | 'dark'

export function Brand() { return <div className="brand"><span><ClipboardCheck size={21} strokeWidth={2.2} /></span><strong>Attendance</strong></div> }

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

  if (me.isPending) return <main className="gate"><Brand /><Pending /></main>
  if (!telegram()?.initData && me.error instanceof ApiError && me.error.status === 401) {
    return <Gate title="Откройте приложение в Telegram" text="Нажмите «Открыть приложение» в меню бота Attendance." />
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
  const reports = owner || me.roles.includes('REPORT_RECIPIENT')
  const member = me.roles.includes('CLASS_MEMBER')
  const home = owner || manager || member || !reports ? '/' : '/reports'
  const primary = owner ? ['/', '/attendance', '/statistics', '/settings'] : manager ? ['/', '/attendance', '/lessons', ...(reports ? ['/reports'] : [])]
    : member ? ['/join', '/lessons', ...(reports ? ['/reports'] : [])] : reports ? ['/reports', '/join'] : ['/join']
  const linkSet = (paths: string[]) => paths.map(path => links.find(link => link.href === path)!)
  const groups = owner ? [linkSet(['/', '/attendance', '/lessons', '/statistics', '/history']),
    linkSet(['/students', '/classes', '/users', '/requests', '/access', '/reports', '/schedule']), linkSet(['/notifications', '/settings', '/audit'])]
    : [linkSet([...primary, ...(history ? ['/history'] : []), ...(manager ? ['/join'] : []), '/notifications'])]
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
    <aside className="sidebar"><Brand /><nav aria-label="Основная навигация">
      {groups.map((group, i) => <div className="nav-group" key={i}>
        {owner && <div className="nav-caption">{['Обзор', 'Управление', 'Система'][i]}</div>}
        {group.map(({ href, label, icon: Icon }) => <NavLink key={href} to={href} end onClick={() => setPopover(null)}><Icon size={18} />{label}</NavLink>)}
      </div>)}
    </nav></aside>
    <div className="work-area">
      <header className="topbar"><div className="top-title"><span className="mobile-logo"><ClipboardCheck size={20}/></span><span>Attendance</span><ChevronRight size={15}/><strong>{selected?.label ?? 'Главная'}</strong></div>
        <div className="top-actions"><span className="top-date">{formatDay(me.today, true)}</span>
          <Button variant="ghost" size="icon" aria-label="Уведомления" onClick={() => { setPopover(null); navigate('/notifications') }}><Bell size={19} /></Button>
          <button className="profile-button" aria-label="Профиль" aria-expanded={popover === 'profile'} onClick={() => setPopover(popover === 'profile' ? null : 'profile')}><span className="avatar">{initials(me.user.name)}</span><span><strong>{me.user.name}</strong><small>{roles[me.roles[0]]}</small></span></button>
        </div>
        {popover === 'profile' && <div className="popover"><strong>{me.user.name}</strong><p className="muted">Telegram ID · {me.user.id}</p><label className="field">Тема<select value={mode} onChange={event => setMode(event.target.value as Mode)}><option value="auto">Как в Telegram</option><option value="light">Светлая</option><option value="dark">Тёмная</option></select></label></div>}
      </header>
      <main className="content" key={location.pathname}>
        <Routes>
          <Route path="/" element={owner || manager ? <Dashboard /> : <Navigate to={member || !reports ? '/join' : '/reports'} replace />} />
          {(owner || manager) && <Route path="/attendance" element={<AttendancePage />} />}
          {(owner || manager || member) && <Route path="/lessons" element={<TimetablePage/>}/>}
          {!owner && <Route path="/join" element={<JoinPage/>}/>}
          <Route path="/notifications" element={<NotificationsPage/>}/>
          {history && <Route path="/history" element={<HistoryPage />} />}
          {reports && <Route path="/reports" element={<ReportsPage />} />}
          {owner && <><Route path="/statistics" element={<Statistics />} /><Route path="/students" element={<StudentsPage />}/>
            <Route path="/classes" element={<ClassPage />}/><Route path="/users" element={<UsersPage />}/><Route path="/access" element={<AccessPage />}/><Route path="/requests" element={<RequestsPage/>}/>
            <Route path="/schedule" element={<SchedulePage />}/><Route path="/settings" element={<SettingsPage mode={mode} setMode={setMode} />}/><Route path="/audit" element={<AuditPage />}/></>}
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
