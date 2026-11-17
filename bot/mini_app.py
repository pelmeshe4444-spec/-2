from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, WebAppInfo


def launch_router(app, url):
    router = Router()
    router.message.filter(F.chat.type == ChatType.PRIVATE, F.from_user)

    @router.message(CommandStart())
    async def start(message):
        user = message.from_user
        await app.directory.register(user.id, user.username, user.full_name)
        if not url:
            await message.answer(f'Приложение Attendance ещё подключается. Ваш Telegram ID: <code>{user.id}</code>.')
            return
        launch = InlineKeyboardButton(text='Открыть приложение', web_app=WebAppInfo(url=url))
        await message.answer('Откройте Attendance, чтобы работать с посещаемостью.',
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=[[launch]]))

    @router.callback_query()
    async def old_button(query):
        await query.answer('Откройте Attendance через /start.', show_alert=True)

    return router


async def configure_menu(bot, url):
    if url:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text='Открыть приложение', web_app=WebAppInfo(url=url)))
