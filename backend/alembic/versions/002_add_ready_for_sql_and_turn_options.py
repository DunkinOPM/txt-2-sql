"""add ready_for_sql to chk_query_status and clarification_options to app_query_turns

Revision ID: 002_ready_for_sql
Revises: 001_initial_metadata
Create Date: 2026-10-26 15:55:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '002_ready_for_sql'
down_revision: Union[str, None] = '001_initial_metadata'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update chk_query_status check constraint to include ready_for_sql
    op.drop_constraint('chk_query_status', 'app_queries', schema='app', type_='check')
    op.create_check_constraint(
        'chk_query_status',
        'app_queries',
        "status IN ('classifying', 'awaiting_clarification', 'ready_for_sql', 'generating_sql', 'validating_sql', 'executing', 'completed', 'rejected', 'failed')",
        schema='app'
    )

    # 2. Add clarification_options JSONB column to app_query_turns for persistent state reconstruction
    op.add_column(
        'app_query_turns',
        sa.Column('clarification_options', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema='app'
    )


def downgrade() -> None:
    op.drop_column('app_query_turns', 'clarification_options', schema='app')
    op.drop_constraint('chk_query_status', 'app_queries', schema='app', type_='check')
    op.create_check_constraint(
        'chk_query_status',
        'app_queries',
        "status IN ('classifying', 'awaiting_clarification', 'generating_sql', 'validating_sql', 'executing', 'completed', 'rejected', 'failed')",
        schema='app'
    )
