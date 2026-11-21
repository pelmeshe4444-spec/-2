# Финальная проверка миграции Attendance

Состояние: **MIGRATED / CORE VERIFIED**, 21.11.2026 22:41 (Asia/Tashkent). Критических блокеров нет. Границы визуальной проверки Telegram перечислены отдельно; автоматический тест с Telegram bridge не выдаётся за настоящий клиент другого пользователя.

## Опубликованная инфраструктура

- Supabase Project ID: `vuwucpvbaaaguksdbznr`, Tokyo (`ap-northeast-1`), существующий Free Project.
- [Telegram-бот](https://t.me/attendance_10V_bot) → [GitHub Pages Mini App](https://pelmeshe4444-spec.github.io/-2/).
- База `VITE_API_URL`: `https://vuwucpvbaaaguksdbznr.supabase.co/functions/v1/api`.
- [Публичная проверка готовности](https://vuwucpvbaaaguksdbznr.supabase.co/functions/v1/api/api/v1/health): HTTP 200, `{"status":"ok"}`.
- Рабочий runtime commit: [`76eae47`](https://github.com/pelmeshe4444-spec/-2/commit/76eae472a98f5096d63aee11f3ab778748840614). [GitHub Actions](https://github.com/pelmeshe4444-spec/-2/actions/runs/44930858710): `validate`, `deploy-edge`, `publish-pages` — success. Pages deployment ID `7966932945`.
- Markdown отчёты обновляются отдельно и не вызывают повторного runtime deployment.

## Обязательная итоговая матрица

| Проверка | Статус | Проверяемое подтверждение |
|---|---|---|
| Все данные PostgreSQL перенесены | PASS | 25 таблиц, 695 строк; все канонические построчные SHA-256 совпали |
| Все API перенесены | PASS | AST-инвентаризация 75 методов/путей; `supabase/tests/routes.test.ts` сопоставляет реально зарегистрированный Router; подробности в MIGRATION_MATRIX.md |
| Telegram /start | PASS | Пользователь отправил /start, получил новый ответ и подтвердил открытие панели; обработанные updates сохранены в Supabase |
| Telegram webhook | PASS | getWebhookInfo указывает на Supabase, pending=0, last_error отсутствует; ни polling, ни старый startup webhook не активны |
| Регистрация пользователей | PASS | Настоящий повторный /start и owner upsert; числовой ID хранится как bigint. Первичная вставка и повторная регистрация покрыты PostgreSQL webhook integration test; 3 синтетических профиля созданы настоящим API |
| Назначение получателей | PASS | Владелец найден в candidates и назначен единственным получателем тестового класса без членства в нём; запись подтверждена SQL. Отдельный тест проверяет родителя вообще без membership |
| OWNER Dashboard | PASS | Подтверждение пользователя из Telegram + опубликованный React с реальными API; административные данные отклоняют MANAGER/CLASS_MEMBER/USER |
| Управление учениками | PASS | Настоящие bulk preview/add, полное длинное ФИО, поиск, archive/restore; редактирование в опубликованной мобильной форме и повторная загрузка |
| Управление классами | PASS | Отдельный QA класс создан настоящим API, сохранены права и состав; после проверки класс архивирован |
| Посещаемость | PASS | Все 5 статусов сохранены SQL; manager изменил отметку в опубликованном React и увидел её после reload; owner видит те же результаты, история сохранена |
| Расписание уроков | PASS | Предмет, урок понедельника, время/кабинет, изменение, bells, дата-замена и история сохранены Supabase API; CLASS_MEMBER получил свой план; day/week copy проверены Playwright |
| Ручные отчёты | PASS | Кнопка старосты в опубликованном React → реальный Telegram ACK, delivery id 6 / message_id 128 / sent / 1 из 1 частей |
| Автоматические отчёты | PASS | Настоящий pg_cron → pg_net → Edge → Telegram: delivery id 7 / message_id 129 / sent / 1 из 1 частей |
| Supabase Cron | PASS | Job `attendance-reports`, `* * * * *`, active=true; минимум 2 успешных запуска после включения тестового расписания, HTTP 200, автоматическая доставка остаётся единственной |
| GitHub Pages | PASS | Последний deployment success; HTTPS, base `/-2/`, HashRouter, production JS/CSS загружаются |
| React → Supabase API | PASS | 20 опубликованных браузерных проверок, настоящие API/DB; Render requests=0, pageErrors=0. Все 14 проверенных разделов дождались HTTP 200 своих данных |
| Сохранность данных | PASS | Реальный pg_restore в отдельной локальной PostgreSQL 18 и повторная сверка всех таблиц. После живых тестов все 695 исходных строк остаются неизменными |
| Безопасность и RLS | PASS | RLS 29/29; 29 запретов чтения через настоящий anonymous Data API, 2 запрета private schemas, 1 запрет Cron RPC; подпись/TTL/роли/nonce проверяются сервером |
| Полный E2E тест | PASS | Настоящий owner Telegram → Pages → Edge → PostgreSQL; scripted MANAGER React → Edge → Telegram Bot API и отдельный настоящий Cron. Telegram bridge остальных тестовых ролей — симуляция, см. ограничения |
| Отсутствие зависимости от Render | PASS | Runtime — Deno/TypeScript/Supabase PostgreSQL; в production bundle нет Render URL; старый workflow удалён, Render read-only и auto-deploy=off |

## Перенесённые данные

Это количества в момент финальной синхронизации **до QA-записей**. Проверены все строки, а не только суммы. В Supabase перед первоначальным копированием не было пользовательских данных; перед финальным импортом независимых изменений/конфликтов или устаревших лишних строк не обнаружено. Повторный импорт использует PK upsert и конфликтный preflight.

| Таблица | Перенесено строк |
|---|---:|
| `alembic_version` | 1 |
| `announcements` | 0 |
| `attendance` | 74 |
| `attendance_history` | 80 |
| `audit_logs` | 226 |
| `class_join_requests` | 16 |
| `class_memberships` | 14 |
| `class_timetables` | 1 |
| `classes` | 2 |
| `enrollments` | 38 |
| `lesson_time_slots` | 0 |
| `manager_assignments` | 3 |
| `notifications` | 33 |
| `report_deliveries` | 5 |
| `report_recipients` | 2 |
| `report_schedules` | 2 |
| `school_settings` | 1 |
| `students` | 38 |
| `subjects` | 17 |
| `system_events` | 84 |
| `timetable_change_history` | 2 |
| `timetable_exceptions` | 0 |
| `timetable_lessons` | 32 |
| `user_roles` | 5 |
| `users` | 19 |

Итого **695 строк, 25 исходных таблиц**. Настройки находятся в фактической `school_settings`, а не в вымышленной `settings`. Дополнительно созданы `api_rate_limits`, `download_tickets`, `telegram_updates`, `background_leases`.

Схема: 174 исходных столбца, 77 сопоставимых исходных ограничений, 57 исходных индексов, 19 точных serial states. Исходные 35 FK сохранены; вместе со служебным download ticket FK в Supabase валидны 36 FK. Невалидных ограничений — 0. В исходном public schema пользовательских triggers/functions не было; добавлена защищённая `attendance_queue_scheduler()`.

PostgreSQL 18 отдельно хранит 141 NOT NULL constraint, а PostgreSQL 17 — nullable metadata столбцов: проверены оба представления. Три CHECK отличаются только эквивалентной печатью casts/скобок; определения и типы сопоставлены.

Совпадающий SHA-256 файлов исходного и конечного manifest:

`5174d1090c401ca9d51a68c1358db4126db9f2d2791b5e9112e023563f5a35e4`

После тестов повторно проверено: missing original records=0, changed original records=0. Дополнительная read-only сверка самого Render также подтвердила прежние 695 строк и все fingerprints; поздних неперенесённых изменений нет, сетевые правила снова восстановлены. Добавлены только QA-записи и новые журнальные события. QA-класс `QA Supabase 20261121` оставлен в архиве с 5 вымышленными учениками и историей; 3 синтетических аккаунта заблокированы, временные manager/recipient назначения сняты, QA-рассылка отключена. Исходные школьные назначения и данные не удалялись.

## Edge Functions

| Функция | Версия | Статус |
|---|---:|---|
| `api` | 5 | ACTIVE |
| `report-scheduler` | 4 | ACTIVE |
| `send-report` | 4 | ACTIVE |
| `telegram-webhook` | 4 | ACTIVE |

`verify_jwt=false` используется намеренно: API проверяет Telegram HMAC и срок initData, webhook — Telegram secret header, scheduler — Vault HMAC/timestamp/одноразовый nonce либо серверный bearer. Telegram initData не считается Supabase Auth JWT. OWNER определяется по серверному OWNER_ID, а разрешения на класс перечитываются из БД.

## Тесты и доказательства

- **24 автоматических теста, 0 открытых failures**: 7 Deno, 3 Vitest, 8 Playwright, 6 legacy registration/write-freeze pytest. Deno дополнительно содержит **13 вложенных PostgreSQL integration steps**; они не складываются повторно с родительским тестом.
- Deno/CI используют настоящую изолированную PostgreSQL 17; локальная проверка также выполнена на PostgreSQL 18. Telegram transport локальных tests — подмена, а не доказательство доставки.
- **20 живых браузерных проверок** опубликованного Pages: desktop/mobile, light/dark, watermark, разделы OWNER, сохранение ФИО/отметок после reload, ограничение ролей, manual report, double-click/replay. Telegram bridge и initData тестовых ролей сгенерированы тестом; запросы API, PostgreSQL и Telegram Bot API настоящие.
- **22 staging API/auth запроса** перед cutover и **32 отрицательных Data API/RPC проверки** после deployment. Последние охватывают все 29 таблиц, net/vault schemas и Cron RPC.
- Реальные deliveries: manual id=6/message=128 и scheduled id=7/message=129, status=sent, parts_sent=parts_total=1. В обоих случаях получатель только владелец. Повторный manual request_id и минимум два Cron запуска не создали дополнительных доставок.
- Нативный pg_dump восстановлен, все 25 fingerprints совпали; после финального повторного подключения исходные 695 строк всё ещё совпали.
- Owner JSON backup реально загрузился в private Storage; защищённая ссылка скачивания работает; 29 таблиц и 19 counters сохранены. XLSX из настоящего API независимо прочитан openpyxl, полный длинный ФИО сохранён, присутствующие не перечислены поимённо.
- Production bundle проверен на текущие BOT_TOKEN/webhook/scheduler secrets и secret-key prefixes: совпадений нет. Серверные значения не публикуются.
- Supabase function logs за 21.11.2026 17:00–17:30 UTC: 153 записи, 0 error и 0 warning. System events после переключения — 0 ошибок. Промежуточные ошибки диагностических SQL-запросов к формату логов не являются ошибками приложения.
- Security advisor сообщил только 29 INFO `rls_enabled_no_policy`: намеренный запрет прямого клиентского доступа. [Описание advisor](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy). Permissive policies не добавлялись; фактический anonymous доступ проверен отказами.

Полная живая браузерная проверка выполнена на release `c886cd9`; следующий release добавляет только `database.backup` в журнал. После него повторно проверены readiness, OWNER session, database/webhook health, новая полная private backup и наличие audit event, deployment/Pages и целостность исходных данных. Frontend, auth, Telegram webhook, Cron и отчётный алгоритм не менялись; полный CI последнего release успешен.

## Найденные и исправленные проблемы

1. Миграция была незавершённой конфигурационно: локальный порт и Supabase staging уже существовали, но main/Pages, webhook и GitHub scheduler продолжали использовать Render. Выполнены проверенный merge/deploy, финальная синхронизация и cutover всех трёх путей.
2. Между первоначальной и финальной копиями источник вырос с 630 до 695 строк; перенесены все последующие изменения без дубликатов и без удаления данных Supabase.
3. Устранены PostgreSQL CASE/type ambiguity и двойное кодирование JSON/jsonb; тесты реально восстановили версии расписаний и exceptions.
4. Unicode casefold и полные ФИО соответствуют прежним ключам; слово-count ограничений нет. Serial counters берутся из источника, а не сбрасываются в max(id).
5. Старую SQLite-only кнопку backup адаптировали к PostgreSQL: private Storage, 29 таблиц, 19 counters, tickets; сохранены audit events `statistics.exported` и `database.backup`.
6. В pg_net не передаётся reusable scheduler secret: вместо него короткоживущая HMAC подпись и одноразовый nonce; secret хранится в Vault. Net/vault не доступны через Data API.
7. Linux CI требовал дополнительное test-only Deno system permission для независимого ExcelJS reader; исправлено. Первоначальные failed CI прогоны закрыты успешными. Браузерные проверки стали ожидать реальные данные облака вместо локального 5-секундного timeout и быстрой навигации с искусственной очередью запросов.

## Непроверенные визуальные сценарии

**3 группы NOT VERIFIED**, без критического backend блокера:

1. Первый `/start` совершенно нового независимого реального Telegram-аккаунта после cutover. Проверены native повторный owner /start, production profile inserts и полный first-start webhook сценарий на isolated PostgreSQL.
2. Настоящие отдельные Telegram-клиенты MANAGER и CLASS_MEMBER. Их роль/маршруты/данные/изменения проверены браузером через реальные API и production PostgreSQL с тестовым Telegram bridge.
3. Матрица iOS/Android/Desktop Telegram и нативное сохранение файла через Telegram downloadFile. Опубликованный браузер проверен при 390 и 1440 px, native owner запуск подтверждён пользователем, сами XLSX/JSON/download endpoints проверены реально.

Массовые объявления реальным школьным получателям специально не отправлялись: их audience/confirmation/queue/права проверены isolated integration tests; реальный transport подтверждён owner уведомлением о QA заявке и двумя отчётами. Это не обещание визуального теста каждого устройства или каждой комбинации полей.

## Render и безопасное отключение

Старые Web Service и attendance-db **не удалены**. На Render активны ATTENDANCE_READ_ONLY=true, TELEGRAM_UPDATES_MODE=polling для отключения startup setWebhook в web-процессе, auto-deploy=off. Этот web-процесс не запускает polling; локальная Windows polling task тоже Disabled. Старый GitHub workflow удалён после отключения. Исходный DB ipAllowList восстановлен в []; база не открывалась всему интернету, временно использовался только workstation IPv4 /32.

Рабочее приложение не требует Render. Перед любым последующим удалением: сохранить свежий Supabase backup, проверить его восстановление, убедиться в отсутствии старых ссылок/отправителей и отдельно согласовать удаление старых ресурсов. До этого Render остаётся закрытой точкой отката. Free Render PostgreSQL имеет объявленный срок окончания 17.12.2026; локальные копии не зависят от его доступности.

### Откат с сохранением новых данных

1. При необходимости отката временно ограничить записи **в Supabase**, выключить Cron, дождаться завершения активных отправок и проверить фактический 503; webhook на этом этапе не удалять и pending updates не сбрасывать.
2. Сохранить свежие 29 таблиц/counters и конфигурацию. Старый Render snapshot — только контрольная точка, его нельзя автоматически считать последними данными после новых действий пользователей.
3. Восстановить/сверить актуальные 25 бизнес-таблиц в отдельной проверочной базе, затем подготовить обратную синхронизацию в Render с проверкой конфликтов, PK/FK и актуальных permissions. Простого переключения на устаревшую БД недостаточно.
4. Только после сверки развернуть совместимую сохранённую Python версию с восстановленной БД и отключённым read-only, собрать Pages с Render API, переключить webhook на прежний endpoint с его серверным secret. Проверить owner доступ, новые действия и доставку.
5. Вернуть ровно один старый scheduler при выключенном Supabase Cron; polling одновременно с webhook не включать. Не пересылать автоматически deliveries с неопределённым результатом.

## Резервные копии и восстановление

Копии хранятся **вне публикуемого checkout**, в рабочей папке Codex `data/attendance-backups/`. Начальная `initial-20261120` и финальная `final-20261121-verified` сохранены; промежуточный частичный экспорт не используется как проверенная контрольная точка. Финальная папка содержит custom `attendance.dump`, schema.sql, переносимый restore.sql, rows.json, manifest, catalog, сравнение Supabase и integrity proof. Архив полностью прочитан pg_restore и реально восстановлен в отдельную local `attendance_restore_check`; совпали все строки.

Нативный архив Render создан PostgreSQL 18. Проверенное нативное восстановление — в PostgreSQL 18. Для Supabase PostgreSQL 17 применены совместимые repo migrations и проверенный PK import с сохранением serial states; нельзя считать прямое выполнение произвольного PG18 DDL на PG17 проверенным.

Владелец может получить свежий JSON через «Настройки» Mini App: файл отдаётся владельцу и сохраняется в **private** bucket attendance-backups. Копия содержит 29 application tables и 19 точных serial states; schema/Edge source берутся из соответствующего GitHub commit. Provider Auth/Storage internals и secrets не включаются в эту application-копию. Зафиксировать вместе с копией runtime commit, дату, manifest и серверную конфигурацию в защищённом хранилище.

Практический план: ежедневная owner копия после работы и перед массовыми изменениями; отдельная зашифрованная offline копия; хранить, например, 30 дневных и 12 месячных поколений, контролируя Storage quota. Автоматического nightly pg_dump и PITR эта миграция **не обещает**. Это план эксплуатации; новый платный backup service не создавался.

Восстановление JSON выполнять сначала в **пустую отдельную базу** с соответствующими migrations, затем импортировать таблицы в FK порядке, восстановить counters и проверить все количества/fingerprints и роли. Не импортировать копию поверх действующих независимых изменений без preflight. Secrets/Vault/Cron и webhook конфигурируются отдельно, Cron активируется только после проверки и остановки прежнего sender. Восстановленные транзитные leases/tickets не должны считаться бессрочными разрешениями.

## Бесплатный тариф

Ресурсы остались на Free, новые платные сервисы не создавались. По [текущим условиям Supabase](https://supabase.com/pricing): 500 MB БД, 1 GB Storage, 500 000 Edge invocations, логи API/DB — 1 день, возможна пауза после недели неактивности. По [лимитам Edge](https://supabase.com/docs/guides/functions/limits): 256 MB памяти, 2 s CPU, 150 s wall-clock на Free. Cron раз в минуту — около 43 200 вызовов за 30 дней, до пользовательского трафика.

Нет гарантии 24/7 на Free. Cold starts, пауза проекта, сеть или Telegram rate limits могут задержать отчёты; catch-up ограничен 18 часами, а неопределённая доставка не повторяется автоматически. Приватный Storage в том же проекте не заменяет независимую offline копию. Платные upgrades, PITR или гарантированный SLA не подключались.
