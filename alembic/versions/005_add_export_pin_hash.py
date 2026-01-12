"""Add export_pin_hash to wallets

Revision ID: 005_export_pin
Revises: 004_chain_fees
Create Date: 2025-01-12

Adds export_pin_hash column to wallets table for PIN verification
during private key export. The PIN itself is never stored.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005_export_pin'
down_revision: Union[str, None] = '004_chain_fees'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add export_pin_hash column
    op.add_column(
        'wallets',
        sa.Column('export_pin_hash', sa.String(255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('wallets', 'export_pin_hash')
