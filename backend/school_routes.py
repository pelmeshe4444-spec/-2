from datetime import date
from typing import Annotated, Literal

from fastapi import BackgroundTasks, Query
from pydantic import Field

from backend import presentation as view
from backend.schemas import Input
from database.models import ManagerAssignment, User
from services.permissions import UserError, audit
from sqlalchemy import select


class JoinInput(Input):
    class_id: int = Field(gt=0)


class DecisionInput(Input):
    decision: Literal['APPROVED', 'REJECTED', 'BLOCKED', 'PENDING']
    class_id: int | None = Field(default=None, gt=0)


class EnabledInput(Input):
    enabled: bool


class SubjectInput(Input):
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(pattern=r'^#[0-9a-fA-F]{6}$')
    icon: str = Field(max_length=24)
    active: bool = True


class TimeSlotInput(Input):
    lesson_number: int = Field(ge=1, le=20)
    start_time: str = Field(min_length=5, max_length=5)
    end_time: str = Field(min_length=5, max_length=5)


class LessonInput(TimeSlotInput):
    weekday: int = Field(ge=0, le=6)
    subject_id: int = Field(gt=0)
    teacher_name: str | None = Field(default=None, max_length=100)
    classroom: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=250)


class BellInput(Input):
    shift: str = Field(min_length=1, max_length=32)
    slots: list[TimeSlotInput] = Field(max_length=20)


class PlanInput(Input):
    name: str = Field(min_length=1, max_length=80)
    cycle: Literal['A', 'B']
    active: bool = True
    effective_from: date
    effective_to: date | None = None
    lessons: list[LessonInput] = Field(max_length=140)
    revision: int = Field(ge=0)
    notify: bool = False


class ExceptionInput(Input):
    action: Literal['closed', 'replace', 'regular']
    lessons: list[LessonInput] = Field(max_length=20)
    comment: str | None = Field(default=None, max_length=250)
    revision: int = Field(ge=0)
    notify: bool = False


def brief(row, school=None):
    return {'id': row.id, 'class_id': row.class_id, 'class_name': school.name if school else None,
            'status': row.status, 'requested_at': view.timestamp(row.requested_at), 'decided_at': view.timestamp(row.decided_at)}


def school_routes(api, core, Account, Owner, telegram_sender):
    async def dispatch_notices():
        async with telegram_sender() as bot:
            await core.memberships.flush(bot)

    @api.get('/api/join-requests/me')
    async def my_requests(uid: Account):
        schools, membership, items = await core.memberships.browse(uid)
        return {'classes': [view.school_class(row, can_history=False) for row in schools],
                'member': membership.class_id if membership else None,
                'notify_schedule': membership.notify_schedule if membership else False,
                'requests': [brief(row, school) for row, school in items]}

    @api.post('/api/join-requests', status_code=201)
    async def submit_request(body: JoinInput, uid: Account, background: BackgroundTasks):
        row = await core.memberships.request(uid, body.class_id)
        background.add_task(dispatch_notices)
        return brief(row)

    @api.get('/api/join-requests')
    async def requests(uid: Owner, pending: bool = False):
        return [{**brief(row, school), 'user': view.profile(user)} for row, school, user in
                await core.memberships.listing(uid, pending)]

    @api.patch('/api/join-requests/{request_id}')
    async def resolve_request(request_id: int, body: DecisionInput, uid: Owner, background: BackgroundTasks):
        row = await core.memberships.decide(uid, request_id, body.decision, body.class_id)
        background.add_task(dispatch_notices)
        return brief(row)

    @api.put('/api/me/lesson-notifications')
    async def preferences(body: EnabledInput, uid: Account):
        await core.memberships.notification_preference(uid, body.enabled)
        return {'enabled': body.enabled}

    @api.get('/api/notifications')
    async def notifications(uid: Account):
        return [{'id': row.id, 'message': row.message, 'category': row.category, 'status': row.status,
                 'created_at': view.timestamp(row.created_at), 'read': row.read_at is not None}
                for row in await core.memberships.alerts(uid)]

    @api.post('/api/notifications/read')
    async def read_notices(uid: Account):
        await core.memberships.alerts(uid, read=True)
        return {'read': True}

    @api.put('/api/users/{target}/classes/{class_id}/timetable-access')
    async def delegate_editor(target: int, class_id: int, body: EnabledInput, uid: Owner):
        async with core.db.write() as session:
            actor = await core.permissions.owner(session, uid)
            await core.timetables.scope(session, uid, class_id, edit=True)
            user = await session.scalar(select(User).where(User.telegram_id == target))
            role = await session.get(ManagerAssignment, (user.id, class_id)) if user else None
            if not role:
                raise UserError('Сначала назначьте ответственного за класс.')
            role.can_edit_timetable = body.enabled
            audit(session, actor, 'timetable.permission', 'user', user.id, f'class={class_id}')
        return {'enabled': body.enabled}

    @api.get('/api/subjects')
    async def subjects(uid: Owner):
        return await core.timetables.subjects(uid)

    @api.post('/api/subjects', status_code=201)
    async def create_subject(body: SubjectInput, uid: Owner):
        return await core.timetables.save_subject(uid, body)

    @api.put('/api/subjects/{subject_id}')
    async def update_subject(subject_id: int, body: SubjectInput, uid: Owner):
        return await core.timetables.save_subject(uid, body, subject_id)

    @api.get('/api/classes/{class_id}/timetable')
    async def lessons(class_id: int, uid: Account, day: date | None = None, week: bool = False):
        return await core.timetables.view(uid, class_id, day or core.attendance.today(), week)

    @api.get('/api/classes/{class_id}/timetable/editor')
    async def editor(class_id: int, uid: Account, cycle: Literal['A', 'B'] = 'A', starts: date | None = None):
        return await core.timetables.editor(uid, class_id, cycle, starts)

    @api.put('/api/classes/{class_id}/timetable')
    async def publish(class_id: int, body: PlanInput, uid: Account, background: BackgroundTasks):
        result = await core.timetables.publish(uid, class_id, body.model_dump(mode='json', exclude={'notify'}), body.notify)
        if body.notify:
            background.add_task(dispatch_notices)
        return result

    @api.put('/api/classes/{class_id}/timetable/bells')
    async def bells(class_id: int, body: BellInput, uid: Owner):
        return await core.timetables.slots(uid, class_id, body.shift, [item.model_dump() for item in body.slots])

    @api.put('/api/classes/{class_id}/timetable/exceptions/{day}')
    async def exception(class_id: int, day: date, body: ExceptionInput, uid: Account, background: BackgroundTasks):
        result = await core.timetables.exception(uid, class_id, day, body.model_dump(exclude={'notify'}), body.notify)
        if body.notify:
            background.add_task(dispatch_notices)
        return result

    @api.get('/api/classes/{class_id}/timetable/history')
    async def schedule_history(class_id: int, uid: Owner):
        return await core.timetables.history(uid, class_id)

    @api.post('/api/classes/{class_id}/timetable/history/{change_id}/restore')
    async def restore(class_id: int, change_id: int, uid: Owner):
        return await core.timetables.restore(uid, class_id, change_id)
