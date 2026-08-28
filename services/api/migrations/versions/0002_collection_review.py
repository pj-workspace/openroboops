"""Add persisted collection review state.

Revision ID: 0002_collection_review
Revises: 0001_initial
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_collection_review"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("collection_sessions")}
    if "review_status" not in columns:
        op.add_column(
            "collection_sessions",
            sa.Column("review_status", sa.String(length=40), nullable=False, server_default="pending"),
        )
    if "reviewed_at" not in columns:
        op.add_column(
            "collection_sessions",
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        )
    indexes = {index["name"] for index in inspector.get_indexes("collection_sessions")}
    if "ix_collection_sessions_review_status" not in indexes:
        op.create_index(
            "ix_collection_sessions_review_status",
            "collection_sessions",
            ["review_status"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("collection_sessions")}
    if "ix_collection_sessions_review_status" in indexes:
        op.drop_index("ix_collection_sessions_review_status", table_name="collection_sessions")
    columns = {column["name"] for column in inspector.get_columns("collection_sessions")}
    if "reviewed_at" in columns:
        op.drop_column("collection_sessions", "reviewed_at")
    if "review_status" in columns:
        op.drop_column("collection_sessions", "review_status")
