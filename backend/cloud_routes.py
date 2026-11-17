import secrets

from aiogram import Dispatcher
from aiogram.types import Update
from fastapi import HTTPException, Request
from pydantic import ValidationError

from bot.mini_app import launch_router


def check_secret(supplied, expected):
    if not expected or not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(403, 'Доступ запрещён.')


def cloud_routes(api, core, config, telegram_sender):
    dispatcher = Dispatcher()
    dispatcher.include_router(launch_router(core, config.mini_app_url))

    @api.post('/api/telegram/webhook')
    async def webhook(request: Request):
        check_secret(request.headers.get('X-Telegram-Bot-Api-Secret-Token', ''), config.webhook_secret)
        try:
            update = Update.model_validate(await request.json())
        except (ValueError, ValidationError):
            raise HTTPException(400, 'Неверный формат обновления.') from None
        async with telegram_sender() as bot:
            await dispatcher.feed_update(bot, update)
        return {'ok': True}

    @api.post('/api/internal/scheduler/run')
    async def scheduler(request: Request):
        check_secret(request.headers.get('Authorization', '').removeprefix('Bearer ') if
                     request.headers.get('Authorization', '').startswith('Bearer ') else '', config.scheduler_secret)
        async with telegram_sender() as bot:
            await core.reports.tick(bot)
            await core.memberships.flush(bot, limit=50)
        return {'ok': True}
