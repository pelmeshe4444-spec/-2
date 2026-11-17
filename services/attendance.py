from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntEnum

from sqlalchemy import and_, or_, select

from database.models import Attendance, AttendanceChange, Enrollment, SchoolClass, Student, utc_now
from services.directory import bounded, sort_student
from services.permissions import Conflict, Forbidden, UserError, audit
from services.school_settings import school_zone


class Status(IntEnum):
    UNMARKED = 0
    PRESENT = 1
    SICK = 2
    EXCUSED = 3
    ABSENT = 4

    @property
    def allows_reason(self):
        return self in (Status.SICK, Status.EXCUSED, Status.ABSENT)


ICONS = {Status.UNMARKED: '⏳', Status.PRESENT: '✅', Status.SICK: '🤒', Status.EXCUSED: '📝', Status.ABSENT: '❌'}
LABELS = {
    Status.UNMARKED: 'Не отмечен', Status.PRESENT: 'Присутствует', Status.SICK: 'Болеет',
    Status.EXCUSED: 'По уважительной причине', Status.ABSENT: 'Отсутствует без причины',
}
REPORT_LABELS = {
    Status.PRESENT: 'Присутствуют', Status.SICK: 'Болеют', Status.EXCUSED: 'По уважительной причине',
    Status.ABSENT: 'Отсутствуют без причины', Status.UNMARKED: 'Не отмечены',
}


def parse_date(value):
    for pattern in ('%d.%m.%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except ValueError:
            continue
    raise UserError('Введите дату в формате ДД.ММ.ГГГГ.')


def period_days(start, end, today):
    if start > end or end > today or (end - start).days >= 366:
        raise UserError('Укажите период до 366 дней, без будущих дат.')
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


@dataclass(frozen=True)
class Entry:
    student: Student
    mark: Attendance | None

    @property
    def status(self):
        return Status(self.mark.status) if self.mark else Status.UNMARKED

    @property
    def reason(self):
        return self.mark.reason if self.mark else None


def counts(entries):
    return Counter(entry.status for entry in entries)


def enrolled_on(day):
    return and_(Enrollment.starts_on <= day, or_(Enrollment.ends_before.is_(None), Enrollment.ends_before > day))


async def roster(session, class_id, day):
    query = (select(Student, Attendance).select_from(Enrollment)
             .join(Student, Student.id == Enrollment.student_id)
             .outerjoin(Attendance, and_(Attendance.student_id == Student.id, Attendance.date == day))
             .where(Enrollment.class_id == class_id, enrolled_on(day)))
    return [Entry(student, mark) for student, mark in sorted(await session.execute(query),
                                                            key=lambda row: sort_student(row[0]))]


class AttendanceService:
    def __init__(self, db, permissions, zone):
        self.db, self.permissions, self.zone = db, permissions, zone

    def today(self):
        return datetime.now(school_zone(self.zone)).date()

    def local(self, stamp):
        return stamp.replace(tzinfo=UTC).astimezone(school_zone(self.zone))

    async def scope(self, session, telegram_id, class_id, day, *, writing=False):
        today = self.today()
        if day > today:
            raise UserError('Дата ещё не наступила.')
        return await self.permissions.for_class(session, telegram_id, class_id, history=day < today,
                                                correction=writing and day < today,
                                                allow_archived=not writing and self.permissions.is_owner(telegram_id))

    async def daily(self, telegram_id, class_id, day):
        async with self.db.read() as session:
            _, school_class = await self.scope(session, telegram_id, class_id, day)
            if school_class.archived_on and day > school_class.archived_on:
                return school_class, []
            return school_class, await roster(session, class_id, day)

    async def _entry(self, session, class_id, day, student_id):
        query = (select(Student, Attendance).select_from(Enrollment).join(Student, Student.id == Enrollment.student_id)
                 .outerjoin(Attendance, and_(Attendance.student_id == Student.id, Attendance.date == day))
                 .where(Enrollment.class_id == class_id, Enrollment.student_id == student_id, enrolled_on(day)))
        row = (await session.execute(query)).one_or_none()
        if row is None:
            raise UserError('Ученик не числится в этом классе на выбранную дату.')
        return Entry(*row)

    async def entry(self, telegram_id, class_id, day, student_id):
        async with self.db.read() as session:
            _, school_class = await self.scope(session, telegram_id, class_id, day)
            return school_class, await self._entry(session, class_id, day, student_id)

    async def mark(self, telegram_id, class_id, day, student_id, status, *, reason=None, expected=None):
        status = Status(status)
        if reason is not None:
            if not status.allows_reason:
                raise UserError('Комментарий доступен для статусов отсутствия.')
            reason = bounded(reason, 300)
        async with self.db.write() as session:
            actor, _ = await self.scope(session, telegram_id, class_id, day, writing=True)
            entry = await self._entry(session, class_id, day, student_id)
            mark = entry.mark
            version = mark.updated_at.isoformat() if mark else ''
            if expected is not None and version != expected:
                raise Conflict('Отметка уже изменилась. Проверьте новое значение и повторите действие.')
            if mark is None and status == Status.UNMARKED:
                return entry
            if entry.status == status and (reason == entry.reason or (expected is None and reason is None)):
                return entry
            previous = entry.status
            old_reason = entry.reason
            if mark is None:
                mark = Attendance(student_id=student_id, date=day)
                session.add(mark)
            mark.status, mark.reason, mark.marked_by, mark.updated_at = status, reason, actor.id, utc_now()
            session.add(AttendanceChange(student_id=student_id, class_id=class_id, date=day, actor_id=actor.id,
                                        before_status=previous, after_status=status, before_reason=old_reason, after_reason=reason))
            audit(session, actor, 'attendance.marked', 'student', student_id,
                  f'class={class_id} date={day} status={int(previous)}→{int(status)}')
            return Entry(entry.student, mark)

    async def mark_all(self, telegram_id, class_id, day):
        async with self.db.write() as session:
            actor, _ = await self.scope(session, telegram_id, class_id, day, writing=True)
            changed = 0
            for entry in await roster(session, class_id, day):
                if entry.status != Status.UNMARKED:
                    continue
                mark = entry.mark
                if mark is None:
                    mark = Attendance(student_id=entry.student.id, date=day)
                    session.add(mark)
                mark.status, mark.reason, mark.marked_by, mark.updated_at = Status.PRESENT, None, actor.id, utc_now()
                session.add(AttendanceChange(student_id=entry.student.id, class_id=class_id, date=day, actor_id=actor.id,
                                            before_status=Status.UNMARKED, after_status=Status.PRESENT))
                audit(session, actor, 'attendance.marked', 'student', entry.student.id,
                      f'class={class_id} date={day} status=0→1')
                changed += 1
            if changed:
                audit(session, actor, 'attendance.bulk', 'class', class_id, f'date={day} count={changed}')
            return changed

    async def finish(self, telegram_id, class_id, day):
        async with self.db.write() as session:
            actor, school_class = await self.scope(session, telegram_id, class_id, day, writing=True)
            entries = await roster(session, class_id, day)
            audit(session, actor, 'attendance.finished', 'class', class_id, f'date={day} unmarked={counts(entries)[Status.UNMARKED]}')
            return school_class, entries

    async def pupil_history(self, telegram_id, student_id, start, end):
        days = period_days(start, end, self.today())
        async with self.db.read() as session:
            await self.permissions.owner(session, telegram_id)
            student = await session.get(Student, student_id)
            if student is None:
                raise UserError('Ученик недоступен.')
            enrollment_query = (select(Enrollment, SchoolClass.name).join(SchoolClass, SchoolClass.id == Enrollment.class_id)
                                .where(Enrollment.student_id == student_id, Enrollment.starts_on <= end,
                                       or_(Enrollment.ends_before.is_(None), Enrollment.ends_before >= start))
                                .order_by(Enrollment.starts_on.desc()))
            enrollments = list(await session.execute(enrollment_query))
            marks = {row.date: row for row in await session.scalars(select(Attendance).where(
                Attendance.student_id == student_id, Attendance.date.between(start, end)))}
            items = []
            for day in reversed(days):
                for enrollment, class_name in enrollments:
                    inside = enrollment.ends_before is None or day < enrollment.ends_before
                    archived_mark = day == enrollment.ends_before and day in marks
                    if enrollment.starts_on <= day and (inside or archived_mark):
                        items.append((day, class_name, Entry(student, marks.get(day))))
                        break
            return student, items

    async def period(self, telegram_id, class_id, start, end, *, student_id=None, owner_only=False, statistics=False):
        days = period_days(start, end, self.today())
        async with self.db.read() as session:
            if owner_only:
                await self.permissions.owner(session, telegram_id)
            if statistics:
                _, school_class = await self.permissions.for_class(session, telegram_id, class_id, statistics=True,
                                    allow_archived=self.permissions.is_owner(telegram_id))
            else:
                _, school_class = await self.scope(session, telegram_id, class_id, start)
            enrollment_query = (select(Enrollment, Student).join(Student, Student.id == Enrollment.student_id)
                                .where(Enrollment.class_id == class_id, Enrollment.starts_on <= end,
                                       or_(Enrollment.ends_before.is_(None), Enrollment.ends_before > start)))
            if student_id is not None:
                enrollment_query = enrollment_query.where(Student.id == student_id)
            enrollments = list(await session.execute(enrollment_query))
            marks_query = (select(Attendance).join(Enrollment, and_(Enrollment.student_id == Attendance.student_id,
                                                                    enrolled_on(Attendance.date)))
                           .where(Enrollment.class_id == class_id, Attendance.date.between(start, end)))
            if student_id is not None:
                marks_query = marks_query.where(Attendance.student_id == student_id)
            marks = {(mark.student_id, mark.date): mark for mark in await session.scalars(marks_query)}
            enrollments.sort(key=lambda row: sort_student(row[1]))
            entries = {day: [Entry(student, marks.get((student.id, day))) for enrollment, student in enrollments
                             if enrollment.starts_on <= day and (enrollment.ends_before is None or day < enrollment.ends_before)]
                       if not school_class.archived_on or day <= school_class.archived_on else []
                       for day in days}
            return school_class, entries
