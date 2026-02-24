"""Add Privy wallet integration columns

Revision ID: 018_privy_wallets
Revises: 017_jupiter_platform
Create Date: 2026-02-23

Adds columns for Privy server-managed wallets:
- users.privy_user_id: Privy user ID (did:privy:...)
- wallets.privy_wallet_id: Privy wallet ID
- wallets.wallet_type: "legacy" or "privy"
- wallets.encrypted_private_key: made nullable (Privy wallets don't store keys)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '018_privy_wallets'
down_revision: Union[str, None] = '017_jupiter_platform'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users table: add privy_user_id
    op.add_column('users', sa.Column('privy_user_id', sa.String(255), nullable=True))
    op.create_unique_constraint('uq_users_privy_user_id', 'users', ['privy_user_id'])

    # Wallets table: add privy columns and wallet_type
    op.add_column('wallets', sa.Column('wallet_type', sa.String(20), nullable=False, server_default='legacy'))
    op.add_column('wallets', sa.Column('privy_wallet_id', sa.String(255), nullable=True))
    op.create_unique_constraint('uq_wallets_privy_wallet_id', 'wallets', ['privy_wallet_id'])

    # Make encrypted_private_key nullable (Privy wallets don't have local keys)
    op.alter_column('wallets', 'encrypted_private_key', existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    # Revert encrypted_private_key to non-nullable (delete Privy wallets first)
    op.execute("DELETE FROM wallets WHERE wallet_type = 'privy'")
    op.alter_column('wallets', 'encrypted_private_key', existing_type=sa.Text(), nullable=False)

    # Drop wallet columns
    op.drop_constraint('uq_wallets_privy_wallet_id', 'wallets', type_='unique')
    op.drop_column('wallets', 'privy_wallet_id')
    op.drop_column('wallets', 'wallet_type')

    # Drop user column
    op.drop_constraint('uq_users_privy_user_id', 'users', type_='unique')
    op.drop_column('users', 'privy_user_id')
