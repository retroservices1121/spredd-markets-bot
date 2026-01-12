"""Delete stale position with wrong token_id

Revision ID: 006_stale_pos
Revises: 005_export_pin
Create Date: 2025-01-12

Deletes a stale position that was stored with incorrect token_id,
causing sell operations to fail.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '006_stale_pos'
down_revision: Union[str, None] = '005_export_pin'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The stale token_id that doesn't match on-chain state
STALE_TOKEN_ID = "18289842382539867639079362738467334752951741961393928566628307174343542320349"


def upgrade() -> None:
    # Delete the stale position
    op.execute(
        f"DELETE FROM positions WHERE token_id = '{STALE_TOKEN_ID}'"
    )


def downgrade() -> None:
    # Cannot restore deleted data - this is a cleanup migration
    pass
