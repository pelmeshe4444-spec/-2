from datetime import UTC, date as CalendarDate, datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, JSON, String, UniqueConstraint, false
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str | None] = mapped_column(String(160))
    started_at: Mapped[datetime | None]
    blocked: Mapped[bool] = mapped_column(default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class UserRole(Base):
    __tablename__ = 'user_roles'
    __table_args__ = (CheckConstraint("role IN ('MANAGER', 'REPORT_RECIPIENT')", name='ck_delegated_role'),)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    role: Mapped[str] = mapped_column(String(24), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class SchoolClass(Base):
    __tablename__ = 'classes'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32))
    name_key: Mapped[str] = mapped_column(String(64), unique=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    archived_on: Mapped[CalendarDate | None]


class Student(Base):
    __tablename__ = 'students'
    __table_args__ = (UniqueConstraint('class_id', 'active_name_key', name='uq_student_active_name'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(48))
    last_name: Mapped[str] = mapped_column(String(48))
    class_id: Mapped[int] = mapped_column(ForeignKey('classes.id'), index=True)
    active_name_key: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)

    @property
    def name(self) -> str:
        return f'{self.last_name} {self.first_name}'


class Enrollment(Base):
    __tablename__ = 'enrollments'
    __table_args__ = (Index('ix_enrollment_class_period', 'class_id', 'starts_on', 'ends_before'),)
    student_id: Mapped[int] = mapped_column(ForeignKey('students.id'), primary_key=True)
    starts_on: Mapped[CalendarDate] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey('classes.id'))
    ends_before: Mapped[CalendarDate | None]


class ManagerAssignment(Base):
    __tablename__ = 'manager_assignments'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey('classes.id'), primary_key=True, index=True)
    can_view_history: Mapped[bool] = mapped_column(default=False)
    can_edit_timetable: Mapped[bool] = mapped_column(default=False, server_default=false())
    can_edit_history: Mapped[bool] = mapped_column(default=False, server_default=false())
    can_view_statistics: Mapped[bool] = mapped_column(default=False, server_default=false())
    can_view_reports: Mapped[bool] = mapped_column(default=False, server_default=false())


class ReportRecipient(Base):
    __tablename__ = 'report_recipients'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey('classes.id'), primary_key=True, index=True)


class Attendance(Base):
    __tablename__ = 'attendance'
    __table_args__ = (
        UniqueConstraint('student_id', 'date', name='uq_attendance_student_date'),
        CheckConstraint('status BETWEEN 0 AND 4', name='ck_attendance_status'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('students.id'))
    date: Mapped[CalendarDate] = mapped_column(index=True)
    status: Mapped[int]
    reason: Mapped[str | None] = mapped_column(String(300))
    marked_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class ReportSchedule(Base):
    __tablename__ = 'report_schedules'
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey('classes.id'), unique=True)
    time: Mapped[str] = mapped_column(String(5), default='08:30')
    timezone: Mapped[str] = mapped_column(String(64))
    weekdays: Mapped[str] = mapped_column(String(7), default='01234')
    is_enabled: Mapped[bool] = mapped_column(default=False)
    deleted: Mapped[bool] = mapped_column(default=False, server_default=false())
    reminder_one: Mapped[str | None] = mapped_column(String(5))
    reminder_two: Mapped[str | None] = mapped_column(String(5))


class ReportDelivery(Base):
    __tablename__ = 'report_deliveries'
    __table_args__ = (
        UniqueConstraint('schedule_id', 'recipient_id', 'report_date', 'dispatch_key', name='uq_delivery_dispatch'),
        Index('ix_delivery_status_time', 'status', 'created_at'),
        Index('ix_delivery_class_latest', 'schedule_id', 'report_date', 'sent_at'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey('report_schedules.id'))
    recipient_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    report_date: Mapped[CalendarDate]
    dispatch_key: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), default='sending')
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    sent_at: Mapped[datetime | None]
    error_message: Mapped[str | None] = mapped_column(String(160))
    parts_sent: Mapped[int] = mapped_column(default=0)
    parts_total: Mapped[int] = mapped_column(default=0)
    body: Mapped[str | None]
    attempts: Mapped[int] = mapped_column(default=1, server_default='1')
    retry_at: Mapped[datetime | None]


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int | None]
    timestamp: Mapped[datetime] = mapped_column(default=utc_now, index=True)
    details: Mapped[str | None] = mapped_column(String(300))


class SchoolSettings(Base):
    __tablename__ = 'school_settings'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    preferences: Mapped[dict | None] = mapped_column(JSON)


class ClassMembership(Base):
    __tablename__ = 'class_memberships'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey('classes.id'), index=True)
    notify_schedule: Mapped[bool] = mapped_column(default=False)
    approved_at: Mapped[datetime] = mapped_column(default=utc_now)


class ClassJoinRequest(Base):
    __tablename__ = 'class_join_requests'
    __table_args__ = (CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','BLOCKED')", name='ck_join_status'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey('classes.id'))
    pending_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), unique=True)
    status: Mapped[str] = mapped_column(String(12), index=True, default='PENDING')
    requested_at: Mapped[datetime] = mapped_column(default=utc_now)
    decided_at: Mapped[datetime | None]
    decided_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))


class Subject(Base):
    __tablename__ = 'subjects'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    name_key: Mapped[str] = mapped_column(String(160), unique=True)
    color: Mapped[str] = mapped_column(String(7))
    icon: Mapped[str] = mapped_column(String(24))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class LessonTimeSlot(Base):
    __tablename__ = 'lesson_time_slots'
    __table_args__ = (UniqueConstraint('class_id', 'shift', 'lesson_number', name='uq_bell_slot'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey('classes.id'))
    shift: Mapped[str] = mapped_column(String(32))
    lesson_number: Mapped[int]
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))


class ClassTimetable(Base):
    __tablename__ = 'class_timetables'
    __table_args__ = (UniqueConstraint('class_id', 'cycle', 'effective_from', name='uq_timetable_effective'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey('classes.id'), index=True)
    name: Mapped[str] = mapped_column(String(80))
    cycle: Mapped[str] = mapped_column(String(1))
    effective_from: Mapped[CalendarDate]
    effective_to: Mapped[CalendarDate | None]
    is_active: Mapped[bool] = mapped_column(default=True)
    revision: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class TimetableLesson(Base):
    __tablename__ = 'timetable_lessons'
    __table_args__ = (UniqueConstraint('timetable_id', 'weekday', 'lesson_number', name='uq_lesson_number'),
                      CheckConstraint('weekday BETWEEN 0 AND 6 AND lesson_number BETWEEN 1 AND 20 AND start_time < end_time', name='ck_lesson_times'))
    id: Mapped[int] = mapped_column(primary_key=True)
    timetable_id: Mapped[int] = mapped_column(ForeignKey('class_timetables.id'), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey('subjects.id'))
    weekday: Mapped[int]
    lesson_number: Mapped[int]
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    teacher_name: Mapped[str | None] = mapped_column(String(100))
    classroom: Mapped[str | None] = mapped_column(String(40))
    comment: Mapped[str | None] = mapped_column(String(250))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class TimetableException(Base):
    __tablename__ = 'timetable_exceptions'
    __table_args__ = (UniqueConstraint('class_id', 'date', name='uq_class_exception_date'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey('classes.id'))
    date: Mapped[CalendarDate]
    action: Mapped[str] = mapped_column(String(12))
    lessons: Mapped[list] = mapped_column(JSON)
    comment: Mapped[str | None] = mapped_column(String(250))
    revision: Mapped[int] = mapped_column(default=0)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class TimetableChange(Base):
    __tablename__ = 'timetable_change_history'
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey('classes.id'), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    target: Mapped[str] = mapped_column(String(12))
    plan_key: Mapped[str] = mapped_column(String(24))
    before: Mapped[dict] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    changed_at: Mapped[datetime] = mapped_column(default=utc_now)


class AttendanceChange(Base):
    __tablename__ = 'attendance_history'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('students.id'), index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey('classes.id'), index=True)
    date: Mapped[CalendarDate]
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    before_status: Mapped[int]
    after_status: Mapped[int]
    before_reason: Mapped[str | None] = mapped_column(String(300))
    after_reason: Mapped[str | None] = mapped_column(String(300))
    changed_at: Mapped[datetime] = mapped_column(default=utc_now)


class Announcement(Base):
    __tablename__ = 'announcements'
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(32), unique=True)
    class_ids: Mapped[list] = mapped_column(JSON)
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class SystemEvent(Base):
    __tablename__ = 'system_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    operation: Mapped[str] = mapped_column(String(24))
    success: Mapped[bool]
    occurred_at: Mapped[datetime] = mapped_column(default=utc_now)


class Notification(Base):
    __tablename__ = 'notifications'
    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    class_id: Mapped[int | None] = mapped_column(ForeignKey('classes.id'))
    announcement_id: Mapped[int | None] = mapped_column(ForeignKey('announcements.id'), index=True)
    category: Mapped[str] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    attempted_at: Mapped[datetime | None]
    read_at: Mapped[datetime | None]
