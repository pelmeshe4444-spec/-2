import asyncio
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from html import escape
from io import BytesIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiohttp import ClientConnectorError
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from sqlalchemy import func, or_, select, update

from database.models import ManagerAssignment, ReportDelivery, ReportRecipient, ReportSchedule, SchoolClass, User, utc_now
from services.attendance import ICONS, LABELS, REPORT_LABELS, Status, counts, roster
from services.permissions import UserError, audit


log = logging.getLogger(__name__)
WEEKDAYS = ('Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс')
DELIVERY_STATUS = {'sending': 'отправляется', 'sent': 'доставлено', 'failed': 'ошибка',
                   'uncertain': 'доставка не подтверждена', 'cancelled': 'отменено'}


def time_value(value):
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value):
        raise UserError('Введите время в формате ЧЧ:ММ, например 08:30.')
    return value


def weekday_value(value):
    days = re.split(r'[\s,]+', value.strip())
    if not days or any(day not in '1234567' or len(day) != 1 for day in days):
        raise UserError('Введите номера дней от 1 до 7 через пробел. Понедельник — 1.')
    return ''.join(str(int(day) - 1) for day in sorted(set(days)))


def totals(count, *, period=False):
    noun = 'Всего записей' if period else 'Всего учеников'
    lines = ['📊 <b>ИТОГО</b>', f'👥 {noun}: {sum(count.values())}']
    lines.extend(f'{ICONS[status]} {label}: {count[status]}' for status, label in REPORT_LABELS.items())
    return '\n'.join(lines)


def detailed_report(class_name, day, entries, now):
    header = f'🏫 <b>ОТЧЁТ О ПОСЕЩАЕМОСТИ</b>\n\n📅 Дата: {day:%d.%m.%Y}\n🏷 Класс: {escape(class_name)}'
    chunks, current = [], header
    for status, label in REPORT_LABELS.items():
        group = [entry for entry in entries if entry.status == status]
        title = f'{ICONS[status]} <b>{label} ({len(group)})</b>'
        current, chunks = add_section(current, chunks, header, title, [
            f'{i}. {escape(entry.student.name)}' + (f' — {escape(entry.reason)}' if entry.reason else '')
            for i, entry in enumerate(group, 1)
        ])
    footer = f'━━━━━━━━━━━━\n{totals(counts(entries))}\n🕒 Отчёт сформирован: {now:%H:%M}'
    current, chunks = add_section(current, chunks, header, '', [footer])
    return chunks + [current]


def add_section(current, chunks, header, title, lines):
    # Keep serialized HTML conservatively below Telegram's UTF-16 text limit.
    prefix = f'\n\n{title}' if title else '\n'
    first = f'\n{lines[0]}' if lines else ''
    if len((current + prefix + first).encode('utf-16-le')) > 7800:
        chunks.append(current)
        current = header + '\n<i>Продолжение</i>'
    current += prefix
    for line in lines:
        if len((current + '\n' + line).encode('utf-16-le')) > 7800:
            chunks.append(current)
            current = header + '\n<i>Продолжение</i>' + prefix
        current += '\n' + line
    return current, chunks


def excel_report(class_name, by_day):
    workbook = Workbook()
    details = workbook.active
    details.title = 'Посещаемость'
    details.append(['Дата', 'Класс', 'Ученик', 'Статус', 'Комментарий'])
    summary = workbook.create_sheet('Сводка')
    summary.append(['Дата', 'Всего', *REPORT_LABELS.values()])
    for day, entries in by_day.items():
        day_counts = counts(entries)
        summary.append([day, len(entries), *(day_counts[status] for status in REPORT_LABELS)])
        for entry in entries:
            details.append([day, class_name, entry.student.name, LABELS[entry.status], entry.reason])
            for cell in details[details.max_row][1:]:
                if cell.value is not None:
                    cell.data_type = 's'
    for sheet, widths in ((details, (15, 22, 35, 33, 65)), (summary, (15, 12, 20, 14, 32, 32, 18))):
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
        for cell, width in zip(sheet[1], widths):
            cell.font = Font(bold=True, color='1B4F72')
            sheet.column_dimensions[get_column_letter(cell.column)].width = width
        for cell in sheet['A'][1:]:
            cell.number_format = 'dd.mm.yyyy'
    file = BytesIO()
    workbook.save(file)
    return file.getvalue()


class Reports:
    def __init__(self, db, permissions, attendance):
        self.db, self.permissions, self.attendance = db, permissions, attendance

    async def schedule(self, telegram_id, class_id):
        async with self.db.read() as session:
            await self.permissions.owner(session, telegram_id)
            _, school_class = await self.permissions.for_class(session, telegram_id, class_id)
            schedule = await session.scalar(select(ReportSchedule).where(ReportSchedule.class_id == class_id))
            return school_class, schedule

    async def configure(self, telegram_id, class_id, field, value):
        async with self.db.write() as session:
            actor = await self.permissions.owner(session, telegram_id)
            await self.permissions.for_class(session, telegram_id, class_id)
            schedule = await session.scalar(select(ReportSchedule).where(ReportSchedule.class_id == class_id))
            schedule.deleted = False
            if field == 'time':
                schedule.time = time_value(value)
            elif field == 'weekdays':
                schedule.weekdays = weekday_value(value)
            elif field in ('reminder_one', 'reminder_two'):
                setattr(schedule, field, None if value.strip() == '-' else time_value(value))
            elif field == 'is_enabled' and isinstance(value, bool):
                schedule.is_enabled = value
            else:
                raise UserError('Неизвестная настройка.')
            reminders = [reminder for reminder in (schedule.reminder_one, schedule.reminder_two) if reminder]
            if len(set(reminders)) != len(reminders) or any(reminder >= schedule.time for reminder in reminders):
                raise UserError('Напоминания должны быть в разное время и раньше отчёта.')
            audit(session, actor, 'schedule.updated', 'schedule', schedule.id, f'{field}={getattr(schedule, field)}')

    async def save_schedule(self, telegram_id, class_id, values=None):
        async with self.db.write() as session:
            actor = await self.permissions.owner(session, telegram_id)
            await self.permissions.for_class(session, telegram_id, class_id)
            schedule = await session.scalar(select(ReportSchedule).where(ReportSchedule.class_id == class_id))
            if values is None:
                schedule.deleted, schedule.is_enabled = True, False
                schedule.time, schedule.weekdays = '08:30', '01234'
                schedule.reminder_one = schedule.reminder_two = None
                schedule.timezone = self.attendance.zone.key
            else:
                try:
                    schedule.timezone = ZoneInfo(values.timezone).key
                except (ZoneInfoNotFoundError, ValueError):
                    raise UserError('Укажите часовой пояс IANA, например Asia/Tashkent.') from None
                schedule.time = time_value(values.time)
                schedule.weekdays = ''.join(map(str, sorted(set(values.weekdays))))
                reminders = [time_value(r) for r in (values.reminder_one, values.reminder_two) if r]
                if len(set(reminders)) != len(reminders) or any(r >= schedule.time for r in reminders):
                    raise UserError('Напоминания должны быть в разное время и раньше отчёта.')
                schedule.reminder_one, schedule.reminder_two = values.reminder_one, values.reminder_two
                schedule.deleted, schedule.is_enabled = False, values.enabled
            audit(session, actor, 'schedule.deleted' if values is None else 'schedule.updated', 'schedule', schedule.id)
            return schedule

    async def history(self, telegram_id, class_id, page, size):
        async with self.db.read() as session:
            await self.permissions.owner(session, telegram_id)
            await self.permissions.for_class(session, telegram_id, class_id, allow_archived=True)
            query = (select(ReportDelivery, User.telegram_id).join(User, User.id == ReportDelivery.recipient_id)
                     .join(ReportSchedule, ReportSchedule.id == ReportDelivery.schedule_id)
                     .where(ReportSchedule.class_id == class_id))
            count = await session.scalar(select(func.count()).select_from(query.subquery()))
            page = min(page, max(0, (count - 1) // size))
            rows = await session.execute(query.order_by(ReportDelivery.id.desc()).offset(page * size).limit(size))
            return list(rows), page, count

    async def manual_result(self, actor_id, class_id, schedule_id, day, key):
        async with self.db.read() as session:
            await self.permissions.owner(session, actor_id)
            await self.permissions.for_class(session, actor_id, class_id, allow_archived=True)
            states = list(await session.scalars(select(ReportDelivery.status).where(
                ReportDelivery.schedule_id == schedule_id, ReportDelivery.report_date == day, ReportDelivery.dispatch_key == key)))
            return {'sent': states.count('sent'), 'total': len(states)}

    async def latest(self, telegram_id, class_id):
        reports = await self.available(telegram_id, class_id, limit=1)
        return reports[0][1] if reports else []

    async def available(self, telegram_id, class_id, day=None, limit=1):
        async with self.db.read() as session:
            actor, _ = await self.permissions.for_class(session, telegram_id, class_id, recipient=True)
            query = (select(ReportDelivery.report_date, ReportDelivery.body)
                .join(ReportSchedule, ReportSchedule.id == ReportDelivery.schedule_id)
                .where(ReportSchedule.class_id == class_id, ReportDelivery.recipient_id == actor.id,
                       ReportDelivery.report_date >= self.attendance.today() - timedelta(days=89),
                       ReportDelivery.status == 'sent', ReportDelivery.body.is_not(None))
                .order_by(ReportDelivery.report_date.desc(), ReportDelivery.id.desc()).limit(limit))
            if day:
                query = query.where(ReportDelivery.report_date == day)
            return [(report_date, json.loads(body)) for report_date, body in await session.execute(query)]

    async def dispatch(self, bot, schedule_id, day, key, *, manual_actor=None, now=None):
        reminder = key.startswith('reminder_')
        model = ManagerAssignment if reminder else ReportRecipient
        now = now or datetime.now(UTC)
        async with self.db.read() as session:
            if manual_actor is not None:
                await self.permissions.owner(session, manual_actor)
            schedule = await session.get(ReportSchedule, schedule_id)
            if schedule is None:
                return {}
            school_class = await session.get(SchoolClass, schedule.class_id)
            local_now = now.astimezone(ZoneInfo(schedule.timezone))
            if not school_class.is_active or (manual_actor is None and not self.due_on(schedule, key, day, local_now)):
                return {}
            already_claimed = select(ReportDelivery.id).where(
                ReportDelivery.schedule_id == schedule_id, ReportDelivery.report_date == day,
                ReportDelivery.dispatch_key == key, ReportDelivery.recipient_id == User.id,
            ).exists()
            users = list(await session.scalars(select(User).join(model, model.user_id == User.id)
                         .where(model.class_id == school_class.id, User.started_at.is_not(None), ~User.blocked, ~already_claimed)
                         .order_by(User.id)))
            if not users:
                return {}
            entries = await roster(session, school_class.id, day)
        if reminder:
            unmarked = counts(entries)[Status.UNMARKED]
            if not unmarked:
                return {}
            report_time = datetime.combine(day, datetime.strptime(schedule.time, '%H:%M').time(), local_now.tzinfo)
            remaining = max(1, int((report_time - local_now).total_seconds() + 59) // 60)
            parts = [f'🔔 <b>Напоминание</b>\n🏷 Класс: {escape(school_class.name)}\n'
                     f'До отправки отчёта: {remaining} мин.\nНе отмечено учеников: {unmarked}']
        else:
            parts = detailed_report(school_class.name, day, entries, local_now)
        result = {}
        for target in users:
            delivery_id = await self._claim(schedule_id, day, key, target, len(parts), model, school_class.id, manual_actor, now)
            if delivery_id is not None:
                result[target.telegram_id] = await self._send(bot, parts, delivery_id, target, school_class.id, model)
        return result

    async def _claim(self, schedule_id, day, key, target, parts_total, model, class_id, manual_actor, now):
        async with self.db.write() as session:
            actor = await self.permissions.owner(session, manual_actor) if manual_actor is not None else None
            if not (await session.get(SchoolClass, class_id)).is_active:
                return None
            if manual_actor is None:
                schedule = await session.get(ReportSchedule, schedule_id)
                local_now = now.astimezone(ZoneInfo(schedule.timezone))
                if not self.due_on(schedule, key, day, local_now):
                    return None
            if (await session.get(User, target.id)).blocked or await session.get(model, (target.id, class_id)) is None:
                return None
            existing = await session.scalar(select(ReportDelivery.id).where(
                ReportDelivery.schedule_id == schedule_id, ReportDelivery.report_date == day,
                ReportDelivery.dispatch_key == key, ReportDelivery.recipient_id == target.id))
            if existing is not None:
                return None
            delivery = ReportDelivery(schedule_id=schedule_id, recipient_id=target.id, report_date=day,
                                      dispatch_key=key, parts_total=parts_total)
            session.add(delivery)
            await session.flush()
            audit(session, actor, 'delivery.claimed', 'delivery', delivery.id, f'class={class_id} key={key}')
            return delivery.id

    async def _send(self, bot, parts, delivery_id, target, class_id, model, sent=0):
        status, error, retry_delay = 'sent', None, 0
        for part in parts[sent:]:
            for attempt in range(3):
                async with self.db.read() as session:
                    assigned = await session.get(model, (target.id, class_id))
                    blocked = (await session.get(User, target.id)).blocked
                    active_class = (await session.get(SchoolClass, class_id)).is_active
                if assigned is None or blocked or not active_class:
                    status, error = 'cancelled', 'Права получателя отозваны.'
                    break
                try:
                    await bot.send_message(target.telegram_id, part, parse_mode='HTML', protect_content=True)
                    sent += 1
                    break
                except TelegramForbiddenError:
                    status, error = 'failed', 'Бот заблокирован или чат недоступен.'
                    break
                except TelegramBadRequest:
                    status, error = 'failed', 'Telegram отклонил запрос.'
                    break
                except TelegramRetryAfter as exc:
                    if attempt == 2 or exc.retry_after > 15:
                        status, error, retry_delay = 'retry', 'Превышен лимит Telegram.', max(120, exc.retry_after)
                        break
                    await asyncio.sleep(exc.retry_after)
                except TelegramNetworkError as exc:
                    if not isinstance(exc.__cause__, ClientConnectorError):
                        status, error = 'uncertain', 'Telegram не подтвердил приём запроса.'
                        break
                    if attempt == 2:
                        status, error, retry_delay = 'retry', 'Подключиться к Telegram не удалось.', 300
                        break
                    await asyncio.sleep(2 ** attempt)
                except Exception as exc:
                    status, error = 'uncertain', f'Telegram не подтвердил доставку ({type(exc).__name__}).'
                    break
            async with self.db.write() as session:
                delivery = await session.get(ReportDelivery, delivery_id)
                delivery.parts_sent = sent
            if status != 'sent':
                break
        async with self.db.write() as session:
            delivery = await session.get(ReportDelivery, delivery_id)
            if status == 'retry':
                if delivery.attempts < 3 and retry_delay <= 7200:
                    delivery.retry_at = utc_now() + timedelta(seconds=retry_delay)
                    delivery.body = json.dumps(parts, ensure_ascii=False)
                else:
                    status = 'failed'
            if status != 'retry':
                delivery.retry_at, delivery.body = None, None
            delivery.status, delivery.error_message = status, error
            if status == 'sent':
                delivery.sent_at = utc_now()
                if model is ReportRecipient and await session.get(model, (target.id, class_id)) is not None:
                    delivery.body = json.dumps(parts, ensure_ascii=False)
                    stored = list(await session.scalars(select(ReportDelivery).where(
                        ReportDelivery.schedule_id == delivery.schedule_id, ReportDelivery.recipient_id == target.id,
                        ReportDelivery.status == 'sent', ReportDelivery.body.is_not(None))
                        .order_by(ReportDelivery.report_date.desc(), ReportDelivery.id.desc())))
                    dates = set()
                    for previous in stored:
                        if previous.report_date in dates or previous.report_date < delivery.report_date - timedelta(days=89):
                            previous.body = None
                        dates.add(previous.report_date)
            audit(session, None, f'delivery.{status}', 'delivery', delivery_id, f'parts={sent}/{len(parts)}')
        if error:
            log.warning('Рассылка %s: %s', delivery_id, error)
        return status

    async def retry_due(self, bot):
        now = utc_now()
        async with self.db.read() as session:
            due = list(await session.scalars(select(ReportDelivery.id).where(ReportDelivery.status == 'retry',
                ReportDelivery.retry_at <= now).order_by(ReportDelivery.retry_at).limit(50)))
        for delivery_id in due:
            async with self.db.write() as session:
                delivery = await session.get(ReportDelivery, delivery_id)
                if delivery.status != 'retry' or delivery.retry_at > now:
                    continue
                schedule = await session.get(ReportSchedule, delivery.schedule_id)
                reminder = delivery.dispatch_key.startswith('reminder_')
                model = ManagerAssignment if reminder else ReportRecipient
                target = await session.get(User, delivery.recipient_id)
                active = delivery.dispatch_key.startswith('manual_') or schedule.is_enabled and not schedule.deleted
                fresh = delivery.created_at > now - timedelta(hours=18)
                if reminder:
                    local = now.replace(tzinfo=UTC).astimezone(ZoneInfo(schedule.timezone))
                    fresh = self.due_on(schedule, delivery.dispatch_key, delivery.report_date, local)
                if not active or not fresh or not delivery.body:
                    delivery.status, delivery.error_message, delivery.body = 'cancelled', 'Срок отправки истёк или доступ отозван.', None
                    audit(session, None, 'delivery.cancelled', 'delivery', delivery_id)
                    continue
                parts = json.loads(delivery.body)
                delivery.status, delivery.attempts = 'sending', delivery.attempts + 1
                delivery.retry_at = now
            await self._send(bot, parts, delivery_id, target, schedule.class_id, model, delivery.parts_sent)

    @staticmethod
    def is_due(schedule, key, now):
        if schedule.deleted or not schedule.is_enabled or str(now.weekday()) not in schedule.weekdays:
            return False
        current = now.strftime('%H:%M')
        if key == 'scheduled':
            return current >= schedule.time
        reminder_at = getattr(schedule, key)
        if not reminder_at:
            return False
        later = min((value for value in (schedule.reminder_one, schedule.reminder_two, schedule.time)
                     if value and value > reminder_at), default=schedule.time)
        return reminder_at <= current < later

    @classmethod
    def due_on(cls, schedule, key, day, now):
        if key != 'scheduled':
            return day == now.date() and cls.is_due(schedule, key, now)
        if schedule.deleted or not schedule.is_enabled or str(day.weekday()) not in schedule.weekdays:
            return False
        send_at = datetime.combine(day, datetime.strptime(schedule.time, '%H:%M').time(), now.tzinfo)
        return timedelta(0) <= now - send_at <= timedelta(hours=18)

    async def recover(self, *, startup=True):
        async with self.db.write() as session:
            stale = func.coalesce(ReportDelivery.retry_at, ReportDelivery.created_at) < utc_now() - timedelta(minutes=15)
            interrupted = or_(stale, ~ReportDelivery.dispatch_key.startswith('manual_')) if startup else stale
            result = await session.execute(update(ReportDelivery).where(ReportDelivery.status == 'sending', interrupted).values(
                status='uncertain', error_message='Процесс остановился до подтверждения доставки.'))
            if result.rowcount:
                audit(session, None, 'delivery.recovered', 'delivery', details=f'count={result.rowcount}')

    async def tick(self, bot, now=None):
        now = now or datetime.now(UTC)
        await self.recover(startup=False)
        await self.retry_due(bot)
        async with self.db.read() as session:
            schedules = list(await session.scalars(select(ReportSchedule).where(ReportSchedule.is_enabled)))
        for schedule in schedules:
            try:
                local = now.astimezone(ZoneInfo(schedule.timezone))
                for key in ('reminder_one', 'reminder_two', 'scheduled'):
                    if self.due_on(schedule, key, local.date(), local):
                        await self.dispatch(bot, schedule.id, local.date(), key, now=now)
                previous = local.date() - timedelta(days=1)
                if self.due_on(schedule, 'scheduled', previous, local):
                    await self.dispatch(bot, schedule.id, previous, 'scheduled', now=now)
            except Exception as exc:
                log.error('Ошибка расписания %s (%s)', schedule.id, type(exc).__name__)
