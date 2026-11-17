"""Persist administrative preferences, delegated permissions and delivery diagnostics."""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('school_settings', sa.Column('preferences', sa.JSON(), nullable=True))
    for column in ('can_edit_history', 'can_view_statistics', 'can_view_reports'):
        op.add_column('manager_assignments', sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('announcements',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('request_id', sa.String(32), nullable=False, unique=True),
                    sa.Column('class_ids', sa.JSON(), nullable=False),
                    sa.Column('message', sa.String(500), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_table('system_events',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('operation', sa.String(24), nullable=False),
                    sa.Column('success', sa.Boolean(), nullable=False),
                    sa.Column('occurred_at', sa.DateTime(), nullable=False))
    with op.batch_alter_table('notifications') as batch:
        batch.add_column(sa.Column('announcement_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_notification_announcement', 'announcements', ['announcement_id'], ['id'])
        batch.create_index('ix_notifications_announcement_id', ['announcement_id'])


def downgrade():
    with op.batch_alter_table('notifications') as batch:
        batch.drop_index('ix_notifications_announcement_id')
        batch.drop_constraint('fk_notification_announcement', type_='foreignkey')
        batch.drop_column('announcement_id')
    op.drop_table('system_events')
    op.drop_table('announcements')
    op.drop_column('manager_assignments', 'can_view_reports')
    op.drop_column('manager_assignments', 'can_view_statistics')
    op.drop_column('manager_assignments', 'can_edit_history')
    op.drop_column('school_settings', 'preferences')
