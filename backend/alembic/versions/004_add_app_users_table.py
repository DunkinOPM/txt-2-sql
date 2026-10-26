"""create app_users table for authentication and ownership

Revision ID: 004_app_users
Revises: 003_result_payload
Create Date: 2026-10-27 02:25:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '004_app_users'
down_revision: Union[str, None] = '003_result_payload'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'app_users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('username', sa.String(length=100), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        schema='app'
    )
    op.create_index('idx_app_users_email', 'app_users', ['email'], unique=True, schema='app')
    op.create_index('idx_app_users_username', 'app_users', ['username'], unique=True, schema='app')
    op.create_index(
        'idx_app_users_email_lower',
        'app_users',
        [sa.text('lower(email)')],
        unique=True,
        schema='app'
    )
    op.create_index(
        'idx_app_users_username_lower',
        'app_users',
        [sa.text('lower(username)')],
        unique=True,
        schema='app'
    )

    # Security: explicitly revoke all access on app_users from readonly_user
    op.execute("REVOKE ALL ON TABLE app.app_users FROM readonly_user;")


def downgrade() -> None:
    op.drop_index('idx_app_users_username_lower', table_name='app_users', schema='app')
    op.drop_index('idx_app_users_email_lower', table_name='app_users', schema='app')
    op.drop_index('idx_app_users_username', table_name='app_users', schema='app')
    op.drop_index('idx_app_users_email', table_name='app_users', schema='app')
    op.drop_table('app_users', schema='app')
