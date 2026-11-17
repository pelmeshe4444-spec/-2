import asyncio
from collections import Counter
from datetime import date, datetime, timedelta
from html import escape

from bot.common import PAGE, back, button, navigation, paginate, title
from services.attendance import ICONS, LABELS, Status, counts, parse_date
from services.permissions import UserError, audit
from services.reports import detailed_report, excel_report, totals


OWNER_MODES = {'students', 'settings', 'schedule', 'stats', 'managers', 'recipients'}
MODES = OWNER_MODES | {'today', 'view', 'summary', 'latest', 'history'}


def validate_status(status):
    try:
        return Status(status)
    except ValueError:
        raise UserError('Статус недоступен.') from None


def range_value(value):
    parts = value.split()
    if len(parts) != 2:
        raise UserError('Введите две даты через пробел, например 01.09.2026 07.09.2026.')
    return tuple(parse_date(part) for part in parts)


def week_start(day):
    return day - timedelta(days=day.weekday())


def register(routes):
    @routes.route('classes', str, int)
    async def classes(ui, mode, page):
        if mode not in MODES:
            raise UserError('Раздел недоступен.')
        scope = ('owner' if mode in OWNER_MODES else 'receive' if mode == 'latest'
                 else 'history' if mode == 'history' else 'manage')
        async with ui.app.db.read() as session:
            choices = await ui.permissions.classes(session, ui.uid, scope)
        page, listed = paginate(choices, page)
        rows = [[button(school_class.name, 'class', mode, school_class.id)] for school_class in listed]
        rows += navigation(page, len(choices), 'classes', mode)
        if ui.permissions.is_owner(ui.uid) and (mode == 'settings' or not choices):
            rows.append([button('➕ Добавить класс', 'newclass')])
        previous = {'settings': 'settings', 'managers': 'access', 'recipients': 'receivers'}.get(mode, 'home')
        await ui.show('🏷 <b>Выберите класс</b>' if choices else '🏷 Нет доступных классов.', [*rows, back(previous)])

    @routes.route('class', str, int)
    async def pick_class(ui, mode, class_id):
        today = ui.attendance.today()
        destinations = {
            'today': ('day', class_id, today, 1, 0), 'view': ('day', class_id, today, 0, 0),
            'summary': ('summary', class_id, today), 'latest': ('latest', class_id), 'history': ('history', class_id),
            'students': ('students', class_id), 'settings': ('classinfo', class_id), 'schedule': ('schedule', class_id),
            'stats': ('stats', class_id), 'managers': ('assign', class_id, 0, 0), 'recipients': ('assign', class_id, 1, 0),
        }
        if mode not in destinations:
            raise UserError('Раздел недоступен.')
        action, *args = destinations[mode]
        route = routes.callbacks[action]
        if route.owner:
            async with ui.app.db.read() as session:
                await ui.permissions.owner(session, ui.uid)
        await route.handler(ui, *args)

    @routes.route('classinfo', int, owner=True)
    async def class_info(ui, class_id):
        school_class, students = await ui.directory.students(ui.uid, class_id)
        await ui.show(f'{title("🏷 Класс", school_class)}\nАктивных учеников: {len(students)}', [
            [button('🎓 Ученики', 'students', class_id), button('⏰ Расписание', 'schedule', class_id)],
            [button('👥 Ответственные', 'assign', class_id, 0, 0), button('📩 Получатели', 'assign', class_id, 1, 0)],
            back('classes', 'settings', 0),
        ])

    @routes.route('day', int, date, int, int)
    async def day_panel(ui, class_id, day, edit, page):
        school_class, entries = await ui.attendance.daily(ui.uid, class_id, day)
        page, listed = paginate(entries, page)
        edit = int(bool(edit) and (day == ui.attendance.today() or ui.permissions.is_owner(ui.uid)))
        header = title('📋 Отметить посещаемость' if edit else '📋 Посещаемость', school_class)
        rows = [[button(f'{page * PAGE + i}. {ICONS[entry.status]} {entry.student.name[:50]}',
                        'mark', class_id, day, entry.student.id, edit, page)] for i, entry in enumerate(listed, 1)]
        rows += navigation(page, len(entries), 'day', class_id, day, edit)
        if edit and entries:
            rows.append([button('✅ Отметить всех присутствующими', 'all', class_id, day, page)])
            rows.append([button('📌 Готово', 'finish', class_id, day), button('📊 Сводка', 'summary', class_id, day)])
        elif entries:
            rows.append([button('📊 Сводка', 'summary', class_id, day)])
        previous = ('classes', 'today' if edit else 'view', 0) if day == ui.attendance.today() else ('history', class_id)
        count = counts(entries)
        lines = ' · '.join(f'{ICONS[status]} {count[status]}' for status in ICONS)
        await ui.show(f'{header}\n📅 {day:%d.%m.%Y}\n\n{lines if entries else "На эту дату список пуст."}',
                      [*rows, back(*previous)])

    @routes.route('mark', int, date, int, int, int)
    async def mark_panel(ui, class_id, day, student_id, edit, page):
        school_class, entry = await ui.attendance.entry(ui.uid, class_id, day, student_id)
        edit = int(bool(edit) and (day == ui.attendance.today() or ui.permissions.is_owner(ui.uid)))
        timestamp = ui.attendance.local(entry.mark.updated_at).strftime('%d.%m.%Y %H:%M') if entry.mark else '—'
        reason = f'\n💬 {escape(entry.reason)}' if entry.reason else ''
        text = (f'{title("🎓 " + escape(entry.student.name), school_class)}\n📅 {day:%d.%m.%Y}\n\n'
                f'{ICONS[entry.status]} <b>{LABELS[entry.status]}</b>{reason}\n🕒 Изменено: {timestamp}')
        rows = []
        if edit:
            rows = [[button(f'{ICONS[status]} {LABELS[status]}', 'setmark', class_id, day, student_id, int(status), page)]
                    for status in (Status.PRESENT, Status.SICK, Status.EXCUSED, Status.ABSENT, Status.UNMARKED)]
            if entry.status.allows_reason:
                rows.append([button('💬 Добавить или изменить комментарий', 'reason', class_id, day, student_id, page)])
        await ui.show(text, [*rows, back('day', class_id, day, edit, page)])

    @routes.route('setmark', int, date, int, int, int)
    async def set_mark(ui, class_id, day, student_id, status, page):
        status = validate_status(status)
        entry = await ui.attendance.mark(ui.uid, class_id, day, student_id, status)
        if status.allows_reason and not entry.reason:
            await reason_prompt(ui, class_id, day, student_id, page)
            return
        await mark_panel(ui, class_id, day, student_id, 1, page)

    @routes.route('reason', int, date, int, int)
    async def reason_prompt(ui, class_id, day, student_id, page):
        async with ui.app.db.read() as session:
            await ui.attendance.scope(session, ui.uid, class_id, day, writing=True)
        _, entry = await ui.attendance.entry(ui.uid, class_id, day, student_id)
        if not entry.status.allows_reason:
            raise UserError('Комментарий доступен для статусов отсутствия.')
        await ui.prompt(f'{ICONS[entry.status]} <b>{LABELS[entry.status]}</b> · {escape(entry.student.name)}\n\n'
                        'Отметка сохранена. Можно добавить комментарий до 300 символов. Чтобы удалить комментарий, введите -.',
                        'reason', (class_id, day, student_id, entry.status, entry.mark.updated_at.isoformat(), page),
                        ('mark', class_id, day, student_id, 1, page),
                        rows=[[button('Пропустить', 'day', class_id, day, 1, page)]])

    @routes.input('reason')
    async def save_reason(ui, value, class_id, day, student_id, status, version, page):
        await ui.attendance.mark(ui.uid, class_id, day, student_id, status, reason=None if value == '-' else value,
                                 expected=version)
        await ui.state.clear()
        await mark_panel(ui, class_id, day, student_id, 1, page)

    @routes.route('all', int, date, int)
    async def all_confirmation(ui, class_id, day, page):
        async with ui.app.db.read() as session:
            await ui.attendance.scope(session, ui.uid, class_id, day, writing=True)
        school_class, entries = await ui.attendance.daily(ui.uid, class_id, day)
        unmarked = counts(entries)[Status.UNMARKED]
        if not unmarked:
            await ui.show('✅ Все ученики уже отмечены.', [back('day', class_id, day, 1, page)])
            return
        await ui.confirm(f'{title("✅ Массовая отметка", school_class)}\n📅 {day:%d.%m.%Y}\n\n'
                         f'Отметить присутствующими неотмеченных учеников? Сейчас их {unmarked}.',
                         'allapply', (class_id, day, page), ('day', class_id, day, 1, page))

    @routes.route('allapply', int, date, int, confirmed=True)
    async def mark_all(ui, class_id, day, page, *, payload):
        changed = await ui.attendance.mark_all(ui.uid, class_id, day)
        await ui.show(f'✅ Отмечено присутствующими: {changed}.',
                      [[button('📌 Готово', 'finish', class_id, day)], back('day', class_id, day, 1, page)])

    @routes.route('finish', int, date)
    async def finish(ui, class_id, day):
        school_class, entries = await ui.attendance.finish(ui.uid, class_id, day)
        await ui.show(f'{title("📌 Отметка завершена", school_class)}\n📅 {day:%d.%m.%Y}\n\n{totals(counts(entries))}', [
            [button('📋 Вернуться к отметкам', 'day', class_id, day, 1, 0)], back(),
        ])

    @routes.route('summary', int, date)
    async def summary(ui, class_id, day):
        school_class, entries = await ui.attendance.daily(ui.uid, class_id, day)
        previous = ('classes', 'summary', 0) if day == ui.attendance.today() else ('history', class_id)
        await ui.show(f'{title("📊 Сводка", school_class)}\n📅 {day:%d.%m.%Y}\n\n{totals(counts(entries))}', [
            [button('📄 Полный отчёт', 'full', class_id, day), button('📋 Список отметок', 'day', class_id, day, 0, 0)],
            back(*previous),
        ])

    @routes.route('full', int, date)
    async def full(ui, class_id, day):
        school_class, entries = await ui.attendance.daily(ui.uid, class_id, day)
        chunks = detailed_report(school_class.name, day, entries, datetime.now(ui.attendance.zone))
        await ui.report(chunks, [back('summary', class_id, day)])

    @routes.route('latest', int)
    async def latest(ui, class_id):
        await ui.report(await ui.reports.latest(ui.uid, class_id), [back('classes', 'latest', 0)])

    @routes.route('history', int)
    async def history(ui, class_id):
        async with ui.app.db.read() as session:
            _, school_class = await ui.permissions.for_class(session, ui.uid, class_id, history=True)
        today = ui.attendance.today()
        edit = int(ui.permissions.is_owner(ui.uid))
        rows = [[button('Вчера', 'day', class_id, today - timedelta(days=1), edit, 0),
                 button('📅 Выбрать дату', 'dateask', class_id, 'history')]]
        if edit:
            rows.append([button('🎓 История отдельного ученика', 'stulist', class_id, 'list', 0)])
        await ui.show(title('📅 История посещаемости', school_class), [*rows, back('classes', 'history', 0)])

    @routes.route('dateask', int, str)
    async def day_prompt(ui, class_id, mode):
        if mode not in ('history', 'stats'):
            raise UserError('Раздел недоступен.')
        async with ui.app.db.read() as session:
            if mode == 'stats':
                await ui.permissions.owner(session, ui.uid)
            await ui.permissions.for_class(session, ui.uid, class_id, history=True)
        await ui.prompt('📅 Введите дату в формате ДД.ММ.ГГГГ.', 'choose_day', (class_id, mode), (mode, class_id))

    @routes.input('choose_day')
    async def choose_day(ui, value, class_id, mode):
        day = parse_date(value)
        if mode == 'stats':
            await stat_result(ui, class_id, day, day)
        else:
            await day_panel(ui, class_id, day, int(ui.permissions.is_owner(ui.uid)), 0)
        await ui.state.clear()

    @routes.route('stats', int, owner=True)
    async def statistics(ui, class_id):
        async with ui.app.db.read() as session:
            _, school_class = await ui.directory.owner_class(session, ui.uid, class_id)
        today = ui.attendance.today()
        await ui.show(title('📊 Статистика', school_class), [
            [button('📅 Выбрать день', 'dateask', class_id, 'stats'), button('📆 Текущая неделя', 'stat', class_id, week_start(today), today)],
            [button('🗓 Текущий месяц', 'stat', class_id, today.replace(day=1), today),
             button('🗓 Свой период', 'rangeask', class_id)], back('classes', 'stats', 0),
        ])

    @routes.route('rangeask', int, owner=True)
    async def range_prompt(ui, class_id):
        await ui.prompt('Введите начало и конец периода через пробел, например 01.09.2026 07.09.2026.',
                        'choose_range', (class_id,), ('stats', class_id))

    @routes.input('choose_range', owner=True)
    async def choose_range(ui, value, class_id):
        start, end = range_value(value)
        await stat_result(ui, class_id, start, end)
        await ui.state.clear()

    @routes.route('stat', int, date, date, owner=True)
    async def stat_result(ui, class_id, start, end):
        school_class, by_day = await ui.attendance.period(ui.uid, class_id, start, end, owner_only=True)
        count = Counter()
        for entries in by_day.values():
            count.update(counts(entries))
        rows = [[button('📥 Excel (.xlsx)', 'xlsx', class_id, start, end)]]
        if start == end:
            rows.append([button('📄 Полный отчёт', 'full', class_id, start), button('✏️ Отметки', 'day', class_id, start, 1, 0)])
        else:
            rows.append([button('📅 Отчёты по дням', 'statdays', class_id, start, end, 0)])
        period = f'{start:%d.%m.%Y}' + (f' — {end:%d.%m.%Y}' if start != end else '')
        await ui.show(f'{title("📊 Статистика класса", school_class)}\n📅 {period}\n\n{totals(count, period=start != end)}',
                      [*rows, back('stats', class_id)])

    @routes.route('statdays', int, date, date, int, owner=True)
    async def reports_by_day(ui, class_id, start, end, page):
        school_class, by_day = await ui.attendance.period(ui.uid, class_id, start, end, owner_only=True)
        days = [(day, entries) for day, entries in reversed(by_day.items()) if entries]
        page, listed = paginate(days, page)
        rows = []
        for day, entries in listed:
            count = counts(entries)
            badges = ' · '.join(f'{ICONS[status]} {count[status]}' for status in ICONS)
            rows.append([button(f'{day:%d.%m.%Y} · {badges}', 'full', class_id, day)])
        header = title('📅 Отчёты по дням', school_class)
        await ui.show(header if days else header + '\nЗа этот период список пуст.',
                      [*rows, *navigation(page, len(days), 'statdays', class_id, start, end), back('stat', class_id, start, end)])

    @routes.route('xlsx', int, date, date, owner=True)
    async def export(ui, class_id, start, end):
        school_class, by_day = await ui.attendance.period(ui.uid, class_id, start, end, owner_only=True)
        data = await asyncio.to_thread(excel_report, school_class.name, by_day)
        if len(data) > 49_000_000:
            raise UserError('Файл слишком большой. Выберите более короткий период.')
        async with ui.app.db.write() as session:
            actor = await ui.permissions.owner(session, ui.uid)
            audit(session, actor, 'statistics.exported', 'class', class_id, f'start={start} end={end}')
        await ui.document(data, f'attendance-{class_id}-{start}-{end}.xlsx')
        await ui.show('✅ Файл Excel отправлен.', [back('stat', class_id, start, end)])

    @routes.route('pupil', int, owner=True)
    async def pupil(ui, student_id):
        today = ui.attendance.today()
        await pupil_history(ui, student_id, today - timedelta(days=29), today, 0)

    @routes.route('pupilrange', int, owner=True)
    async def pupil_range(ui, student_id):
        await ui.prompt('Введите начало и конец периода через пробел, например 01.09.2026 07.09.2026.',
                        'pupil_range', (student_id,), ('pupil', student_id))

    @routes.input('pupil_range', owner=True)
    async def save_pupil_range(ui, value, student_id):
        start, end = range_value(value)
        await pupil_history(ui, student_id, start, end, 0)
        await ui.state.clear()

    @routes.route('pupage', int, date, date, int, owner=True)
    async def pupil_history(ui, student_id, start, end, page):
        student, items = await ui.attendance.pupil_history(ui.uid, student_id, start, end)
        page, listed = paginate(items, page)
        lines = []
        for day, school_class, entry in listed:
            reason = f' · {escape(entry.reason[:160])}{"…" if len(entry.reason) > 160 else ""}' if entry.reason else ''
            lines.append(f'<b>{day:%d.%m.%Y}</b> · {escape(school_class)}\n{ICONS[entry.status]} {LABELS[entry.status]}{reason}')
        text = (f'📅 <b>История ученика</b>\n🎓 {escape(student.name)}\n{start:%d.%m.%Y} — {end:%d.%m.%Y}\n\n'
                + ('\n\n'.join(lines) or 'В выбранном периоде ученик не числился в классе.'))
        await ui.show(text, [*navigation(page, len(items), 'pupage', student_id, start, end),
                            [button('📅 Изменить период', 'pupilrange', student_id)], back('stucard', student_id)])
