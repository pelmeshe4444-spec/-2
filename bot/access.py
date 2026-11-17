import logging
from html import escape

from aiogram.exceptions import TelegramAPIError

from bot.common import PAGE, back, button, navigation, paginate, title
from services.permissions import DENIED, UserError


log = logging.getLogger(__name__)
ROLE_NAMES = {'MANAGER': 'Ответственный', 'REPORT_RECIPIENT': 'Получатель отчётов'}
OPERATIONS = {
    'manager_add': '➕ Назначить ответственного', 'manager_remove': '➖ Убрать ответственного',
    'recipient_add': '📩 Добавить получателя отчётов', 'recipient_remove': '🗑 Удалить получателя',
    'history_on': '📅 Разрешить просмотр истории', 'history_off': '🔒 Закрыть просмотр истории',
}


async def home(ui, *, first_start=False):
    if ui.permissions.is_owner(ui.uid):
        await ui.show('🏫 <b>Управление посещаемостью</b>', [
            [button('📋 Посещаемость сегодня', 'classes', 'today', 0)],
            [button('🎓 Ученики', 'classes', 'students', 0), button('👥 Управление доступом', 'access')],
            [button('📩 Получатели отчётов', 'receivers'), button('⏰ Расписание', 'classes', 'schedule', 0)],
            [button('📊 Статистика', 'classes', 'stats', 0), button('📅 История', 'classes', 'history', 0)],
            [button('⚙️ Настройки', 'settings')],
        ])
        return
    async with ui.app.db.read() as session:
        manage = await ui.permissions.classes(session, ui.uid)
        receive = await ui.permissions.classes(session, ui.uid, 'receive')
        history = await ui.permissions.classes(session, ui.uid, 'history')
    if not manage and not receive:
        await ui.show(DENIED)
        return
    rows = []
    if manage:
        rows += [
            [button('📋 Отметить посещаемость', 'classes', 'today', 0)],
            [button('✅ Сегодняшние отметки', 'classes', 'view', 0), button('📊 Сводка за сегодня', 'classes', 'summary', 0)],
        ]
    if history:
        rows.append([button('📅 История класса', 'classes', 'history', 0)])
    if receive:
        rows.append([button('📩 Последний доступный отчёт', 'classes', 'latest', 0)])
    notice = '\n🔓 Вам предоставили доступ.' if first_start else ''
    await ui.show(f'🏫 <b>Посещаемость</b>{notice}', rows)


def user_name(user):
    return user.full_name or (f'@{user.username}' if user.username else str(user.telegram_id))


def access_rows(recipient_only=False):
    rows = []
    if not recipient_only:
        rows.extend([[button(OPERATIONS['manager_add'], 'acpick', 'manager_add', 0)],
                     [button(OPERATIONS['manager_remove'], 'acpick', 'manager_remove', 0)],
                     [button('📅 Права на историю', 'classes', 'managers', 0)]])
    rows.extend([[button(OPERATIONS['recipient_add'], 'acpick', 'recipient_add', 0)],
                 [button(OPERATIONS['recipient_remove'], 'acpick', 'recipient_remove', 0)]])
    if recipient_only:
        rows.append([button('📋 Получатели по классам', 'classes', 'recipients', 0)])
    else:
        rows.append([button('📋 Список пользователей', 'users', 0)])
    return [*rows, back()]


def register(routes):
    routes.route('home')(home)

    @routes.route('access', owner=True)
    async def access_panel(ui):
        await ui.show('👥 <b>Управление доступом</b>', access_rows())

    @routes.route('receivers', owner=True)
    async def recipient_panel(ui):
        await ui.show('📩 <b>Получатели отчётов</b>', access_rows(recipient_only=True))

    @routes.route('acpick', str, int, owner=True)
    async def pick(ui, operation, page):
        if operation not in OPERATIONS or operation.startswith('history'):
            raise UserError('Действие недоступно.')
        role_filter = {'manager_remove': 'MANAGER', 'recipient_remove': 'REPORT_RECIPIENT'}.get(operation)
        users, _, page, total = await ui.directory.users(ui.uid, page, PAGE, started_only=operation.endswith('_add'), role=role_filter)
        rows = [[button(user_name(user)[:54], 'acuser', operation, user.telegram_id, 0)]
                for user in users if not ui.permissions.is_owner(user.telegram_id)]
        rows.extend(navigation(page, total, 'acpick', operation))
        rows.append([button('⌨️ Ввести Telegram ID', 'acid', operation)])
        await ui.show(f'<b>{OPERATIONS[operation]}</b>\nВыберите пользователя или введите его Telegram ID.',
                      [*rows, back('receivers' if operation.startswith('recipient') else 'access')])

    @routes.route('acid', str, owner=True)
    async def id_prompt(ui, operation):
        if operation not in OPERATIONS or operation.startswith('history'):
            raise UserError('Действие недоступно.')
        await ui.prompt('Введите числовой Telegram ID. Пользователь может узнать его командой /id.',
                        'target_id', (operation,), ('acpick', operation, 0))

    @routes.input('target_id', owner=True)
    async def read_id(ui, value, operation):
        if not value.isascii() or not value.isdecimal() or len(value) > 16 or not 0 < int(value) < 2**52:
            raise UserError('Введите числовой Telegram ID.')
        await pick_class(ui, operation, int(value), 0)
        await ui.state.clear()

    @routes.route('acuser', str, int, int, owner=True)
    async def pick_class(ui, operation, target, page):
        if operation not in OPERATIONS or operation.startswith('history') or ui.permissions.is_owner(target):
            raise UserError('Действие недоступно для этого пользователя.')
        user, managers, recipients = await ui.directory.user_details(ui.uid, target)
        if operation == 'recipient_add' and (user is None or user.started_at is None):
            raise UserError('Получатель должен сначала запустить бота командой /start.')
        if operation == 'manager_remove':
            choices = [school_class for school_class, _ in managers]
        elif operation == 'recipient_remove':
            choices = recipients
        else:
            async with ui.app.db.read() as session:
                choices = await ui.permissions.classes(session, ui.uid, 'owner')
        page, schools = paginate(choices, page)
        rows = [[button(school_class.name, 'acproof', operation, target, school_class.id)] for school_class in schools]
        label = escape(user_name(user)) if user else 'Пользователь ещё не запускал бота'
        prompt = 'Выберите класс.' if choices else 'Подходящих классов пока нет.'
        await ui.show(f'<b>{OPERATIONS[operation]}</b>\n{label}\nTelegram ID: <code>{target}</code>\n\n{prompt}',
                      [*rows, *navigation(page, len(choices), 'acuser', operation, target), back('acpick', operation, 0)])

    @routes.route('acproof', str, int, int, owner=True)
    async def access_confirmation(ui, operation, target, class_id):
        if operation not in OPERATIONS or ui.permissions.is_owner(target):
            raise UserError('Действие недоступно для этого пользователя.')
        user, _, _ = await ui.directory.user_details(ui.uid, target)
        async with ui.app.db.read() as session:
            _, school_class = await ui.directory.owner_class(session, ui.uid, class_id)
        label = escape(user_name(user)) if user else 'Пользователь ещё не запускал бота'
        return_to = ('assign', class_id, 0, 0) if operation.startswith('history') else ('acuser', operation, target, 0)
        await ui.confirm(f'<b>{OPERATIONS[operation]}</b>\n{label}\nTelegram ID: <code>{target}</code>\n'
                         f'🏷 Класс: {escape(school_class.name)}', 'acapply', (operation, target, class_id), return_to)

    @routes.route('acapply', str, int, int, owner=True, confirmed=True)
    async def apply_access(ui, operation, target, class_id, *, payload):
        user, changed = await ui.directory.access(ui.uid, target, class_id, operation)
        text = '✅ Права обновлены.' if changed else 'Это назначение уже действует.'
        if changed and operation.endswith('_add'):
            if user.started_at:
                try:
                    await ui.bot.send_message(user.telegram_id, '🔓 Вам предоставили доступ в боте посещаемости. Откройте /menu.')
                except TelegramAPIError as exc:
                    log.warning('Уведомление о доступе не доставлено пользователю %s (%s)', user.id, type(exc).__name__)
                    text += '\nУведомление не доставлено.'
            else:
                text += '\nПрава появятся в меню после команды /start.'
        await ui.show(text, [back('receivers' if operation.startswith('recipient') else 'access')])

    @routes.route('users', int, owner=True)
    async def users(ui, page):
        users, roles, page, total = await ui.directory.users(ui.uid, page, PAGE)
        rows = [[button(user_name(user)[:48], 'person', user.telegram_id)] for user in users]
        labels = []
        for user in users:
            names = ['Владелец'] if ui.permissions.is_owner(user.telegram_id) else [ROLE_NAMES[r] for r in roles.get(user.id, [])]
            labels.append(f'• {escape(user_name(user))} · {escape(", ".join(names) or "Пользователь")}')
        await ui.show('👥 <b>Пользователи и роли</b>\n\n' + ('\n'.join(labels) or 'Список пуст.'),
                      [*rows, *navigation(page, total, 'users'), back('access')])

    @routes.route('person', int, owner=True)
    async def person(ui, target):
        user, managers, recipients = await ui.directory.user_details(ui.uid, target)
        if user is None:
            raise UserError('Пользователь недоступен.')
        manager_list = ', '.join(escape(item.name) + (' (с историей)' if history else '') for item, history in managers[:15])
        recipient_list = ', '.join(escape(item.name) for item in recipients[:15])
        identity = f'<b>{escape(user_name(user))}</b>\nTelegram ID: <code>{target}</code>'
        if user.username:
            identity += f'\n@{escape(user.username)}'
        if ui.permissions.is_owner(target):
            identity += '\nВладелец'
        await ui.show(f'{identity}\n\nОтветственный: {manager_list or "—"}{"…" if len(managers) > 15 else ""}\n'
                      f'Получатель: {recipient_list or "—"}{"…" if len(recipients) > 15 else ""}', [back('users', 0)])

    @routes.route('assign', int, int, int, owner=True)
    async def assignments(ui, class_id, recipient, page):
        school_class, items = await ui.directory.assignments(ui.uid, class_id, bool(recipient))
        page, listed = paginate(items, page)
        rows = []
        if not recipient:
            for user, assignment in listed:
                operation = 'history_off' if assignment.can_view_history else 'history_on'
                icon = '📅' if assignment.can_view_history else '🔒'
                rows.append([button(f'{icon} {user_name(user)[:45]}', 'acproof', operation, user.telegram_id, class_id)])
        description = '\n'.join('• ' + escape(user_name(user)) for user, _ in listed) if recipient else (
            'Выберите ответственного, чтобы изменить доступ к истории.' if items else '')
        header = title('📩 Получатели' if recipient else '📅 Права на историю', school_class)
        await ui.show(f'{header}\n\n{description or "Назначений пока нет."}',
                      [*rows, *navigation(page, len(items), 'assign', class_id, recipient),
                       back('classes', 'recipients' if recipient else 'managers', 0)])
