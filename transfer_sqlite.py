import argparse
import asyncio
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.engine import URL, make_url

from config import database_url
from database.models import Base
from database.session import Database
from main import migrate


async def transfer(source_url, destination_url):
    origin = Database(source_url)
    target = Database(destination_url)
    try:
        async with origin.read() as local, target.write() as remote:
            for table in Base.metadata.sorted_tables:
                if await remote.scalar(select(table).limit(1)) is not None:
                    raise ValueError('База PostgreSQL уже содержит данные. Используйте отдельную пустую базу.')
            for table in Base.metadata.sorted_tables:
                result = await local.stream(select(table))
                async for rows in result.mappings().partitions(500):
                    await remote.execute(table.insert(), [dict(row) for row in rows])
                if 'id' in table.c and table.c.id.primary_key:
                    highest = await remote.scalar(select(func.max(table.c.id)))
                    if highest is not None:
                        await remote.execute(text("SELECT setval(pg_get_serial_sequence(:name, 'id'), :highest, true)"),
                                             {'name': table.name, 'highest': highest})
    finally:
        await origin.engine.dispose()
        await target.engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Перенос копии Attendance из SQLite в отдельную пустую PostgreSQL')
    parser.add_argument('sqlite_copy', type=Path)
    args = parser.parse_args()
    copy = args.sqlite_copy.resolve()
    if not copy.is_file():
        parser.error('Укажите существующий файл резервной копии SQLite.')
    destination = database_url()
    if make_url(destination).drivername != 'postgresql+asyncpg':
        parser.error('DATABASE_URL должен указывать на PostgreSQL.')
    source = URL.create('sqlite+aiosqlite', database=copy.as_posix()).render_as_string(hide_password=False)
    migrate(source)
    migrate(destination)
    asyncio.run(transfer(source, destination))
    print('Данные перенесены.')
