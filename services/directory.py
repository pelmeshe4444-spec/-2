import asyncio
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unicodedata import category

from sqlalchemy import func, select, update

from database.models import (
    AuditLog, Enrollment, ManagerAssignment, ReportDelivery, ReportRecipient, ReportSchedule, SchoolClass,
    Student, User, UserRole, utc_now,
)
from services.permissions import UserError, audit
from services.school_settings import school_settings, school_zone


def normalized(value: str) -> str:
    return ' '.join(value.split()).casefold()


def sort_student(student):
    return normalized(student.name).replace('ё', 'е'), student.id


def bounded(text: str, max_length: int) -> str:
    text = ' '.join(text.split())
    if not text or len(text) > max_length or not text.isprintable():
        raise UserError(f'Введите от 1 до {max_length} символов.')
    return text


MAX_STUDENT_NAME = 255


def parse_students(value: str, many: bool) -> list[str]:
    lines = [' '.join(line.split()) for line in value.splitlines() if line.strip()]
    if not lines or len(lines) > (100 if many else 1):
        raise UserError('Отправьте от 1 до 100 строк.' if many else 'Введите полное имя ученика одной строкой.')
    for index, line in enumerate(lines, 1):
        if len(line) > MAX_STUDENT_NAME or not any(ch.isalpha() for ch in line) or any(
            not (ch.isalpha() or category(ch).startswith('M') or ch in " -‐‑'’‘ʻʼ") for ch in line
        ):
            raise UserError(f'Строка {index}. Введите до {MAX_STUDENT_NAME} символов. Допустимы буквы, пробелы, дефисы и апострофы.')
    return lines


class Directory:
    def __init__(self, db, permissions, zone):
        self.db, self.permissions, self.zone = db, permissions, zone

    def today(self):
        return datetime.now(school_zone(self.zone)).date()

    async def register(self, telegram_id, username, full_name, *, started=True):
        async with self.db.write() as session:
            user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
            if user is None:
                user = User(telegram_id=telegram_id)
                session.add(user)
                await session.flush()
            first_start = started and user.started_at is None
            new_username = username[:64] if username else None
            new_name = full_name[:160] if full_name else None
            if first_start:
                user.started_at = utc_now()
                audit(session, user, 'user.started', 'user', user.id)
            elif (user.username, user.full_name) != (new_username, new_name):
                audit(session, user, 'user.profile_updated', 'user', user.id)
            user.username, user.full_name = new_username, new_name
            return first_start

    async def add_class(self, telegram_id, value):
        name = bounded(value, 32)
        async with self.db.write() as session:
            actor = await self.permissions.owner(session, telegram_id)
            if await session.scalar(select(SchoolClass.id).where(SchoolClass.name_key == normalized(name))):
                raise UserError('Класс с таким названием уже существует.')
            school_class = SchoolClass(name=name, name_key=normalized(name))
            session.add(school_class)
            await session.flush()
            defaults = await school_settings(session, self.zone.key)
            session.add(ReportSchedule(class_id=school_class.id, timezone=defaults['timezone'],
                                       time=defaults['report_time'], weekdays=''.join(map(str, defaults['school_days']))))
            audit(session, actor, 'class.added', 'class', school_class.id)
            return school_class

    async def owner_class(self, session, telegram_id, class_id):
        await self.permissions.owner(session, telegram_id)
        return await self.permissions.for_class(session, telegram_id, class_id)

    async def students(self, telegram_id, class_id, query='', include_archived=False):
        query = normalized(query)
        async with self.db.read() as session:
            await self.permissions.owner(session, telegram_id)
            _, school_class = await self.permissions.for_class(session, telegram_id, class_id, allow_archived=True)
            statement = select(Student).where(Student.class_id == class_id)
            if not include_archived:
                statement = statement.where(Student.is_active)
            students = await session.scalars(statement)
            return school_class, sorted((s for s in students if query in normalized(s.name)), key=sort_student)

    async def student(self, telegram_id, student_id):
        async with self.db.read() as session:
            await self.permissions.owner(session, telegram_id)
            student = await session.get(Student, student_id)
            if student is None:
                raise UserError('Ученик недоступен.')
            return student, await session.get(SchoolClass, student.class_id)

    async def add_students(self, telegram_id, class_id, names, *, preview=False):
        context = self.db.read if preview else self.db.write
        async with context() as session:
            actor, _ = await self.owner_class(session, telegram_id, class_id)
            existing = set(await session.scalars(select(Student.active_name_key).where(
                Student.class_id == class_id, Student.is_active)))
            added, duplicates = [], []
            for name in names:
                key = normalized(name)
                if key in existing:
                    duplicates.append(name)
                    continue
                existing.add(key)
                added.append(name)
                if not preview:
                    student = Student(full_name=name, class_id=class_id, active_name_key=key)
                    session.add(student)
                    await session.flush()
                    session.add(Enrollment(student_id=student.id, class_id=class_id, starts_on=self.today()))
                    audit(session, actor, 'student.added', 'student', student.id, f'class={class_id}')
            return added, duplicates

    async def edit_student(self, telegram_id, student_id, *, name=None, new_class=None, archive=False):
        async with self.db.write() as session:
            actor = await self.permissions.owner(session, telegram_id)
            student = await session.get(Student, student_id)
            if student is None or not student.is_active:
                raise UserError('Ученик уже в архиве или недоступен.')
            class_id = student.class_id if new_class is None else new_class
            await self.owner_class(session, telegram_id, class_id)
            full_name = name if name is not None else student.name
            key = normalized(full_name)
            other = await session.scalar(select(Student.id).where(
                Student.class_id == class_id, Student.active_name_key == key, Student.id != student_id))
            if other and not archive:
                raise UserError('В этом классе уже есть ученик с таким именем.')
            if archive or student.class_id != class_id:
                today = self.today()
                effective = today + timedelta(days=1)
                latest = await session.scalar(select(Enrollment).where(Enrollment.student_id == student_id)
                                              .order_by(Enrollment.starts_on.desc()).limit(1))
                if archive:
                    if latest.starts_on > today:
                        await session.delete(latest)
                        latest = await session.scalar(select(Enrollment).where(
                            Enrollment.student_id == student_id, Enrollment.starts_on <= today)
                            .order_by(Enrollment.starts_on.desc()).limit(1))
                    latest.ends_before = today
                    class_id = latest.class_id
                elif latest.starts_on == effective:
                    latest.class_id = class_id
                else:
                    latest.ends_before = effective
                    session.add(Enrollment(student_id=student_id, class_id=class_id, starts_on=effective))
            student.class_id, student.full_name = class_id, full_name
            student.is_active = not archive
            student.active_name_key = None if archive else key
            audit(session, actor, 'student.archived' if archive else 'student.updated', 'student', student_id,
                  f'class={class_id}')
            return student

    async def restore_student(self, telegram_id, student_id):
        async with self.db.write() as session:
            actor = await self.permissions.owner(session, telegram_id)
            student = await session.get(Student, student_id)
            if student is None:
                raise UserError('Ученик недоступен.')
            await self.owner_class(session, telegram_id, student.class_id)
            if student.is_active:
                return student
            key = normalized(student.name)
            if await session.scalar(select(Student.id).where(Student.class_id == student.class_id,
                                                              Student.active_name_key == key)):
                raise UserError('В этом классе уже есть ученик с таким именем.')
            today = self.today()
            previous = await session.scalar(select(Enrollment).where(Enrollment.student_id == student_id)
                                            .order_by(Enrollment.starts_on.desc()).limit(1))
            if previous and previous.ends_before == today and previous.class_id == student.class_id:
                previous.ends_before = None
            else:
                session.add(Enrollment(student_id=student.id, class_id=student.class_id, starts_on=today))
            student.is_active, student.active_name_key = True, key
            audit(session, actor, 'student.restored', 'student', student_id, f'class={student.class_id}')
            return student

    async def update_class(self, telegram_id, class_id, *, name=None, archive=False, restore=False):
        async with self.db.write() as session:
            if restore:
                actor, school_class = await self.permissions.for_class(session, telegram_id, class_id, allow_archived=True)
                await self.permissions.owner(session, telegram_id)
            else:
                actor, school_class = await self.owner_class(session, telegram_id, class_id)
            if name is not None:
                name = bounded(name, 32)
                key = normalized(name)
                duplicate = await session.scalar(select(SchoolClass.id).where(
                    SchoolClass.name_key == key, SchoolClass.id != class_id))
                if duplicate:
                    raise UserError('Класс с таким названием уже существует.')
                school_class.name, school_class.name_key = name, key
            if archive:
                school_class.is_active, school_class.archived_on = False, self.today()
                schedule = await session.scalar(select(ReportSchedule).where(ReportSchedule.class_id == class_id))
                schedule.is_enabled = False
            if restore:
                school_class.is_active, school_class.archived_on = True, None
            action = 'class.restored' if restore else 'class.archived' if archive else 'class.updated'
            audit(session, actor, action, 'class', class_id)
            return school_class

    async def manage_user(self, telegram_id, target_id, blocked=None):
        async with self.db.write() as session:
            actor = await self.permissions.owner(session, telegram_id)
            if not 0 < target_id < 2**52 or target_id == telegram_id:
                raise UserError('Укажите Telegram ID другого пользователя.')
            target = await session.scalar(select(User).where(User.telegram_id == target_id))
            if blocked is None:
                if target is None:
                    target = User(telegram_id=target_id)
                    session.add(target)
                    await session.flush()
                    audit(session, actor, 'user.added', 'user', target.id)
            elif target is None:
                raise UserError('Пользователь недоступен.')
            elif blocked != target.blocked:
                target.blocked = blocked
                audit(session, actor, 'user.blocked' if blocked else 'user.unblocked', 'user', target.id)
            return target

    async def users(self, telegram_id, page, page_size, *, started_only=False, role=None):
        async with self.db.read() as session:
            await self.permissions.owner(session, telegram_id)
            query = select(User)
            if started_only:
                query = query.where(User.started_at.is_not(None), User.telegram_id != self.permissions.owner_id)
            if role:
                query = query.join(UserRole, UserRole.user_id == User.id).where(UserRole.role == role)
            count = await session.scalar(select(func.count()).select_from(query.subquery()))
            page = min(page, max(0, (count - 1) // page_size))
            users = list(await session.scalars(query.order_by(User.id).offset(page * page_size).limit(page_size)))
            roles = await session.execute(select(UserRole.user_id, UserRole.role).where(
                UserRole.user_id.in_([user.id for user in users])))
            role_map = {}
            for uid, role in roles:
                role_map.setdefault(uid, []).append(role)
            return users, role_map, page, count

    async def user_details(self, telegram_id, target_id):
        async with self.db.read() as session:
            await self.permissions.owner(session, telegram_id)
            user = await session.scalar(select(User).where(User.telegram_id == target_id))
            if user is None:
                return None, [], []
            managers = list(await session.execute(select(SchoolClass, ManagerAssignment.can_view_history)
                            .join(ManagerAssignment, ManagerAssignment.class_id == SchoolClass.id)
                            .where(ManagerAssignment.user_id == user.id).order_by(SchoolClass.name_key)))
            recipients = list(await session.scalars(select(SchoolClass)
                              .join(ReportRecipient, ReportRecipient.class_id == SchoolClass.id)
                              .where(ReportRecipient.user_id == user.id).order_by(SchoolClass.name_key)))
            return user, managers, recipients

    async def access(self, telegram_id, target_id, class_id, operation):
        async with self.db.write() as session:
            actor, _ = await self.owner_class(session, telegram_id, class_id)
            permission_fields = {'history': 'can_view_history', 'correction': 'can_edit_history',
                                 'statistics': 'can_view_statistics', 'timetable': 'can_edit_timetable',
                                 'report_view': 'can_view_reports', 'report_send': 'can_send_reports'}
            permission, _, setting = operation.rpartition('_')
            permission_field = permission_fields.get(permission) if setting in ('on', 'off') else None
            if not permission_field and operation not in {'manager_add', 'manager_remove', 'recipient_add', 'recipient_remove'}:
                raise UserError('Действие недоступно.')
            recipient = operation.startswith('recipient_')
            if not 0 < target_id < 2**52 or (self.permissions.is_owner(target_id) and not recipient):
                raise UserError('Укажите корректный Telegram ID. Права владельца задаются в .env.')
            target = await session.scalar(select(User).where(User.telegram_id == target_id))
            if operation == 'recipient_add' and (target is None or target.started_at is None):
                raise UserError('Получатель должен сначала запустить бота командой /start.')
            if target is None:
                if operation != 'manager_add':
                    raise UserError('Назначение для этого пользователя не найдено.')
                target = User(telegram_id=target_id)
                session.add(target)
                await session.flush()
            model = ReportRecipient if recipient else ManagerAssignment
            role = 'REPORT_RECIPIENT' if recipient else 'MANAGER'
            assignment = await session.get(model, (target.id, class_id))
            role_row = await session.get(UserRole, (target.id, role))
            if operation.endswith('_add'):
                if assignment is not None:
                    return target, False
                session.add(model(user_id=target.id, class_id=class_id))
                if role_row is None:
                    session.add(UserRole(user_id=target.id, role=role))
            elif assignment is None:
                raise UserError('Назначение для этого класса не найдено.')
            elif operation.endswith('_remove'):
                await session.delete(assignment)
                if recipient:
                    schedules = select(ReportSchedule.id).where(ReportSchedule.class_id == class_id)
                    await session.execute(update(ReportDelivery).where(ReportDelivery.recipient_id == target.id,
                                          ReportDelivery.schedule_id.in_(schedules)).values(body=None))
                await session.flush()
                remains = await session.scalar(select(model.user_id).where(model.user_id == target.id).limit(1))
                if remains is None and role_row is not None:
                    await session.delete(role_row)
            elif permission_field:
                enabled = setting == 'on'
                if getattr(assignment, permission_field) == enabled:
                    return target, False
                setattr(assignment, permission_field, enabled)
            else:
                raise UserError('Действие недоступно.')
            audit(session, actor, f'access.{operation}', 'user', target.id, f'class={class_id}')
            return target, True

    async def assignments(self, telegram_id, class_id, recipient):
        model = ReportRecipient if recipient else ManagerAssignment
        async with self.db.read() as session:
            _, school_class = await self.owner_class(session, telegram_id, class_id)
            rows = await session.execute(select(User, model).join(model, model.user_id == User.id)
                                         .where(model.class_id == class_id).order_by(User.id))
            return school_class, list(rows)

    async def audit_page(self, telegram_id, page, size, *, subject=None):
        async with self.db.read() as session:
            await self.permissions.owner(session, telegram_id)
            predicate = (AuditLog.entity_type == 'user', AuditLog.entity_id == subject) if subject is not None else ()
            count = await session.scalar(select(func.count(AuditLog.id)).where(*predicate))
            page = min(page, max(0, (count - 1) // size))
            query = (select(AuditLog, User.telegram_id).outerjoin(User, AuditLog.actor_id == User.id).where(*predicate)
                     .order_by(AuditLog.id.desc()).offset(page * size).limit(size))
            return list(await session.execute(query)), page, count

    async def backup(self, telegram_id):
        if self.db.engine.dialect.name != 'sqlite':
            raise UserError('Резервное копирование в боте доступно для SQLite.')
        async with self.db.write() as session:
            actor = await self.permissions.owner(session, telegram_id)
            audit(session, actor, 'database.backup', 'database')
        source = Path(self.db.engine.url.database).resolve()
        return await asyncio.to_thread(sqlite_backup, source)


def sqlite_backup(source):
    with TemporaryDirectory(dir=source.parent, prefix='attendance-backup-') as folder:
        backup = Path(folder) / 'attendance.sqlite3'
        with closing(sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True)) as src, closing(sqlite3.connect(backup)) as dest:
            src.backup(dest)
        return backup.read_bytes()
