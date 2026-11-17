from services.attendance import AttendanceService
from services.directory import Directory
from services.memberships import Memberships
from services.permissions import Forbidden, Permissions
from services.reports import Reports
from services.timetable import Timetables


class AttendanceApplication:
    def __init__(self, db, config):
        self.db = db
        self.permissions = Permissions(config.owner_id)
        self.directory = Directory(db, self.permissions, config.zone)
        self.attendance = AttendanceService(db, self.permissions, config.zone)
        self.memberships = Memberships(db, self.permissions)
        self.timetables = Timetables(db, self.permissions)
        self.reports = Reports(db, self.permissions, self.attendance)

    async def allowed(self, uid):
        async with self.db.read() as session:
            if not await self.permissions.has_access(session, uid):
                raise Forbidden()
