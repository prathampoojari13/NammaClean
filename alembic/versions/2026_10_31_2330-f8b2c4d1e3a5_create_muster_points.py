"""create_muster_points

Revision ID: f8b2c4d1e3a5
Revises: c1a7f0e9b421
Create Date: 2026-10-31 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = 'f8b2c4d1e3a5'
down_revision: Union[str, None] = 'c1a7f0e9b421'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create muster_points table
    op.create_table(
        'muster_points',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('ward_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column(
            'location',
            geoalchemy2.types.Geometry(
                geometry_type='POINT',
                srid=4326,
                from_text='ST_GeomFromEWKT',
                name='geometry',
                nullable=False,
                spatial_index=False,
            ),
            nullable=False,
        ),
        sa.Column(
            'geofence_radius_meters',
            sa.Integer(),
            server_default=sa.text('150'),
            nullable=False,
        ),
        sa.Column(
            'is_active',
            sa.Boolean(),
            server_default=sa.text('true'),
            nullable=False,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            'geofence_radius_meters > 0',
            name='ck_muster_points_positive_geofence_radius',
        ),
        sa.ForeignKeyConstraint(['ward_id'], ['wards.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # 2. Create spatial index and foreign key / status indexes
    op.create_index(
        'idx_muster_points_location',
        'muster_points',
        ['location'],
        unique=False,
        postgresql_using='gist',
    )
    op.create_index(
        op.f('ix_muster_points_is_active'),
        'muster_points',
        ['is_active'],
        unique=False,
    )
    op.create_index(
        op.f('ix_muster_points_ward_id'),
        'muster_points',
        ['ward_id'],
        unique=False,
    )


def downgrade() -> None:
    # Reverse indexes and table
    op.drop_index(op.f('ix_muster_points_ward_id'), table_name='muster_points')
    op.drop_index(op.f('ix_muster_points_is_active'), table_name='muster_points')
    op.drop_index('idx_muster_points_location', table_name='muster_points', postgresql_using='gist')
    op.drop_table('muster_points')
