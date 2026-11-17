import asyncio
from datetime import date
from zoneinfo import ZoneInfo

import pytest

from bot.app import Application
from config import Config
from database.session import Database
from main import migrate


OWNER, MANAGER, RECIPIENT, VISITOR = 101, 102, 103, 104
MONDAY = date(2026, 11, 16)


@pytest.fixture
async def app(tmp_path):
    url = f'sqlite+aiosqlite:///{(tmp_path / "test.sqlite3").as_posix()}'
    await asyncio.to_thread(migrate, url)
    db = Database(url)
    app = Application(db, Config('123456:local-test', OWNER, ZoneInfo('Asia/Tashkent'), url))
    app.directory.today = app.attendance.today = lambda: MONDAY
    for uid in (OWNER, MANAGER, RECIPIENT, VISITOR):
        await app.directory.register(uid, None, f'Test {uid}')
    try:
        yield app
    finally:
        await db.engine.dispose()


@pytest.fixture
async def schools(app):
    first = await app.directory.add_class(OWNER, '9-А')
    second = await app.directory.add_class(OWNER, '9-Б')
    return first, second
