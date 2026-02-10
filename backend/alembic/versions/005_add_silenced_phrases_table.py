"""add silenced_phrases table

Revision ID: 005
Revises: 004
Create Date: 2026-02-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "silenced_phrases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("keyword_id", UUID(as_uuid=True), sa.ForeignKey("keywords.id"), nullable=False),
        sa.Column("phrase", sa.String(), nullable=False),
        sa.Column("restore_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_silenced_phrases_keyword_id"), "silenced_phrases", ["keyword_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_silenced_phrases_keyword_id"), table_name="silenced_phrases")
    op.drop_table("silenced_phrases")
