import argparse
import asyncio
from urllib.parse import urlsplit

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from bot.mini_app import configure_menu, launch_router
from config import Config


async def configure(origin):
    config = Config.load()
    path = urlsplit(origin)
    if path.scheme != 'https' or not path.hostname or path.query or path.fragment or path.path not in ('', '/'):
        raise ValueError('Укажите корневой HTTPS-адрес backend.')
    if not config.webhook_secret or not config.mini_app_url:
        raise ValueError('Укажите TELEGRAM_WEBHOOK_SECRET и MINI_APP_URL.')
    dispatcher = Dispatcher()
    dispatcher.include_router(launch_router(None, config.mini_app_url))
    async with Bot(config.token) as bot:
        await bot.set_my_commands([BotCommand(command='start', description='Открыть Attendance')])
        await configure_menu(bot, config.mini_app_url)
        url = origin.rstrip('/') + '/api/telegram/webhook'
        await bot.set_webhook(url, secret_token=config.webhook_secret, allowed_updates=dispatcher.resolve_used_update_types())
        info = await bot.get_webhook_info()
        if info.url != url:
            raise RuntimeError('Telegram не сохранил адрес webhook.')
    print('Telegram webhook настроен и адрес подтверждён.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Подключить Telegram к действующему Attendance backend')
    parser.add_argument('backend_url')
    try:
        asyncio.run(configure(parser.parse_args().backend_url))
    except Exception as exc:
        parser.exit(1, f'Не удалось подключить webhook ({type(exc).__name__}).\n')
