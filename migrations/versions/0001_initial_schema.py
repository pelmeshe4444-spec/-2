"""initial_schema."""
from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('classes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.Column('name_key', sa.String(length=64), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name_key')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('telegram_id', sa.BigInteger(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=True),
    sa.Column('full_name', sa.String(length=160), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('telegram_id')
    )
    op.create_table('audit_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('entity_type', sa.String(length=32), nullable=False),
    sa.Column('entity_id', sa.Integer(), nullable=True),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.Column('details', sa.String(length=300), nullable=True),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_logs_timestamp'), ['timestamp'], unique=False)

    op.create_table('manager_assignments',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('class_id', sa.Integer(), nullable=False),
    sa.Column('can_view_history', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('user_id', 'class_id')
    )
    with op.batch_alter_table('manager_assignments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_manager_assignments_class_id'), ['class_id'], unique=False)

    op.create_table('report_recipients',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('class_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('user_id', 'class_id')
    )
    with op.batch_alter_table('report_recipients', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_report_recipients_class_id'), ['class_id'], unique=False)

    op.create_table('report_schedules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('class_id', sa.Integer(), nullable=False),
    sa.Column('time', sa.String(length=5), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('weekdays', sa.String(length=7), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), nullable=False),
    sa.Column('reminder_one', sa.String(length=5), nullable=True),
    sa.Column('reminder_two', sa.String(length=5), nullable=True),
    sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('class_id')
    )
    op.create_table('students',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('first_name', sa.String(length=48), nullable=False),
    sa.Column('last_name', sa.String(length=48), nullable=False),
    sa.Column('class_id', sa.Integer(), nullable=False),
    sa.Column('active_name_key', sa.String(length=200), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('class_id', 'active_name_key', name='uq_student_active_name')
    )
    with op.batch_alter_table('students', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_students_class_id'), ['class_id'], unique=False)

    op.create_table('user_roles',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=24), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("role IN ('MANAGER', 'REPORT_RECIPIENT')", name='ck_delegated_role'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('user_id', 'role')
    )
    op.create_table('attendance',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('student_id', sa.Integer(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('status', sa.Integer(), nullable=False),
    sa.Column('reason', sa.String(length=300), nullable=True),
    sa.Column('marked_by', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('status BETWEEN 0 AND 4', name='ck_attendance_status'),
    sa.ForeignKeyConstraint(['marked_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['student_id'], ['students.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('student_id', 'date', name='uq_attendance_student_date')
    )
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_attendance_date'), ['date'], unique=False)

    op.create_table('enrollments',
    sa.Column('student_id', sa.Integer(), nullable=False),
    sa.Column('starts_on', sa.Date(), nullable=False),
    sa.Column('class_id', sa.Integer(), nullable=False),
    sa.Column('ends_before', sa.Date(), nullable=True),
    sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ),
    sa.ForeignKeyConstraint(['student_id'], ['students.id'], ),
    sa.PrimaryKeyConstraint('student_id', 'starts_on')
    )
    with op.batch_alter_table('enrollments', schema=None) as batch_op:
        batch_op.create_index('ix_enrollment_class_period', ['class_id', 'starts_on', 'ends_before'], unique=False)

    op.create_table('report_deliveries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('schedule_id', sa.Integer(), nullable=False),
    sa.Column('recipient_id', sa.Integer(), nullable=False),
    sa.Column('report_date', sa.Date(), nullable=False),
    sa.Column('dispatch_key', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('sent_at', sa.DateTime(), nullable=True),
    sa.Column('error_message', sa.String(length=160), nullable=True),
    sa.Column('parts_sent', sa.Integer(), nullable=False),
    sa.Column('parts_total', sa.Integer(), nullable=False),
    sa.Column('body', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['recipient_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['schedule_id'], ['report_schedules.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('schedule_id', 'recipient_id', 'report_date', 'dispatch_key', name='uq_delivery_dispatch')
    )
    with op.batch_alter_table('report_deliveries', schema=None) as batch_op:
        batch_op.create_index('ix_delivery_class_latest', ['schedule_id', 'report_date', 'sent_at'], unique=False)
        batch_op.create_index('ix_delivery_status_time', ['status', 'created_at'], unique=False)



def downgrade():
    with op.batch_alter_table('report_deliveries', schema=None) as batch_op:
        batch_op.drop_index('ix_delivery_status_time')
        batch_op.drop_index('ix_delivery_class_latest')

    op.drop_table('report_deliveries')
    with op.batch_alter_table('enrollments', schema=None) as batch_op:
        batch_op.drop_index('ix_enrollment_class_period')

    op.drop_table('enrollments')
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_attendance_date'))

    op.drop_table('attendance')
    op.drop_table('user_roles')
    with op.batch_alter_table('students', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_students_class_id'))

    op.drop_table('students')
    op.drop_table('report_schedules')
    with op.batch_alter_table('report_recipients', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_report_recipients_class_id'))

    op.drop_table('report_recipients')
    with op.batch_alter_table('manager_assignments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_manager_assignments_class_id'))

    op.drop_table('manager_assignments')
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_logs_timestamp'))

    op.drop_table('audit_logs')
    op.drop_table('users')
    op.drop_table('classes')
