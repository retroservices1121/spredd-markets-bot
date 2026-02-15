"""Add DFlow Proof KYC verification column

Revision ID: 016_proof_kyc
Revises: 015_myriad_platform
Create Date: 2026-02-14

Adds proof_verified_at column to users table for DFlow Proof KYC verification.
Verification is permanent once achieved.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '016_proof_kyc'
down_revision: Union[str, None] = '015_myriad_platform'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('proof_verified_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'proof_verified_at')
