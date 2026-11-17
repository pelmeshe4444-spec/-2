import asyncio
from datetime import datetime, time
from io import BytesIO
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from openpyxl import load_workbook
from sqlalchemy import select

from database.models import ReportDelivery, User
from services.attendance import Status
from services.permissions import Forbidden, UserError
from services.reports import detailed_report, excel_report
from conftest import MANAGER, MONDAY, OWNER, RECIPIENT, VISITOR


class Sender:
    def __init__(self, failures=None):
        self.messages = []
        self.failures = failures or {}

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))
        if chat_id in self.failures:
            raise self.failures[chat_id]


def at(app, hour, minute):
    return datetime.combine(MONDAY, time(hour, minute), app.attendance.zone)


async def test_report_totals_escape_and_xlsx(app, schools):
    a, _ = schools
    await app.directory.add_students(OWNER, a.id, [('Иванов', 'Иван'), ('Ким', 'Юлия'), ('Чен', 'Ян')])
    _, students = await app.directory.students(OWNER, a.id)
    await app.attendance.mark(OWNER, a.id, MONDAY, students[0].id, Status.EXCUSED, reason='=1+1 <семья> & школа')
    await app.attendance.mark(OWNER, a.id, MONDAY, students[1].id, Status.PRESENT)
    _, entries = await app.attendance.daily(OWNER, a.id, MONDAY)
    parts = detailed_report('<9-А>', MONDAY, entries, at(app, 8, 30))
    assert len(parts) == 1
    report = parts[0]
    for expected in ('Всего учеников: 3', 'Присутствуют (1)', 'Не отмечены (1)', 'По уважительной причине (1)',
                     'Отсутствуют без причины (0)', 'Болеют (0)', '&lt;9-А&gt;', '=1+1 &lt;семья&gt; &amp; школа'):
        assert expected in report
    assert all(report.count(student.name) == 1 for student in students)
    result = load_workbook(BytesIO(excel_report(a.name, {MONDAY: entries})))
    assert result['Посещаемость']['E2'].data_type == 's'
    assert result['Посещаемость']['E2'].value == '=1+1 <семья> & школа'
    row = list(result['Сводка'].values)[1]
    assert row[1] == sum(row[2:]) == 3


def test_long_report_keeps_sections_order_and_limits():
    entries = [SimpleNamespace(student=SimpleNamespace(name=f'Ученик {i:03d}'), status=Status.SICK,
                               reason='Причина & 💬 ' * 20) for i in range(70)]
    report = detailed_report('9-А', MONDAY, entries, datetime.now())
    assert len(report) > 1
    assert all(len(part.encode('utf-16-le')) <= 7800 for part in report)
    assert all('ОТЧЁТ О ПОСЕЩАЕМОСТИ' in part for part in report)
    assert all('Болеют (70)' in part for part in report if 'Ученик' in part)
    merged = '\n'.join(report)
    positions = [merged.index(entry.student.name) for entry in entries]
    assert positions == sorted(positions)
    assert all(merged.count(entry.student.name) == 1 for entry in entries)
    assert 'Всего учеников: 70' in report[-1]


async def test_reminders_schedule_catchup_and_no_duplicate(app, schools):
    a, b = schools
    sender = Sender()
    await app.directory.add_students(OWNER, a.id, [('Иванов', 'Иван')])
    await app.directory.access(OWNER, MANAGER, a.id, 'manager_add')
    await app.directory.access(OWNER, VISITOR, b.id, 'manager_add')
    await app.directory.access(OWNER, RECIPIENT, a.id, 'recipient_add')
    await app.directory.access(OWNER, MANAGER, a.id, 'recipient_add')
    await app.reports.configure(OWNER, a.id, 'reminder_one', '07:45')
    await app.reports.configure(OWNER, a.id, 'reminder_two', '08:15')
    await app.reports.configure(OWNER, a.id, 'is_enabled', True)
    await app.reports.tick(sender, at(app, 7, 44))
    assert not sender.messages
    await app.reports.tick(sender, at(app, 7, 45))
    await app.reports.tick(sender, at(app, 7, 46))
    await app.reports.tick(sender, at(app, 8, 15))
    assert [uid for uid, _, _ in sender.messages] == [MANAGER, MANAGER]
    assert 'Не отмечено учеников: 1' in sender.messages[0][1]
    late = at(app, 9, 5)
    await asyncio.gather(app.reports.tick(sender, late), app.reports.tick(sender, late))
    assert sorted(uid for uid, _, _ in sender.messages[2:]) == [MANAGER, RECIPIENT]
    await app.reports.recover()
    await app.reports.tick(sender, late)
    assert len(sender.messages) == 4
    assert 'Не отмечены (1)' in (await app.reports.latest(RECIPIENT, a.id))[0]
    with pytest.raises(Forbidden):
        await app.reports.latest(RECIPIENT, b.id)
    async with app.db.read() as session:
        rows = list(await session.scalars(select(ReportDelivery)))
        assert len(rows) == 4 and all(row.status == 'sent' for row in rows)


async def test_weekdays_and_disabled_schedule(app, schools):
    a, _ = schools
    await app.directory.access(OWNER, RECIPIENT, a.id, 'recipient_add')
    sender = Sender()
    await app.reports.tick(sender, at(app, 8, 30))
    await app.reports.configure(OWNER, a.id, 'weekdays', '2 4,7')
    await app.reports.configure(OWNER, a.id, 'is_enabled', True)
    await app.reports.tick(sender, at(app, 8, 30))
    assert sender.messages == []
    with pytest.raises(UserError):
        await app.reports.configure(OWNER, a.id, 'reminder_one', '09:00')
    with pytest.raises(Forbidden):
        await app.reports.configure(RECIPIENT, a.id, 'time', '08:00')


async def test_delivery_errors_do_not_stop_other_recipients(app, schools):
    a, _ = schools
    await app.directory.access(OWNER, RECIPIENT, a.id, 'recipient_add')
    await app.directory.access(OWNER, VISITOR, a.id, 'recipient_add')
    await app.directory.access(OWNER, MANAGER, a.id, 'recipient_add')
    forbidden = TelegramForbiddenError(SendMessage(chat_id=RECIPIENT, text='test'), 'bot blocked')
    sender = Sender({RECIPIENT: forbidden, VISITOR: TimeoutError()})
    _, schedule = await app.reports.schedule(OWNER, a.id)
    result = await app.reports.dispatch(sender, schedule.id, MONDAY, 'manual_example', manual_actor=OWNER)
    assert result == {MANAGER: 'sent', RECIPIENT: 'failed', VISITOR: 'uncertain'}
    assert await app.reports.latest(RECIPIENT, a.id) == []
    assert await app.reports.dispatch(sender, schedule.id, MONDAY, 'manual_example', manual_actor=OWNER) == {}
    assert len(sender.messages) == 3
    rows, _, size = await app.reports.history(OWNER, a.id, 0, 10)
    assert size == 3
    assert all(row.error_message for row, _ in rows if row.status != 'sent')


async def test_schedule_retries_explicit_temporary_rejection_once(app, schools):
    a, _ = schools
    await app.directory.access(OWNER, RECIPIENT, a.id, 'recipient_add')
    await app.reports.configure(OWNER, a.id, 'is_enabled', True)

    class RetryOnce(Sender):
        async def send_message(self, chat_id, text, **kwargs):
            await super().send_message(chat_id, text, **kwargs)
            if len(self.messages) == 1:
                raise TelegramRetryAfter(SendMessage(chat_id=chat_id, text=text), 'wait', retry_after=0)

    sender = RetryOnce()
    await app.reports.tick(sender, at(app, 8, 30))
    await app.reports.tick(sender, at(app, 8, 45))
    assert len(sender.messages) == 2
    deliveries, _, size = await app.reports.history(OWNER, a.id, 0, 10)
    assert size == 1 and deliveries[0][0].status == 'sent' and deliveries[0][0].parts_sent == 1


async def test_interrupted_delivery_is_never_automatically_replayed(app, schools):
    a, _ = schools
    await app.directory.access(OWNER, RECIPIENT, a.id, 'recipient_add')
    await app.reports.configure(OWNER, a.id, 'is_enabled', True)
    _, schedule = await app.reports.schedule(OWNER, a.id)
    async with app.db.write() as session:
        recipient = await session.scalar(select(User).where(User.telegram_id == RECIPIENT))
        session.add(ReportDelivery(schedule_id=schedule.id, recipient_id=recipient.id, report_date=MONDAY,
                                   dispatch_key='scheduled', parts_total=2, parts_sent=1))
    await app.reports.recover()
    sender = Sender()
    await app.reports.tick(sender, at(app, 8, 30))
    assert not sender.messages
    rows, _, _ = await app.reports.history(OWNER, a.id, 0, 10)
    assert rows[0][0].status == 'uncertain' and rows[0][0].parts_sent == 1


async def test_snapshot_cleared_after_replacement_and_revocation(app, schools):
    a, _ = schools
    await app.directory.access(OWNER, RECIPIENT, a.id, 'recipient_add')
    _, schedule = await app.reports.schedule(OWNER, a.id)
    sender = Sender()
    for key in ('manual_one', 'manual_two'):
        assert (await app.reports.dispatch(sender, schedule.id, MONDAY, key, manual_actor=OWNER))[RECIPIENT] == 'sent'
    rows, _, _ = await app.reports.history(OWNER, a.id, 0, 10)
    assert sum(bool(row.body) for row, _ in rows) == 1
    await app.directory.access(OWNER, RECIPIENT, a.id, 'recipient_remove')
    with pytest.raises(Forbidden):
        await app.reports.latest(RECIPIENT, a.id)
    rows, _, _ = await app.reports.history(OWNER, a.id, 0, 10)
    assert all(row.body is None for row, _ in rows)
