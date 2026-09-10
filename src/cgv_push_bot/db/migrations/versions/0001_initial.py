from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "monitor_targets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("theater_id", sa.String(length=64), nullable=False),
        sa.Column("theater_name", sa.String(length=255), nullable=False),
        sa.Column("show_date", sa.Date(), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("theater_id", "show_date", name="uq_monitor_targets_theater_date"),
    )
    op.create_index(
        "ix_monitor_targets_next_poll_at",
        "monitor_targets",
        ["next_poll_at"],
        unique=False,
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("discord_user_id", sa.String(length=32), nullable=False),
        sa.Column("guild_id", sa.String(length=32), nullable=True),
        sa.Column("channel_id", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(length=255), nullable=False),
        sa.Column("normalized_keyword", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "expired",
                name="subscription_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["target_id"], ["monitor_targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "discord_user_id",
            "channel_id",
            "target_id",
            "normalized_keyword",
            name="uq_subscriptions_owner_channel_target_keyword",
        ),
    )
    op.create_index(
        "ix_subscriptions_user_status",
        "subscriptions",
        ["discord_user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_subscriptions_target_status",
        "subscriptions",
        ["target_id", "status"],
        unique=False,
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "sent",
                "failed",
                name="notification_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("discord_message_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notifications_status_retry",
        "notifications",
        ["status", "next_retry_at"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_subscription",
        "notifications",
        ["subscription_id"],
        unique=False,
    )

    op.create_table(
        "subscription_movies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.String(length=64), nullable=False),
        sa.Column("movie_title", sa.String(length=255), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_baseline", sa.Boolean(), nullable=False),
        sa.Column("notification_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subscription_id",
            "movie_id",
            name="uq_subscription_movies_subscription_movie",
        ),
    )
    op.create_index(
        "ix_subscription_movies_notification",
        "subscription_movies",
        ["notification_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_subscription_movies_notification", table_name="subscription_movies")
    op.drop_table("subscription_movies")
    op.drop_index("ix_notifications_subscription", table_name="notifications")
    op.drop_index("ix_notifications_status_retry", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_subscriptions_target_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_user_status", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index("ix_monitor_targets_next_poll_at", table_name="monitor_targets")
    op.drop_table("monitor_targets")
