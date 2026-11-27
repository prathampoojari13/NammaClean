"""add_worker_schedules_and_overrides

Revision ID: a1b2c3d4e5f6
Revises: f9a2b3c4d5e6
Create Date: 2026-11-27 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f9a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create worker_schedules table
    op.create_table(
        'worker_schedules',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('worker_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('ward_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('wards.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('route_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('collection_routes.id', ondelete='SET NULL'), nullable=True),
        sa.Column('days_of_week', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[1,2,3,4,5,6]'),
        sa.Column('shift_start_time', sa.String(length=10), nullable=False, server_default='07:00'),
        sa.Column('shift_end_time', sa.String(length=10), nullable=False, server_default='14:00'),
        sa.Column('check_in_start_time', sa.String(length=10), nullable=False, server_default='06:45'),
        sa.Column('check_in_end_time', sa.String(length=10), nullable=False, server_default='07:30'),
        sa.Column('check_out_start_time', sa.String(length=10), nullable=True),
        sa.Column('check_out_end_time', sa.String(length=10), nullable=True),
        sa.Column('grace_period_minutes', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('timezone', sa.String(length=50), nullable=False, server_default='Asia/Kolkata'),
        sa.Column('effective_from', sa.Date(), nullable=False, server_default=sa.func.current_date()),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(op.f('ix_worker_schedules_worker_id'), 'worker_schedules', ['worker_id'], unique=False)
    op.create_index(op.f('ix_worker_schedules_ward_id'), 'worker_schedules', ['ward_id'], unique=False)
    op.create_index(op.f('ix_worker_schedules_route_id'), 'worker_schedules', ['route_id'], unique=False)
    op.create_index(op.f('ix_worker_schedules_is_active'), 'worker_schedules', ['is_active'], unique=False)

    # 2. Create schedule_overrides table
    op.create_table(
        'schedule_overrides',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('worker_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('override_date', sa.Date(), nullable=False),
        sa.Column('override_type', sa.String(length=30), nullable=False),
        sa.Column('shift_start_time', sa.String(length=10), nullable=True),
        sa.Column('shift_end_time', sa.String(length=10), nullable=True),
        sa.Column('check_in_start_time', sa.String(length=10), nullable=True),
        sa.Column('check_in_end_time', sa.String(length=10), nullable=True),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(op.f('ix_schedule_overrides_worker_id'), 'schedule_overrides', ['worker_id'], unique=False)
    op.create_index(op.f('ix_schedule_overrides_override_date'), 'schedule_overrides', ['override_date'], unique=False)

    # 3. Add schedule_id and duration_minutes to attendance_records
    op.add_column('attendance_records', sa.Column('schedule_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('worker_schedules.id', ondelete='SET NULL'), nullable=True))
    op.add_column('attendance_records', sa.Column('duration_minutes', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_attendance_records_schedule_id'), 'attendance_records', ['schedule_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_attendance_records_schedule_id'), table_name='attendance_records')
    op.drop_column('attendance_records', 'duration_minutes')
    op.drop_column('attendance_records', 'schedule_id')

    op.drop_index(op.f('ix_schedule_overrides_override_date'), table_name='schedule_overrides')
    op.drop_index(op.f('ix_schedule_overrides_worker_id'), table_name='schedule_overrides')
    op.drop_table('schedule_overrides')

    op.drop_index(op.f('ix_worker_schedules_is_active'), table_name='worker_schedules')
    op.drop_index(op.f('ix_worker_schedules_route_id'), table_name='worker_schedules')
    op.drop_index(op.f('ix_worker_schedules_ward_id'), table_name='worker_schedules')
    op.drop_index(op.f('ix_worker_schedules_worker_id'), table_name='worker_schedules')
    op.drop_table('worker_schedules')
