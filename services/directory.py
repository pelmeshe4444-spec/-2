import asyncio
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import func, select, update

from database.models import (
    AuditLog, Enrollment, ManagerAssignment, ReportDelivery, ReportRecipient, ReportSchedule, SchoolClass,
    Student, User, UserRole, utc_now,
)
from services.permissions import UserError, audit


def normalized(value: str) -> str:
    return ' '.join(value.split()).casefold()


def name_key(last: str, first: str) -> str:
    return normalized(f'{last} {first}')


def sort_student(student):
    return normalized(student.name).replace('ё', 'е'), student.id


def bounded(text: str, max_length: int) -> str:
    text = ' '.join(text.split())
    if not text or len(text) > max_length or not text.isprintable():
        raise UserError(f'Введите от 1 до {max_length} символов.')
    return text


def parse_students(value: str, many: bool) -> list[tuple[str, str]]:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines or len(lines) > (100 if many else 1):
        raise UserError('Отправьте от 1 до 100 строк.' if many else 'Введите фамилию и имя одной строкой.')
    result = []
    for index, line in enumerate(lines, 1):
        parts = line.split()
        if len(parts) != 2 or any(
            len(part) > 48 or not part[0].isalpha() or not part[-1].isalpha()
            or any(not ch.isalpha() and ch not in "-'’" for ch in part)
            for part in parts
        ):
            raise UserError(f'Строка {index}. Введите фамилию и имя через пробел, до 48 букв в каждой части.')
        result.append((parts[0], parts[1]))
    return result


class Directory:
    def __init__(self, db, permissions, zone):
        self.db, self.permissions, self.zone = db, permissions, zone

    def today(self):
        return datetime.now(self.zone).date()

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
            session.add(ReportSchedule(class_id=school_class.id, timezone=self.zone.key))
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
            for last, first in names:
                key = name_key(last, first)
                if key in existing:
                    duplicates.append(f'{last} {first}')
                    continue
                existing.add(key)
                added.append(f'{last} {first}')
                if not preview:
                    student = Student(last_name=last, first_name=first, class_id=class_id, active_name_key=key)
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
            last, first = name or (student.last_name, student.first_name)
            key = name_key(last, first)
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
            student.class_id, student.last_name, student.first_name = class_id, last, first
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
            key = name_key(student.last_name, student.first_name)
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

    async def update_class(self, telegram_id, class_id, *, name=None, archive=False):
        async with self.db.write() as session:
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
            audit(session, actor, 'class.archived' if archive else 'class.updated', 'class', class_id)
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
            if operation not in {'manager_add', 'manager_remove', 'recipient_add', 'recipient_remove', 'history_on', 'history_off'}:
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
            elif operation in {'history_on', 'history_off'}:
                assignment.can_view_history = operation == 'history_on'
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

    async def audit_page(self, telegram_id, page, size):
        async with self.db.read() as session:
            await self.permissions.owner(session, telegram_id)
            count = await session.scalar(select(func.count(AuditLog.id)))
            page = min(page, max(0, (count - 1) // size))
            query = (select(AuditLog, User.telegram_id).outerjoin(User, AuditLog.actor_id == User.id)
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
