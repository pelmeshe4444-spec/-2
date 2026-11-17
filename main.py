import argparse
import asyncio
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import BotCommand
from alembic import command
from alembic.config import Config as AlembicConfig
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text

from bot.mini_app import configure_menu, launch_router
from config import ROOT, Config, database_url
from database.session import Database
from services.application import AttendanceApplication


log = logging.getLogger(__name__)


def migrate(url):
    config = AlembicConfig(str(ROOT / 'alembic.ini'))
    config.attributes['database_url'] = url
    command.upgrade(config, 'head')


async def check_database(url):
    db = Database(url)
    try:
        async with db.read() as session:
            await session.execute(text('SELECT id FROM classes WHERE 1 = 0'))
    finally:
        await db.engine.dispose()


def dispatcher(app):
    dp = Dispatcher(events_isolation=SimpleEventIsolation())
    dp.include_router(app.router())
    return dp


async def serve(config):
    db = Database(config.db_url)
    app = AttendanceApplication(db, config)
    dp = Dispatcher(events_isolation=SimpleEventIsolation())
    dp.include_router(launch_router(app, config.mini_app_url))
    scheduler = AsyncIOScheduler(timezone=config.zone)
    if db.engine.dialect.name == 'sqlite':
        async with db.engine.connect() as connection:
            await connection.exec_driver_sql('PRAGMA journal_mode = WAL')
    try:
        async with Bot(config.token, default=DefaultBotProperties(
            parse_mode='HTML', protect_content=True, link_preview_is_disabled=True,
        )) as bot:
            await bot.set_my_commands([BotCommand(command='start', description='Открыть Attendance')])
            await configure_menu(bot, config.mini_app_url)
            await bot.delete_webhook(drop_pending_updates=False)
            await app.reports.recover()
            scheduler.add_job(app.reports.tick, 'interval', seconds=30, args=(bot,), id='attendance-reports',
                              coalesce=True, max_instances=1, next_run_time=datetime.now(UTC))
            scheduler.start()
            try:
                await dp.start_polling(bot, close_bot_session=False, allowed_updates=dp.resolve_used_update_types(),
                                       tasks_concurrency_limit=64)
            finally:
                scheduler.shutdown(wait=False)
                await asyncio.sleep(0)
    finally:
        await db.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description='Telegram-бот учёта посещаемости')
    parser.add_argument('--check', action='store_true', help='Проверить импорты и базу без подключения к Telegram')
    parser.add_argument('--log-file', help='Записывать журнал в файл с ротацией')
    args = parser.parse_args()
    handlers = ([RotatingFileHandler(args.log_file, maxBytes=2_000_000, backupCount=2, encoding='utf-8')]
                if args.log_file else None)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s', handlers=handlers)
    logging.getLogger('aiogram.event').setLevel(logging.WARNING)
    logging.getLogger('apscheduler.executors').setLevel(logging.WARNING)
    try:
        if args.check:
            url = database_url()
            migrate(url)
            asyncio.run(check_database(url))
            print('Импорты, миграции и подключение к базе проверены.')
        else:
            config = Config.load()
            logging.getLogger().setLevel(config.log_level)
            migrate(config.db_url)
            asyncio.run(serve(config))
    except ValueError as exc:
        log.error('%s', exc)
        return 1
    except TelegramUnauthorizedError:
        log.error('Telegram отклонил токен. Проверьте BOT_TOKEN.')
        return 1
    except TelegramNetworkError:
        log.error('Не удалось подключиться к Telegram. Проверьте сеть и доступ к api.telegram.org.')
        return 1
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        log.error('Запуск завершился ошибкой (%s). Проверьте подключение к базе и конфигурацию.', type(exc).__name__)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
