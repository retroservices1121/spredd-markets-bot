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
    # Add referral columns to users table
    op.add_column('users', sa.Column('referral_code', sa.String(32), nullable=True))
    op.add_column('users', sa.Column('referred_by_id', sa.String(36), nullable=True))

    # Create indexes and foreign key for referral fields
    op.create_index('ix_users_referral_code', 'users', ['referral_code'], unique=True)
    op.create_foreign_key(
        'fk_users_referred_by',
        'users', 'users',
        ['referred_by_id'], ['id'],
        ondelete='SET NULL'
    )

    # Add pin_protected column to wallets table
    op.add_column('wallets', sa.Column('pin_protected', sa.Boolean(), nullable=False, server_default='false'))

    # Create fee_balances table
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

    # Create fee_transactions table
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

    # Create indexes for fee_transactions
    op.create_index('ix_fee_tx_user', 'fee_transactions', ['user_id'])
    op.create_index('ix_fee_tx_type', 'fee_transactions', ['tx_type'])
    op.create_index('ix_fee_tx_order', 'fee_transactions', ['order_id'])


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
