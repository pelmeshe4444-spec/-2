import re
from datetime import date, timedelta

from sqlalchemy import delete, or_, select

from database.models import (ClassMembership, ClassTimetable, LessonTimeSlot, ManagerAssignment, SchoolClass, Subject,
                             TimetableChange, TimetableException, TimetableLesson, User)
from services.directory import bounded, normalized
from services.memberships import queue_notice
from services.permissions import Conflict, Forbidden, UserError, audit
from services.reports import time_value


WEEK_ANCHOR = date(2026, 1, 5)
FIRST_PLAN = date(2000, 1, 3)
ICONS = {'book', 'calculator', 'globe', 'flask', 'music', 'monitor', 'dumbbell', 'palette', 'languages', 'atom'}
LESSON_FIELDS = ('weekday', 'lesson_number', 'subject_id', 'start_time', 'end_time', 'teacher_name', 'classroom', 'comment')


def subject_dict(subject):
    return {'id': subject.id, 'name': subject.name, 'color': subject.color, 'icon': subject.icon, 'active': subject.is_active}


def lesson_dict(lesson):
    return {field: getattr(lesson, field) for field in LESSON_FIELDS}


def normalized_rows(rows, *, slots=False):
    result, occupied = [], set()
    for row in rows:
        item = dict(row)
        weekday, number = item.get('weekday', 0), item['lesson_number']
        if not 0 <= weekday <= 6 or not 1 <= number <= 20 or (weekday, number) in occupied:
            raise UserError('Проверьте уникальные номера уроков в каждом дне.')
        occupied.add((weekday, number))
        start, end = time_value(item['start_time']), time_value(item['end_time'])
        if start >= end:
            raise UserError(f'Урок {number}: окончание должно быть позже начала.')
        if not slots:
            for key, size in [('teacher_name', 100), ('classroom', 40), ('comment', 250)]:
                item[key] = bounded(item[key], size) if (item.get(key) or '').strip() else None
        result.append(item)
    result.sort(key=lambda row: (row.get('weekday', 0), row['lesson_number']))
    for before, after in zip(result, result[1:]):
        if before.get('weekday', 0) == after.get('weekday', 0) and before['end_time'] > after['start_time']:
            raise UserError(f'Время уроков {before["lesson_number"]} и {after["lesson_number"]} пересекается или нарушает порядок.')
    return result


class Timetables:
    def __init__(self, db, permissions):
        self.db = db
        self.permissions = permissions

    async def scope(self, session, uid, class_id, *, edit=False):
        actor = await self.permissions.actor(session, uid)
        owner = self.permissions.is_owner(uid)
        manager = await session.get(ManagerAssignment, (actor.id, class_id))
        member = await session.get(ClassMembership, actor.id)
        editable = owner or bool(manager and manager.can_edit_timetable)
        if (edit and not editable) or (not edit and not owner and not manager and (not member or member.class_id != class_id)):
            raise Forbidden()
        school = await session.get(SchoolClass, class_id)
        if school is None or not school.is_active:
            raise UserError('Класс недоступен.')
        return actor, school, editable

    async def subjects(self, uid):
        async with self.db.read() as session:
            await self.permissions.owner(session, uid)
            return await self._subjects(session)

    async def _subjects(self, session):
        return [subject_dict(row) for row in await session.scalars(select(Subject).order_by(Subject.name_key))]

    async def save_subject(self, uid, values, subject_id=None):
        async with self.db.write() as session:
            actor = await self.permissions.owner(session, uid)
            name, kind, color = bounded(values.name, 80), values.icon, values.color
            if kind not in ICONS or not re.fullmatch(r'#[a-fA-F0-9]{6}', color):
                raise UserError('Проверьте цвет и значок предмета.')
            key = normalized(name)
            existing = await session.scalar(select(Subject).where(Subject.name_key == key))
            if existing and existing.id != subject_id:
                raise Conflict('Предмет с таким названием уже существует.')
            row = await session.get(Subject, subject_id) if subject_id else Subject()
            if row is None:
                raise UserError('Предмет не найден.')
            row.name, row.name_key, row.color, row.icon, row.is_active = name, key, color.lower(), kind, values.active
            session.add(row)
            await session.flush()
            audit(session, actor, 'timetable.subject', 'subject', row.id)
            return subject_dict(row)

    async def _plan(self, session, class_id, cycle, *, starts=None, day=None):
        query = select(ClassTimetable).where(ClassTimetable.class_id == class_id, ClassTimetable.cycle == cycle)
        if starts is not None:
            query = query.where(ClassTimetable.effective_from == starts)
        elif day is not None:
            query = query.where(ClassTimetable.is_active, ClassTimetable.effective_from <= day,
                                or_(ClassTimetable.effective_to.is_(None), ClassTimetable.effective_to >= day))
        return await session.scalar(query.order_by(ClassTimetable.effective_from.desc()).limit(1))

    async def _snapshot(self, session, plan, cycle, starts=None):
        if plan is None:
            return {'name': 'Расписание', 'cycle': cycle, 'effective_from': (starts or FIRST_PLAN).isoformat(),
                    'effective_to': None, 'active': True, 'lessons': [], 'revision': 0}
        rows = list(await session.scalars(select(TimetableLesson).where(TimetableLesson.timetable_id == plan.id)
                                          .order_by(TimetableLesson.weekday, TimetableLesson.lesson_number)))
        return {'name': plan.name, 'cycle': plan.cycle, 'effective_from': plan.effective_from.isoformat(),
                'effective_to': plan.effective_to.isoformat() if plan.effective_to else None, 'active': plan.is_active,
                'lessons': [lesson_dict(row) for row in rows], 'revision': plan.revision}

    async def _slots(self, session, class_id):
        rows = await session.scalars(select(LessonTimeSlot).where(LessonTimeSlot.class_id == class_id)
                                     .order_by(LessonTimeSlot.shift, LessonTimeSlot.lesson_number))
        return [{'shift': row.shift, 'lesson_number': row.lesson_number, 'start_time': row.start_time,
                 'end_time': row.end_time} for row in rows]

    async def editor(self, uid, class_id, cycle, starts=None):
        async with self.db.read() as session:
            await self.scope(session, uid, class_id, edit=True)
            plan = await self._plan(session, class_id, cycle, starts=starts)
            versions = list(await session.scalars(select(ClassTimetable.effective_from).where(
                ClassTimetable.class_id == class_id, ClassTimetable.cycle == cycle).order_by(ClassTimetable.effective_from.desc())))
            return {'plan': await self._snapshot(session, plan, cycle, starts), 'periods': versions,
                    'subjects': await self._subjects(session), 'slots': await self._slots(session, class_id)}

    async def _validate_subjects(self, session, rows):
        wanted = {row['subject_id'] for row in rows}
        existing = set(await session.scalars(select(Subject.id).where(Subject.id.in_(wanted))))
        if wanted != existing:
            raise UserError('В расписании указан неизвестный предмет.')

    async def _change(self, session, actor, school, target, key, before, after, notify):
        session.add(TimetableChange(class_id=school.id, actor_id=actor.id, target=target, plan_key=key, before=before, after=after))
        audit(session, actor, 'timetable.published', 'class', school.id, key)
        if notify:
            subject_ids = {row['subject_id'] for value in (before, after) for row in value['lessons']}
            subjects = {row.id: row.name for row in await session.scalars(select(Subject).where(Subject.id.in_(subject_ids)))}
            def refs(value):
                return {(row['weekday'], row['lesson_number']): row for row in value['lessons']}
            old, new = refs(before), refs(after)
            days = ('Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс')
            details = []
            for slot in sorted(old.keys() | new.keys()):
                left, right = old.get(slot), new.get(slot)
                if left == right:
                    continue
                was = subjects[left['subject_id']] if left else '—'
                changed = f'{subjects[right["subject_id"]]} {right["start_time"]}–{right["end_time"]}' if right else 'отменён'
                details.append(f'{days[slot[0]]}, урок {slot[1]}: {was} → {changed}')
            summary = f'📚 Расписание изменено. Класс {school.name}. {key}.\n' + '\n'.join(details[:3])
            if len(details) > 3:
                summary += f'\nДругих изменений: {len(details) - 3}'
            users = await session.scalars(select(ClassMembership.user_id).where(ClassMembership.class_id == school.id,
                                                                                 ClassMembership.notify_schedule))
            for user_id in users:
                queue_notice(session, user_id, 'timetable', summary[:500], school.id)

    async def publish(self, uid, class_id, payload, notify=False):
        async with self.db.write() as session:
            actor, school, _ = await self.scope(session, uid, class_id, edit=True)
            return await self._publish(session, actor, school, payload, notify)

    async def _publish(self, session, actor, school, payload, notify):
        start = date.fromisoformat(payload['effective_from'])
        end = date.fromisoformat(payload['effective_to']) if payload.get('effective_to') else None
        cycle = payload['cycle']
        if end and end < start:
            raise UserError('Конец периода должен быть не раньше начала.')
        plan = await self._plan(session, school.id, cycle, starts=start)
        before = await self._snapshot(session, plan, cycle, start)
        if payload['revision'] != before['revision']:
            raise Conflict('Расписание уже изменилось. Обновите его перед сохранением.')
        rows = normalized_rows(payload['lessons'])
        await self._validate_subjects(session, rows)
        if payload['active']:
            overlaps = select(ClassTimetable.id).where(ClassTimetable.class_id == school.id, ClassTimetable.cycle == cycle,
                ClassTimetable.is_active, ClassTimetable.effective_from != start,
                or_(ClassTimetable.effective_to.is_(None), ClassTimetable.effective_to >= start))
            if end:
                overlaps = overlaps.where(ClassTimetable.effective_from <= end)
            if await session.scalar(overlaps.limit(1)):
                raise Conflict('Периоды этой недели пересекаются. Сначала завершите предыдущий период.')
        if not plan:
            plan = ClassTimetable(class_id=school.id, cycle=cycle, effective_from=start, name='Расписание')
            session.add(plan)
            await session.flush()
        plan.name, plan.effective_to, plan.is_active = bounded(payload['name'], 80), end, payload['active']
        plan.revision = before['revision'] + 1
        await session.execute(delete(TimetableLesson).where(TimetableLesson.timetable_id == plan.id))
        session.add_all(TimetableLesson(timetable_id=plan.id, **row) for row in rows)
        await session.flush()
        after = await self._snapshot(session, plan, cycle)
        await self._change(session, actor, school, 'week', f'{cycle}:{start}', before, after, notify)
        return after

    async def slots(self, uid, class_id, shift, items):
        shift = bounded(shift, 32)
        rows = normalized_rows(items, slots=True)
        async with self.db.write() as session:
            actor = await self.permissions.owner(session, uid)
            await self.scope(session, uid, class_id, edit=True)
            await session.execute(delete(LessonTimeSlot).where(LessonTimeSlot.class_id == class_id, LessonTimeSlot.shift == shift))
            session.add_all(LessonTimeSlot(class_id=class_id, shift=shift, **row) for row in rows)
            audit(session, actor, 'timetable.slots', 'class', class_id)
            return await self._slots(session, class_id)

    async def _effective(self, session, class_id, day):
        cycle = 'A' if ((day - WEEK_ANCHOR).days // 7) % 2 == 0 else 'B'
        chosen = await self._plan(session, class_id, cycle, day=day)
        if cycle == 'B' and not chosen:
            cycle, chosen = 'A', await self._plan(session, class_id, 'A', day=day)
        lessons = []
        if chosen:
            lessons = [lesson_dict(row) for row in await session.scalars(select(TimetableLesson)
                .where(TimetableLesson.timetable_id == chosen.id, TimetableLesson.weekday == day.weekday())
                .order_by(TimetableLesson.lesson_number))]
        row = await session.scalar(select(TimetableException).where(TimetableException.class_id == class_id,
                                                                    TimetableException.date == day))
        exception = row.action if row else 'regular'
        result = row.lessons if exception != 'regular' else lessons
        return {'day': day.isoformat(), 'cycle': cycle, 'lessons': result, 'regular': lessons, 'action': exception,
                'comment': row.comment if row else None, 'revision': row.revision if row else 0}

    async def view(self, uid, class_id, day, week):
        async with self.db.read() as session:
            _, school, editable = await self.scope(session, uid, class_id)
            days = [day] if not week else [day + timedelta(days=offset-day.weekday()) for offset in range(7)]
            plans = [await self._effective(session, class_id, day) for day in days]
            subjects = await self._subjects(session)
            used = {row['subject_id'] for plan in plans for row in plan['lessons'] + plan['regular']}
            return {'class_name': school.name, 'days': plans, 'editable': editable,
                    'subjects': [subject for subject in subjects if subject['id'] in used]}

    async def exception(self, uid, class_id, day, payload, notify=False):
        async with self.db.write() as session:
            actor, school, _ = await self.scope(session, uid, class_id, edit=True)
            return await self._exception(session, actor, school, day, payload, notify)

    async def _exception(self, session, actor, school, day, payload, notify):
        before = await self._effective(session, school.id, day)
        if payload['revision'] != before['revision']:
            raise Conflict('Исключение уже изменилось. Обновите расписание.')
        action = payload['action']
        rows = normalized_rows([{**row, 'weekday': day.weekday()} for row in payload['lessons']]) if action == 'replace' else []
        await self._validate_subjects(session, rows)
        row = await session.scalar(select(TimetableException).where(TimetableException.class_id == school.id,
                                                                    TimetableException.date == day))
        if not row:
            row = TimetableException(class_id=school.id, date=day, created_by=actor.id)
            session.add(row)
        row.action, row.lessons, row.revision = action, rows, before['revision'] + 1
        comment = payload.get('comment')
        row.comment = bounded(comment, 250) if comment and action != 'regular' else None
        await session.flush()
        after = await self._effective(session, school.id, day)
        await self._change(session, actor, school, 'exception', day.isoformat(), before, after, notify)
        return after

    async def history(self, uid, class_id):
        async with self.db.read() as session:
            await self.permissions.owner(session, uid)
            rows = await session.execute(select(TimetableChange, User.full_name).join(User, User.id == TimetableChange.actor_id)
                                         .where(TimetableChange.class_id == class_id).order_by(TimetableChange.id.desc()).limit(100))
            return [{'id': row.id, 'target': row.target, 'key': row.plan_key, 'before': row.before, 'after': row.after,
                     'changed_at': row.changed_at.isoformat() + 'Z', 'actor': name} for row, name in rows]

    async def restore(self, uid, class_id, change_id):
        async with self.db.write() as session:
            await self.permissions.owner(session, uid)
            actor, school, _ = await self.scope(session, uid, class_id, edit=True)
            change = await session.get(TimetableChange, change_id)
            if not change or change.class_id != class_id:
                raise UserError('Версия расписания недоступна.')
            values = dict(change.before)
            if change.target == 'week':
                plan = await self._plan(session, class_id, values['cycle'], starts=date.fromisoformat(values['effective_from']))
                values['revision'] = plan.revision if plan else 0
                return await self._publish(session, actor, school, values, False)
            day = date.fromisoformat(change.plan_key)
            values['revision'] = (await self._effective(session, class_id, day))['revision']
            return await self._exception(session, actor, school, day, values, False)
