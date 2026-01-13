"""Add uppercase BASE chain enum value

Revision ID: 011_base_chain
Revises: 010_uppercase_limitless
Create Date: 2026-01-13

Adds BASE (uppercase) to the chain enum for Limitless on Base chain.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '011_base_chain'
down_revision: Union[str, None] = '010_uppercase_limitless'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add BASE (uppercase) to the chain enum
    from sqlalchemy import text
    connection = op.get_bind()
    connection.execute(text("ALTER TYPE chain ADD VALUE IF NOT EXISTS 'BASE'"))


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values
    pass
