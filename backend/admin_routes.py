import asyncio
import os
from datetime import UTC, datetime, time, timedelta
from typing import Annotated
from urllib.parse import urlsplit

from aiogram.exceptions import TelegramAPIError
from fastapi import BackgroundTasks
from pydantic import Field
from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import SQLAlchemyError

from backend import presentation as view
from backend.schemas import Input
from database.models import (Attendance, ClassJoinRequest, Enrollment, ManagerAssignment, ReportDelivery,
                             SchoolClass, Student, SystemEvent, User)
from services import announcements
from services.attendance import Status, enrolled_on
from services.directory import bounded
from services.school_settings import school_settings, school_zone


class AnnouncementInput(Input):
    class_ids: list[Annotated[int, Field(gt=0)]] = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)


class ConfirmedAnnouncement(AnnouncementInput):
    confirmation: str = Field(pattern=r'^[0-9a-f]{64}$')
    request_id: str = Field(pattern=r'^[0-9a-f]{32}$')


async def attendance_for_day(session, day):
    status = func.coalesce(Attendance.status, 0)
    rows = await session.execute(select(status, func.count()).select_from(Enrollment)
        .join(SchoolClass, SchoolClass.id == Enrollment.class_id)
        .outerjoin(Attendance, and_(Attendance.student_id == Enrollment.student_id, Attendance.date == day))
        .where(enrolled_on(day), SchoolClass.is_active).group_by(status))
    by_status = dict(rows.all())
    return [by_status.get(kind, 0) for kind in Status]


async def inspect_webhook(config, telegram_sender, checked_at):
    if not config.webhook_secret:
        return {'state': 'not_configured', 'checked_at': checked_at}
    try:
        async with telegram_sender() as bot:
            info = await asyncio.wait_for(bot.get_webhook_info(), timeout=4)
    except (TimeoutError, TelegramAPIError):
        return {'state': 'unavailable', 'checked_at': checked_at}
    destination = urlsplit(info.url)
    origin = os.getenv('RENDER_EXTERNAL_URL', '')
    expected_path = destination.scheme == 'https' and destination.path == '/api/telegram/webhook'
    expected_host = not origin or urlsplit(origin).netloc == destination.netloc
    state = ('not_registered' if not info.url else 'unexpected' if not (expected_path and expected_host)
             else 'error' if info.last_error_date else 'ok')
    return {'state': state, 'checked_at': checked_at, 'pending': info.pending_update_count,
            'last_error_at': view.timestamp(info.last_error_date)}


def admin_routes(api, core, config, Owner, telegram_sender):
    @api.get('/api/admin/dashboard')
    async def dashboard(uid: Owner):
        today = core.attendance.today()
        zone = school_zone(config.zone)
        start = datetime.combine(today, time.min, zone).astimezone(UTC).replace(tzinfo=None)
        end = datetime.combine(today + timedelta(days=1), time.min, zone).astimezone(UTC).replace(tzinfo=None)
        async with core.db.read() as session:
            await core.permissions.owner(session, uid)
            settings = await school_settings(session, config.zone.key)
            active = select(SchoolClass.id).where(SchoolClass.is_active)
            pupils = await session.scalar(select(func.count(Student.id)).where(Student.is_active, Student.class_id.in_(active)))
            classes = await session.scalar(select(func.count()).select_from(active.subquery()))
            pending = await session.scalar(select(func.count(ClassJoinRequest.id)).where(ClassJoinRequest.status == 'PENDING'))
            managers = await session.scalar(select(func.count(func.distinct(ManagerAssignment.user_id)))
                .join(User, User.id == ManagerAssignment.user_id).where(~User.blocked, ManagerAssignment.class_id.in_(active)))
            sent = await session.scalar(select(func.count(ReportDelivery.id)).where(ReportDelivery.status == 'sent',
                ReportDelivery.sent_at >= start, ReportDelivery.sent_at < end, ~ReportDelivery.dispatch_key.startswith('reminder_')))
            attendance = await attendance_for_day(session, today)
            trend = []
            if settings['dashboard_chart']:
                for offset in range(6, 0, -1):
                    day = today - timedelta(days=offset)
                    trend.append({'day': day, 'counts': await attendance_for_day(session, day)})
                trend.append({'day': today, 'counts': attendance})
        rows, _, _ = await core.directory.audit_page(uid, 0, 6)
        return {'school': settings['school'], 'system_name': settings['system_name'], 'today': today, 'backend': 'ok',
                'students': pupils, 'classes': classes, 'attendance': attendance, 'pending_requests': pending,
                'managers': managers, 'sent_reports': sent, 'trend': trend,
                'recent_actions': [view.audit_item(row, actor) for row, actor in rows]}

    @api.get('/api/admin/system-health')
    async def system_health(uid: Owner):
        checked = datetime.now(UTC).isoformat()
        latest = scheduler = None
        errors = []
        database = 'ok'
        try:
            async with core.db.read() as session:
                await session.execute(text('SELECT 1'))
                scheduler = await session.scalar(select(SystemEvent).where(SystemEvent.operation == 'scheduler',
                    SystemEvent.success).order_by(SystemEvent.id.desc()).limit(1))
                latest = await session.scalar(select(ReportDelivery).where(~ReportDelivery.dispatch_key.startswith('reminder_'))
                    .order_by(ReportDelivery.id.desc()).limit(1))
                rows = await session.scalars(select(SystemEvent).where(~SystemEvent.success).order_by(SystemEvent.id.desc()).limit(10))
                errors = [{'source': row.operation, 'time': view.timestamp(row.occurred_at)} for row in rows]
        except SQLAlchemyError:
            database = 'unavailable'
        webhook = await inspect_webhook(config, telegram_sender, checked)
        return {'backend': 'ok', 'checked_at': checked, 'database': {'engine': core.db.engine.dialect.name, 'state': database},
                'webhook': webhook, 'last_scheduler_success': view.timestamp(scheduler.occurred_at) if scheduler else None,
                'last_report': {'status': latest.status, 'time': view.timestamp(latest.sent_at or latest.created_at)} if latest else None,
                'recent_errors': errors}

    @api.get('/api/admin/announcements')
    async def recent_announcements(uid: Owner):
        async with core.db.read() as session:
            await core.permissions.owner(session, uid)
            return [{'id': row.id, 'message': row.message, 'class_ids': row.class_ids,
                     'time': view.timestamp(row.created_at), 'statuses': statuses}
                    for row, statuses in await announcements.deliveries(session)]

    @api.post('/api/admin/announcements/preview')
    async def preview_announcement(body: AnnouncementInput, uid: Owner):
        async with core.db.read() as session:
            await core.permissions.owner(session, uid)
            _, recipients, confirmation = await announcements.preview(session, body.class_ids, bounded(body.message, 500))
        return {'recipients': len(recipients), 'confirmation': confirmation}

    @api.post('/api/admin/announcements', status_code=202)
    async def send_announcement(body: ConfirmedAnnouncement, uid: Owner, background: BackgroundTasks):
        async with core.db.write() as session:
            actor = await core.permissions.owner(session, uid)
            row = await announcements.queue_announcement(session, actor, body)

        async def deliver():
            async with telegram_sender() as bot:
                await core.memberships.flush(bot, limit=2000, announcement_id=row.id)

        background.add_task(deliver)
        return {'id': row.id}
