"""add guild_id and channel_id to webhook_configs

Revision ID: 003
Revises: 002
Create Date: 2026-02-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("webhook_configs", sa.Column("guild_id", sa.String(), nullable=True))
    op.add_column("webhook_configs", sa.Column("channel_id", sa.String(), nullable=True))
    op.create_index(op.f("ix_webhook_configs_guild_id"), "webhook_configs", ["guild_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_webhook_configs_guild_id"), table_name="webhook_configs")
    op.drop_column("webhook_configs", "channel_id")
    op.drop_column("webhook_configs", "guild_id")
