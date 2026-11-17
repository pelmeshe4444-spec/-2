from contextvars import ContextVar
from zoneinfo import ZoneInfo

from database.models import SchoolSettings


request_zone = ContextVar('school_timezone', default=None)


def school_zone(fallback: ZoneInfo) -> ZoneInfo:
    return request_zone.get() or fallback


async def school_settings(session, timezone):
    row = await session.get(SchoolSettings, 1)
    values = {
        'school': row.name if row else 'Школа', 'system_name': 'Attendance', 'timezone': timezone,
        'school_days': [0, 1, 2, 3, 4], 'join_open': True, 'join_retry_days': 0,
        'notify_owner': True, 'notify_schedule': False, 'lesson_start': '08:00', 'lesson_minutes': 45,
        'report_time': '08:30', 'dashboard_chart': True, 'statistics_days': 7,
    }
    if row and row.preferences:
        values.update(row.preferences)
    return values
