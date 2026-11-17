from sqlalchemy import select

from database.models import AuditLog, ManagerAssignment, ReportRecipient, SchoolClass, User


DENIED = '🔒 Доступ ограничен. Обратитесь к администратору для получения прав'


class UserError(Exception):
    pass


class Forbidden(UserError):
    def __init__(self):
        super().__init__(DENIED)


class Conflict(UserError):
    pass


def audit(session, actor: User | None, action: str, entity: str, entity_id=None, details=None):
    session.add(AuditLog(actor_id=actor.id if actor else None, action=action,
                         entity_type=entity, entity_id=entity_id, details=details))


class Permissions:
    def __init__(self, owner_id: int):
        self.owner_id = owner_id

    def is_owner(self, telegram_id: int) -> bool:
        return telegram_id == self.owner_id

    async def actor(self, session, telegram_id: int) -> User:
        actor = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if actor is None or (actor.blocked and not self.is_owner(telegram_id)):
            raise Forbidden()
        return actor

    async def owner(self, session, telegram_id: int) -> User:
        if not self.is_owner(telegram_id):
            raise Forbidden()
        return await self.actor(session, telegram_id)

    async def for_class(self, session, telegram_id: int, class_id: int, *, history=False, recipient=False,
                        allow_archived=False):
        actor = await self.actor(session, telegram_id)
        if not self.is_owner(telegram_id):
            model = ReportRecipient if recipient else ManagerAssignment
            assignment = await session.get(model, (actor.id, class_id))
            if assignment is None or (history and not recipient and not assignment.can_view_history):
                raise Forbidden()
        school_class = await session.get(SchoolClass, class_id)
        if school_class is None or (not school_class.is_active and not allow_archived):
            raise UserError('Класс недоступен.')
        return actor, school_class

    async def classes(self, session, telegram_id: int, mode='manage') -> list[SchoolClass]:
        actor = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if actor is None or (actor.blocked and not self.is_owner(telegram_id)):
            return []
        query = select(SchoolClass).where(SchoolClass.is_active).order_by(SchoolClass.name_key, SchoolClass.id)
        if not self.is_owner(telegram_id):
            if mode == 'owner':
                raise Forbidden()
            model = ReportRecipient if mode == 'receive' else ManagerAssignment
            query = query.join(model, model.class_id == SchoolClass.id).where(model.user_id == actor.id)
            if mode == 'history':
                query = query.where(ManagerAssignment.can_view_history)
        return list(await session.scalars(query))

    async def has_access(self, session, telegram_id: int) -> bool:
        if self.is_owner(telegram_id):
            return True
        return bool(await self.classes(session, telegram_id) or await self.classes(session, telegram_id, 'receive'))
