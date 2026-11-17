"""Add school settings, class archive dates and access controls for Mini App."""

from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('blocked', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('classes', sa.Column('archived_on', sa.Date(), nullable=True))
    op.add_column('report_schedules', sa.Column('deleted', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('school_settings', sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('name', sa.String(120), nullable=False))


def downgrade():
    op.drop_table('school_settings')
    op.drop_column('report_schedules', 'deleted')
    op.drop_column('classes', 'archived_on')
    op.drop_column('users', 'blocked')
