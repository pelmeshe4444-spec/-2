from datetime import date
from html import escape
from secrets import token_hex

from bot.common import PAGE, back, button, navigation, paginate, title
from services.directory import parse_students
from services.permissions import UserError
from services.reports import DELIVERY_STATUS, WEEKDAYS, add_section


SCHEDULE_FIELDS = {
    'time': ('🕒 Время отчёта', 'Введите время отчёта в формате ЧЧ:ММ, например 08:30.'),
    'weekdays': ('📆 Дни недели', 'Введите номера дней через пробел. Пн — 1, Вс — 7. Например, 1 2 3 4 5.'),
    'reminder_one': ('🔔 Напоминание 1', 'Введите время первого напоминания в формате ЧЧ:ММ. Для отключения введите -.'),
    'reminder_two': ('🔔 Напоминание 2', 'Введите время второго напоминания в формате ЧЧ:ММ. Для отключения введите -.'),
}

ACTIONS = {
    'user.started': 'Пользователь запустил бота', 'user.profile_updated': 'Профиль пользователя обновлён',
    'class.added': 'Класс добавлен', 'student.added': 'Ученик добавлен',
    'student.updated': 'Данные ученика изменены', 'student.archived': 'Ученик архивирован',
    'attendance.marked': 'Отметка изменена', 'attendance.bulk': 'Массовая отметка',
    'attendance.finished': 'Отметка завершена', 'schedule.updated': 'Расписание изменено',
    'database.backup': 'Запрошена резервная копия', 'delivery.claimed': 'Начата отправка',
    'delivery.sent': 'Сообщение доставлено', 'delivery.failed': 'Ошибка отправки',
    'delivery.uncertain': 'Доставка не подтверждена', 'delivery.cancelled': 'Отправка отменена',
    'delivery.recovered': 'Проверены прерванные отправки', 'statistics.exported': 'Экспорт в Excel',
    'access.manager_add': 'Ответственный назначен', 'access.manager_remove': 'Права ответственного отозваны',
    'access.recipient_add': 'Получатель добавлен', 'access.recipient_remove': 'Получатель удалён',
    'access.history_on': 'Доступ к истории открыт', 'access.history_off': 'Доступ к истории закрыт',
}


def register(routes):
    @routes.route('settings', owner=True)
    async def settings(ui):
        await ui.show('⚙️ <b>Настройки</b>', [
            [button('🏷 Классы', 'classes', 'settings', 0), button('➕ Добавить класс', 'newclass')],
            [button('📜 Журнал действий', 'audit', 0)],
            [button('💾 Резервная копия SQLite', 'backup')], back(),
        ])

    @routes.route('newclass', owner=True)
    async def new_class(ui):
        await ui.prompt('Введите название класса, например 9-А.', 'new_class', (), ('classes', 'settings', 0))

    @routes.input('new_class', owner=True)
    async def save_class(ui, value):
        school_class = await ui.directory.add_class(ui.uid, value)
        await ui.state.clear()
        await ui.show(f'✅ Класс <b>{escape(school_class.name)}</b> добавлен.', [
            [button('🎓 Добавить учеников', 'students', school_class.id)],
            [button('⏰ Настроить рассылку', 'schedule', school_class.id)], back('settings'),
        ])

    @routes.route('students', int, owner=True)
    async def students(ui, class_id):
        school_class, _ = await ui.directory.students(ui.uid, class_id)
        await ui.show(title('🎓 Ученики', school_class), [
            [button('➕ Добавить ученика', 'stuadd', class_id, 0), button('➕ Массовое добавление', 'stuadd', class_id, 1)],
            [button('📋 Список учеников', 'stulist', class_id, 'list', 0)],
            [button('✏️ Редактировать', 'stulist', class_id, 'edit', 0), button('🗑 Удалить в архив', 'stulist', class_id, 'archive', 0)],
            [button('🔎 Поиск', 'stusearch', class_id), button('🗃 Архив', 'stulist', class_id, 'archived', 0)],
            back('classes', 'students', 0),
        ])

    @routes.route('stuadd', int, int, owner=True)
    async def add_students(ui, class_id, mass):
        async with ui.app.db.read() as session:
            _, school_class = await ui.directory.owner_class(session, ui.uid, class_id)
        text = ('Отправьте до 100 строк. В каждой строке — полное имя одного ученика.' if mass else
                'Введите полное имя ученика одной строкой (до 255 символов).')
        await ui.prompt(f'{title("➕ Добавление учеников", school_class)}\n\n{text}', 'add_students', (class_id, bool(mass)),
                        ('students', class_id))

    @routes.input('add_students', owner=True)
    async def preview_students(ui, value, class_id, mass):
        names = parse_students(value, mass)
        added, duplicates = await ui.directory.add_students(ui.uid, class_id, names, preview=True)
        if not added:
            raise UserError('Все указанные ученики уже есть в этом классе.')
        header = f'🎓 <b>Проверьте список</b>\nДобавится: {len(added)} · Дубликатов: {len(duplicates)}\n\n'
        lines = [f'{n}. {escape(name)}' for n, name in enumerate(added, 1)]
        last, previous = add_section(header, [], header, '', lines)
        for part in previous:
            await ui.bot.send_message(ui.uid, part)
        if previous:
            ui.panel = None
        await ui.confirm(last, 'stuapply', (class_id,), ('students', class_id),
                         label='Добавить', payload=names)

    @routes.route('stuapply', int, owner=True, confirmed=True)
    async def apply_students(ui, class_id, *, payload):
        added, duplicates = await ui.directory.add_students(ui.uid, class_id, payload)
        await ui.show(f'✅ Добавлено учеников: {len(added)}\nПропущено дубликатов: {len(duplicates)}.',
                      [[button('📋 Список учеников', 'stulist', class_id, 'list', 0)], back('students', class_id)])

    @routes.route('stulist', int, str, int, owner=True)
    async def student_list(ui, class_id, mode, page):
        if mode not in ('list', 'edit', 'archive', 'archived'):
            raise UserError('Действие недоступно.')
        school_class, items = await ui.directory.students(ui.uid, class_id, include_archived=mode == 'archived')
        if mode == 'archived':
            items = [student for student in items if not student.is_active]
        page, listed = paginate(items, page)
        action = {'edit': 'stuedit', 'archive': 'stuarch', 'list': 'stucard', 'archived': 'stucard'}[mode]
        rows = [[button(student.name[:60], action, student.id)] for student in listed]
        label = {'edit': '✏️ Выберите ученика', 'archive': '🗑 Выберите ученика для архива',
                 'list': '🎓 Список учеников', 'archived': '🗃 Архив' }[mode]
        await ui.show(f'{title(label, school_class)}\n\nВсего: {len(items)}',
                      [*rows, *navigation(page, len(items), 'stulist', class_id, mode), back('students', class_id)])

    @routes.route('stusearch', int, owner=True)
    async def search_prompt(ui, class_id):
        await ui.prompt('Введите фамилию, имя или их часть. Поиск включает архив.', 'student_search', (class_id,),
                        ('students', class_id))

    @routes.input('student_search', owner=True)
    async def student_search(ui, value, class_id):
        if not 1 <= len(value) <= 96:
            raise UserError('Введите от 1 до 96 символов.')
        school_class, items = await ui.directory.students(ui.uid, class_id, value, include_archived=True)
        rows = [[button(f'{"🗃 " if not student.is_active else ""}{student.name[:54]}', 'stucard', student.id)]
                for student in items[:25]]
        tail = '\nПервые 25 результатов. Уточните запрос, чтобы сузить список.' if len(items) > 25 else ''
        await ui.state.clear()
        await ui.show(f'{title("🔎 Поиск учеников", school_class)}\n\nНайдено: {len(items)}{tail}',
                      [*rows, [button('🔎 Новый поиск', 'stusearch', class_id)], back('students', class_id)])

    @routes.route('stucard', int, owner=True)
    async def student_card(ui, student_id):
        student, school_class = await ui.directory.student(ui.uid, student_id)
        rows = [[button('📅 История ученика', 'pupil', student.id)]]
        if student.is_active:
            rows.extend([[button('✏️ Редактировать', 'stuedit', student.id), button('🗑 В архив', 'stuarch', student.id)]])
        label = 'Активен' if student.is_active else 'В архиве'
        await ui.show(f'🎓 <b>{escape(student.name)}</b>\n🏷 {escape(school_class.name)}\n{label}',
                      [*rows, back('stulist', school_class.id, 'list' if student.is_active else 'archived', 0)])

    @routes.route('stuedit', int, owner=True)
    async def edit_student(ui, student_id):
        student, school_class = await ui.directory.student(ui.uid, student_id)
        if not student.is_active:
            raise UserError('Ученик в архиве.')
        await ui.show(f'✏️ <b>{escape(student.name)}</b>\n🏷 {escape(school_class.name)}', [
            [button('⌨️ Изменить полное имя', 'stuname', student.id)],
            [button('🏷 Перевести в другой класс', 'stumove', student.id, 0)], back('stucard', student.id),
        ])

    @routes.route('stuname', int, owner=True)
    async def name_prompt(ui, student_id):
        await ui.prompt('Введите полное имя ученика (до 255 символов).', 'student_name', (student_id,), ('stuedit', student_id))

    @routes.input('student_name', owner=True)
    async def save_name(ui, value, student_id):
        await ui.directory.edit_student(ui.uid, student_id, name=parse_students(value, False)[0])
        await ui.state.clear()
        await student_card(ui, student_id)

    @routes.route('stumove', int, int, owner=True)
    async def pick_transfer(ui, student_id, page):
        student, _ = await ui.directory.student(ui.uid, student_id)
        async with ui.app.db.read() as session:
            choices = [item for item in await ui.permissions.classes(session, ui.uid, 'owner') if item.id != student.class_id]
        page, listed = paginate(choices, page)
        rows = [[button(item.name, 'stumcheck', student_id, item.id)] for item in listed]
        await ui.show('🏷 Выберите новый класс. Перевод вступит в силу завтра.' if rows else 'Добавьте второй класс в настройках.',
                      [*rows, *navigation(page, len(choices), 'stumove', student_id), back('stuedit', student_id)])

    @routes.route('stumcheck', int, int, owner=True)
    async def transfer_confirmation(ui, student_id, class_id):
        student, _ = await ui.directory.student(ui.uid, student_id)
        async with ui.app.db.read() as session:
            _, school_class = await ui.directory.owner_class(session, ui.uid, class_id)
        await ui.confirm(f'Перевести ученика <b>{escape(student.name)}</b> в класс <b>{escape(school_class.name)}</b> '
                         'со следующего дня?', 'stumapply', (student_id, class_id), ('stumove', student_id, 0))

    @routes.route('stumapply', int, int, owner=True, confirmed=True)
    async def transfer_student(ui, student_id, class_id, *, payload):
        await ui.directory.edit_student(ui.uid, student_id, new_class=class_id)
        await ui.show('✅ Перевод вступит в силу завтра.', [back('stucard', student_id)])

    @routes.route('stuarch', int, owner=True)
    async def archive_confirmation(ui, student_id):
        student, _ = await ui.directory.student(ui.uid, student_id)
        await ui.confirm(f'Перенести в архив <b>{escape(student.name)}</b>?\nИстория сохранится. '
                         'Ученик исчезнет из сегодняшних и будущих списков.',
                         'stuarchive', (student_id,), ('stucard', student_id), label='В архив')

    @routes.route('stuarchive', int, owner=True, confirmed=True)
    async def archive(ui, student_id, *, payload):
        student = await ui.directory.edit_student(ui.uid, student_id, archive=True)
        await ui.show('✅ Ученик перемещён в архив.', [back('students', student.class_id)])

    @routes.route('schedule', int, owner=True)
    async def schedule_panel(ui, class_id):
        school_class, schedule = await ui.reports.schedule(ui.uid, class_id)
        status = '🟢 Включена' if schedule.is_enabled else '⚪ Выключена'
        days = ', '.join(WEEKDAYS[int(day)] for day in schedule.weekdays)
        text = (f'{title("⏰ Расписание", school_class)}\n\nРассылка: {status}\n'
                f'🕒 {schedule.time} · {escape(schedule.timezone)}\n📆 {days}\n'
                f'🔔 Напоминания: {schedule.reminder_one or "—"} / {schedule.reminder_two or "—"}')
        await ui.show(text, [
            [button('⏸ Выключить рассылку' if schedule.is_enabled else '▶️ Включить рассылку', 'schtoggle', class_id)],
            [button(SCHEDULE_FIELDS[key][0], 'schfield', class_id, key) for key in ('time', 'weekdays')],
            [button(SCHEDULE_FIELDS[key][0], 'schfield', class_id, key) for key in ('reminder_one', 'reminder_two')],
            [button('📤 Отправить сейчас', 'sendnow', class_id), button('📜 История доставок', 'delivery', class_id, 0)],
            back('classes', 'schedule', 0),
        ])

    @routes.route('schtoggle', int, owner=True)
    async def toggle_confirmation(ui, class_id):
        _, schedule = await ui.reports.schedule(ui.uid, class_id)
        enable = not schedule.is_enabled
        await ui.confirm('Включить автоматическую рассылку?' if enable else 'Выключить рассылку и напоминания?',
                         'schtapply', (class_id, int(enable)), ('schedule', class_id))

    @routes.route('schtapply', int, int, owner=True, confirmed=True)
    async def apply_toggle(ui, class_id, enable, *, payload):
        await ui.reports.configure(ui.uid, class_id, 'is_enabled', bool(enable))
        await schedule_panel(ui, class_id)

    @routes.route('schfield', int, str, owner=True)
    async def schedule_field(ui, class_id, field):
        if field not in SCHEDULE_FIELDS:
            raise UserError('Неизвестная настройка.')
        await ui.reports.schedule(ui.uid, class_id)
        await ui.prompt(SCHEDULE_FIELDS[field][1], 'schedule_field', (class_id, field), ('schedule', class_id))

    @routes.input('schedule_field', owner=True)
    async def update_schedule(ui, value, class_id, field):
        await ui.reports.configure(ui.uid, class_id, field, value)
        await ui.state.clear()
        await schedule_panel(ui, class_id)

    @routes.route('sendnow', int, owner=True)
    async def send_confirmation(ui, class_id):
        school_class, _ = await ui.reports.schedule(ui.uid, class_id)
        day = ui.attendance.today()
        await ui.confirm(f'{title("📤 Отправка отчёта", school_class)}\n\nОтправить отчёт за {day:%d.%m.%Y} '
                         'всем назначенным получателям?', 'sendapply', (class_id, day, token_hex(8)), ('schedule', class_id))

    @routes.route('sendapply', int, date, str, owner=True, confirmed=True)
    async def send_report(ui, class_id, day, token, *, payload):
        _, schedule = await ui.reports.schedule(ui.uid, class_id)
        if day != ui.attendance.today():
            raise UserError('Дата изменилась. Запустите отправку заново.')
        await ui.show('📤 Отправляю отчёт…')
        results = await ui.reports.dispatch(ui.bot, schedule.id, day, f'manual_{token}', manual_actor=ui.uid)
        delivered = sum(status == 'sent' for status in results.values())
        text = (f'📤 Доставлено: {delivered} из {len(results)}.' if results else 'Для класса нет получателей.')
        await ui.show(text, [[button('📜 История доставок', 'delivery', class_id, 0)], back('schedule', class_id)])

    @routes.route('delivery', int, int, owner=True)
    async def deliveries(ui, class_id, page):
        rows, page, total = await ui.reports.history(ui.uid, class_id, page, PAGE)
        lines = []
        for item, telegram_id, sender_id, sender_name in rows:
            kind = ('Напоминание' if item.dispatch_key.startswith('reminder_') else
                    'Отчёт вручную' if item.dispatch_key.startswith('manual_') else 'Отчёт по расписанию')
            time = ui.attendance.local(item.sent_at or item.created_at).strftime('%H:%M')
            error = f'\n{escape(item.error_message)}' if item.error_message else ''
            sender = f' · Отправитель: {escape(sender_name or str(sender_id))}' if sender_id else ''
            lines.append(f'<b>{item.report_date:%d.%m.%Y} · {time}</b> · {kind}{sender}\nTelegram ID: <code>{telegram_id}</code> · '
                         f'{DELIVERY_STATUS[item.status]} · {item.parts_sent}/{item.parts_total}{error}')
        await ui.show('📜 <b>История доставок</b>\n\n' + ('\n\n'.join(lines) or 'Отправок пока нет.'),
                      [*navigation(page, total, 'delivery', class_id), back('schedule', class_id)])

    @routes.route('audit', int, owner=True)
    async def audit_panel(ui, page):
        rows, page, total = await ui.directory.audit_page(ui.uid, page, PAGE)
        lines = []
        for item, telegram_id in rows:
            moment = ui.attendance.local(item.timestamp).strftime('%d.%m.%Y %H:%M')
            actor = f'<code>{telegram_id}</code>' if telegram_id else 'Система'
            description = f' · ID записи {item.entity_id}' if item.entity_id else ''
            details = f'\n<code>{escape(item.details)}</code>' if item.details else ''
            lines.append(f'{moment} · {actor}\n<b>{ACTIONS.get(item.action, escape(item.action))}</b>{description}{details}')
        await ui.show('📜 <b>Журнал действий</b>\n\n' + ('\n\n'.join(lines) or 'Действий пока нет.'),
                      [*navigation(page, total, 'audit'), back('settings')])

    @routes.route('backup', owner=True)
    async def backup_confirmation(ui):
        await ui.confirm('💾 Отправить резервную копию базы SQLite в этот чат? Файл содержит данные учеников.',
                         'backupgo', (), ('settings',), label='Отправить копию')

    @routes.route('backupgo', owner=True, confirmed=True)
    async def backup(ui, *, payload):
        data = await ui.directory.backup(ui.uid)
        if len(data) > 49_000_000:
            raise UserError('Копия превышает лимит Telegram. Сделайте копию SQLite на сервере.')
        await ui.document(data, f'attendance-{ui.attendance.today():%Y-%m-%d}.sqlite3')
        await ui.show('✅ Резервная копия отправлена.', [back('settings')])
