import hashlib
import json

from sqlalchemy import func, or_, select

from database.models import Announcement, ClassMembership, ManagerAssignment, Notification, ReportRecipient, SchoolClass, User
from services.directory import bounded
from services.permissions import Conflict, UserError, audit


def audience(class_ids):
    active = select(SchoolClass.id).where(SchoolClass.id.in_(class_ids), SchoolClass.is_active)
    assignments = [User.id.in_(select(model.user_id).where(model.class_id.in_(active)))
                   for model in (ClassMembership, ManagerAssignment, ReportRecipient)]
    return select(User.id).where(User.started_at.is_not(None), ~User.blocked, or_(*assignments)).order_by(User.id)


async def preview(session, class_ids, message):
    ids = sorted(set(class_ids))
    active = list(await session.scalars(select(SchoolClass.id).where(SchoolClass.is_active, SchoolClass.id.in_(ids))))
    if sorted(active) != ids:
        raise UserError('Выберите действующие классы.')
    recipients = list(await session.scalars(audience(ids)))
    digest = hashlib.sha256(json.dumps([ids, message, recipients], ensure_ascii=False).encode()).hexdigest()
    return ids, recipients, digest


async def queue_announcement(session, actor, values):
    message = bounded(values.message, 500)
    previous = await session.scalar(select(Announcement).where(Announcement.request_id == values.request_id))
    if previous:
        if previous.class_ids != sorted(set(values.class_ids)) or previous.message != message:
            raise Conflict('Этот запрос уже использован для другого объявления.')
        return previous
    ids, recipients, digest = await preview(session, values.class_ids, message)
    if digest != values.confirmation:
        raise Conflict('Состав получателей или текст изменился. Выполните новый предпросмотр.')
    if not recipients:
        raise UserError('В выбранных классах нет пользователей, запустивших бота.')
    if len(recipients) > 2000:
        raise UserError('Для одной отправки выберите до 2000 получателей.')
    row = Announcement(request_id=values.request_id, class_ids=ids, message=message)
    session.add(row)
    await session.flush()
    session.add_all(Notification(announcement_id=row.id, recipient_id=recipient, category='announcement',
                                 message=message, status='pending') for recipient in recipients)
    audit(session, actor, 'announcement.queued', 'announcement', row.id, f'recipients={len(recipients)}')
    return row


async def deliveries(session):
    announcements = list(await session.scalars(select(Announcement).order_by(Announcement.id.desc()).limit(30)))
    grouped = await session.execute(select(Notification.announcement_id, Notification.status, func.count()).where(
        Notification.announcement_id.in_([row.id for row in announcements])).group_by(Notification.announcement_id, Notification.status))
    statuses = {}
    for announcement_id, status, count in grouped:
        statuses.setdefault(announcement_id, {})[status] = count
    return [(row, statuses.get(row.id, {})) for row in announcements]
