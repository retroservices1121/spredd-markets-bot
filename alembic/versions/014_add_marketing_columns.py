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
    # Note: Using execute for IF NOT EXISTS since alembic doesn't support it natively
    conn = op.get_bind()

    # Add columns if they don't exist
    conn.execute(sa.text("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS cm_click_id VARCHAR(255);
        ALTER TABLE users ADD COLUMN IF NOT EXISTS cm_registration_sent BOOLEAN DEFAULT false NOT NULL;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS cm_qualification_sent BOOLEAN DEFAULT false NOT NULL;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS cm_qualified_at TIMESTAMP WITH TIME ZONE;
    """))

    # Create index if it doesn't exist
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_users_cm_click_id ON users (cm_click_id);
    """))


def downgrade() -> None:
    op.drop_index('ix_users_cm_click_id', table_name='users')
    op.drop_column('users', 'cm_qualified_at')
    op.drop_column('users', 'cm_qualification_sent')
    op.drop_column('users', 'cm_registration_sent')
    op.drop_column('users', 'cm_click_id')
