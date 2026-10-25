import uuid
from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    CheckConstraint,
    UniqueConstraint,
    Index,
    text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class AppDataset(Base):
    __tablename__ = "app_datasets"
    __table_args__ = (
        CheckConstraint("file_format IN ('csv', 'xlsx')", name="chk_dataset_file_format"),
        CheckConstraint(
            "status IN ('uploading', 'importing', 'ready', 'failed', 'deleting')",
            name="chk_dataset_status"
        ),
        CheckConstraint("row_count >= 0", name="chk_dataset_row_count"),
        CheckConstraint("column_count >= 0", name="chk_dataset_column_count"),
        Index("idx_app_datasets_owner_created", "owner_id", text("created_at DESC")),
        {"schema": "app"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(String, nullable=False)
    display_name = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    file_format = Column(String, nullable=False)
    status = Column(String, nullable=False)
    row_count = Column(BigInteger, nullable=False, default=0)
    column_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    error_code = Column(String, nullable=True)
    error_message = Column(String, nullable=True)

    # Relationships
    table_mapping = relationship("AppDatasetTable", back_populates="dataset", uselist=False, cascade="all, delete-orphan")
    columns = relationship("AppDatasetColumn", back_populates="dataset", cascade="all, delete-orphan", order_by="AppDatasetColumn.ordinal_position")
    queries = relationship("AppQuery", back_populates="dataset", cascade="all, delete-orphan")


class AppDatasetTable(Base):
    __tablename__ = "app_dataset_tables"
    __table_args__ = (
        {"schema": "app"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("app.app_datasets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True
    )
    schema_name = Column(String, nullable=False, default="uploaded_data")
    table_name = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    dataset = relationship("AppDataset", back_populates="table_mapping")


class AppDatasetColumn(Base):
    __tablename__ = "app_dataset_columns"
    __table_args__ = (
        CheckConstraint("ordinal_position > 0", name="chk_column_ordinal_position"),
        UniqueConstraint("dataset_id", "ordinal_position", name="uq_dataset_column_ordinal"),
        UniqueConstraint("dataset_id", "internal_name", name="uq_dataset_column_internal_name"),
        {"schema": "app"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("app.app_datasets.id", ondelete="CASCADE"),
        nullable=False
    )
    ordinal_position = Column(Integer, nullable=False)
    original_name = Column(String, nullable=False)
    internal_name = Column(String, nullable=False)
    inferred_type = Column(String, nullable=False)
    nullable = Column(Boolean, nullable=False, default=True)
    sample_values = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    dataset = relationship("AppDataset", back_populates="columns")


class AppQuery(Base):
    __tablename__ = "app_queries"
    __table_args__ = (
        CheckConstraint(
            "category IN ('RELEVANT_CLEAR', 'RELEVANT_AMBIGUOUS', 'RELEVANT_UNANSWERABLE', 'OUT_OF_SCOPE', 'NONSENSICAL', 'IMPROPER_OR_UNSAFE')",
            name="chk_query_category"
        ),
        CheckConstraint(
            "status IN ('classifying', 'awaiting_clarification', 'generating_sql', 'validating_sql', 'executing', 'completed', 'rejected', 'failed')",
            name="chk_query_status"
        ),
        Index("idx_app_queries_owner_created", "owner_id", text("created_at DESC")),
        Index("idx_app_queries_dataset_created", "dataset_id", text("created_at DESC")),
        {"schema": "app"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("app.app_datasets.id", ondelete="CASCADE"),
        nullable=False
    )
    owner_id = Column(String, nullable=False)
    original_question = Column(String, nullable=False)
    refined_question = Column(String, nullable=True)
    category = Column(String, nullable=True)
    status = Column(String, nullable=False)
    generated_sql = Column(String, nullable=True)
    explanation = Column(String, nullable=True)
    result_row_count = Column(BigInteger, nullable=True)
    execution_duration_ms = Column(Integer, nullable=True)
    error_code = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    dataset = relationship("AppDataset", back_populates="queries")
    turns = relationship("AppQueryTurn", back_populates="query", cascade="all, delete-orphan", order_by="AppQueryTurn.turn_number")


class AppQueryTurn(Base):
    __tablename__ = "app_query_turns"
    __table_args__ = (
        CheckConstraint("turn_number > 0", name="chk_turn_number"),
        CheckConstraint("role IN ('assistant', 'user', 'system')", name="chk_turn_role"),
        CheckConstraint(
            "turn_type IN ('question', 'clarification', 'clarification_answer', 'status', 'explanation')",
            name="chk_turn_type"
        ),
        UniqueConstraint("query_id", "turn_number", name="uq_query_turn_number"),
        Index("idx_app_query_turns_query_turn", "query_id", "turn_number"),
        {"schema": "app"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_id = Column(
        UUID(as_uuid=True),
        ForeignKey("app.app_queries.id", ondelete="CASCADE"),
        nullable=False
    )
    turn_number = Column(Integer, nullable=False)
    role = Column(String, nullable=False)
    turn_type = Column(String, nullable=False)
    content = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    query = relationship("AppQuery", back_populates="turns")

