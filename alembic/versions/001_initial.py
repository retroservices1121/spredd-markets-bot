"""Initial schema

Revision ID: 001_initial
Revises: 
Create Date: 2025-01-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types
    op.execute("CREATE TYPE chainfamily AS ENUM ('solana', 'evm')")
    op.execute("CREATE TYPE platform AS ENUM ('kalshi', 'polymarket', 'opinion')")
    op.execute("CREATE TYPE chain AS ENUM ('solana', 'polygon', 'bsc')")
    op.execute("CREATE TYPE outcome AS ENUM ('yes', 'no')")
    op.execute("CREATE TYPE orderside AS ENUM ('buy', 'sell')")
    op.execute("CREATE TYPE orderstatus AS ENUM ('pending', 'submitted', 'confirmed', 'failed', 'cancelled')")
    op.execute("CREATE TYPE positionstatus AS ENUM ('open', 'closed', 'redeemed', 'expired')")
    
    # Users table
    op.create_table(
        'users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False, unique=True, index=True),
        sa.Column('username', sa.String(255), nullable=True),
        sa.Column('first_name', sa.String(255), nullable=True),
        sa.Column('last_name', sa.String(255), nullable=True),
        sa.Column('active_platform', sa.Enum('kalshi', 'polymarket', 'opinion', name='platform'), 
                  nullable=False, server_default='kalshi'),
        sa.Column('default_slippage_bps', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # Wallets table
    op.create_table(
        'wallets',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chain_family', sa.Enum('solana', 'evm', name='chainfamily'), nullable=False),
        sa.Column('public_key', sa.String(255), nullable=False, index=True),
        sa.Column('encrypted_private_key', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_wallets_user_chain', 'wallets', ['user_id', 'chain_family'], unique=True)
    
    # Positions table
    op.create_table(
        'positions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('platform', sa.Enum('kalshi', 'polymarket', 'opinion', name='platform'), nullable=False),
        sa.Column('chain', sa.Enum('solana', 'polygon', 'bsc', name='chain'), nullable=False),
        sa.Column('market_id', sa.String(255), nullable=False),
        sa.Column('market_title', sa.Text(), nullable=False),
        sa.Column('event_id', sa.String(255), nullable=True),
        sa.Column('outcome', sa.Enum('yes', 'no', name='outcome'), nullable=False),
        sa.Column('token_id', sa.String(255), nullable=False),
        sa.Column('token_amount', sa.String(78), nullable=False),
        sa.Column('entry_price', sa.Numeric(18, 8), nullable=False),
        sa.Column('current_price', sa.Numeric(18, 8), nullable=True),
        sa.Column('status', sa.Enum('open', 'closed', 'redeemed', 'expired', name='positionstatus'), 
                  nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('redeemed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_positions_user_status', 'positions', ['user_id', 'status'])
    op.create_index('ix_positions_market', 'positions', ['market_id'])
    
    # Orders table
    op.create_table(
        'orders',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('platform', sa.Enum('kalshi', 'polymarket', 'opinion', name='platform'), nullable=False),
        sa.Column('chain', sa.Enum('solana', 'polygon', 'bsc', name='chain'), nullable=False),
        sa.Column('market_id', sa.String(255), nullable=False),
        sa.Column('event_id', sa.String(255), nullable=True),
        sa.Column('outcome', sa.Enum('yes', 'no', name='outcome'), nullable=False),
        sa.Column('side', sa.Enum('buy', 'sell', name='orderside'), nullable=False),
        sa.Column('input_token', sa.String(255), nullable=False),
        sa.Column('input_amount', sa.String(78), nullable=False),
        sa.Column('output_token', sa.String(255), nullable=False),
        sa.Column('expected_output', sa.String(78), nullable=False),
        sa.Column('actual_output', sa.String(78), nullable=True),
        sa.Column('price', sa.Numeric(18, 8), nullable=True),
        sa.Column('status', sa.Enum('pending', 'submitted', 'confirmed', 'failed', 'cancelled', name='orderstatus'),
                  nullable=False, server_default='pending'),
        sa.Column('tx_hash', sa.String(255), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_orders_user_status', 'orders', ['user_id', 'status'])
    op.create_index('ix_orders_tx', 'orders', ['tx_hash'])
    
    # Market cache table
    op.create_table(
        'market_cache',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('platform', sa.Enum('kalshi', 'polymarket', 'opinion', name='platform'), nullable=False),
        sa.Column('market_id', sa.String(255), nullable=False),
        sa.Column('event_id', sa.String(255), nullable=True),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(255), nullable=True),
        sa.Column('yes_price', sa.Numeric(18, 8), nullable=True),
        sa.Column('no_price', sa.Numeric(18, 8), nullable=True),
        sa.Column('volume_24h', sa.String(78), nullable=True),
        sa.Column('liquidity', sa.String(78), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('close_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('yes_token', sa.String(255), nullable=True),
        sa.Column('no_token', sa.String(255), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_market_cache_platform_market', 'market_cache', ['platform', 'market_id'], unique=True)
    op.create_index('ix_market_cache_active', 'market_cache', ['is_active'])


def downgrade() -> None:
    # Drop tables
    op.drop_table('market_cache')
    op.drop_table('orders')
    op.drop_table('positions')
    op.drop_table('wallets')
    op.drop_table('users')
    
    # Drop enum types
    op.execute("DROP TYPE positionstatus")
    op.execute("DROP TYPE orderstatus")
    op.execute("DROP TYPE orderside")
    op.execute("DROP TYPE outcome")
    op.execute("DROP TYPE chain")
    op.execute("DROP TYPE platform")
    op.execute("DROP TYPE chainfamily")
