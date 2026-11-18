import asyncio
import sqlite3
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from database.models import Attendance, AuditLog
from services.attendance import Status, counts
from services.directory import parse_students
from services.permissions import Forbidden, UserError
from conftest import MANAGER, MONDAY, OWNER, RECIPIENT, VISITOR


async def test_roles_and_class_isolation(app, schools):
    a, b = schools
    assert not app.permissions.is_owner(VISITOR)
    with pytest.raises(Forbidden):
        await app.directory.access(VISITOR, VISITOR, a.id, 'manager_add')
    with pytest.raises(UserError, match='OWNER|владельца'):
        await app.directory.access(OWNER, OWNER, a.id, 'manager_add')
    await app.directory.access(OWNER, MANAGER, a.id, 'manager_add')
    await app.directory.access(OWNER, MANAGER, b.id, 'recipient_add')
    assert (await app.attendance.daily(MANAGER, a.id, MONDAY))[0].id == a.id
    with pytest.raises(Forbidden):
        await app.attendance.daily(MANAGER, b.id, MONDAY)
    with pytest.raises(Forbidden):
        await app.directory.add_students(MANAGER, a.id, ['Иванов Иван'])
    with pytest.raises(Forbidden):
        await app.reports.latest(MANAGER, a.id)
    assert await app.reports.latest(MANAGER, b.id) == []
    await app.directory.access(OWNER, MANAGER, a.id, 'manager_remove')
    with pytest.raises(Forbidden):
        await app.attendance.daily(MANAGER, a.id, MONDAY)
    assert await app.reports.latest(MANAGER, b.id) == []


async def test_recipient_must_start_but_manager_can_be_assigned_by_id(app, schools):
    a, _ = schools
    new_id = 9876543210
    with pytest.raises(UserError, match='/start'):
        await app.directory.access(OWNER, new_id, a.id, 'recipient_add')
    user, changed = await app.directory.access(OWNER, new_id, a.id, 'manager_add')
    assert changed and user.started_at is None
    await app.directory.register(new_id, 'verified', 'First User')
    assert (await app.directory.access(OWNER, new_id, a.id, 'recipient_add'))[1]


async def test_add_and_bulk_preview_commit_and_duplicate_protection(app, schools):
    a, b = schools
    await app.directory.add_students(OWNER, a.id, parse_students('Петров Александр', False))
    names = parse_students('Петров АЛЕКСАНДР\nЁлкин Иван\nИванов Иван\nиванов  Иван', True)
    added, duplicate = await app.directory.add_students(OWNER, a.id, names, preview=True)
    assert len(added) == len(duplicate) == 2
    assert len((await app.directory.students(OWNER, a.id))[1]) == 1
    assert await app.directory.add_students(OWNER, a.id, names) == (added, duplicate)
    names = [s.name for s in (await app.directory.students(OWNER, a.id))[1]]
    assert names == ['Ёлкин Иван', 'Иванов Иван', 'Петров Александр']
    assert len((await app.directory.add_students(OWNER, b.id, ['Иванов Иван']))[0]) == 1
    with pytest.raises(UserError):
        parse_students('— нет имени', False)


async def test_mark_reason_bulk_and_concurrent_edit(app, schools):
    a, _ = schools
    await app.directory.add_students(OWNER, a.id, parse_students('Иванов Иван\nПетров Пётр\nСидорова Мария', True))
    await app.directory.access(OWNER, MANAGER, a.id, 'manager_add')
    _, students = await app.directory.students(OWNER, a.id)
    first, second, third = [student.id for student in students]
    await app.attendance.mark(MANAGER, a.id, MONDAY, first, Status.SICK, reason='Высокая температура')
    entry = await app.attendance.mark(MANAGER, a.id, MONDAY, second, Status.EXCUSED)
    version = entry.mark.updated_at.isoformat()
    await app.attendance.mark(MANAGER, a.id, MONDAY, second, Status.EXCUSED, reason='Семейные обстоятельства', expected=version)
    with pytest.raises(UserError, match='изменилась'):
        await app.attendance.mark(MANAGER, a.id, MONDAY, second, Status.EXCUSED, reason='Устарело', expected=version)
    responses = await asyncio.gather(*(app.attendance.mark_all(uid, a.id, MONDAY) for uid in (OWNER, MANAGER)))
    assert sorted(responses) == [0, 1]
    _, entries = await app.attendance.daily(MANAGER, a.id, MONDAY)
    assert [entry.status for entry in entries] == [Status.SICK, Status.EXCUSED, Status.PRESENT]
    assert [entry.reason for entry in entries] == ['Высокая температура', 'Семейные обстоятельства', None]
    await app.attendance.mark(MANAGER, a.id, MONDAY, third, Status.ABSENT)
    await app.attendance.mark(OWNER, a.id, MONDAY, first, Status.PRESENT)
    _, entries = await app.attendance.finish(OWNER, a.id, MONDAY)
    assert counts(entries) == {Status.PRESENT: 1, Status.EXCUSED: 1, Status.ABSENT: 1}
    assert entries[0].reason is None
    async with app.db.read() as session:
        assert await session.scalar(select(func.count(Attendance.id))) == 3
        assert await session.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == 'attendance.finished')) == 1


async def test_archive_preserves_individual_history_and_removes_today(app, schools):
    a, _ = schools
    await app.directory.add_students(OWNER, a.id, ['Иванов Иван'])
    student = (await app.directory.students(OWNER, a.id))[1][0]
    await app.attendance.mark(OWNER, a.id, MONDAY, student.id, Status.SICK)
    await app.directory.edit_student(OWNER, student.id, archive=True)
    assert not (await app.attendance.daily(OWNER, a.id, MONDAY))[1]
    assert not (await app.directory.students(OWNER, a.id))[1]
    archived, history = await app.attendance.pupil_history(OWNER, student.id, MONDAY, MONDAY)
    assert not archived.is_active and history[0][2].status == Status.SICK


async def test_transfer_keeps_history_and_controls_manager_access(app, schools):
    a, b = schools
    await app.directory.add_students(OWNER, a.id, ['Иванов Иван'])
    await app.directory.access(OWNER, MANAGER, a.id, 'manager_add')
    student = (await app.directory.students(OWNER, a.id))[1][0]
    await app.attendance.mark(OWNER, a.id, MONDAY, student.id, Status.SICK)
    await app.directory.edit_student(OWNER, student.id, new_class=b.id)
    tuesday = MONDAY + timedelta(days=1)
    app.attendance.today = lambda: tuesday
    assert [e.student.id for e in (await app.attendance.daily(OWNER, b.id, tuesday))[1]] == [student.id]
    with pytest.raises(Forbidden):
        await app.attendance.daily(MANAGER, a.id, MONDAY)
    await app.directory.access(OWNER, MANAGER, a.id, 'history_on')
    assert (await app.attendance.daily(MANAGER, a.id, MONDAY))[1][0].status == Status.SICK
    with pytest.raises(Forbidden):
        await app.attendance.mark(MANAGER, a.id, MONDAY, student.id, Status.PRESENT)
    assert [class_name for _, class_name, _ in (await app.attendance.pupil_history(OWNER, student.id, MONDAY, tuesday))[1]] == [b.name, a.name]


async def test_backup_is_a_consistent_sqlite_copy(app, schools, tmp_path):
    with pytest.raises(Forbidden):
        await app.directory.backup(RECIPIENT)
    content = await app.directory.backup(OWNER)
    backup = tmp_path / 'copy.sqlite3'
    backup.write_bytes(content)
    connection = sqlite3.connect(backup)
    try:
        assert connection.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert connection.execute('SELECT count(*) FROM classes').fetchone() == (2,)
    finally:
        connection.close()
