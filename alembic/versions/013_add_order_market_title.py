"""Add market_title field to orders table

Revision ID: 013_order_market_title
Revises: 012_user_country
Create Date: 2026-01-14

Adds market_title to orders for better order history display.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '013_order_market_title'
down_revision: Union[str, None] = '012_user_country'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add market_title column to orders table
    op.add_column('orders', sa.Column('market_title', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'market_title')
