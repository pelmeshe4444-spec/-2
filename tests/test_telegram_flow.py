import asyncio
from datetime import UTC, datetime, time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, DeleteWebhook, EditMessageText, GetMe, SendDocument, SendMessage, SetMyCommands
from aiogram.types import CallbackQuery, Chat, Message, Update, User

import main
from config import Config
from main import dispatcher
from services.permissions import DENIED
from services.reports import Reports
from conftest import MANAGER, MONDAY, OWNER, RECIPIENT, VISITOR


class TelegramSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.bot_user = User(id=123456, is_bot=True, first_name='Attendance', username='attendance_test_bot')
        self.panels = {}
        self.documents = []
        self.next_id = 1000

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, GetMe):
            return self.bot_user
        if isinstance(method, (AnswerCallbackQuery, DeleteWebhook, SetMyCommands)):
            return True
        if isinstance(method, SendDocument):
            self.documents.append((method.chat_id, method.document.filename))
            return self.panels[method.chat_id]
        assert isinstance(method, (SendMessage, EditMessageText))
        self.next_id += 1
        panel = Message(message_id=method.message_id if isinstance(method, EditMessageText) else self.next_id,
                        date=datetime.now(UTC), chat=Chat(id=method.chat_id, type='private'),
                        from_user=self.bot_user, text=method.text, reply_markup=method.reply_markup)
        self.panels[method.chat_id] = panel
        return panel

    async def stream_content(self, *args, **kwargs):
        yield b''


class ChatDriver:
    def __init__(self, app):
        self.session = TelegramSession()
        self.bot = Bot('123456:local-test', session=self.session, default=DefaultBotProperties(parse_mode='HTML'))
        self.dp = dispatcher(app)
        self.index = 0

    async def text(self, uid, text, *, group=False):
        self.index += 1
        msg = Message(message_id=self.index, date=datetime.now(UTC), text=text,
                      chat=Chat(id=-100 if group else uid, type='group' if group else 'private'),
                      from_user=User(id=uid, is_bot=False, first_name=f'Test {uid}'))
        await self.dp.feed_update(self.bot, Update(update_id=self.index, message=msg))
        return self.session.panels.get(uid)

    async def press(self, uid, startswith, *, literal=False):
        self.index += 1
        panel = self.session.panels[uid]
        data = startswith
        if not literal:
            data = next(b.callback_data for row in panel.reply_markup.inline_keyboard for b in row if b.text.startswith(startswith))
        callback = CallbackQuery(id=str(self.index), from_user=User(id=uid, is_bot=False, first_name=f'Test {uid}'),
                                 chat_instance='test', message=panel, data=data)
        await self.dp.feed_update(self.bot, Update(update_id=self.index, callback_query=callback))
        return self.session.panels[uid]


async def test_owner_setup_add_student_grant_and_complete_attendance(app):
    chat = ChatDriver(app)
    menu = await chat.text(OWNER, '/start')
    assert 'Управление посещаемостью' in menu.text
    await chat.press(OWNER, '⚙️ Настройки')
    await chat.press(OWNER, '➕ Добавить класс')
    result = await chat.text(OWNER, '9-А')
    assert result.message_id == menu.message_id and 'добавлен' in result.text
    await chat.press(OWNER, '🎓 Добавить учеников')
    await chat.press(OWNER, '➕ Добавить ученика')
    preview = await chat.text(OWNER, 'Иванов Иван')
    assert 'Проверьте список' in preview.text
    assert 'Добавлено учеников: 1' in (await chat.press(OWNER, '✅ Добавить')).text
    await chat.text(OWNER, '/menu')
    await chat.press(OWNER, '👥 Управление доступом')
    await chat.press(OWNER, '➕ Назначить ответственного')
    await chat.press(OWNER, '⌨️ Ввести Telegram ID')
    await chat.text(OWNER, str(MANAGER))
    await chat.press(OWNER, '9-А')
    assert 'Права обновлены' in (await chat.press(OWNER, '✅ Подтвердить')).text
    assert 'предоставили доступ' in chat.session.panels[MANAGER].text
    await chat.text(MANAGER, '/start')
    await chat.press(MANAGER, '📋 Отметить')
    await chat.press(MANAGER, '9-А')
    await chat.press(MANAGER, '1. ⏳')
    assert 'Можно добавить комментарий' in (await chat.press(MANAGER, '📝 По уважительной')).text
    assert 'Семейные обстоятельства' in (await chat.text(MANAGER, 'Семейные обстоятельства')).text
    await chat.press(MANAGER, '🔙 Назад')
    assert 'Отметка завершена' in (await chat.press(MANAGER, '📌 Готово')).text
    await chat.text(OWNER, '/menu')
    await chat.press(OWNER, '📊 Статистика')
    await chat.press(OWNER, '9-А')
    await chat.press(OWNER, '📅 Выбрать день')
    await chat.text(OWNER, '16.11.2026')
    await chat.press(OWNER, '📥 Excel')
    assert chat.session.documents == [(OWNER, 'attendance-1-2026-11-16-2026-11-16.xlsx')]


async def test_stale_revoked_and_forged_callbacks_never_leak_data(app, schools):
    a, b = schools
    await app.directory.access(OWNER, MANAGER, a.id, 'manager_add')
    await app.directory.access(OWNER, RECIPIENT, b.id, 'recipient_add')
    chat = ChatDriver(app)
    assert (await chat.text(VISITOR, '/start')).text == DENIED
    assert (await chat.text(567, '/start', group=True)) is None
    await chat.text(MANAGER, '/start')
    response = await chat.press(MANAGER, f'day:{b.id}:{MONDAY:%Y%m%d}:1:0', literal=True)
    assert response.text == DENIED
    assert (await chat.press(MANAGER, 'settings', literal=True)).text == DENIED
    await chat.text(RECIPIENT, '/start')
    assert (await chat.press(RECIPIENT, f'day:{b.id}:{MONDAY:%Y%m%d}:0:0', literal=True)).text == DENIED
    await app.directory.access(OWNER, MANAGER, a.id, 'manager_remove')
    response = await chat.press(MANAGER, f'day:{a.id}:{MONDAY:%Y%m%d}:1:0', literal=True)
    assert response.text == DENIED
    await chat.text(OWNER, '/start')
    assert 'устарела' in (await chat.press(OWNER, 'stuarchive:1', literal=True)).text


async def test_cancel_and_restarted_confirmation(app):
    chat = ChatDriver(app)
    await chat.text(OWNER, '/start')
    await chat.press(OWNER, '⚙️ Настройки')
    await chat.press(OWNER, '➕ Добавить класс')
    assert 'Нет доступных классов' in (await chat.text(OWNER, '/cancel')).text
    await chat.text(OWNER, '/menu')
    await chat.press(OWNER, '⚙️ Настройки')
    await chat.press(OWNER, '💾 Резервная копия')
    chat.dp = dispatcher(app)
    assert 'Подтверждение устарело' in (await chat.press(OWNER, '✅ Отправить копию')).text
    assert chat.session.documents == []


async def test_main_starts_scheduler_and_delivers_due_report(app, schools, monkeypatch):
    school, _ = schools
    await app.directory.access(OWNER, RECIPIENT, school.id, 'recipient_add')
    await app.reports.configure(OWNER, school.id, 'is_enabled', True)
    session = TelegramSession()
    completed = asyncio.Event()
    tick = Reports.tick

    async def fixed_tick(self, bot):
        await tick(self, bot, datetime.combine(MONDAY, time(8, 30), app.attendance.zone))
        completed.set()

    async def fake_polling(self, bot, **kwargs):
        await asyncio.wait_for(completed.wait(), timeout=5)

    monkeypatch.setattr(main, 'Bot', lambda *args, **kwargs: Bot(*args, session=session, **kwargs))
    monkeypatch.setattr(Reports, 'tick', fixed_tick)
    monkeypatch.setattr(Dispatcher, 'start_polling', fake_polling)
    config = Config('123456:local-test', OWNER, app.attendance.zone, app.db.engine.url.render_as_string(hide_password=False))
    await main.serve(config)
    assert 'ОТЧЁТ О ПОСЕЩАЕМОСТИ' in session.panels[RECIPIENT].text
