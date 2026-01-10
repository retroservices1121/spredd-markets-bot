"""Add chain-specific fee tracking

Revision ID: 004_chain_fees
Revises: 003_fix_pin
Create Date: 2026-01-10

Adds chain_family column to fee_balances and fee_transactions tables
to track earnings separately for Solana vs EVM chains.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004_chain_fees'
down_revision: Union[str, None] = '003_fix_pin'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The chainfamily enum already exists from wallets table
    # It uses uppercase values: 'SOLANA', 'EVM'

    # Check if chain_family column already exists on fee_balances
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'fee_balances' AND column_name = 'chain_family'"
    ))
    column_exists = result.fetchone() is not None

    if not column_exists:
        # Add chain_family column to fee_balances (using existing enum with uppercase values)
        op.add_column(
            'fee_balances',
            sa.Column('chain_family', sa.Enum('SOLANA', 'EVM', name='chainfamily', create_type=False), nullable=True)
        )

        # Set default value for existing records (uppercase!)
        op.execute("UPDATE fee_balances SET chain_family = 'EVM' WHERE chain_family IS NULL")

        # Make column non-nullable
        op.alter_column('fee_balances', 'chain_family', nullable=False, server_default='EVM')

    # Drop old unique constraint on user_id if it exists
    op.execute("ALTER TABLE fee_balances DROP CONSTRAINT IF EXISTS fee_balances_user_id_key")

    # Create new unique index on (user_id, chain_family) if not exists
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_fee_balances_user_chain
        ON fee_balances (user_id, chain_family)
    """)

    # Check if chain_family column already exists on fee_transactions
    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'fee_transactions' AND column_name = 'chain_family'"
    ))
    column_exists = result.fetchone() is not None

    if not column_exists:
        # Add chain_family column to fee_transactions
        op.add_column(
            'fee_transactions',
            sa.Column('chain_family', sa.Enum('SOLANA', 'EVM', name='chainfamily', create_type=False), nullable=True)
        )

        # Set default value for existing records (uppercase!)
        op.execute("UPDATE fee_transactions SET chain_family = 'EVM' WHERE chain_family IS NULL")

        # Make column non-nullable
        op.alter_column('fee_transactions', 'chain_family', nullable=False, server_default='EVM')

    # Create index on chain_family if not exists
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_fee_tx_chain
        ON fee_transactions (chain_family)
    """)


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_fee_tx_chain', table_name='fee_transactions')
    op.drop_index('ix_fee_balances_user_chain', table_name='fee_balances')

    # Drop columns
    op.drop_column('fee_transactions', 'chain_family')
    op.drop_column('fee_balances', 'chain_family')

    # Re-add unique constraint on user_id only
    op.create_unique_constraint('fee_balances_user_id_key', 'fee_balances', ['user_id'])
