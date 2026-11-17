from aiogram import Dispatcher

from bot.mini_app import launch_router
from conftest import OWNER
from test_telegram_flow import ChatDriver


async def test_token_bot_start_exposes_only_mini_app_launch(app):
    url = 'https://attendance.example.org'
    chat = ChatDriver(app)
    chat.dp = Dispatcher()
    chat.dp.include_router(launch_router(app, url))
    for _ in range(2):
        response = await chat.text(OWNER, '/start')
        [row] = response.reply_markup.inline_keyboard
        [button] = row
        assert 'Откройте Attendance' in response.text
        assert button.text == 'Открыть Attendance' and button.web_app.url == url and button.callback_data is None
    unknown = await chat.text(OWNER, '/attendance_test_unknown')
    assert 'Команда не найдена' in unknown.text and '/start' in unknown.text
