# Итоговая проверка Attendance

Статус на подготовительном этапе: IN PROGRESS. Этот файл обновляется фактическими результатами после последнего развёртывания; наличие кода не считается подтверждением работы production.

| Проверка | Статус | Подтверждение |
|---|---|---|
| Первоначальная копия 25 таблиц | PASS | Согласованный pg_dump snapshot; все построчные fingerprints совпали |
| Финальная копия и целостность данных | NOT VERIFIED | Требуется ограничить записи и повторно синхронизировать источник |
| Полнота API | PASS | 75 AST-discovered методов/путей, routes.test.ts |
| Серверные сценарии | PASS | 6 Deno тестов, 13 PostgreSQL integration steps; Telegram transport тестовый |
| Telegram HMAC / роли / RLS | PASS | Положительные и отрицательные проверки, anonymous SQL denied |
| Frontend unit | PASS | 3 Vitest теста |
| Telegram webhook после переключения | NOT VERIFIED | Пока Render primary |
| Регистрация через настоящий /start | NOT VERIFIED | Требуется после cutover |
| Назначение получателя в production | NOT VERIFIED | Требуется после cutover |
| OWNER Dashboard опубликованной версии | NOT VERIFIED | Требуется новая Pages сборка |
| Управление учениками / классами | NOT VERIFIED | Локальные integration и browser проверки отдельно от production |
| Посещаемость / расписание | NOT VERIFIED | Требуется проверка опубликованной версии |
| Ручной отчёт Telegram | NOT VERIFIED | Требуется реальный ACK Telegram |
| Автоматический отчёт Telegram | NOT VERIFIED | Требуется Cron и реальный ACK Telegram |
| Supabase Cron | NOT VERIFIED | Job создан, пока выключен |
| GitHub Pages → Supabase | NOT VERIFIED | Production пока использует Render |
| Отсутствие зависимости от Render | NOT VERIFIED | Переключение ещё не выполнено |
| Полная цепочка E2E | NOT VERIFIED | Требуется опубликованная проверка и настоящий Telegram |

Подробный перечень проверок, ограничения бесплатного тарифа, безопасный откат и восстановление добавляются по результатам cutover. Секреты и персональные сведения в отчёт не включаются.
