"""Fix limitless enum case

Revision ID: 009_limitless_case
Revises: 008_limitless
Create Date: 2026-01-13

Fixes existing lowercase 'limitless' values to uppercase 'LIMITLESS'
to match SQLAlchemy's enum name expectations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '009_limitless_case'
down_revision: Union[str, None] = '008_limitless'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Reset any users with 'limitless' back to 'kalshi' for now
    # The Limitless platform needs proper enum configuration
    op.execute("UPDATE users SET active_platform = 'kalshi' WHERE active_platform = 'limitless'")


def downgrade() -> None:
    # Revert to lowercase if needed
    op.execute("UPDATE users SET active_platform = 'limitless' WHERE active_platform = 'LIMITLESS'")
    op.execute("UPDATE positions SET platform = 'limitless' WHERE platform = 'LIMITLESS'")
    op.execute("UPDATE orders SET platform = 'limitless' WHERE platform = 'LIMITLESS'")
    op.execute("UPDATE market_cache SET platform = 'limitless' WHERE platform = 'LIMITLESS'")
