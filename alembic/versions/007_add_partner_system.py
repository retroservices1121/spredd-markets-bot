"""Add partner revenue sharing system

Revision ID: 007_partner
Revises: 006_delete_stale_position
Create Date: 2026-01-13

Adds:
- Partners table for partner entities
- Partner_groups table for group-partner mapping
- Partner attribution fields to users table
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '007_partner'
down_revision: Union[str, None] = '006_stale_pos'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Helper to check if column exists
    def column_exists(table, column):
        result = conn.execute(sa.text(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{table}' AND column_name = '{column}'"
        ))
        return result.fetchone() is not None

    # Helper to check if table exists
    def table_exists(table):
        result = conn.execute(sa.text(
            f"SELECT table_name FROM information_schema.tables "
            f"WHERE table_name = '{table}'"
        ))
        return result.fetchone() is not None

    # Create partners table if not exists
    if not table_exists('partners'):
        op.create_table(
            'partners',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('code', sa.String(32), nullable=False, unique=True),
            sa.Column('telegram_user_id', sa.BigInteger(), nullable=True),
            sa.Column('telegram_username', sa.String(255), nullable=True),
            sa.Column('contact_info', sa.Text(), nullable=True),
            sa.Column('revenue_share_bps', sa.Integer(), nullable=False, server_default='1000'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('total_users', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('total_volume_usdc', sa.String(78), nullable=False, server_default='0'),
            sa.Column('total_fees_usdc', sa.String(78), nullable=False, server_default='0'),
            sa.Column('total_paid_usdc', sa.String(78), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        )
        op.execute("CREATE INDEX IF NOT EXISTS ix_partners_code ON partners (code)")

    # Create partner_groups table if not exists
    if not table_exists('partner_groups'):
        op.create_table(
            'partner_groups',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('partner_id', sa.String(36), sa.ForeignKey('partners.id', ondelete='CASCADE'), nullable=False),
            sa.Column('telegram_chat_id', sa.BigInteger(), nullable=False, unique=True),
            sa.Column('chat_title', sa.String(255), nullable=True),
            sa.Column('chat_type', sa.String(32), nullable=False, server_default='group'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('bot_removed', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('revenue_share_bps', sa.Integer(), nullable=True),  # Per-group override, falls back to partner default
            sa.Column('users_attributed', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        )
        op.execute("CREATE INDEX IF NOT EXISTS ix_partner_groups_chat_id ON partner_groups (telegram_chat_id)")

    # Add partner attribution columns to users table
    if not column_exists('users', 'partner_id'):
        op.add_column('users', sa.Column('partner_id', sa.String(36), nullable=True))
        op.execute("CREATE INDEX IF NOT EXISTS ix_users_partner_id ON users (partner_id)")
        op.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_users_partner') THEN
                    ALTER TABLE users ADD CONSTRAINT fk_users_partner
                    FOREIGN KEY (partner_id) REFERENCES partners(id) ON DELETE SET NULL;
                END IF;
            END $$;
        """)

    if not column_exists('users', 'partner_group_id'):
        op.add_column('users', sa.Column('partner_group_id', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    # Remove partner attribution from users
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_users_partner') THEN
                ALTER TABLE users DROP CONSTRAINT fk_users_partner;
            END IF;
        END $$;
    """)
    op.execute("DROP INDEX IF EXISTS ix_users_partner_id")
    op.drop_column('users', 'partner_group_id')
    op.drop_column('users', 'partner_id')

    # Drop partner_groups table
    op.execute("DROP INDEX IF EXISTS ix_partner_groups_chat_id")
    op.drop_table('partner_groups')

    # Drop partners table
    op.execute("DROP INDEX IF EXISTS ix_partners_code")
    op.drop_table('partners')
