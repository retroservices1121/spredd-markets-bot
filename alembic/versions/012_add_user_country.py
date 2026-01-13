"""Add country field to users table

Revision ID: 012_user_country
Revises: 011_base_chain
Create Date: 2026-01-13

Adds country fields for IP-based geo-blocking compliance.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '012_user_country'
down_revision: Union[str, None] = '011_base_chain'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add country columns to users table
    op.add_column('users', sa.Column('country', sa.String(2), nullable=True))
    op.add_column('users', sa.Column('country_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('geo_verify_token', sa.String(64), nullable=True))
    op.create_index('ix_users_geo_verify_token', 'users', ['geo_verify_token'])


def downgrade() -> None:
    op.drop_index('ix_users_geo_verify_token', 'users')
    op.drop_column('users', 'geo_verify_token')
    op.drop_column('users', 'country_verified_at')
    op.drop_column('users', 'country')
