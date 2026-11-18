"""Store whole student names and identify manual report deliveries."""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('students', sa.Column('full_name', sa.String(255), nullable=False, server_default=''))
    op.execute("UPDATE students SET full_name = trim(last_name || ' ' || first_name)")
    if op.get_context().dialect.name == 'postgresql':
        op.alter_column('students', 'active_name_key', type_=sa.String(765), existing_type=sa.String(200))
        op.add_column('report_deliveries', sa.Column('initiated_by', sa.Integer(), sa.ForeignKey('users.id')))
    else:
        op.execute('ALTER TABLE report_deliveries ADD COLUMN initiated_by INTEGER REFERENCES users(id)')
    op.add_column('report_deliveries', sa.Column('telegram_message_id', sa.BigInteger()))
    op.add_column('manager_assignments', sa.Column('can_send_reports', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    # Preserve full names when restoring the legacy reader, including names longer than its original fields.
    if op.get_context().dialect.name == 'postgresql':
        op.alter_column('students', 'last_name', type_=sa.String(255), existing_type=sa.String(48))
    op.execute("UPDATE students SET last_name = full_name, first_name = '' "
               "WHERE full_name <> '' AND full_name <> trim(last_name || ' ' || first_name)")
    op.drop_column('students', 'full_name')
    op.drop_column('report_deliveries', 'initiated_by')
    op.drop_column('report_deliveries', 'telegram_message_id')
    op.drop_column('manager_assignments', 'can_send_reports')
