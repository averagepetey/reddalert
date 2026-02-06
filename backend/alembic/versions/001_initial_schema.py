"""initial_schema

Revision ID: 001
Revises:
Create Date: 2026-02-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID, ARRAY

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- clients ---
    op.create_table(
        "clients",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("api_key", sa.String(), unique=True, nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("polling_interval", sa.Integer(), server_default="60", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- keywords ---
    op.create_table(
        "keywords",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "client_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phrases", ARRAY(sa.String()), nullable=False),
        sa.Column("exclusions", ARRAY(sa.String()), nullable=True),
        sa.Column("proximity_window", sa.Integer(), server_default="15", nullable=False),
        sa.Column("require_order", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("use_stemming", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_keywords_client_id", "keywords", ["client_id"])

    # --- monitored_subreddits ---
    subreddit_status = sa.Enum("active", "inaccessible", "private", name="subreddit_status")
    subreddit_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "monitored_subreddits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "client_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "status",
            subreddit_status,
            server_default="active",
            nullable=False,
        ),
        sa.Column("include_media_posts", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("dedupe_crossposts", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("filter_bots", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_monitored_subreddits_client_id", "monitored_subreddits", ["client_id"])

    # --- webhook_configs ---
    op.create_table(
        "webhook_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "client_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_webhook_configs_client_id", "webhook_configs", ["client_id"])

    # --- reddit_content ---
    content_type = sa.Enum("post", "comment", name="content_type")
    content_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "reddit_content",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("reddit_id", sa.String(), unique=True, nullable=False),
        sa.Column("subreddit", sa.String(), nullable=False),
        sa.Column("content_type", content_type, nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(), unique=True, nullable=False),
        sa.Column("reddit_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index("ix_reddit_content_reddit_id", "reddit_content", ["reddit_id"])
    op.create_index("ix_reddit_content_subreddit", "reddit_content", ["subreddit"])
    op.create_index("ix_reddit_content_content_hash", "reddit_content", ["content_hash"])

    # --- matches ---
    alert_status = sa.Enum("pending", "sent", "failed", name="alert_status")
    alert_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "matches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "client_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "keyword_id",
            UUID(as_uuid=True),
            sa.ForeignKey("keywords.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "content_id",
            UUID(as_uuid=True),
            sa.ForeignKey("reddit_content.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content_type", content_type, nullable=False),
        sa.Column("subreddit", sa.String(), nullable=False),
        sa.Column("matched_phrase", sa.String(), nullable=False),
        sa.Column("also_matched", ARRAY(sa.String()), nullable=True),
        sa.Column("snippet", sa.String(200), nullable=False),
        sa.Column("full_text", sa.Text(), nullable=False),
        sa.Column("proximity_score", sa.Float(), nullable=True),
        sa.Column("reddit_url", sa.String(), nullable=False),
        sa.Column("reddit_author", sa.String(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("alert_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "alert_status",
            alert_status,
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_matches_client_id", "matches", ["client_id"])
    op.create_index("ix_matches_subreddit", "matches", ["subreddit"])
    op.create_index("ix_matches_alert_status", "matches", ["alert_status"])


def downgrade() -> None:
    op.drop_table("matches")
    op.drop_table("reddit_content")
    op.drop_table("webhook_configs")
    op.drop_table("monitored_subreddits")
    op.drop_table("keywords")
    op.drop_table("clients")

    op.execute("DROP TYPE IF EXISTS alert_status")
    op.execute("DROP TYPE IF EXISTS content_type")
    op.execute("DROP TYPE IF EXISTS subreddit_status")
