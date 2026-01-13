"""Add uppercase LIMITLESS enum value

Revision ID: 010_uppercase_limitless
Revises: 009_limitless_case
Create Date: 2026-01-13

Adds LIMITLESS (uppercase) to match other enum values (KALSHI, POLYMARKET, OPINION).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '010_uppercase_limitless'
down_revision: Union[str, None] = '009_limitless_case'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add LIMITLESS (uppercase) to the platform enum
    # This is a DDL statement that bypasses SQLAlchemy ORM validation
    from sqlalchemy import text
    connection = op.get_bind()
    connection.execute(text("ALTER TYPE platform ADD VALUE IF NOT EXISTS 'LIMITLESS'"))


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values
    pass
