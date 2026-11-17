from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from secrets import token_hex

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from services.permissions import UserError


PAGE = 7


class Input(StatesGroup):
    waiting = State()
    confirming = State()


def encode(action, *args):
    data = ':'.join([action, *(value.isoformat().replace('-', '') if isinstance(value, date) else str(value) for value in args)])
    if len(data.encode()) > 64:
        raise ValueError('Callback data exceeds 64 bytes')
    return data


def button(label, action, *args):
    return InlineKeyboardButton(text=label, callback_data=encode(action, *args))


def back(action='home', *args):
    return [button('🔙 Назад', action, *args)]


def navigation(page, count, action, *args):
    row = []
    if page:
        row.append(button('‹', action, *args, page - 1))
    if (page + 1) * PAGE < count:
        row.append(button('›', action, *args, page + 1))
    return [row] if row else []


def paginate(items, page):
    page = min(page, max(0, (len(items) - 1) // PAGE))
    return page, items[page * PAGE:(page + 1) * PAGE]


def title(label, school_class):
    return f'<b>{label}</b>\n🏷 {escape(school_class.name)}'


@dataclass(frozen=True)
class Route:
    handler: object
    types: tuple
    owner: bool
    confirmed: bool

    def parse(self, args):
        if len(args) != len(self.types):
            raise UserError('Кнопка устарела. Откройте раздел заново.')
        parsed = []
        for kind, value in zip(self.types, args):
            if kind is int:
                if not value.isascii() or not value.isdecimal() or len(value) > 16 or int(value) >= 2**52:
                    raise UserError('Некорректный идентификатор.')
                value = int(value)
            elif kind is date:
                try:
                    if len(value) != 8:
                        raise ValueError
                    value = datetime.strptime(value, '%Y%m%d').date()
                except ValueError:
                    raise UserError('Некорректная дата.') from None
            parsed.append(value)
        return parsed


class Routes:
    def __init__(self):
        self.callbacks = {}
        self.inputs = {}

    def route(self, action, *types, owner=False, confirmed=False):
        def decorate(handler):
            self.callbacks[action] = Route(handler, types, owner, confirmed)
            return handler
        return decorate

    def input(self, flow, *, owner=False):
        def decorate(handler):
            self.inputs[flow] = (handler, owner)
            return handler
        return decorate


class UI:
    def __init__(self, app, event, bot, state, panel=None):
        self.app, self.event, self.bot, self.state = app, event, bot, state
        self.uid = event.from_user.id
        self.panel = event.message.message_id if isinstance(event, CallbackQuery) else panel
        self.directory = app.directory
        self.attendance = app.attendance
        self.reports = app.reports
        self.permissions = app.permissions

    async def show(self, text, rows=()):
        markup = InlineKeyboardMarkup(inline_keyboard=list(rows)) if rows else None
        if self.panel is not None:
            try:
                await self.bot.edit_message_text(text, chat_id=self.uid, message_id=self.panel, reply_markup=markup)
                return
            except TelegramBadRequest as exc:
                if 'message is not modified' in exc.message:
                    return
                if not any(value in exc.message for value in ('message to edit not found', "message can't be edited")):
                    raise
        message = await self.bot.send_message(self.uid, text, reply_markup=markup)
        self.panel = message.message_id
        if await self.state.get_state() in (Input.waiting.state, Input.confirming.state):
            await self.state.update_data(panel=self.panel)

    async def document(self, data, filename):
        await self.bot.send_document(self.uid, BufferedInputFile(data, filename=filename))

    async def report(self, parts, rows):
        if not parts:
            await self.show('📩 Доставленных отчётов пока нет.', rows)
            return
        await self.show(parts[0], rows)
        for part in parts[1:]:
            await self.bot.send_message(self.uid, part)

    async def prompt(self, text, flow, args, return_to, *, rows=()):
        await self.state.set_state(Input.waiting)
        await self.state.set_data(dict(flow=flow, args=args, panel=self.panel, return_to=return_to))
        await self.show(text + '\n\nОтмена — /cancel', [*rows, back(*return_to)])

    async def confirm(self, text, action, args, return_to, *, label='Подтвердить', payload=None):
        token = token_hex(8)
        await self.state.set_state(Input.confirming)
        await self.state.set_data(dict(token=token, action=encode(action, *args), panel=self.panel,
                                       return_to=return_to, payload=payload))
        await self.show(text, [[button(f'✅ {label}', 'ok', token)], back(*return_to)])
