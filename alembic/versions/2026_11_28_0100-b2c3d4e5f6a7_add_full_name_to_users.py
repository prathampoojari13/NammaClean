"""add_full_name_to_users

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-28 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Safely ensure full_name column exists on users table
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(100);")


def downgrade() -> None:
    op.drop_column('users', 'full_name')
