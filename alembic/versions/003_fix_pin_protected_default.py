"""Fix pin_protected default value

Revision ID: 003_fix_pin
Revises: 002_referral
Create Date: 2025-01-10

Sets existing wallets to pin_protected=False since they were created
before PIN protection was implemented.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_fix_pin'
down_revision: Union[str, None] = '002_referral'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Set all existing wallets to pin_protected=False
    # since they were created before PIN protection was implemented
    op.execute("UPDATE wallets SET pin_protected = false WHERE pin_protected = true")

    # Also update the server default for future rows
    op.alter_column('wallets', 'pin_protected', server_default='false')


def downgrade() -> None:
    # Revert to original default (though we can't know which wallets were actually PIN-protected)
    op.alter_column('wallets', 'pin_protected', server_default='true')
