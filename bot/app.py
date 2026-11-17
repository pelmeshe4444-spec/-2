import logging
from html import escape

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot import access, admin, marks
from bot.common import Input, Routes, UI, back
from services.application import AttendanceApplication
from services.permissions import DENIED, Forbidden, UserError


log = logging.getLogger(__name__)
routes = Routes()
access.register(routes)
admin.register(routes)
marks.register(routes)


class Application(AttendanceApplication):
    def router(self):
        router = Router()
        router.message.filter(F.chat.type == ChatType.PRIVATE, F.from_user)

        @router.message(Command('id'))
        async def show_id(message: Message):
            await message.answer(f'Ваш Telegram ID: <code>{message.from_user.id}</code>')

        @router.message(CommandStart())
        async def start(message, bot, state):
            await state.clear()
            user = message.from_user
            first_start = await self.directory.register(user.id, user.username, user.full_name)
            await access.home(UI(self, message, bot, state), first_start=first_start)

        @router.message(Command('cancel', 'menu'))
        async def cancel(message, bot, state):
            data = await state.get_data()
            await state.clear()
            ui = UI(self, message, bot, state, data.get('panel'))
            if data.get('return_to'):
                try:
                    await self.allowed(ui.uid)
                    action, *args = data['return_to']
                    route = routes.callbacks[action]
                    if route.owner and not self.permissions.is_owner(ui.uid):
                        raise Forbidden()
                    await route.handler(ui, *args)
                    return
                except UserError:
                    pass
            await access.home(ui)

        @router.callback_query()
        async def callback(query, bot, state):
            if (not isinstance(query.message, Message) or query.message.chat.type != ChatType.PRIVATE
                    or query.message.chat.id != query.from_user.id or not query.data):
                await query.answer(DENIED, show_alert=True)
                return
            await query.answer()
            ui = UI(self, query, bot, state)
            try:
                await self.allowed(ui.uid)
                action, *args = query.data.split(':')
                confirmed = action == 'ok'
                data = await state.get_data() if confirmed else {}
                if confirmed:
                    if args != [data.get('token')] or data.get('panel') != ui.panel:
                        raise UserError('Подтверждение устарело. Откройте действие заново.')
                    action, *args = data['action'].split(':')
                route = routes.callbacks.get(action)
                if route is None or route.confirmed != confirmed:
                    raise UserError('Кнопка устарела. Откройте раздел заново.')
                if route.owner and not self.permissions.is_owner(ui.uid):
                    raise Forbidden()
                parsed = route.parse(args)
                await state.clear()
                if confirmed:
                    await route.handler(ui, *parsed, payload=data.get('payload'))
                else:
                    await route.handler(ui, *parsed)
            except UserError as exc:
                await ui.show(escape(str(exc)), [back()] if not isinstance(exc, Forbidden) else [])

        @router.message(Input.waiting)
        async def take_input(message, bot, state):
            data = await state.get_data()
            ui = UI(self, message, bot, state, data.get('panel'))
            try:
                await self.allowed(ui.uid)
                handler, owner = routes.inputs[data['flow']]
                if owner and not self.permissions.is_owner(ui.uid):
                    raise Forbidden()
                if not message.text or len(message.text) > 4096 or message.text.startswith('/'):
                    raise UserError('Отправьте текст или используйте /cancel.')
                await handler(ui, message.text.strip(), *data['args'])
            except Forbidden as exc:
                await state.clear()
                await ui.show(escape(str(exc)))
            except UserError as exc:
                # Keep the input panel and its navigation available for corrections.
                await message.answer(f'⚠️ {escape(str(exc))}')

        @router.message()
        async def fallback(message, bot, state):
            ui = UI(self, message, bot, state)
            try:
                await self.allowed(ui.uid)
            except Forbidden:
                await message.answer(DENIED)
                return
            await message.answer('Используйте кнопки в меню. Чтобы открыть его, отправьте /menu.')

        @router.error()
        async def on_error(event, bot):
            # Telegram exceptions can contain API request payloads. Log just the error type.
            log.error('Не удалось обработать обновление %s (%s)', event.update.update_id,
                      type(event.exception).__name__)
            query = event.update.callback_query
            message = event.update.message if query is None else query.message
            if isinstance(message, Message) and message.chat.type == ChatType.PRIVATE:
                try:
                    await bot.send_message(message.chat.id, 'Не удалось выполнить действие. Откройте меню командой /menu.')
                except (TelegramBadRequest, TelegramForbiddenError):
                    pass
            return True

        return router
