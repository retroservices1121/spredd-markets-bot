"""Add Jupiter platform enum value

Revision ID: 017_jupiter_platform
Revises: 016_proof_kyc
Create Date: 2026-02-20

Adds JUPITER to the platform enum so users can have active_platform set to Jupiter
(Polymarket markets settled on Solana).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '017_jupiter_platform'
down_revision: Union[str, None] = '016_proof_kyc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE platform ADD VALUE IF NOT EXISTS 'jupiter'")
    op.execute("ALTER TYPE platform ADD VALUE IF NOT EXISTS 'JUPITER'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values directly
    pass
