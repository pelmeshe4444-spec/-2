import logging

from database.models import SystemEvent


log = logging.getLogger(__name__)


async def record_event(db, operation, success):
    try:
        async with db.write() as session:
            session.add(SystemEvent(operation=operation, success=success))
    except Exception as exc:
        log.error('Could not record %s status (%s)', operation, type(exc).__name__)
