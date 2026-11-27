"""add_official_id_phone_and_attendance_accuracy

Revision ID: e8f1c2a3b4d5
Revises: b7e4d2c9f1a8
Create Date: 2026-11-26 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8f1c2a3b4d5'
down_revision: Union[str, None] = 'b7e4d2c9f1a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add official_id and phone_number to users table
    op.add_column('users', sa.Column('official_id', sa.String(length=50), nullable=True))
    op.add_column('users', sa.Column('phone_number', sa.String(length=20), nullable=True))
    op.create_index(op.f('ix_users_official_id'), 'users', ['official_id'], unique=True)

    # 2. Add GPS accuracy meters to attendance_records table
    op.add_column('attendance_records', sa.Column('check_in_accuracy_meters', sa.Float(), nullable=True))
    op.add_column('attendance_records', sa.Column('check_out_accuracy_meters', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('attendance_records', 'check_out_accuracy_meters')
    op.drop_column('attendance_records', 'check_in_accuracy_meters')
    op.drop_index(op.f('ix_users_official_id'), table_name='users')
    op.drop_column('users', 'phone_number')
    op.drop_column('users', 'official_id')
