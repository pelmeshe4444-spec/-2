import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend import presentation as view
from backend.admin_routes import admin_routes
from backend.auth import InvalidInitData, TelegramAuth
from backend.schemas import (AdminAccessInput, BlockInput, ClassInput, MarkInput, NamesInput, ScheduleInput,
                             SendInput, SendNowInput, SettingsInput, StudentInput, UserInput)
from backend.school_routes import school_routes
from config import ROOT
from database.models import AttendanceChange, ClassMembership, ManagerAssignment, ReportRecipient, SchoolClass, SchoolSettings, User
from services.application import AttendanceApplication
from services.attendance import Status, counts, parse_date, period_days, roster
from services.directory import bounded, parse_students
from services.permissions import Conflict, Forbidden, UserError, audit
from services.reports import detailed_report, excel_report, time_value
from services.school_settings import request_zone, school_settings, school_zone
from services.system_status import record_event


log = logging.getLogger(__name__)


class RateLimit:
    def __init__(self):
        self.windows = {}
        self.cleanup_at = 0

    def take(self, key, maximum):
        now = monotonic()
        if now >= self.cleanup_at:
            self.windows = {key: value for key, value in self.windows.items() if value[0] > now}
            self.cleanup_at = now + 60
        if key not in self.windows and len(self.windows) >= 20_000:
            return False
        expires, count = self.windows.get(key, (now + 60, 0))
        if expires <= now:
            expires, count = now + 60, 0
        if count >= maximum:
            return False
        self.windows[key] = (expires, count + 1)
        return True


def create_api(config, db, *, sender=None, dist=None, desktop=None):
    core = AttendanceApplication(db, config)
    auth, limits = TelegramAuth(config.token, config.init_data_ttl), RateLimit()
    dist = Path(dist or ROOT / 'frontend' / 'dist')
    tickets = {}

    @asynccontextmanager
    async def telegram_sender():
        if sender is not None:
            yield sender
        else:
            async with Bot(config.token) as bot:
                yield bot

    @asynccontextmanager
    async def lifespan(_):
        try:
            if config.updates_mode == 'webhook':
                try:
                    async with telegram_sender() as bot:
                        if not await asyncio.wait_for(bot.set_webhook(
                            url=config.webhook_url, secret_token=config.webhook_secret,
                            allowed_updates=['message', 'callback_query'], drop_pending_updates=False), timeout=15):
                            raise RuntimeError('Telegram webhook registration failed.')
                except Exception as exc:
                    log.error('telegram_webhook configuration_failed error=%s', type(exc).__name__)
                    raise RuntimeError('Telegram webhook configuration failed.') from None
                log.info('telegram_webhook configured mode=webhook')
            yield
        finally:
            await db.engine.dispose()

    api = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    if config.frontend_origin:
        api.add_middleware(CORSMiddleware, allow_origins=[config.frontend_origin],
                           allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'],
                           allow_headers=['Authorization', 'Content-Type'],
                           expose_headers=['Content-Disposition'])
    if desktop is not None:
        api.add_api_route('/desktop/open/{key}', desktop.open, methods=['GET'])

    @api.middleware('http')
    async def headers(request, call_next):
        if desktop is not None and not desktop.is_local(request):
            return JSONResponse({'detail': 'Локальная панель доступна на этом компьютере.'}, status_code=403)
        try:
            too_large = int(request.headers.get('content-length', 0)) > 64_000
        except ValueError:
            too_large = True
        if too_large:
            return JSONResponse({'detail': 'Запрос слишком большой.'}, status_code=413)
        if request.scope['path'].startswith('/api/v1/'):
            request.scope['path'] = '/api/' + request.scope['path'][8:]
        zone = None
        is_api = request.scope['path'].startswith('/api/')
        try:
            if is_api and (desktop is not None or request.headers.get('Authorization', '').startswith('tma ')):
                async with db.read() as session:
                    settings = await school_settings(session, config.zone.key)
                zone = request_zone.set(ZoneInfo(settings['timezone']))
            response = await call_next(request)
        except Exception as exc:
            if not is_api:
                raise
            log.error('Ошибка API Attendance (%s)', type(exc).__name__)
            if not isinstance(exc, (SQLAlchemyError, OSError)):
                await record_event(db, 'backend', False)
            response = JSONResponse({'detail': 'Сервер временно недоступен.'}, status_code=503)
        finally:
            if zone is not None:
                request_zone.reset(zone)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        telegram_origin = '' if desktop is not None else ' https://telegram.org'
        frames = "'none'" if desktop is not None else 'https://web.telegram.org https://*.telegram.org'
        response.headers['Content-Security-Policy'] = (
            f"default-src 'self'; script-src 'self'{telegram_origin}; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
            f'frame-ancestors {frames}'
        )
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @api.exception_handler(UserError)
    async def user_error(_, exc):
        status = 403 if isinstance(exc, Forbidden) else 409 if isinstance(exc, Conflict) else 400
        return JSONResponse({'detail': str(exc)}, status_code=status)

    @api.exception_handler(RequestValidationError)
    async def invalid_input(_, __):
        return JSONResponse({'detail': 'Проверьте заполненные поля.'}, status_code=422)

    async def identify(request: Request):
        address = request.client.host if request.client else 'local'
        if not limits.take(('ip', address), 600):
            raise HTTPException(429, 'Слишком много запросов. Подождите минуту.')
        raw = request.headers.get('Authorization', '')
        identity = desktop.authenticate(request) if desktop is not None and not raw else None
        try:
            if identity is None:
                if not raw.startswith('tma '):
                    raise InvalidInitData
                identity = auth.validate(raw[4:])
        except InvalidInitData:
            raise HTTPException(401, 'Откройте приложение заново из Telegram.') from None
        if not limits.take(('account', identity.telegram_id), 180):
            raise HTTPException(429, 'Слишком много запросов. Подождите минуту.')
        return identity

    async def active_account(identity=Depends(identify)):
        async with db.read() as session:
            await core.permissions.actor(session, identity.telegram_id)
        return identity.telegram_id

    async def owner_account(uid=Depends(active_account)):
        if not core.permissions.is_owner(uid):
            raise Forbidden()
        return uid

    Account = Annotated[int, Depends(active_account)]
    Owner = Annotated[int, Depends(owner_account)]
    school_routes(api, core, Account, Owner, telegram_sender)
    admin_routes(api, core, config, Owner, telegram_sender)
    if config.webhook_secret or config.scheduler_secret:
        from backend.cloud_routes import cloud_routes
        cloud_routes(api, core, config, telegram_sender)

    def day_or_today(value):
        return parse_date(value) if value else core.attendance.today()

    async def signed_user(session, uid):
        return await session.scalar(select(User).where(User.telegram_id == uid))

    async def team(uid, class_id):
        return {role: [{'user': view.profile(user), 'history': getattr(assignment, 'can_view_history', False)}
                       for user, assignment in (await core.directory.assignments(uid, class_id, role == 'recipients'))[1]]
                for role in ('managers', 'recipients')}

    @api.get('/api/health')
    async def health():
        async with db.read() as session:
            await session.scalar(select(SchoolClass.id).limit(1))
        return {'status': 'ok'}

    @api.get('/api/me')
    async def me(identity=Depends(identify)):
        uid = identity.telegram_id
        async with db.read() as session:
            user = await signed_user(session, uid)
        if user is None or (user.started_at is None and not user.full_name):
            await core.directory.register(uid, identity.username, identity.full_name, started=False)
        async with db.read() as session:
            user = await signed_user(session, uid)
            owner = core.permissions.is_owner(uid)
            managed = await core.permissions.classes(session, uid)
            received = [] if owner else await core.permissions.classes(session, uid, 'receive')
            history = {item.id for item in await core.permissions.classes(session, uid, 'history')}
            settings = await school_settings(session, config.zone.key)
            member = await session.get(ClassMembership, user.id)
            member_class = await session.get(SchoolClass, member.class_id) if member and not user.blocked else None
            member_class = member_class if member_class and member_class.is_active else None
            assignments = {} if owner else {row.class_id: row for row in await session.scalars(select(ManagerAssignment)
                                                                 .where(ManagerAssignment.user_id == user.id))}
        roles = ['OWNER'] if owner else [role for role, classes in (('MANAGER', managed), ('REPORT_RECIPIENT', received)) if classes]
        if member_class and not owner:
            roles.append('CLASS_MEMBER')
        viewer_ids = {class_id for class_id, assignment in assignments.items() if assignment.can_view_reports}
        report_classes = {item.id: item for item in [*received, *(item for item in managed if item.id in viewer_ids)]}
        return {'user': view.profile(user), 'roles': roles or ['USER'], 'school': settings['school'],
                'system_name': settings['system_name'], 'join_open': settings['join_open'], 'statistics_days': settings['statistics_days'],
                'today': core.attendance.today(), 'timezone': settings['timezone'], 'sqlite': db.engine.dialect.name == 'sqlite',
                'managed': [{**view.school_class(item, can_history=item.id in history),
                             'can_edit_history': owner or assignments[item.id].can_edit_history,
                             'can_view_statistics': owner or assignments[item.id].can_view_statistics,
                             'can_send_reports': owner or assignments[item.id].can_send_reports} for item in managed],
                'reports': [{**view.school_class(item), 'can_view_reports': item.id in viewer_ids}
                            for item in sorted(report_classes.values(), key=lambda row: row.name_key)],
                'member': view.school_class(member_class, can_history=False) if member_class else None}

    @api.get('/api/classes')
    async def classes(uid: Owner):
        async with db.read() as session:
            await core.permissions.owner(session, uid)
            items = await session.scalars(select(SchoolClass).order_by(SchoolClass.is_active.desc(), SchoolClass.name_key))
            return [view.school_class(item) for item in items]

    @api.post('/api/classes', status_code=201)
    async def add_class(body: ClassInput, uid: Owner):
        return view.school_class(await core.directory.add_class(uid, body.name))

    @api.patch('/api/classes/{class_id}')
    async def update_class(class_id: int, body: ClassInput, uid: Owner):
        return view.school_class(await core.directory.update_class(uid, class_id, name=body.name))

    @api.delete('/api/classes/{class_id}')
    async def archive_class(class_id: int, uid: Owner):
        return view.school_class(await core.directory.update_class(uid, class_id, archive=True))

    @api.post('/api/classes/{class_id}/restore')
    async def restore_class(class_id: int, uid: Owner):
        return view.school_class(await core.directory.update_class(uid, class_id, restore=True))

    @api.get('/api/classes/{class_id}/access')
    async def class_access(class_id: int, uid: Owner):
        return await team(uid, class_id)

    @api.get('/api/classes/{class_id}/students')
    async def students(class_id: int, uid: Owner, q: Annotated[str, Query(max_length=255)] = ''):
        _, students = await core.directory.students(uid, class_id, query=q, include_archived=True)
        _, entries = await core.attendance.daily(uid, class_id, core.attendance.today())
        marks = {entry.student.id: entry for entry in entries}
        return [{**view.student(item), 'status': int(marks[item.id].status) if item.id in marks else 0,
                 'marked_at': view.timestamp(marks[item.id].mark.updated_at) if item.id in marks and marks[item.id].mark else None}
                for item in students]

    @api.post('/api/classes/{class_id}/students')
    async def add_students(class_id: int, body: NamesInput, uid: Owner):
        names = parse_students(body.names, body.bulk)
        added, duplicates = await core.directory.add_students(uid, class_id, names, preview=body.preview)
        return {'added': added, 'duplicates': duplicates}

    @api.get('/api/students/{student_id}')
    async def student_details(student_id: int, uid: Owner, start: str = '', end: str = ''):
        last = day_or_today(end)
        first = parse_date(start) if start else last - timedelta(days=29)
        student, history = await core.attendance.pupil_history(uid, student_id, first, last)
        return {**view.student(student), 'history': [{'day': day, 'class_name': name, **view.attendance(entry)}
                                                    for day, name, entry in history]}

    @api.patch('/api/students/{student_id}')
    async def edit_student(student_id: int, body: StudentInput, uid: Owner):
        name = parse_students(body.full_name, False)[0] if body.full_name is not None else None
        return view.student(await core.directory.edit_student(uid, student_id, name=name, new_class=body.class_id))

    @api.delete('/api/students/{student_id}')
    async def archive_student(student_id: int, uid: Owner):
        return view.student(await core.directory.edit_student(uid, student_id, archive=True))

    @api.post('/api/students/{student_id}/restore')
    async def restore_student(student_id: int, uid: Owner):
        return view.student(await core.directory.restore_student(uid, student_id))

    @api.get('/api/classes/{class_id}/attendance')
    async def read_attendance(class_id: int, uid: Account, day: str = ''):
        day = day_or_today(day)
        async with db.read() as session:
            actor, school = await core.attendance.scope(session, uid, class_id, day)
            entries = [] if school.archived_on and day > school.archived_on else await roster(session, class_id, day)
            mark_users = {entry.mark.marked_by for entry in entries if entry.mark}
            authors = {user.id: user.full_name or user.username or 'Пользователь Telegram' for user in
                       await session.scalars(select(User).where(User.id.in_(mark_users)))}
            can_correct = core.permissions.is_owner(uid)
            if not can_correct and day < core.attendance.today():
                assignment = await session.get(ManagerAssignment, (actor.id, class_id))
                can_correct = bool(assignment and assignment.can_edit_history)
        writable = school.is_active and (can_correct or day == core.attendance.today())
        return {'class': view.school_class(school), 'day': day, 'counts': view.totals(counts(entries)), 'writable': writable,
                'entries': [view.attendance(entry, authors) for entry in entries]}

    @api.put('/api/classes/{class_id}/attendance/{student_id}')
    async def set_mark(class_id: int, student_id: int, day: str, body: MarkInput, uid: Account):
        entry = await core.attendance.mark(uid, class_id, parse_date(day), student_id, body.status,
                                          reason=body.reason, expected=body.version)
        return view.attendance(entry)

    @api.get('/api/classes/{class_id}/attendance/history')
    async def attendance_history(class_id: int, day: str, uid: Account):
        chosen = parse_date(day)
        async with db.read() as session:
            await core.attendance.scope(session, uid, class_id, chosen)
            rows = await session.execute(select(AttendanceChange, User.full_name).join(User, User.id == AttendanceChange.actor_id)
                                         .where(AttendanceChange.class_id == class_id, AttendanceChange.date == chosen)
                                         .order_by(AttendanceChange.id.desc()).limit(100))
            return [{'id': row.id, 'student_id': row.student_id, 'before_status': row.before_status,
                     'after_status': row.after_status, 'before_reason': row.before_reason, 'after_reason': row.after_reason,
                     'actor': name, 'time': view.timestamp(row.changed_at)} for row, name in rows]

    @api.post('/api/classes/{class_id}/attendance/mark-all')
    async def mark_all(class_id: int, day: str, uid: Account):
        return {'changed': await core.attendance.mark_all(uid, class_id, parse_date(day))}

    @api.post('/api/classes/{class_id}/attendance/finish')
    async def finish(class_id: int, day: str, uid: Account):
        _, entries = await core.attendance.finish(uid, class_id, parse_date(day))
        return {'counts': view.totals(counts(entries))}

    @api.get('/api/admin/recipient-candidates')
    async def recipient_candidates(uid: Owner, class_id: Annotated[int, Query(gt=0)],
                                   page: Annotated[int, Query(ge=0, le=100000)] = 0,
                                   q: Annotated[str, Query(max_length=160)] = ''):
        users, page, total = await core.directory.recipient_candidates(uid, class_id, page, q)
        return {'users': [view.profile(user) for user in users], 'page': page, 'total': total}

    @api.get('/api/users')
    @api.get('/api/admin/users')
    async def users(uid: Owner, page: Annotated[int, Query(ge=0, le=100000)] = 0):
        users, roles, page, total = await core.directory.users(uid, page, 50)
        async with db.read() as session:
            await core.permissions.owner(session, uid)
            by_user = {}
            members = set()
            for model in (ManagerAssignment, ReportRecipient, ClassMembership):
                rows = await session.execute(select(model.user_id, SchoolClass.name).join(SchoolClass, SchoolClass.id == model.class_id)
                                             .where(model.user_id.in_([item.id for item in users]), SchoolClass.is_active))
                for user_id, name in rows:
                    by_user.setdefault(user_id, set()).add(name)
                    if model is ClassMembership:
                        members.add(user_id)
        return {'users': [{**view.profile(item), 'roles': ['OWNER'] if item.telegram_id == uid else
                           (roles.get(item.id, []) + (['CLASS_MEMBER'] if item.id in members else []) or ['USER']),
                           'classes': sorted(by_user.get(item.id, set()))} for item in users], 'page': page, 'total': total}

    @api.post('/api/users')
    async def add_user(body: UserInput, uid: Owner):
        return view.profile(await core.directory.manage_user(uid, body.telegram_id))

    @api.get('/api/users/{target}')
    async def user_details(target: int, uid: Owner):
        user, managed, received = await core.directory.user_details(uid, target)
        if user is None:
            raise HTTPException(404, 'Пользователь недоступен.')
        async with db.read() as session:
            assignments = {row.class_id: row for row in await session.scalars(select(ManagerAssignment)
                                                                            .where(ManagerAssignment.user_id == user.id))}
            member = await session.get(ClassMembership, user.id)
            school = await session.get(SchoolClass, member.class_id) if member else None
        return {**view.profile(user), 'managed': [{**view.school_class(item, can_history=history),
                   'can_edit_timetable': assignments[item.id].can_edit_timetable,
                   'can_edit_history': assignments[item.id].can_edit_history,
                   'can_view_statistics': assignments[item.id].can_view_statistics,
                   'can_view_reports': assignments[item.id].can_view_reports,
                   'can_send_reports': assignments[item.id].can_send_reports} for item, history in managed],
                'received': [view.school_class(item) for item in received],
                'member': view.school_class(school) if school else None}

    @api.patch('/api/users/{target}')
    async def block_user(target: int, body: BlockInput, uid: Owner):
        return view.profile(await core.directory.manage_user(uid, target, body.blocked))

    @api.post('/api/users/{target}/access')
    @api.patch('/api/admin/users/{target}/roles')
    async def change_access(target: int, body: AdminAccessInput, uid: Owner):
        user, changed = await core.directory.access(uid, target, body.class_id, body.operation)
        if body.operation in {'recipient_add', 'recipient_remove'}:
            log.info('recipient_assignment committed operation=%s changed=%s', body.operation, changed)
        if changed and target != uid and body.operation.endswith('_add') and user.started_at and not user.blocked:
            try:
                async with telegram_sender() as bot:
                    await bot.send_message(user.telegram_id, 'Вам предоставлен доступ к Attendance. Откройте приложение из меню бота.',
                                           protect_content=True)
            except TelegramAPIError as exc:
                log.warning('Уведомление о доступе не доставлено пользователю %s (%s)', user.id, type(exc).__name__)
        return {'changed': changed}

    @api.get('/api/classes/{class_id}/schedule')
    async def schedule(class_id: int, uid: Owner):
        return view.schedule((await core.reports.schedule(uid, class_id))[1])

    @api.put('/api/classes/{class_id}/schedule')
    async def save_schedule(class_id: int, body: ScheduleInput, uid: Owner):
        return view.schedule(await core.reports.save_schedule(uid, class_id, body))

    @api.delete('/api/classes/{class_id}/schedule')
    async def delete_schedule(class_id: int, uid: Owner):
        return view.schedule(await core.reports.save_schedule(uid, class_id))

    @api.post('/api/classes/{class_id}/send')
    async def send_report(class_id: int, body: SendInput, uid: Owner):
        async with telegram_sender() as bot:
            return await core.reports.send_now(bot, uid, class_id, 'manual_' + body.request_id, body.day)

    @api.post('/api/reports/send-now')
    async def send_now(body: SendNowInput, uid: Account):
        async with telegram_sender() as bot:
            return await core.reports.send_now(bot, uid, body.class_id, 'manual_' + body.request_id)

    @api.get('/api/classes/{class_id}/reports/last-manual')
    async def last_manual_report(class_id: int, uid: Account):
        return {'sent_at': view.timestamp(await core.reports.manual_status(uid, class_id))}

    @api.get('/api/classes/{class_id}/deliveries')
    async def deliveries(class_id: int, uid: Owner, page: Annotated[int, Query(ge=0, le=100000)] = 0):
        items, page, total = await core.reports.history(uid, class_id, page, 20)
        return {'page': page, 'total': total, 'items': [
            {'id': item.id, 'day': item.report_date, 'telegram_id': telegram_id, 'status': item.status,
             'time': view.timestamp(item.sent_at or item.created_at), 'error': item.error_message,
             'sent_at': view.timestamp(item.sent_at), 'initiated_by': sender_id, 'initiated_by_name': sender_name,
             'telegram_message_id': item.telegram_message_id,
             'parts_sent': item.parts_sent, 'parts_total': item.parts_total,
             'kind': 'reminder' if item.dispatch_key.startswith('reminder_') else 'manual' if item.dispatch_key.startswith('manual_') else 'scheduled'}
            for item, telegram_id, sender_id, sender_name in items]}

    @api.get('/api/classes/{class_id}/report')
    async def report(class_id: int, uid: Account, day: str = ''):
        owner = core.permissions.is_owner(uid)
        async with db.read() as session:
            actor = await core.permissions.actor(session, uid)
            assignment = None if owner else await session.get(ManagerAssignment, (actor.id, class_id))
            if owner or (assignment and assignment.can_view_reports):
                chosen = day_or_today(day)
                if chosen > core.attendance.today():
                    raise UserError('Дата ещё не наступила.')
                _, school = await core.permissions.for_class(session, uid, class_id, allow_archived=owner)
                entries = [] if school.archived_on and chosen > school.archived_on else await roster(session, class_id, chosen)
                parts = detailed_report(school.name, chosen, entries, datetime.now(school_zone(config.zone)))
                return {'day': chosen, 'dates': [], 'parts': view.report_text(parts)}
        available = await core.reports.available(uid, class_id, limit=90)
        selected = parse_date(day) if day else available[0][0] if available else None
        parts = next((parts for date, parts in available if date == selected), [])
        return {'day': selected, 'dates': [date for date, _ in available], 'parts': view.report_text(parts)}

    @api.get('/api/classes/{class_id}/stats')
    async def stats(class_id: int, start: str, end: str, uid: Account):
        school, items = await core.attendance.period(uid, class_id, parse_date(start), parse_date(end), statistics=True)
        timeline = [{'day': day, 'counts': view.totals(counts(entries))} for day, entries in items.items()]
        combined = [sum(point['counts'][i] for point in timeline) for i in range(len(Status))]
        return {'class': view.school_class(school), 'counts': combined, 'timeline': timeline}

    @api.get('/api/admin/stats/comparison')
    async def comparison(start: str, end: str, uid: Owner):
        first, last = parse_date(start), parse_date(end)
        period_days(first, last, core.attendance.today())
        async with db.read() as session:
            available = await core.permissions.classes(session, uid)
        result = []
        for school in available:
            _, entries = await core.attendance.period(uid, school.id, first, last, owner_only=True)
            collected = [view.totals(counts(day)) for day in entries.values()]
            result.append({'class': view.school_class(school),
                           'counts': [sum(day[index] for day in collected) for index in range(len(Status))]})
        return result

    @api.get('/api/audit')
    @api.get('/api/admin/audit-logs')
    async def audit_log(uid: Owner, page: Annotated[int, Query(ge=0, le=100000)] = 0):
        rows, page, total = await core.directory.audit_page(uid, page, 20)
        return {'page': page, 'total': total, 'items': [view.audit_item(item, actor) for item, actor in rows]}

    @api.get('/api/admin/users/{target}/audit-logs')
    async def user_audit_log(target: int, uid: Owner, page: Annotated[int, Query(ge=0, le=100000)] = 0):
        user, _, _ = await core.directory.user_details(uid, target)
        if not user:
            raise HTTPException(404, 'Пользователь недоступен.')
        rows, page, total = await core.directory.audit_page(uid, page, 20, subject=user.id)
        return {'page': page, 'total': total, 'items': [view.audit_item(item, actor) for item, actor in rows]}

    @api.get('/api/settings')
    async def read_settings(uid: Owner):
        async with db.read() as session:
            return await school_settings(session, config.zone.key)

    @api.put('/api/settings')
    async def settings(body: SettingsInput, uid: Owner):
        name = bounded(body.school, 120)
        values = body.model_dump(exclude_none=True, exclude={'school'})
        if 'system_name' in values:
            values['system_name'] = bounded(values['system_name'], 40)
        if 'timezone' in values:
            try:
                values['timezone'] = ZoneInfo(values['timezone']).key
            except (ValueError, ZoneInfoNotFoundError):
                raise UserError('Укажите часовой пояс IANA, например Asia/Tashkent.') from None
        if 'school_days' in values:
            values['school_days'] = sorted(set(values['school_days']))
        for key in ('lesson_start', 'report_time'):
            if key in values:
                values[key] = time_value(values[key])
        async with db.write() as session:
            actor = await core.permissions.owner(session, uid)
            current = await school_settings(session, config.zone.key)
            current.update(values)
            hour, minute = map(int, current['lesson_start'].split(':'))
            if hour * 60 + minute + current['lesson_minutes'] >= 1440:
                raise UserError('Урок должен закончиться в тот же календарный день.')
            pref = await session.get(SchoolSettings, 1)
            if pref is None:
                pref = SchoolSettings(id=1)
                session.add(pref)
            pref.name = name
            pref.preferences = {**(pref.preferences or {}), **values}
            audit(session, actor, 'settings.updated', 'school')
        return {**current, 'school': name}

    def binary(name, media, data):
        return Response(data, media_type=media, headers={'Content-Disposition': f'attachment; filename="{name}"',
                                                          'Access-Control-Allow-Origin': '*',
                                                          'Access-Control-Expose-Headers': 'Content-Disposition, Content-Length'})

    def deliver_file(name, media, data, ticket):
        if len(data) > 49_000_000:
            raise UserError('Файл слишком большой. Сократите период или сделайте копию на сервере.')
        if not ticket:
            return binary(name, media, data)
        for key, (expires, *_rest) in list(tickets.items()):
            if expires <= monotonic():
                del tickets[key]
        if len(tickets) >= 3:
            raise HTTPException(429, 'Подождите завершения предыдущих загрузок.')
        key = secrets.token_urlsafe(24)
        tickets[key] = (monotonic() + 90, name, media, data)
        asyncio.get_running_loop().call_later(90, tickets.pop, key, None)
        return {'path': '/api/downloads/' + key, 'name': name}

    @api.get('/api/classes/{class_id}/export')
    async def export(class_id: int, uid: Owner, start: str, end: str, ticket: bool = False):
        school, entries = await core.attendance.period(uid, class_id, parse_date(start), parse_date(end), owner_only=True)
        data = await asyncio.to_thread(excel_report, school.name, entries)
        async with db.write() as session:
            actor = await core.permissions.owner(session, uid)
            audit(session, actor, 'statistics.exported', 'class', class_id)
        return deliver_file(f'attendance-{class_id}.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', data, ticket)

    @api.get('/api/backup')
    async def backup(uid: Owner, ticket: bool = False):
        data = await core.directory.backup(uid)
        return deliver_file(f'attendance-{core.attendance.today()}.sqlite3', 'application/octet-stream', data, ticket)

    @api.api_route('/api/downloads/{key}', methods=['GET', 'HEAD'])
    async def download(key: str):
        expires, *file = tickets.get(key, (0,))
        if expires <= monotonic():
            tickets.pop(key, None)
            raise HTTPException(404, 'Срок ссылки истёк. Создайте файл заново.')
        return binary(*file)

    if (dist / 'assets').is_dir():
        api.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

    @api.get('/{path:path}')
    async def frontend(path: str):
        if path == 'api' or path.startswith('api/'):
            raise HTTPException(404, 'Такого запроса нет.')
        index = dist / 'index.html'
        if not index.is_file():
            raise HTTPException(503, 'Соберите интерфейс или запустите Vite.')
        if desktop is not None:
            html = index.read_text(encoding='utf-8').replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>', '')
            return HTMLResponse(html, headers={'Cache-Control': 'no-cache'})
        return FileResponse(index, headers={'Cache-Control': 'no-cache'})

    return api
