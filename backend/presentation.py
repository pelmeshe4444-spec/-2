import re
from datetime import UTC
from html import unescape

from services.attendance import Status


def timestamp(value):
    return value.replace(tzinfo=UTC).isoformat() if value else None


def school_class(value, *, can_history=True):
    return {'id': value.id, 'name': value.name, 'active': value.is_active, 'can_history': can_history}


def student(value):
    return {'id': value.id, 'name': value.name, 'class_id': value.class_id, 'active': value.is_active,
            'updated_at': timestamp(value.updated_at)}


def attendance(entry, authors=None):
    mark = entry.mark
    return {'id': entry.student.id, 'name': entry.student.name, 'status': int(entry.status), 'reason': entry.reason,
            'version': mark.updated_at.isoformat() if mark else '', 'updated_at': timestamp(mark.updated_at) if mark else None,
            'author': authors.get(mark.marked_by) if mark and authors else None}


def totals(values):
    return [values[status] for status in Status]


def profile(user):
    return {'id': user.telegram_id, 'username': user.username, 'name': user.full_name or f'Telegram {user.telegram_id}',
            'started': user.started_at is not None, 'blocked': user.blocked}


def schedule(value):
    return {'time': value.time, 'timezone': value.timezone, 'weekdays': list(map(int, value.weekdays)),
            'enabled': value.is_enabled, 'reminder_one': value.reminder_one, 'reminder_two': value.reminder_two,
            'deleted': value.deleted}


def report_text(parts):
    return [unescape(re.sub(r'</?(?:b|i)>', '', part)) for part in parts]
