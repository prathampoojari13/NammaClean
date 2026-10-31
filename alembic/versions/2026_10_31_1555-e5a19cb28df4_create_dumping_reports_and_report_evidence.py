"""create_dumping_reports_and_report_evidence

Revision ID: e5a19cb28df4
Revises: d4feeafd2b2c
Create Date: 2026-10-31 15:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = 'e5a19cb28df4'
down_revision: Union[str, None] = 'd4feeafd2b2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create dumping_reports table
    op.create_table(
        'dumping_reports',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('reporter_id', sa.UUID(), nullable=True),
        sa.Column('ward_id', sa.UUID(), nullable=True),
        sa.Column('location', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', spatial_index=False), nullable=False),
        sa.Column('description', sa.String(length=1000), nullable=False),
        sa.Column('status', sa.String(length=50), server_default=sa.text("'SUBMITTED'"), nullable=False),
        sa.Column('official_notes', sa.String(length=1000), nullable=True),
        sa.Column('status_history', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('SUBMITTED', 'UNDER_REVIEW', 'ACTION_SCHEDULED', 'RESOLVED', 'REJECTED')",
            name='ck_dumping_reports_valid_status',
        ),
        sa.ForeignKeyConstraint(['reporter_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['ward_id'], ['wards.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_dumping_reports_reporter_id'), 'dumping_reports', ['reporter_id'], unique=False)
    op.create_index(op.f('ix_dumping_reports_ward_id'), 'dumping_reports', ['ward_id'], unique=False)
    op.create_index(op.f('ix_dumping_reports_status'), 'dumping_reports', ['status'], unique=False)
    op.create_index('idx_dumping_reports_location', 'dumping_reports', ['location'], unique=False, postgresql_using='gist')

    # 2. Create report_evidence table
    op.create_table(
        'report_evidence',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('report_id', sa.UUID(), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('storage_key', sa.String(length=255), nullable=False),
        sa.Column('file_size_bytes', sa.Integer(), nullable=False),
        sa.Column('content_type', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('file_size_bytes > 0', name='ck_evidence_positive_size'),
        sa.ForeignKeyConstraint(['report_id'], ['dumping_reports.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_report_evidence_report_id'), 'report_evidence', ['report_id'], unique=False)
    op.create_index(op.f('ix_report_evidence_storage_key'), 'report_evidence', ['storage_key'], unique=True)


def downgrade() -> None:
    # Drop report_evidence
    op.drop_index(op.f('ix_report_evidence_storage_key'), table_name='report_evidence')
    op.drop_index(op.f('ix_report_evidence_report_id'), table_name='report_evidence')
    op.drop_table('report_evidence')

    # Drop dumping_reports
    op.drop_index('idx_dumping_reports_location', table_name='dumping_reports', postgresql_using='gist')
    op.drop_index(op.f('ix_dumping_reports_status'), table_name='dumping_reports')
    op.drop_index(op.f('ix_dumping_reports_ward_id'), table_name='dumping_reports')
    op.drop_index(op.f('ix_dumping_reports_reporter_id'), table_name='dumping_reports')
    op.drop_table('dumping_reports')
