import postgres from 'postgres'
import { createClient } from '@supabase/supabase-js'
import { z } from 'zod'
import { HttpError, type Identity } from './auth.ts'
import { casefold } from './unicode.ts'

// SQL rows are typed at the presentation boundary. Parameter values always use PostgreSQL placeholders.
// deno-lint-ignore no-explicit-any
export type Row = Record<string, any>
export type Sql = postgres.Sql
export type Transaction = postgres.TransactionSql
export interface Configuration {
  token: string; ownerId: number; miniAppUrl: string; webhookSecret: string; schedulerSecret: string
  url: string; schema: string; projectUrl: string; apiName: string; test: boolean; readOnly: boolean
}
export function configuration(overrides: Partial<Configuration> = {}): Configuration {
  const config = {
    token: Deno.env.get('BOT_TOKEN') ?? '', ownerId: Number(Deno.env.get('OWNER_ID')),
    miniAppUrl: Deno.env.get('MINI_APP_URL') ?? '', webhookSecret: Deno.env.get('TELEGRAM_WEBHOOK_SECRET') ?? '',
    schedulerSecret: Deno.env.get('SCHEDULER_SECRET') ?? '',
    url: Deno.env.get('ATTENDANCE_DATABASE_URL') ?? Deno.env.get('SUPABASE_DB_URL') ?? '',
    projectUrl: Deno.env.get('SUPABASE_URL') ?? '', schema: 'public', apiName: 'api', test: false,
    readOnly: Deno.env.get('ATTENDANCE_READ_ONLY') === 'true', ...overrides,
  }
  if (!/^(public|attendance_qa_[a-z0-9_]+)$/.test(config.schema)) throw new Error('Invalid server database schema')
  if (!config.token || !Number.isSafeInteger(config.ownerId) || config.ownerId <= 0 || !config.url) throw new Error('Missing server configuration')
  return config
}
export function connection(config: Configuration): Sql {
  return postgres(config.url, { prepare: false, max: 1, idle_timeout: 20, connect_timeout: 10,
    connection: { search_path: config.schema, application_name: 'attendance-edge' },
    types: {
      bigint: { to: 20, from: [20], serialize: String, parse: Number },
      date: { to: 1082, from: [1082], serialize: String, parse: String },
      timestamp: { to: 1114, from: [1114], serialize: String, parse: (value: string) => value.replace(' ', 'T') },
    }, onnotice: () => {},
  })
}
export function storage(config: Configuration) {
  const modern = JSON.parse(Deno.env.get('SUPABASE_SECRET_KEYS') ?? '{}')
  return createClient(config.projectUrl, modern.default ?? Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? '',
    { auth: { persistSession: false, autoRefreshToken: false } })
}
export async function rows(db: Transaction | Sql, statement: string, values: unknown[] = []): Promise<Row[]> {
  return await db.unsafe(statement, values as postgres.ParameterOrJSON<never>[])
}
export async function one(db: Transaction | Sql, statement: string, values: unknown[] = []): Promise<Row | undefined> {
  return (await rows(db, statement, values))[0]
}
export const normal = (value: string): string => casefold(value.trim().replace(/\s+/gu, ' '))
export const stamp = (value: string | Date | null): string | null => value ? new Date(value instanceof Date ? value : value.endsWith('Z') ? value : value + 'Z').toISOString() : null
export const profile = (user: Row) => ({ id: user.telegram_id, username: user.username, name: user.full_name || `Telegram ${user.telegram_id}`,
  started: user.started_at != null, blocked: user.blocked, registered_at: stamp(user.created_at) })
export const schoolView = (school: Row, canHistory = true) => ({ id: school.id, name: school.name, active: school.is_active, can_history: canHistory })
export const studentView = (student: Row) => ({ id: student.id, name: student.full_name, full_name: student.full_name,
  class_id: student.class_id, active: student.is_active, updated_at: stamp(student.updated_at) })
export const id = (value: unknown): number => z.coerce.number().int().positive().max(2 ** 52 - 1).parse(value)
export function bounded(value: string, maximum: number): string {
  const text = value.trim().replace(/\s+/gu, ' ')
  if (!text || [...text].length > maximum || /[\p{C}]/u.test(text)) throw new HttpError(400, `Введите от 1 до ${maximum} символов.`)
  return text
}
export function studentNames(text: string, bulk: boolean): string[] {
  const names = text.split(/\r?\n/).filter(line => line.trim()).map(line => line.trim().replace(/\s+/gu, ' '))
  if (!names.length || names.length > (bulk ? 100 : 1)) throw new HttpError(400, 'Введите полное имя ученика, для массового ввода по одному ученику в строке.')
  if (names.some(name => [...name].length > 255 || !/\p{L}/u.test(name) || !/^[\p{L}\p{M} \-‐‑'’‘ʻʼ]+$/u.test(name))) throw new HttpError(400, 'В полном имени допустимы буквы, пробелы, дефисы и апострофы, до 255 символов.')
  return names
}
export function localDay(zone = 'Asia/Tashkent', instant = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(instant)
  return ['year', 'month', 'day'].map(part => parts.find(item => item.type === part)!.value).join('-')
}
export function date(value: string): string {
  const selected = /^\d{2}\.\d{2}\.\d{4}$/.test(value) ? value.split('.').reverse().join('-') : value
  if (!/^\d{4}-\d{2}-\d{2}$/.test(selected) || Number.isNaN(Date.parse(selected)) || new Date(selected).toISOString().slice(0, 10) !== selected) throw new HttpError(400, 'Введите корректную дату.')
  return selected
}
export const addDays = (day: string, days: number): string => new Date(Date.parse(day) + days * 86400000).toISOString().slice(0, 10)
export const weekday = (day: string): number => (new Date(day).getUTCDay() + 6) % 7
export function period(start: string, end: string, today: string): string[] {
  start = date(start); end = date(end)
  const length = (Date.parse(end) - Date.parse(start)) / 86400000
  if (length < 0 || length >= 366 || end > today) throw new HttpError(400, 'Укажите период до 366 дней, без будущих дат.')
  return Array.from({ length: length + 1 }, (_, index) => addDays(start, index))
}
export async function settings(db: Transaction | Sql): Promise<Row> {
  const row = await one(db, 'SELECT * FROM school_settings WHERE id=1')
  return { school: row?.name ?? 'Школа', system_name: 'Attendance', timezone: 'Asia/Tashkent', school_days: [0, 1, 2, 3, 4],
    join_open: true, join_retry_days: 0, notify_owner: true, notify_schedule: false, lesson_start: '08:00', lesson_minutes: 45,
    report_time: '08:30', dashboard_chart: true, statistics_days: 7, ...row?.preferences }
}
export async function register(db: Transaction, identity: Identity, started: boolean): Promise<Row> {
  const previous = await one(db, 'SELECT * FROM users WHERE telegram_id=$1', [identity.id])
  const user = (await one(db, `INSERT INTO users (telegram_id,username,full_name,started_at,created_at,blocked)
    VALUES ($1,$2,$3,CASE WHEN $4 THEN timezone('UTC',now()) END,timezone('UTC',now()),false)
    ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username,full_name=excluded.full_name,
    started_at=coalesce(users.started_at,excluded.started_at) RETURNING *`,
    [identity.id, identity.username ? [...identity.username].slice(0, 64).join('') : null, [...identity.name].slice(0, 160).join(''), started]))!
  if (started && !previous?.started_at) await audit(db, user, 'user.started', 'user', user.id)
  else if (previous?.username !== user.username || previous?.full_name !== user.full_name) await audit(db, user, 'user.profile_updated', 'user', user.id)
  console.info('telegram_registration committed', { created: !previous, first_start: started && !previous?.started_at })
  return user
}
export async function audit(db: Transaction | Sql, actor: Row | null, action: string, entity: string, entityId?: number, details?: string): Promise<void> {
  await rows(db, `INSERT INTO audit_logs(actor_id,action,entity_type,entity_id,details,timestamp)
    VALUES($1,$2,$3,$4,$5,timezone('UTC',now()))`, [actor?.id ?? null, action, entity, entityId ?? null, details?.slice(0, 300) ?? null])
}
export interface Context {
  request: Request; url: URL; params: Record<string, string>; db: Transaction; sql: Sql; config: Configuration
  user: Row; identity: Identity; preferences: Row; today: string
  effects: (() => Promise<void>)[]
}
export class AfterCommit {
  constructor(public execute: () => Promise<unknown>) {}
}
export function owner(context: Context): void {
  if (context.identity.id !== context.config.ownerId) throw new HttpError(403, 'Доступ ограничен.')
}
export async function scope(context: Context, classId: number, permission: 'manage' | 'history' | 'correction' | 'statistics' | 'report' | 'send' | 'timetable' | 'timetable_edit' = 'manage', archived = false): Promise<Row> {
  const school = await one(context.db, 'SELECT * FROM classes WHERE id=$1', [classId])
  if (!school || (!archived && !school.is_active)) throw new HttpError(403, 'Класс недоступен.')
  if (context.identity.id === context.config.ownerId) return school
  const manager = await one(context.db, 'SELECT * FROM manager_assignments WHERE user_id=$1 AND class_id=$2', [context.user.id, classId])
  const flags: Record<string, boolean> = { manage: !!manager, history: !!(manager?.can_view_history || manager?.can_edit_history),
    correction: !!manager?.can_edit_history, statistics: !!manager?.can_view_statistics, send: !!manager?.can_send_reports,
    timetable_edit: !!manager?.can_edit_timetable }
  if (permission === 'report') flags.report = !!manager?.can_view_reports || !!await one(context.db, 'SELECT 1 FROM report_recipients WHERE user_id=$1 AND class_id=$2', [context.user.id, classId])
  if (permission === 'timetable') flags.timetable = !!manager || !!await one(context.db, 'SELECT 1 FROM class_memberships WHERE user_id=$1 AND class_id=$2', [context.user.id, classId])
  if (!flags[permission]) throw new HttpError(403, 'Доступ ограничен.')
  return school
}
export async function body<T>(context: Context, schema: z.ZodType<T>): Promise<T> {
  const raw = await context.request.text()
  if (new TextEncoder().encode(raw).length > 64000) throw new HttpError(413, 'Запрос слишком большой.')
  try { return schema.parse(JSON.parse(raw)) } catch (error) {
    if (error instanceof SyntaxError) throw new HttpError(422, 'Проверьте заполненные поля.')
    throw error
  }
}
type Handler = (context: Context) => Promise<unknown>
export class Router {
  entries: { method: string; pattern: RegExp; names: string[]; handler: Handler }[] = []
  add(method: string, path: string, handler: Handler): void {
    const names: string[] = []
    const pattern = path.split('/').map(part => {
      if (part.startsWith(':')) { names.push(part.slice(1)); return '([^/]+)' }
      return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    }).join('/')
    this.entries.push({ method, pattern: new RegExp('^' + pattern + '$'), names, handler })
  }
  async run(path: string, context: Context): Promise<unknown> {
    for (const route of this.entries) {
      const match = route.method === context.request.method && route.pattern.exec(path)
      if (match) { context.params = Object.fromEntries(route.names.map((name, index) => [name, match[index + 1]])); return route.handler(context) }
    }
    throw new HttpError(404, 'Маршрут не найден.')
  }
}
