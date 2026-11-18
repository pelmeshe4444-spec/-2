export type Role = 'OWNER' | 'MANAGER' | 'REPORT_RECIPIENT' | 'CLASS_MEMBER' | 'USER'
export interface Person { id: number; name: string; username: string | null; started: boolean; blocked: boolean; registered_at: string }
export interface SchoolClass { id: number; name: string; active: boolean; can_history: boolean; can_edit_timetable?: boolean; can_edit_history?: boolean; can_view_statistics?: boolean; can_view_reports?: boolean; can_send_reports?: boolean }
export interface Me { user: Person; roles: Role[]; school: string; system_name: string; join_open: boolean; statistics_days: 1 | 7 | 30; today: string; timezone: string; sqlite: boolean; managed: SchoolClass[]; reports: SchoolClass[]; member: SchoolClass | null }
export interface Entry { id: number; name: string; status: number; reason: string | null; version: string; author: string | null; updated_at: string | null }
export interface Attendance { class: SchoolClass; day: string; counts: number[]; writable: boolean; entries: Entry[] }
export interface Student { id: number; name: string; class_id: number; active: boolean; updated_at: string; status: number; marked_at: string | null }
export interface StudentHistory extends Student { history: (Entry & { day: string; class_name: string })[] }
export interface AuditItem { id: number; action: string; by: number | null; time: string; entity: string; entity_id: number | null; details: string | null }
export interface Page<T> { page: number; total: number; items: T[] }
export interface Schedule { time: string; weekdays: number[]; timezone: string; enabled: boolean; reminder_one: string | null; reminder_two: string | null; deleted: boolean }
export interface Team { managers: { user: Person; history: boolean }[]; recipients: { user: Person; history: boolean }[] }
export interface Report { day: string | null; dates: string[]; parts: string[] }
export interface Delivery { id: number; day: string; telegram_id: number; status: string; time: string; error: string | null; kind: string; parts_sent: number; parts_total: number; initiated_by: number | null; initiated_by_name: string | null }
