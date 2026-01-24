"""Add marketing tracking columns to users table

Revision ID: 014_marketing_columns
Revises: 013_order_market_title
Create Date: 2026-01-24

Adds cm_click_id, cm_registration_sent, cm_qualification_sent, cm_qualified_at
for marketing attribution tracking.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '014_marketing_columns'
down_revision: Union[str, None] = '013_order_market_title'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add marketing tracking columns to users table
    op.add_column('users', sa.Column('cm_click_id', sa.String(255), nullable=True, index=True))
    op.add_column('users', sa.Column('cm_registration_sent', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('cm_qualification_sent', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('cm_qualified_at', sa.DateTime(timezone=True), nullable=True))

    # Create index on cm_click_id
    op.create_index('ix_users_cm_click_id', 'users', ['cm_click_id'])


def downgrade() -> None:
    op.drop_index('ix_users_cm_click_id', table_name='users')
    op.drop_column('users', 'cm_qualified_at')
    op.drop_column('users', 'cm_qualification_sent')
    op.drop_column('users', 'cm_registration_sent')
    op.drop_column('users', 'cm_click_id')
