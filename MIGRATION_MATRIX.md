# Матрица миграции Attendance

Исходный commit: `38fe3c821351957d66bf59bf65fc7dab75dfda97`. Маршруты автоматически извлечены AST из четырёх файлов FastAPI. `supabase/tests/routes.test.ts` проверяет наличие каждого метода и пути в реально зарегистрированном TypeScript Router.

## API

Префикс старого API: `https://2-cmnw.onrender.com/api`. Новый: `https://vuwucpvbaaaguksdbznr.supabase.co/functions/v1/api/api/v1`. Параметры пути сохранены; дополнительные `/api` aliases поддерживаются. Наличие маршрута проверено отдельно от поведения: интеграционные и опубликованные проверки перечислены в FINAL_VERIFICATION_REPORT.md.

| Метод | Старый путь | Новый путь после префикса | Исходник |
|---|---|---|---|
| GET | `/api/admin/announcements` | `/admin/announcements` | `backend/admin_routes.py:115` |
| POST | `/api/admin/announcements` | `/admin/announcements` | `backend/admin_routes.py:130` |
| POST | `/api/admin/announcements/preview` | `/admin/announcements/preview` | `backend/admin_routes.py:123` |
| GET | `/api/admin/audit-logs` | `/admin/audit-logs` | `backend/api.py:496` |
| GET | `/api/admin/dashboard` | `/admin/dashboard` | `backend/admin_routes.py:62` |
| GET | `/api/admin/join-requests` | `/admin/join-requests` | `backend/school_routes.py:101` |
| POST | `/api/admin/join-requests/{request_id}/approve` | `/admin/join-requests/{request_id}/approve` | `backend/school_routes.py:112` |
| POST | `/api/admin/join-requests/{request_id}/reject` | `/admin/join-requests/{request_id}/reject` | `backend/school_routes.py:117` |
| GET | `/api/admin/recipient-candidates` | `/admin/recipient-candidates` | `backend/api.py:349` |
| GET | `/api/admin/stats/comparison` | `/admin/stats/comparison` | `backend/api.py:481` |
| GET | `/api/admin/system-health` | `/admin/system-health` | `backend/admin_routes.py:92` |
| GET | `/api/admin/users` | `/admin/users` | `backend/api.py:357` |
| GET | `/api/admin/users/{target}/audit-logs` | `/admin/users/{target}/audit-logs` | `backend/api.py:501` |
| PUT | `/api/admin/users/{target}/membership` | `/admin/users/{target}/membership` | `backend/school_routes.py:121` |
| PATCH | `/api/admin/users/{target}/roles` | `/admin/users/{target}/roles` | `backend/api.py:403` |
| GET | `/api/audit` | `/audit` | `backend/api.py:495` |
| GET | `/api/backup` | `/backup` | `backend/api.py:575` |
| GET | `/api/classes` | `/classes` | `backend/api.py:242` |
| POST | `/api/classes` | `/classes` | `backend/api.py:249` |
| DELETE | `/api/classes/{class_id}` | `/classes/{class_id}` | `backend/api.py:257` |
| PATCH | `/api/classes/{class_id}` | `/classes/{class_id}` | `backend/api.py:253` |
| GET | `/api/classes/{class_id}/access` | `/classes/{class_id}/access` | `backend/api.py:265` |
| GET | `/api/classes/{class_id}/attendance` | `/classes/{class_id}/attendance` | `backend/api.py:305` |
| POST | `/api/classes/{class_id}/attendance/finish` | `/classes/{class_id}/attendance/finish` | `backend/api.py:344` |
| GET | `/api/classes/{class_id}/attendance/history` | `/classes/{class_id}/attendance/history` | `backend/api.py:328` |
| POST | `/api/classes/{class_id}/attendance/mark-all` | `/classes/{class_id}/attendance/mark-all` | `backend/api.py:340` |
| PUT | `/api/classes/{class_id}/attendance/{student_id}` | `/classes/{class_id}/attendance/{student_id}` | `backend/api.py:322` |
| GET | `/api/classes/{class_id}/deliveries` | `/classes/{class_id}/deliveries` | `backend/api.py:443` |
| GET | `/api/classes/{class_id}/export` | `/classes/{class_id}/export` | `backend/api.py:566` |
| GET | `/api/classes/{class_id}/report` | `/classes/{class_id}/report` | `backend/api.py:455` |
| GET | `/api/classes/{class_id}/reports/last-manual` | `/classes/{class_id}/reports/last-manual` | `backend/api.py:439` |
| POST | `/api/classes/{class_id}/restore` | `/classes/{class_id}/restore` | `backend/api.py:261` |
| DELETE | `/api/classes/{class_id}/schedule` | `/classes/{class_id}/schedule` | `backend/api.py:425` |
| GET | `/api/classes/{class_id}/schedule` | `/classes/{class_id}/schedule` | `backend/api.py:417` |
| PUT | `/api/classes/{class_id}/schedule` | `/classes/{class_id}/schedule` | `backend/api.py:421` |
| POST | `/api/classes/{class_id}/send` | `/classes/{class_id}/send` | `backend/api.py:429` |
| GET | `/api/classes/{class_id}/stats` | `/classes/{class_id}/stats` | `backend/api.py:474` |
| GET | `/api/classes/{class_id}/students` | `/classes/{class_id}/students` | `backend/api.py:269` |
| POST | `/api/classes/{class_id}/students` | `/classes/{class_id}/students` | `backend/api.py:278` |
| GET | `/api/classes/{class_id}/timetable` | `/classes/{class_id}/timetable` | `backend/school_routes.py:168` |
| PUT | `/api/classes/{class_id}/timetable` | `/classes/{class_id}/timetable` | `backend/school_routes.py:176` |
| PUT | `/api/classes/{class_id}/timetable/bells` | `/classes/{class_id}/timetable/bells` | `backend/school_routes.py:183` |
| GET | `/api/classes/{class_id}/timetable/editor` | `/classes/{class_id}/timetable/editor` | `backend/school_routes.py:172` |
| PUT | `/api/classes/{class_id}/timetable/exceptions/{day}` | `/classes/{class_id}/timetable/exceptions/{day}` | `backend/school_routes.py:187` |
| GET | `/api/classes/{class_id}/timetable/history` | `/classes/{class_id}/timetable/history` | `backend/school_routes.py:194` |
| POST | `/api/classes/{class_id}/timetable/history/{change_id}/restore` | `/classes/{class_id}/timetable/history/{change_id}/restore` | `backend/school_routes.py:198` |
| GET | `/api/downloads/{key}` | `/downloads/{key}` | `backend/api.py:580` |
| HEAD | `/api/downloads/{key}` | `/downloads/{key}` | `backend/api.py:580` |
| GET | `/api/health` | `/health` | `backend/api.py:201` |
| POST | `/api/internal/scheduler/run` | `/internal/scheduler/run` | `backend/cloud_routes.py:43` |
| GET | `/api/join-requests` | `/join-requests` | `backend/school_routes.py:100` |
| POST | `/api/join-requests` | `/join-requests` | `backend/school_routes.py:94` |
| GET | `/api/join-requests/me` | `/join-requests/me` | `backend/school_routes.py:86` |
| PATCH | `/api/join-requests/{request_id}` | `/join-requests/{request_id}` | `backend/school_routes.py:106` |
| GET | `/api/me` | `/me` | `backend/api.py:207` |
| PUT | `/api/me/lesson-notifications` | `/me/lesson-notifications` | `backend/school_routes.py:127` |
| GET | `/api/notifications` | `/notifications` | `backend/school_routes.py:132` |
| POST | `/api/notifications/read` | `/notifications/read` | `backend/school_routes.py:138` |
| POST | `/api/reports/send-now` | `/reports/send-now` | `backend/api.py:434` |
| GET | `/api/settings` | `/settings` | `backend/api.py:509` |
| PUT | `/api/settings` | `/settings` | `backend/api.py:514` |
| DELETE | `/api/students/{student_id}` | `/students/{student_id}` | `backend/api.py:297` |
| GET | `/api/students/{student_id}` | `/students/{student_id}` | `backend/api.py:284` |
| PATCH | `/api/students/{student_id}` | `/students/{student_id}` | `backend/api.py:292` |
| POST | `/api/students/{student_id}/restore` | `/students/{student_id}/restore` | `backend/api.py:301` |
| GET | `/api/subjects` | `/subjects` | `backend/school_routes.py:156` |
| POST | `/api/subjects` | `/subjects` | `backend/school_routes.py:160` |
| PUT | `/api/subjects/{subject_id}` | `/subjects/{subject_id}` | `backend/school_routes.py:164` |
| POST | `/api/telegram/webhook` | `/telegram/webhook` | `backend/cloud_routes.py:25` |
| GET | `/api/users` | `/users` | `backend/api.py:356` |
| POST | `/api/users` | `/users` | `backend/api.py:375` |
| GET | `/api/users/{target}` | `/users/{target}` | `backend/api.py:379` |
| PATCH | `/api/users/{target}` | `/users/{target}` | `backend/api.py:398` |
| POST | `/api/users/{target}/access` | `/users/{target}/access` | `backend/api.py:402` |
| PUT | `/api/users/{target}/classes/{class_id}/timetable-access` | `/users/{target}/classes/{class_id}/timetable-access` | `backend/school_routes.py:143` |

Всего 75 методов и путей. Локальный `/desktop/open/{key}` и HTML/asset fallback FastAPI не являются production API: frontend обслуживается GitHub Pages. Защищённые скачивания GET/HEAD перенесены в PostgreSQL tickets со сроком 90 секунд. Резервная копия PostgreSQL возвращает JSON вместо SQLite.

Отдельные входы: `/functions/v1/telegram-webhook`, `/functions/v1/send-report`, `/functions/v1/report-scheduler`. Старые webhook/internal scheduler пути внутри API оставлены защищёнными aliases.

## PostgreSQL

Финальная синхронизация выполнена после ограничения записи на Render. Все 25 таблиц совпали построчно; после живых тестов ни одна из 695 исходных строк не исчезла и не изменилась.

| Render public table → Supabase public table | Первоначально | Финально перенесено |
|---|---:|---:|
| `alembic_version` → `alembic_version` | 1 | 1 |
| `announcements` → `announcements` | 0 | 0 |
| `attendance` → `attendance` | 74 | 74 |
| `attendance_history` → `attendance_history` | 80 | 80 |
| `audit_logs` → `audit_logs` | 211 | 226 |
| `class_join_requests` → `class_join_requests` | 16 | 16 |
| `class_memberships` → `class_memberships` | 6 | 14 |
| `class_timetables` → `class_timetables` | 1 | 1 |
| `classes` → `classes` | 2 | 2 |
| `enrollments` → `enrollments` | 38 | 38 |
| `lesson_time_slots` → `lesson_time_slots` | 0 | 0 |
| `manager_assignments` → `manager_assignments` | 3 | 3 |
| `notifications` → `notifications` | 25 | 33 |
| `report_deliveries` → `report_deliveries` | 3 | 5 |
| `report_recipients` → `report_recipients` | 1 | 2 |
| `report_schedules` → `report_schedules` | 2 | 2 |
| `school_settings` → `school_settings` | 1 | 1 |
| `students` → `students` | 38 | 38 |
| `subjects` → `subjects` | 17 | 17 |
| `system_events` → `system_events` | 55 | 84 |
| `timetable_change_history` → `timetable_change_history` | 2 | 2 |
| `timetable_exceptions` → `timetable_exceptions` | 0 | 0 |
| `timetable_lessons` → `timetable_lessons` | 32 | 32 |
| `user_roles` → `user_roles` | 4 | 5 |
| `users` → `users` | 18 | 19 |

Всего: 630 → 695 строк. Сохранены все 174 столбца, PK/FK, 57 индексов и точные 19 sequences. Сопоставлено 77 исходных ограничений; NOT NULL metadata проверены с учётом PG18/PG17. Дополнительно созданы api_rate_limits, download_tickets, telegram_updates, background_leases; все 29 таблиц закрыты для прямых клиентских обращений.

Новая JSON backup включает все 29 таблиц и 19 serial states, а также исходный audit event database.backup. Секреты находятся в серверной конфигурации и Vault, не в JSON или frontend.

## Компоненты и настройки

| Прежний компонент | Новый компонент |
|---|---|
| FastAPI auth / permissions | `_shared/auth.ts`, `_shared/core.ts`: HMAC, TTL, числовой Telegram ID, серверные OWNER и class permissions |
| SQLAlchemy / Alembic | Parameterized postgres.js и `supabase/migrations/*.sql`; исходная Alembic версия сохранена |
| Directory / memberships | `directory.ts`, `memberships.ts`: профиль, bulk, классы, права, заявки, уведомления |
| Attendance / statistics | `attendance.ts`, `admin.ts`: версии, история, enrolments, статистика и журнал |
| School timetable | `timetable.ts`: предметы, A/B, звонки, даты действия, исключения, копии и restore |
| Reports / Telegram sender | `reports.ts`, `telegram.ts`: единый формат, durable claim, retry/uncertain и checkpoints |
| GitHub scheduled-reports → Render | Supabase pg_cron → pg_net → HMAC protected report-scheduler; переключается после финальной копии |
| Render PostgreSQL credentials | Встроенный `SUPABASE_DB_URL`; старый URL не используется в Edge Functions |
| BOT_TOKEN, OWNER_ID, timezone | Серверные Supabase secrets, не VITE переменные |
| Cron shared secret | Supabase server secret + Vault; pg_net передаёт короткоживущую HMAC подпись и одноразовый nonce |
| GitHub Pages build | `.github/workflows/supabase.yml`, production VITE_API_URL Supabase, Pages base `/-2/` |
| React routing / role dashboard | Существующий React Router и UI сохранены; mobile/desktop и watermark сохранены |
| Excel / database backup | Лёгкий OpenXML XLSX; owner-only JSON в приватном Storage bucket `attendance-backups` |
| Legacy Python / Docker | Оставлены для безопасного отката, не используются новым production backend |
