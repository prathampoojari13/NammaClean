"""create_attendance_qr_tokens

Revision ID: b7e4d2c9f1a8
Revises: a3b9c7d2e5f1
Create Date: 2026-11-01 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e4d2c9f1a8'
down_revision: Union[str, None] = 'a3b9c7d2e5f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create attendance_qr_tokens table
    op.create_table(
        'attendance_qr_tokens',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('muster_point_id', sa.UUID(), nullable=False),
        sa.Column('ward_id', sa.UUID(), nullable=False),
        sa.Column('issued_by', sa.UUID(), nullable=True),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('redeemed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('redeemed_by', sa.UUID(), nullable=True),
        sa.Column('attendance_record_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('expires_at > issued_at', name='ck_qr_token_expiry_after_issue'),
        sa.ForeignKeyConstraint(
            ['muster_point_id'],
            ['muster_points.id'],
            name='fk_attendance_qr_tokens_muster_point_id_muster_points',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['ward_id'],
            ['wards.id'],
            name='fk_attendance_qr_tokens_ward_id_wards',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['issued_by'],
            ['users.id'],
            name='fk_attendance_qr_tokens_issued_by_users',
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['redeemed_by'],
            ['users.id'],
            name='fk_attendance_qr_tokens_redeemed_by_users',
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['attendance_record_id'],
            ['attendance_records.id'],
            name='fk_attendance_qr_tokens_attendance_record_id_attendance_records',
            ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_attendance_qr_tokens'),
    )

    # 2. Indexes
    op.create_index(
        'ix_attendance_qr_tokens_token_hash',
        'attendance_qr_tokens',
        ['token_hash'],
        unique=True,
    )
    op.create_index(
        'ix_attendance_qr_tokens_muster_point_id',
        'attendance_qr_tokens',
        ['muster_point_id'],
        unique=False,
    )
    op.create_index(
        'ix_attendance_qr_tokens_ward_id',
        'attendance_qr_tokens',
        ['ward_id'],
        unique=False,
    )
    op.create_index(
        'ix_attendance_qr_tokens_issued_by',
        'attendance_qr_tokens',
        ['issued_by'],
        unique=False,
    )
    op.create_index(
        'ix_attendance_qr_tokens_redeemed_by',
        'attendance_qr_tokens',
        ['redeemed_by'],
        unique=False,
    )
    op.create_index(
        'ix_attendance_qr_tokens_expires_at',
        'attendance_qr_tokens',
        ['expires_at'],
        unique=False,
    )
    op.create_index(
        'ix_attendance_qr_tokens_redeemed_at',
        'attendance_qr_tokens',
        ['redeemed_at'],
        unique=False,
    )
    op.create_index(
        'ix_attendance_qr_tokens_attendance_record_id',
        'attendance_qr_tokens',
        ['attendance_record_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_attendance_qr_tokens_attendance_record_id', table_name='attendance_qr_tokens')
    op.drop_index('ix_attendance_qr_tokens_redeemed_at', table_name='attendance_qr_tokens')
    op.drop_index('ix_attendance_qr_tokens_expires_at', table_name='attendance_qr_tokens')
    op.drop_index('ix_attendance_qr_tokens_redeemed_by', table_name='attendance_qr_tokens')
    op.drop_index('ix_attendance_qr_tokens_issued_by', table_name='attendance_qr_tokens')
    op.drop_index('ix_attendance_qr_tokens_ward_id', table_name='attendance_qr_tokens')
    op.drop_index('ix_attendance_qr_tokens_muster_point_id', table_name='attendance_qr_tokens')
    op.drop_index('ix_attendance_qr_tokens_token_hash', table_name='attendance_qr_tokens')
    op.drop_table('attendance_qr_tokens')
