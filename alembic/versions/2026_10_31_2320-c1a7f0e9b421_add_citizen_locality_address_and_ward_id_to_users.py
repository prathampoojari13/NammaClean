"""add_citizen_locality_address_and_ward_id_to_users

Revision ID: c1a7f0e9b421
Revises: e5a19cb28df4
Create Date: 2026-10-31 23:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a7f0e9b421'
down_revision: Union[str, None] = 'e5a19cb28df4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add citizen locality, address, and ward association columns to users table
    op.add_column('users', sa.Column('ward_id', sa.UUID(), nullable=True))
    op.add_column('users', sa.Column('locality', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('address', sa.String(length=255), nullable=True))

    # 2. Add index on users.ward_id for fast filtering of residents by ward
    op.create_index(op.f('ix_users_ward_id'), 'users', ['ward_id'], unique=False)

    # 3. Add foreign key from users.ward_id to wards.id with SET NULL on ward deletion
    op.create_foreign_key(
        'fk_users_ward_id_wards',
        'users',
        'wards',
        ['ward_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    # Revert foreign key, index, and columns
    op.drop_constraint('fk_users_ward_id_wards', 'users', type_='foreignkey')
    op.drop_index(op.f('ix_users_ward_id'), table_name='users')
    op.drop_column('users', 'address')
    op.drop_column('users', 'locality')
    op.drop_column('users', 'ward_id')
