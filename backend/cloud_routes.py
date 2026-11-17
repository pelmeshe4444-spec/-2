import logging
import secrets

from aiogram import Dispatcher
from aiogram.types import Update
from fastapi import HTTPException, Request
from pydantic import ValidationError

from bot.mini_app import launch_router
from services.system_status import record_event


log = logging.getLogger(__name__)


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
        try:
            async with telegram_sender() as bot:
                await dispatcher.feed_update(bot, update)
        except Exception as exc:
            log.error('Не удалось обработать обновление Telegram %s (%s)', update.update_id, type(exc).__name__)
            await record_event(core.db, 'webhook', False)
            raise HTTPException(503, 'Не удалось обработать обновление Telegram.') from None
        return {'ok': True}

    @api.post('/api/internal/scheduler/run')
    async def scheduler(request: Request):
        check_secret(request.headers.get('Authorization', '').removeprefix('Bearer ') if
                     request.headers.get('Authorization', '').startswith('Bearer ') else '', config.scheduler_secret)
        try:
            async with telegram_sender() as bot:
                success = await core.reports.tick(bot)
                await core.memberships.recover_sending()
                await core.memberships.flush(bot, limit=50)
            if success is False:
                raise RuntimeError('At least one report schedule could not be processed.')
        except Exception as exc:
            log.error('Ошибка облачного планировщика (%s)', type(exc).__name__)
            await record_event(core.db, 'scheduler', False)
            raise HTTPException(503, 'Планировщик временно недоступен.') from None
        await record_event(core.db, 'scheduler', True)
        return {'ok': True}
