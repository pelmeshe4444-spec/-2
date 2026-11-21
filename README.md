# Attendance · Telegram Mini App

Attendance ведёт посещаемость школы внутри Telegram Mini App. React-интерфейс и бот используют один backend и одну базу. Бот открывает приложение из `/start` и кнопки меню, доставляет автоматические отчёты и напоминания. Для управления откройте Mini App.

## Supabase и GitHub Pages

Новая серверная реализация находится в `supabase/functions`, миграции PostgreSQL — в `supabase/migrations`. Это TypeScript/Deno, без Python в рабочем запросе. Mini App сохраняет существующий React-интерфейс и размещается на GitHub Pages с `VITE_BASE_PATH=/-2/` и `VITE_API_URL=https://vuwucpvbaaaguksdbznr.supabase.co/functions/v1/api`.

Актуальное состояние переключения и доказательства: [аудит](MIGRATION_AUDIT.md), [матрица API и данных](MIGRATION_MATRIX.md), [отчёт проверки](FINAL_VERIFICATION_REPORT.md). Разделы Python/Docker ниже сохранены для локальной работы и отката.

Серверные переменные перечислены в `supabase/.env.example`. Их задают через Supabase Secrets; BOT_TOKEN и service credentials не передают в VITE. Telegram initData проверяет сам backend; это не Supabase Auth JWT. Клиентским ролям Data API запрещён доступ к школьным таблицам. Cron использует защищённую серверную функцию с Vault/HMAC.

Проверка нового backend: `deno task --config supabase/functions/deno.json check` и `deno task --config supabase/functions/deno.json test`. Для PostgreSQL integration задайте `ATTENDANCE_TEST_DATABASE_URL` только для отдельной базы **attendance_test** на loopback. Fixtures пересоздают исключительно её public schema; production URL отклоняется. Frontend: `npm ci`, `npm run test`, `npm run build`, `npm run test:e2e` из `frontend` (Deno в PATH). GitHub Actions выполняет эти проверки с PostgreSQL 17 до развёртывания.

## Возможности

- **Владелец.** Главная со сводкой, диаграммой и последними действиями. Управление учениками, классами, доступом, расписанием и данными школы. Статистика, личная история ученика, Excel, защищённая резервная копия PostgreSQL (SQLite при локальном запуске) и журнал действий.
- **Ответственный.** Отметки сегодняшнего дня по назначенным классам. Автосохранение, комментарии, автор и время изменения. Просмотр прошлых дат включается по классу. Владелец может редактировать прошлые даты.
- **Получатель.** Просмотр доставленных отчётов по разрешённым классам и датам. Получатель должен один раз открыть личный чат с ботом и нажать `/start`. Роли получателя и ответственного могут совмещаться.
- **Новый пользователь.** Выбор класса и подача заявки, без доступа к закрытым данным до одобрения. Заблокированный пользователь видит ограничение доступа.

Массовая отметка меняет только учеников со статусом «Не отмечен». При конфликте версий приложение обновляет данные и просит повторить действие. Перевод ученика действует со следующего календарного дня. Архивирование сразу исключает из текущего списка и сохраняет предыдущие даты и личную историю. Для статистики периода каждая пара «ученик × календарный день» считается одной записью. Процент посещаемости считается от всех записей, включая неотмеченные.

В новых рассылках сохраняется содержимое последнего успешно доставленного отчёта за каждую дату за последние 90 дней. Журнал результатов сохраняется отдельно. При сбое установления соединения или коротком `RetryAfter` бот делает до трёх попыток. Тайм-аут с неизвестным результатом отмечается как «Не подтверждено». После перезапуска бот подхватывает ещё не отправленные отчёты за текущую дату расписания. Одно расписание действует на один класс.

## Запуск на Windows 11

Для работы на этом компьютере с настроенным `.env` запустите `.\.venv\Scripts\python.exe desktop.py`. Attendance откроет панель владельца в браузере на локальном адресе. Сеанс доступен в текущем профиле браузера, пока работает процесс. При первом запуске соберите frontend командами ниже.

Нужны Python 3.12+ и Node.js 22.12+ либо 24+. Если бот уже настроен, сохраните его `.env` и SQLite. Alembic применяет миграции без удаления существующих учеников, отметок или прав.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
```

При первой установке скопируйте `.env.example` в `.env`. Укажите `BOT_TOKEN` от BotFather и числовой `OWNER_ID`. Если ID неизвестен, временно задайте `OWNER_ID=1` и оставьте `MINI_APP_URL` пустым. Запустите бота, нажмите `/start` и возьмите ID из ответа в личном чате. После этого подставьте настоящий ID и остановите временный экземпляр.

```dotenv
BOT_TOKEN=your_bot_token
OWNER_ID=123456789
DATABASE_URL=sqlite+aiosqlite:///data/attendance.sqlite3
TIMEZONE=Asia/Tashkent
MINI_APP_URL=https://attendance.example.org
INIT_DATA_TTL=3600
LOG_LEVEL=INFO
```

Запустите проверку и веб-сервер. `GET http://127.0.0.1:8000/api/health` проверяет готовность базы. Открытие страницы в обычном браузере показывает приглашение открыть её из Telegram. Запросы к данным требуют `initData`, выданную Telegram.

```powershell
.\.venv\Scripts\python.exe main.py --check
.\.venv\Scripts\python.exe web_main.py
```

Для редактирования интерфейса с горячим обновлением можно параллельно запустить `npm.cmd --prefix frontend run dev`. Vite проксирует `/api` на локальный FastAPI. Для полноценного входа из Telegram укажите стабильный HTTPS-адрес. Если веб-сервер работает на Windows, настройте свой HTTPS-прокси до порта `8000`. Приложение ожидает, что оно доступно из корня выделенного домена.

Когда `https://ваш-домен/api/health` отвечает `{"status":"ok"}`, укажите его корневой адрес в `MINI_APP_URL` и запустите бота в отдельном терминале либо перезапустите его существующую задачу Windows. Для одного токена должен работать один экземпляр polling.

```powershell
.\.venv\Scripts\python.exe main.py --log-file data/attendance-service.log
```

Для фонового запуска укажите в Планировщике заданий абсолютный путь к `.venv\Scripts\pythonw.exe`, параметры `-X utf8 main.py --log-file data/attendance-service.log` и рабочую папку проекта. Включите запуск при входе в Windows и перезапуск при сбое. Для веб-сервера нужна отдельная постоянно работающая задача или сервер. Бот и веб-процесс используют один `DATABASE_URL`.

## Сервер с PostgreSQL и HTTPS

### Существующий сервис Render с runtime Docker

В **Settings → Build & Deploy** укажите связанный репозиторий и ветку `main`. Оставьте **Root Directory** пустым, укажите `./Dockerfile` и контекст `.`. Сборке нужны `frontend/`, `backend/`, `bot/`, `database/`, `services/` и `migrations/` из корня репозитория. Контейнер слушает `0.0.0.0` и читает `PORT` при запуске. Для проверки сервиса используйте `/api/health`. Значения `BOT_TOKEN`, `OWNER_ID`, `DATABASE_URL` и секреты webhook и планировщика задайте в **Environment** на Render. [Документация Render](https://render.com/docs/docker)

Для GitHub Pages выберите **GitHub Actions** в качестве источника публикации и укажите адрес Pages в `MINI_APP_URL` на Render. Workflow собирает Mini App для Pages после тестов Python, Vitest и Playwright и проверки Docker с PostgreSQL. В настройках Render выберите **After CI Checks Pass**.

Для облачного расписания задайте секрет `SCHEDULER_SECRET` с одинаковым значением на Render и в GitHub Actions. Workflow вызывает защищённый планировщик дважды в час. Время фактической доставки зависит от запуска GitHub Actions и пробуждения бесплатного Render. История отправок сохраняется в базе.

Mini App открывает нужный раздел после серверной проверки Telegram `initData`. Владелец попадает в `/admin`, ответственный в `/manager`, участник класса в `/student`, новый пользователь в `/register`. На телефоне остальные административные страницы доступны через «Разделы». В «Состоянии системы» видны проверка базы, состояние webhook и результаты планировщика. Изменения общего времени отчёта и учебных дней задают настройки новых классов. У существующих рассылок собственное расписание.

### Самостоятельный сервер с Docker Compose

1. Направьте DNS выделенного домена на сервер с Docker Compose. Откройте входящие `80/tcp` и `443/tcp` для Caddy.
2. Создайте на сервере `.env`. Задайте `BOT_TOKEN`, `OWNER_ID`, `ATTENDANCE_DOMAIN` и случайный URL-безопасный `POSTGRES_PASSWORD`. Пароль можно получить через `python -c "import secrets; print(secrets.token_urlsafe(32))"`. `ATTENDANCE_DOMAIN` указывают без `https://` и косой черты. Compose формирует адрес сервиса и строку PostgreSQL из этих переменных.
3. Если нужно перенести существующую SQLite, остановите старый бот, сделайте согласованную копию базы и выполните перенос перед запуском `bot` и `web`. Если перенос не требуется, запустите весь стек.

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=50 bot web caddy
```

Для переноса на свежую PostgreSQL из копии SQLite выполните следующие команды. `transfer_sqlite.py` обновит схему копии, перенесёт записи с исходными ID и проверит, что база назначения пуста. Используйте отдельную копию `attendance-copy.sqlite3`.

```bash
docker compose up -d --wait db
docker compose build web
docker compose run --rm --no-deps --user root -v "$PWD/attendance-copy.sqlite3:/tmp/attendance-copy.sqlite3" web python transfer_sqlite.py /tmp/attendance-copy.sqlite3
docker compose up -d
```

Caddy завершает HTTPS и проксирует интерфейс и API на FastAPI. `db` и `web` не публикуются наружу. Контейнер бота выполняет polling и APScheduler. Контейнер веб-приложения обслуживает собранный frontend и запросы API. Telegram Mini App может быть закрыт во время отправок. Настройки расписания вступают в силу без перезапуска. [Документация Caddy](https://caddyserver.com/docs/automatic-https)

Для резервной копии PostgreSQL используйте `docker compose exec -T db pg_dump -U attendance attendance > attendance.sql`. Ограничьте доступ к файлу. Резервную копию SQLite можно скачать из настроек Mini App.

## Подключение к BotFather

1. Откройте официального [@BotFather](https://t.me/BotFather), выберите существующего бота через `/mybots` либо создайте нового через `/newbot`.
2. В настройках выбранного бота откройте **Main Mini App** и укажите публичный HTTPS-адрес. В профиле появится кнопка открытия. Этот шаг требует доступа к настройкам владельца бота в BotFather.
3. При старте приложение выставляет кнопку меню через `setChatMenuButton`. В BotFather то же можно настроить через **Menu Button** или `/setmenubutton`. В ответ на `/start` бот показывает кнопку с тем же адресом.
4. Откройте приложение из личного чата. Владелец увидит Главную. Настройте школу, классы и права, затем проверьте рассылку через **Расписание → Отправить сейчас**. Настройки профиля дополнительно можно проверить через ссылку `https://t.me/имя_бота?startapp`. [Руководство Telegram Mini Apps](https://core.telegram.org/bots/webapps)

## Тестирование и безопасность

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
$env:PLAYWRIGHT_CHANNEL = 'msedge'
npm.cmd --prefix frontend run test:e2e
```

Для Chromium вместо Edge установите браузер через `npx playwright install chromium` из `frontend/` и запустите тесты без `PLAYWRIGHT_CHANNEL`. Playwright поднимает отдельный FastAPI с временной базой и тестовыми данными. Он проверяет desktop и мобильную ширину с подменой WebView-моста. Для Linux используйте `.venv/bin/python` и `npm`.

Backend проверяет HMAC и срок действия Telegram `initData`, проверяет блокировку и доступ на сервере, ограничивает запросы по IP и Telegram ID. Токен хранится в окружении сервера. `initData` передаётся только в авторизационном заголовке. Истечение срока действия требует заново открыть Mini App. Для защищённой загрузки в новых клиентах Telegram сервер выдаёт ссылку на 90 секунд. API и отчёты используют данные заданного класса. Содержимое базы и отчётов должно храниться с ограниченным доступом. [Проверка initData в документации Telegram](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app)
