import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Annotated

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from backend import presentation as view
from backend.auth import InvalidInitData, TelegramAuth
from backend.schemas import (AccessInput, BlockInput, ClassInput, MarkInput, NamesInput, ScheduleInput,
                             SendInput, SettingsInput, StudentInput, UserInput)
from backend.school_routes import school_routes
from config import ROOT
from database.models import AttendanceChange, ClassMembership, ManagerAssignment, ReportRecipient, SchoolClass, SchoolSettings, User
from services.application import AttendanceApplication
from services.attendance import Status, counts, parse_date, roster
from services.directory import bounded, parse_students
from services.permissions import Conflict, Forbidden, UserError, audit
from services.reports import detailed_report, excel_report


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
        response = await call_next(request)
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
            school = await session.get(SchoolSettings, 1)
            member = await session.get(ClassMembership, user.id)
            member_class = await session.get(SchoolClass, member.class_id) if member and not user.blocked else None
            member_class = member_class if member_class and member_class.is_active else None
        roles = ['OWNER'] if owner else [role for role, classes in (('MANAGER', managed), ('REPORT_RECIPIENT', received)) if classes]
        if member_class and not owner:
            roles.append('CLASS_MEMBER')
        return {'user': view.profile(user), 'roles': roles or ['USER'], 'school': school.name if school and roles else 'Школа',
                'today': core.attendance.today(), 'timezone': config.zone.key, 'sqlite': db.engine.dialect.name == 'sqlite',
                'managed': [view.school_class(item, can_history=item.id in history) for item in managed],
                'reports': [view.school_class(item) for item in received],
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

    @api.get('/api/classes/{class_id}/access')
    async def class_access(class_id: int, uid: Owner):
        return await team(uid, class_id)

    @api.get('/api/classes/{class_id}/students')
    async def students(class_id: int, uid: Owner):
        _, students = await core.directory.students(uid, class_id, include_archived=True)
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
        name = parse_students(body.name, False)[0] if body.name is not None else None
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
            _, school = await core.attendance.scope(session, uid, class_id, day)
            entries = [] if school.archived_on and day > school.archived_on else await roster(session, class_id, day)
            mark_users = {entry.mark.marked_by for entry in entries if entry.mark}
            authors = {user.id: user.full_name or user.username or 'Пользователь Telegram' for user in
                       await session.scalars(select(User).where(User.id.in_(mark_users)))}
        writable = school.is_active and (core.permissions.is_owner(uid) or day == core.attendance.today())
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

    @api.get('/api/users')
    async def users(uid: Owner, page: Annotated[int, Query(ge=0, le=100000)] = 0):
        users, roles, page, total = await core.directory.users(uid, page, 50)
        async with db.read() as session:
            await core.permissions.owner(session, uid)
            by_user = {}
            for model in (ManagerAssignment, ReportRecipient):
                rows = await session.execute(select(model.user_id, SchoolClass.name).join(SchoolClass, SchoolClass.id == model.class_id)
                                             .where(model.user_id.in_([item.id for item in users]), SchoolClass.is_active))
                for user_id, name in rows:
                    by_user.setdefault(user_id, set()).add(name)
        return {'users': [{**view.profile(item), 'roles': ['OWNER'] if item.telegram_id == uid else roles.get(item.id, ['USER']),
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
            editors = set(await session.scalars(select(ManagerAssignment.class_id).where(
                ManagerAssignment.user_id == user.id, ManagerAssignment.can_edit_timetable)))
        return {**view.profile(user), 'managed': [{**view.school_class(item, can_history=history), 'can_edit_timetable': item.id in editors} for item, history in managed],
                'received': [view.school_class(item) for item in received]}

    @api.patch('/api/users/{target}')
    async def block_user(target: int, body: BlockInput, uid: Owner):
        return view.profile(await core.directory.manage_user(uid, target, body.blocked))

    @api.post('/api/users/{target}/access')
    async def change_access(target: int, body: AccessInput, uid: Owner):
        user, changed = await core.directory.access(uid, target, body.class_id, body.operation)
        if changed and body.operation.endswith('_add') and user.started_at and not user.blocked:
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
        _, schedule = await core.reports.schedule(uid, class_id)
        day = core.attendance.today()
        key = 'manual_' + body.request_id
        async with telegram_sender() as bot:
            await core.reports.dispatch(bot, schedule.id, day, key, manual_actor=uid)
        return await core.reports.manual_result(uid, class_id, schedule.id, day, key)

    @api.get('/api/classes/{class_id}/deliveries')
    async def deliveries(class_id: int, uid: Owner, page: Annotated[int, Query(ge=0, le=100000)] = 0):
        items, page, total = await core.reports.history(uid, class_id, page, 20)
        return {'page': page, 'total': total, 'items': [
            {'id': item.id, 'day': item.report_date, 'telegram_id': telegram_id, 'status': item.status,
             'time': view.timestamp(item.sent_at or item.created_at), 'error': item.error_message,
             'parts_sent': item.parts_sent, 'parts_total': item.parts_total,
             'kind': 'reminder' if item.dispatch_key.startswith('reminder_') else 'manual' if item.dispatch_key.startswith('manual_') else 'scheduled'}
            for item, telegram_id in items]}

    @api.get('/api/classes/{class_id}/report')
    async def report(class_id: int, uid: Account, day: str = ''):
        if core.permissions.is_owner(uid):
            chosen = day_or_today(day)
            school, entries = await core.attendance.daily(uid, class_id, chosen)
            parts = detailed_report(school.name, chosen, entries, datetime.now(config.zone))
            return {'day': chosen, 'dates': [], 'parts': view.report_text(parts)}
        available = await core.reports.available(uid, class_id, limit=90)
        selected = parse_date(day) if day else available[0][0] if available else None
        parts = next((parts for date, parts in available if date == selected), [])
        return {'day': selected, 'dates': [date for date, _ in available], 'parts': view.report_text(parts)}

    @api.get('/api/classes/{class_id}/stats')
    async def stats(class_id: int, start: str, end: str, uid: Owner):
        school, items = await core.attendance.period(uid, class_id, parse_date(start), parse_date(end), owner_only=True)
        timeline = [{'day': day, 'counts': view.totals(counts(entries))} for day, entries in items.items()]
        combined = [sum(point['counts'][i] for point in timeline) for i in range(len(Status))]
        return {'class': view.school_class(school), 'counts': combined, 'timeline': timeline}

    @api.get('/api/audit')
    async def audit_log(uid: Owner, page: Annotated[int, Query(ge=0, le=100000)] = 0):
        rows, page, total = await core.directory.audit_page(uid, page, 20)
        return {'page': page, 'total': total, 'items': [
            {'id': item.id, 'action': item.action, 'by': telegram_id, 'time': view.timestamp(item.timestamp),
             'entity': item.entity_type, 'entity_id': item.entity_id, 'details': item.details} for item, telegram_id in rows]}

    @api.put('/api/settings')
    async def settings(body: SettingsInput, uid: Owner):
        name = bounded(body.school, 120)
        async with db.write() as session:
            actor = await core.permissions.owner(session, uid)
            pref = await session.get(SchoolSettings, 1)
            if pref is None:
                session.add(SchoolSettings(id=1, name=name))
            else:
                pref.name = name
            audit(session, actor, 'settings.updated', 'school')
        return {'school': name}

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
