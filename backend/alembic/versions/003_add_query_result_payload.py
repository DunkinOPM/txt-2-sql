"""add result_columns and result_rows to app_queries

Revision ID: 003_result_payload
Revises: 002_ready_for_sql
Create Date: 2026-10-26 16:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '003_result_payload'
down_revision: Union[str, None] = '002_ready_for_sql'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'app_queries',
        sa.Column('result_columns', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema='app'
    )
    op.add_column(
        'app_queries',
        sa.Column('result_rows', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema='app'
    )


def downgrade() -> None:
    op.drop_column('app_queries', 'result_rows', schema='app')
    op.drop_column('app_queries', 'result_columns', schema='app')
