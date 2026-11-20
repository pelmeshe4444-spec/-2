import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import uvicorn

from backend.api import create_api
from bot.app import Application
from config import Config
from database.session import Database
from main import migrate
from services.attendance import Status


TOKEN = '123456:playwright-test'
OWNER, MANAGER, RECIPIENT = 101, 102, 103


class LocalSender:
    async def send_message(self, *_args, **_kwargs):
        return SimpleNamespace(message_id=1)


async def fixtures(config, db):
    app = Application(db, config)
    await app.directory.register(OWNER, 'owner', 'Алина Мирова')
    await app.directory.register(MANAGER, 'manager', 'Андрей Орлов')
    await app.directory.register(RECIPIENT, 'recipient', 'Ирина Соколова')
    await app.directory.register(9_876_543_210, 'parent_without_class', 'Родитель без класса')
    a = await app.directory.add_class(OWNER, '10-В')
    await app.directory.add_class(OWNER, '9-А')
    await app.directory.access(OWNER, MANAGER, a.id, 'manager_add')
    await app.directory.access(OWNER, RECIPIENT, a.id, 'recipient_add')
    await app.directory.add_students(OWNER, a.id, ['Авдеев Александр', 'Белова Инна', 'Власов Игорь', 'Громова Елена'])
    _, students = await app.directory.students(OWNER, a.id)
    for student, status in zip(students, [Status.PRESENT, Status.PRESENT, Status.SICK, Status.UNMARKED]):
        await app.attendance.mark(OWNER, a.id, app.attendance.today(), student.id, status)


if __name__ == '__main__':
    with TemporaryDirectory(prefix='attendance-browser-qa-') as work:
        url = f'sqlite+aiosqlite:///{(Path(work) / "browser.sqlite3").as_posix()}'
        config = Config(TOKEN, OWNER, ZoneInfo('Asia/Tashkent'), url)
        migrate(url)
        db = Database(url)
        asyncio.run(fixtures(config, db))
        asyncio.run(db.engine.dispose())
        uvicorn.run(create_api(config, db, sender=LocalSender()), host='127.0.0.1', port=int(os.getenv('ATTENDANCE_TEST_PORT', '8109')),
                    access_log=False)
