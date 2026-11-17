from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def make_engine(url: str):
    engine = create_async_engine(url, hide_parameters=True)
    if engine.dialect.name == 'sqlite':
        @event.listens_for(engine.sync_engine, 'connect')
        def configure_sqlite(connection, _):
            cursor = connection.cursor()
            cursor.execute('PRAGMA busy_timeout = 10000')
            cursor.execute('PRAGMA foreign_keys = ON')
            cursor.close()
    return engine


class Database:
    def __init__(self, url: str):
        self.engine = make_engine(url)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def read(self):
        async with self.sessions() as session:
            if self.engine.dialect.name == 'sqlite':
                await session.execute(text('BEGIN'))
            elif self.engine.dialect.name == 'postgresql':
                await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            yield session

    @asynccontextmanager
    async def write(self):
        async with self.sessions.begin() as session:
            if self.engine.dialect.name == 'sqlite':
                await session.execute(text('BEGIN IMMEDIATE'))
            elif self.engine.dialect.name == 'postgresql':
                await session.execute(text('SELECT pg_advisory_xact_lock(1724810925)'))
            yield session
