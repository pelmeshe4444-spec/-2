import { Check, Clock3, HeartPulse, NotebookPen, X } from 'lucide-react'

export const statuses = [
  { name: 'Не отмечен', group: 'Не отмечены', short: 'Не отмечен', icon: Clock3, color: 'slate' },
  { name: 'Присутствует', group: 'Присутствуют', short: 'На уроке', icon: Check, color: 'green' },
  { name: 'Болеет', group: 'Болеют', short: 'Болеет', icon: HeartPulse, color: 'blue' },
  { name: 'По уважительной причине', group: 'По причине', short: 'По причине', icon: NotebookPen, color: 'amber' },
  { name: 'Отсутствует без причины', group: 'Без причины', short: 'Отсутствует', icon: X, color: 'rose' },
] as const

export const statusOrder = [1, 2, 3, 4, 0]
export const colors = ['#94a3b8', '#1aaa82', '#5c86ed', '#e7a63d', '#e36f82']
export const roles: Record<string, string> = { OWNER: 'Владелец', MANAGER: 'Ответственный', REPORT_RECIPIENT: 'Получатель', CLASS_MEMBER: 'Участник класса', USER: 'Пользователь' }
export const deliveryLabels: Record<string, string> = { scheduled: 'По расписанию', manual: 'Вручную', reminder: 'Напоминание', sent: 'Доставлено', failed: 'Ошибка', uncertain: 'Не подтверждено', sending: 'Отправляется', retry: 'Ожидает повтора', cancelled: 'Отменено' }
export const activities: Record<string, string> = {
  'user.started': 'Пользователь запустил бота', 'user.added': 'Пользователь добавлен по ID',
  'user.blocked': 'Доступ заблокирован', 'user.unblocked': 'Доступ восстановлен',
  'user.profile_updated': 'Профиль обновлён', 'class.added': 'Класс создан', 'class.updated': 'Класс переименован',
  'class.archived': 'Класс архивирован', 'student.added': 'Ученик добавлен', 'student.updated': 'Ученик обновлён',
  'student.archived': 'Ученик архивирован', 'student.restored': 'Ученик восстановлен',
  'attendance.marked': 'Отметка изменена', 'attendance.bulk': 'Массовая отметка', 'attendance.finished': 'Отметка завершена',
  'schedule.updated': 'Расписание обновлено', 'schedule.deleted': 'Расписание удалено',
  'delivery.claimed': 'Начата отправка', 'delivery.sent': 'Сообщение доставлено', 'delivery.failed': 'Ошибка доставки',
  'delivery.uncertain': 'Доставка не подтверждена', 'delivery.cancelled': 'Доставка отменена',
  'delivery.recovered': 'Проверены прерванные отправки', 'database.backup': 'Создана резервная копия',
  'statistics.exported': 'Отчёт выгружен в Excel', 'settings.updated': 'Настройки сохранены',
  'access.manager_add': 'Ответственный назначен', 'access.manager_remove': 'Права ответственного отозваны',
  'access.recipient_add': 'Получатель назначен', 'access.recipient_remove': 'Получатель удалён',
  'access.history_on': 'История открыта', 'access.history_off': 'История закрыта',
}

export function toDay(day: string, delta: number) {
  const date = new Date(`${day}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + delta)
  return date.toISOString().slice(0, 10)
}

export function formatDay(day: string, long = false) {
  return new Intl.DateTimeFormat('ru-RU', { timeZone: 'UTC', day: 'numeric', month: long ? 'long' : 'short', ...(long ? { year: 'numeric' } : {}) }).format(new Date(`${day}T00:00:00Z`))
}

export function formatTime(stamp: string | null, zone: string, day = false) {
  return stamp ? new Intl.DateTimeFormat('ru-RU', { timeZone: zone, hour: '2-digit', minute: '2-digit', ...(day ? { day: 'numeric', month: 'short' } : {}) }).format(new Date(stamp)) : '—'
}

export const initials = (name: string) => name.split(/\s+/).slice(0, 2).map(part => part[0]?.toUpperCase()).join('')
export const sum = (counts: number[]) => counts.reduce((total, count) => total + count, 0)
export const attendanceRate = (counts: number[]) => sum(counts) ? Math.round(counts[1] / sum(counts) * 100) : 0
