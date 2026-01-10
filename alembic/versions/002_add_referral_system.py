"""Add referral system and fee tracking

Revision ID: 002_referral
Revises: 001_initial
Create Date: 2025-01-10

Adds:
- Referral fields to users table (referral_code, referred_by_id)
- PIN protection field to wallets table
- Fee balances table for tracking referral earnings
- Fee transactions table for audit trail
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_referral'
down_revision: Union[str, None] = '001_initial'
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

    # Add referral columns to users table
    if not column_exists('users', 'referral_code'):
        op.add_column('users', sa.Column('referral_code', sa.String(32), nullable=True))
    if not column_exists('users', 'referred_by_id'):
        op.add_column('users', sa.Column('referred_by_id', sa.String(36), nullable=True))

    # Create indexes and foreign key for referral fields (idempotent)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_referral_code ON users (referral_code)")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_users_referred_by') THEN
                ALTER TABLE users ADD CONSTRAINT fk_users_referred_by
                FOREIGN KEY (referred_by_id) REFERENCES users(id) ON DELETE SET NULL;
            END IF;
        END $$;
    """)

    # Add pin_protected column to wallets table
    if not column_exists('wallets', 'pin_protected'):
        op.add_column('wallets', sa.Column('pin_protected', sa.Boolean(), nullable=False, server_default='false'))

    # Create fee_balances table if not exists
    if not table_exists('fee_balances'):
        op.create_table(
            'fee_balances',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True),
            sa.Column('claimable_usdc', sa.String(78), nullable=False, server_default='0'),
            sa.Column('total_earned_usdc', sa.String(78), nullable=False, server_default='0'),
            sa.Column('total_withdrawn_usdc', sa.String(78), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        )

    # Create fee_transactions table if not exists
    if not table_exists('fee_transactions'):
        op.create_table(
            'fee_transactions',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('order_id', sa.String(36), sa.ForeignKey('orders.id'), nullable=True),
            sa.Column('tx_type', sa.String(32), nullable=False),
            sa.Column('amount_usdc', sa.String(78), nullable=False),
            sa.Column('source_user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('tier', sa.Integer(), nullable=True),
            sa.Column('withdrawal_tx_hash', sa.String(255), nullable=True),
            sa.Column('withdrawal_address', sa.String(255), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    # Create indexes for fee_transactions (idempotent)
    op.execute("CREATE INDEX IF NOT EXISTS ix_fee_tx_user ON fee_transactions (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_fee_tx_type ON fee_transactions (tx_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_fee_tx_order ON fee_transactions (order_id)")


def downgrade() -> None:
    # Drop fee_transactions indexes and table
    op.drop_index('ix_fee_tx_order', table_name='fee_transactions')
    op.drop_index('ix_fee_tx_type', table_name='fee_transactions')
    op.drop_index('ix_fee_tx_user', table_name='fee_transactions')
    op.drop_table('fee_transactions')

    # Drop fee_balances table
    op.drop_table('fee_balances')

    # Remove pin_protected from wallets
    op.drop_column('wallets', 'pin_protected')

    # Remove referral columns from users
    op.drop_constraint('fk_users_referred_by', 'users', type_='foreignkey')
    op.drop_index('ix_users_referral_code', table_name='users')
    op.drop_column('users', 'referred_by_id')
    op.drop_column('users', 'referral_code')
