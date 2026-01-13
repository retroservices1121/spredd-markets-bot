"""Add Limitless platform enum value

Revision ID: 008_limitless
Revises: 007_partner
Create Date: 2026-01-13

Adds LIMITLESS to the platform enum for Limitless Exchange on Base chain.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '008_limitless'
down_revision: Union[str, None] = '007_partner'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add LIMITLESS to the platform enum
    # PostgreSQL requires special handling for adding enum values
    op.execute("ALTER TYPE platform ADD VALUE IF NOT EXISTS 'limitless'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values directly
    # To properly downgrade, would need to:
    # 1. Create new enum without 'limitless'
    # 2. Update all columns using the enum
    # 3. Drop old enum and rename new one
    # For safety, we just leave the enum value (it won't cause issues)
    pass
