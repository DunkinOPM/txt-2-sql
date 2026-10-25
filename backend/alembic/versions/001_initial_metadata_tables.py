"""initial metadata tables

Revision ID: 001_initial_metadata
Revises: 
Create Date: 2026-10-25 19:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '001_initial_metadata'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. app_datasets
    op.create_table(
        'app_datasets',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('owner_id', sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('original_filename', sa.String(), nullable=False),
        sa.Column('file_format', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('row_count', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('column_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('error_code', sa.String(), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.CheckConstraint("file_format IN ('csv', 'xlsx')", name='chk_dataset_file_format'),
        sa.CheckConstraint("status IN ('uploading', 'importing', 'ready', 'failed', 'deleting')", name='chk_dataset_status'),
        sa.CheckConstraint('row_count >= 0', name='chk_dataset_row_count'),
        sa.CheckConstraint('column_count >= 0', name='chk_dataset_column_count'),
        schema='app'
    )
    op.create_index(
        'idx_app_datasets_owner_created',
        'app_datasets',
        ['owner_id', sa.text('created_at DESC')],
        unique=False,
        schema='app'
    )

    # 2. app_dataset_tables
    op.create_table(
        'app_dataset_tables',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('dataset_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('schema_name', sa.String(), server_default='uploaded_data', nullable=False),
        sa.Column('table_name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['dataset_id'], ['app.app_datasets.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('dataset_id'),
        sa.UniqueConstraint('table_name'),
        schema='app'
    )

    # 3. app_dataset_columns
    op.create_table(
        'app_dataset_columns',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('dataset_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('ordinal_position', sa.Integer(), nullable=False),
        sa.Column('original_name', sa.String(), nullable=False),
        sa.Column('internal_name', sa.String(), nullable=False),
        sa.Column('inferred_type', sa.String(), nullable=False),
        sa.Column('nullable', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('sample_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.CheckConstraint('ordinal_position > 0', name='chk_column_ordinal_position'),
        sa.ForeignKeyConstraint(['dataset_id'], ['app.app_datasets.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('dataset_id', 'ordinal_position', name='uq_dataset_column_ordinal'),
        sa.UniqueConstraint('dataset_id', 'internal_name', name='uq_dataset_column_internal_name'),
        schema='app'
    )

    # 4. app_queries
    op.create_table(
        'app_queries',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('dataset_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('owner_id', sa.String(), nullable=False),
        sa.Column('original_question', sa.String(), nullable=False),
        sa.Column('refined_question', sa.String(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('generated_sql', sa.String(), nullable=True),
        sa.Column('explanation', sa.String(), nullable=True),
        sa.Column('result_row_count', sa.BigInteger(), nullable=True),
        sa.Column('execution_duration_ms', sa.Integer(), nullable=True),
        sa.Column('error_code', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.CheckConstraint(
            "category IN ('RELEVANT_CLEAR', 'RELEVANT_AMBIGUOUS', 'RELEVANT_UNANSWERABLE', 'OUT_OF_SCOPE', 'NONSENSICAL', 'IMPROPER_OR_UNSAFE')",
            name='chk_query_category'
        ),
        sa.CheckConstraint(
            "status IN ('classifying', 'awaiting_clarification', 'generating_sql', 'validating_sql', 'executing', 'completed', 'rejected', 'failed')",
            name='chk_query_status'
        ),
        sa.ForeignKeyConstraint(['dataset_id'], ['app.app_datasets.id'], ondelete='CASCADE'),
        schema='app'
    )
    op.create_index(
        'idx_app_queries_owner_created',
        'app_queries',
        ['owner_id', sa.text('created_at DESC')],
        unique=False,
        schema='app'
    )
    op.create_index(
        'idx_app_queries_dataset_created',
        'app_queries',
        ['dataset_id', sa.text('created_at DESC')],
        unique=False,
        schema='app'
    )

    # 5. app_query_turns
    op.create_table(
        'app_query_turns',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('query_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('turn_number', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('turn_type', sa.String(), nullable=False),
        sa.Column('content', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.CheckConstraint('turn_number > 0', name='chk_turn_number'),
        sa.CheckConstraint("role IN ('assistant', 'user', 'system')", name='chk_turn_role'),
        sa.CheckConstraint(
            "turn_type IN ('question', 'clarification', 'clarification_answer', 'status', 'explanation')",
            name='chk_turn_type'
        ),
        sa.ForeignKeyConstraint(['query_id'], ['app.app_queries.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('query_id', 'turn_number', name='uq_query_turn_number'),
        schema='app'
    )
    op.create_index(
        'idx_app_query_turns_query_turn',
        'app_query_turns',
        ['query_id', 'turn_number'],
        unique=False,
        schema='app'
    )


def downgrade() -> None:
    op.drop_table('app_query_turns', schema='app')
    op.drop_table('app_queries', schema='app')
    op.drop_table('app_dataset_columns', schema='app')
    op.drop_table('app_dataset_tables', schema='app')
    op.drop_table('app_datasets', schema='app')

