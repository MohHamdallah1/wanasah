"""Add V1 warehouse address and optional physical location metadata.

Revision ID: d7a4c9e21b30
Revises: a8c11d4e7f20
"""
from alembic import op
import sqlalchemy as sa

revision = "d7a4c9e21b30"
down_revision = "a8c11d4e7f20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inventory_locations", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("inventory_locations", sa.Column("location_link", sa.String(length=500), nullable=True))
    op.add_column("inventory_locations", sa.Column("latitude", sa.Numeric(10, 7), nullable=True))
    op.add_column("inventory_locations", sa.Column("longitude", sa.Numeric(10, 7), nullable=True))
    op.create_check_constraint("chk_inv_loc_coordinates_pair", "inventory_locations", "(latitude IS NULL AND longitude IS NULL) OR (latitude IS NOT NULL AND longitude IS NOT NULL)")
    op.create_check_constraint("chk_inv_loc_latitude_range", "inventory_locations", "latitude IS NULL OR latitude BETWEEN -90 AND 90")
    op.create_check_constraint("chk_inv_loc_longitude_range", "inventory_locations", "longitude IS NULL OR longitude BETWEEN -180 AND 180")


def downgrade() -> None:
    op.drop_constraint("chk_inv_loc_longitude_range", "inventory_locations", type_="check")
    op.drop_constraint("chk_inv_loc_latitude_range", "inventory_locations", type_="check")
    op.drop_constraint("chk_inv_loc_coordinates_pair", "inventory_locations", type_="check")
    op.drop_column("inventory_locations", "longitude")
    op.drop_column("inventory_locations", "latitude")
    op.drop_column("inventory_locations", "location_link")
    op.drop_column("inventory_locations", "address")
