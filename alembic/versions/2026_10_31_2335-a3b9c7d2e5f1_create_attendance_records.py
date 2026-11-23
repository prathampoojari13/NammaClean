"""create_attendance_records

Revision ID: a3b9c7d2e5f1
Revises: f8b2c4d1e3a5
Create Date: 2026-10-31 23:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = 'a3b9c7d2e5f1'
down_revision: Union[str, None] = 'f8b2c4d1e3a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create attendance_records table
    op.create_table(
        'attendance_records',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('worker_id', sa.UUID(), nullable=False),
        sa.Column('ward_id', sa.UUID(), nullable=False),
        sa.Column('muster_point_id', sa.UUID(), nullable=True),
        sa.Column('attendance_date', sa.Date(), nullable=False),
        sa.Column('check_in_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('check_out_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'check_in_location',
            geoalchemy2.types.Geometry(
                geometry_type='POINT',
                srid=4326,
                from_text='ST_GeomFromEWKT',
                name='geometry',
                nullable=True,
                spatial_index=False,
            ),
            nullable=True,
        ),
        sa.Column(
            'check_out_location',
            geoalchemy2.types.Geometry(
                geometry_type='POINT',
                srid=4326,
                from_text='ST_GeomFromEWKT',
                name='geometry',
                nullable=True,
                spatial_index=False,
            ),
            nullable=True,
        ),
        sa.Column('check_in_distance_meters', sa.Float(), nullable=True),
        sa.Column('check_out_distance_meters', sa.Float(), nullable=True),
        sa.Column(
            'status',
            sa.String(length=30),
            server_default=sa.text("'PRESENT'"),
            nullable=False,
        ),
        sa.Column('exception_reason', sa.String(length=500), nullable=True),
        sa.Column('reviewed_by', sa.UUID(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_notes', sa.String(length=1000), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['worker_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['ward_id'], ['wards.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['muster_point_id'], ['muster_points.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('worker_id', 'attendance_date', name='uq_worker_daily_attendance'),
        sa.CheckConstraint(
            "status IN ('PRESENT', 'ABSENT', 'HALF_DAY', 'EXCEPTION_PENDING', 'REJECTED')",
            name='ck_attendance_valid_status',
        ),
        sa.CheckConstraint(
            'check_out_at IS NULL OR check_in_at IS NOT NULL',
            name='ck_attendance_checkout_requires_checkin',
        ),
        sa.CheckConstraint(
            'check_out_at IS NULL OR check_in_at IS NULL OR check_out_at >= check_in_at',
            name='ck_attendance_checkout_gte_checkin',
        ),
        sa.CheckConstraint(
            'check_in_distance_meters IS NULL OR check_in_distance_meters >= 0',
            name='ck_attendance_check_in_distance_non_negative',
        ),
        sa.CheckConstraint(
            'check_out_distance_meters IS NULL OR check_out_distance_meters >= 0',
            name='ck_attendance_check_out_distance_non_negative',
        ),
    )

    # 2. Create B-tree indexes for lookups and spatial GiST indexes for locations
    op.create_index(
        op.f('ix_attendance_records_worker_id'),
        'attendance_records',
        ['worker_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_attendance_records_ward_id'),
        'attendance_records',
        ['ward_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_attendance_records_muster_point_id'),
        'attendance_records',
        ['muster_point_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_attendance_records_attendance_date'),
        'attendance_records',
        ['attendance_date'],
        unique=False,
    )
    op.create_index(
        op.f('ix_attendance_records_status'),
        'attendance_records',
        ['status'],
        unique=False,
    )
    op.create_index(
        op.f('ix_attendance_records_reviewed_by'),
        'attendance_records',
        ['reviewed_by'],
        unique=False,
    )
    op.create_index(
        'idx_attendance_records_check_in_location',
        'attendance_records',
        ['check_in_location'],
        unique=False,
        postgresql_using='gist',
    )
    op.create_index(
        'idx_attendance_records_check_out_location',
        'attendance_records',
        ['check_out_location'],
        unique=False,
        postgresql_using='gist',
    )


def downgrade() -> None:
    # Reverse indexes and table
    op.drop_index('idx_attendance_records_check_out_location', table_name='attendance_records', postgresql_using='gist')
    op.drop_index('idx_attendance_records_check_in_location', table_name='attendance_records', postgresql_using='gist')
    op.drop_index(op.f('ix_attendance_records_reviewed_by'), table_name='attendance_records')
    op.drop_index(op.f('ix_attendance_records_status'), table_name='attendance_records')
    op.drop_index(op.f('ix_attendance_records_attendance_date'), table_name='attendance_records')
    op.drop_index(op.f('ix_attendance_records_muster_point_id'), table_name='attendance_records')
    op.drop_index(op.f('ix_attendance_records_ward_id'), table_name='attendance_records')
    op.drop_index(op.f('ix_attendance_records_worker_id'), table_name='attendance_records')
    op.drop_table('attendance_records')
