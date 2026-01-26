"""Add Myriad platform and Abstract/Linea chains

Revision ID: 015_myriad_platform
Revises: 014_marketing_columns
Create Date: 2026-01-26

Adds MYRIAD to the platform enum and ABSTRACT/LINEA to the chain enum
for Myriad Protocol support on Abstract and Linea chains.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '015_myriad_platform'
down_revision: Union[str, None] = '014_marketing_columns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add MYRIAD to the platform enum
    # PostgreSQL requires special handling for adding enum values
    op.execute("ALTER TYPE platform ADD VALUE IF NOT EXISTS 'myriad'")
    op.execute("ALTER TYPE platform ADD VALUE IF NOT EXISTS 'MYRIAD'")

    # Add ABSTRACT and LINEA to the chain enum
    op.execute("ALTER TYPE chain ADD VALUE IF NOT EXISTS 'abstract'")
    op.execute("ALTER TYPE chain ADD VALUE IF NOT EXISTS 'ABSTRACT'")
    op.execute("ALTER TYPE chain ADD VALUE IF NOT EXISTS 'linea'")
    op.execute("ALTER TYPE chain ADD VALUE IF NOT EXISTS 'LINEA'")

    # Also add BASE and MONAD if not already present (may have been missed)
    op.execute("ALTER TYPE chain ADD VALUE IF NOT EXISTS 'base'")
    op.execute("ALTER TYPE chain ADD VALUE IF NOT EXISTS 'BASE'")
    op.execute("ALTER TYPE chain ADD VALUE IF NOT EXISTS 'monad'")
    op.execute("ALTER TYPE chain ADD VALUE IF NOT EXISTS 'MONAD'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values directly
    # To properly downgrade, would need to:
    # 1. Create new enum without the values
    # 2. Update all columns using the enum
    # 3. Drop old enum and rename new one
    # For safety, we just leave the enum values (they won't cause issues)
    pass
