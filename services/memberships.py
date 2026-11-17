import logging

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiohttp import ClientConnectorError
from sqlalchemy import select

from database.models import ClassJoinRequest, ClassMembership, Notification, SchoolClass, User, utc_now
from services.permissions import Conflict, Forbidden, UserError, audit


log = logging.getLogger(__name__)


def queue_notice(session, recipient_id, category, message, class_id=None):
    session.add(Notification(recipient_id=recipient_id, class_id=class_id, category=category,
                             message=message, status='pending'))


class Memberships:
    def __init__(self, db, permissions):
        self.db = db
        self.permissions = permissions

    async def browse(self, uid):
        async with self.db.read() as session:
            actor = await self.permissions.actor(session, uid)
            available = list(await session.scalars(select(SchoolClass).where(SchoolClass.is_active).order_by(SchoolClass.name_key)))
            current = await session.get(ClassMembership, actor.id)
            requests = await session.execute(select(ClassJoinRequest, SchoolClass).join(SchoolClass, SchoolClass.id == ClassJoinRequest.class_id)
                                             .where(ClassJoinRequest.user_id == actor.id).order_by(ClassJoinRequest.id.desc()).limit(20))
            return available, current, list(requests)

    async def request(self, uid, class_id):
        async with self.db.write() as session:
            actor = await self.permissions.actor(session, uid)
            if self.permissions.is_owner(uid):
                raise Forbidden()
            school = await session.get(SchoolClass, class_id)
            if not school or not school.is_active:
                raise UserError('Класс недоступен.')
            member = await session.get(ClassMembership, actor.id)
            if member and member.class_id == class_id:
                raise UserError('Вы уже участник этого класса.')
            pending = await session.scalar(select(ClassJoinRequest).where(ClassJoinRequest.pending_user_id == actor.id))
            if pending:
                if pending.class_id == class_id:
                    return pending
                raise Conflict('У вас уже есть заявка на рассмотрении.')
            row = ClassJoinRequest(user_id=actor.id, class_id=class_id, pending_user_id=actor.id, status='PENDING')
            session.add(row)
            await session.flush()
            owner = await session.scalar(select(User).where(User.telegram_id == self.permissions.owner_id))
            if owner:
                queue_notice(session, owner.id, 'join_request', f'Новая заявка в класс {school.name}. Откройте раздел «Заявки».', class_id)
            audit(session, actor, 'membership.requested', 'join_request', row.id)
            return row

    async def listing(self, uid, pending_only):
        async with self.db.read() as session:
            await self.permissions.owner(session, uid)
            query = (select(ClassJoinRequest, SchoolClass, User).join(SchoolClass, SchoolClass.id == ClassJoinRequest.class_id)
                     .join(User, User.id == ClassJoinRequest.user_id))
            if pending_only:
                query = query.where(ClassJoinRequest.status == 'PENDING')
            return list(await session.execute(query.order_by(ClassJoinRequest.id.desc()).limit(200)))

    async def decide(self, uid, request_id, decision, class_id=None):
        async with self.db.write() as session:
            owner = await self.permissions.owner(session, uid)
            row = await session.get(ClassJoinRequest, request_id)
            if not row or row.status != 'PENDING':
                raise Conflict('Заявка уже рассмотрена или удалена.')
            target = await session.get(User, row.user_id)
            if target.telegram_id == uid:
                raise Forbidden()
            if class_id is not None or decision == 'APPROVED':
                school = await session.get(SchoolClass, class_id or row.class_id)
                if not school or not school.is_active:
                    raise UserError('Выберите активный класс.')
                row.class_id = school.id
            if decision == 'APPROVED':
                if target.blocked:
                    raise UserError('Сначала восстановите доступ пользователя.')
                member = await session.get(ClassMembership, target.id)
                if member is None:
                    session.add(ClassMembership(user_id=target.id, class_id=row.class_id, notify_schedule=False))
                else:
                    member.class_id, member.approved_at, member.notify_schedule = row.class_id, utc_now(), False
                queue_notice(session, target.id, 'join_decision', f'Заявка одобрена. Ваш класс — {school.name}.', row.class_id)
            elif decision == 'BLOCKED':
                target.blocked = True
            elif decision == 'REJECTED':
                queue_notice(session, target.id, 'join_decision', 'Владелец отклонил вашу заявку на вступление.', row.class_id)
            if decision != 'PENDING':
                row.pending_user_id, row.decided_at, row.decided_by = None, utc_now(), owner.id
            row.status = decision
            audit(session, owner, f'membership.{decision.lower()}', 'join_request', row.id, f'class={row.class_id}')
            return row

    async def notification_preference(self, uid, enabled):
        async with self.db.write() as session:
            actor = await self.permissions.actor(session, uid)
            row = await session.get(ClassMembership, actor.id)
            if not row:
                raise Forbidden()
            row.notify_schedule = enabled

    async def alerts(self, uid, read=False):
        transaction = self.db.write if read else self.db.read
        async with transaction() as session:
            actor = await self.permissions.actor(session, uid)
            rows = list(await session.scalars(select(Notification).where(Notification.recipient_id == actor.id)
                                             .order_by(Notification.id.desc()).limit(100)))
            if read:
                for row in rows:
                    if row.read_at is None:
                        row.read_at = utc_now()
            return rows

    async def flush(self, bot, limit=15):
        async with self.db.read() as session:
            ids = list(await session.scalars(select(Notification.id).where(Notification.status == 'pending')
                                             .order_by(Notification.id).limit(limit)))
        for notice_id in ids:
            async with self.db.write() as session:
                row = await session.get(Notification, notice_id)
                if row.status != 'pending':
                    continue
                user = await session.get(User, row.recipient_id)
                member = await session.get(ClassMembership, user.id) if row.category == 'timetable' else None
                eligible = row.category != 'timetable' or (member and member.class_id == row.class_id and member.notify_schedule)
                if user.blocked or not user.started_at or not eligible:
                    row.status = 'in_app'
                    continue
                row.attempted_at, row.status = utc_now(), 'sending'
            status = 'sent'
            try:
                await bot.send_message(user.telegram_id, row.message, protect_content=True)
            except (TelegramRetryAfter, TelegramNetworkError) as exc:
                clean_failure = isinstance(exc, TelegramRetryAfter) or isinstance(exc.__cause__, ClientConnectorError)
                status = 'failed' if clean_failure else 'uncertain'
            except (TelegramForbiddenError, TelegramBadRequest):
                status = 'failed'
            except Exception as exc:
                log.error('Notification delivery failed (%s)', type(exc).__name__)
                status = 'uncertain'
            async with self.db.write() as session:
                record = await session.get(Notification, notice_id)
                record.status = status
