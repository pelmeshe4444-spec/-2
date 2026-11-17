import asyncio

from alembic import context

from config import database_url
from database.models import Base
from database.session import make_engine


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=connection.dialect.name == 'sqlite')
    with context.begin_transaction():
        context.run_migrations()


def migrate_connection(connection):
    if connection.dialect.name == 'sqlite':
        # SQLite's legacy transaction mode does not begin a transaction for DDL.
        with connection.begin():
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            run(connection)
    elif connection.dialect.name == 'postgresql':
        with connection.begin():
            connection.exec_driver_sql('SELECT pg_advisory_xact_lock(1724810925)')
            run(connection)
    else:
        run(connection)


async def migrate():
    engine = make_engine(context.config.attributes.get('database_url') or database_url())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(migrate_connection)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(migrate())
