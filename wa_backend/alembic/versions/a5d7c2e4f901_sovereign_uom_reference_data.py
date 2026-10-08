"""Provision sovereign UOM reference data.

Revision ID: a5d7c2e4f901
Revises: 91d6f0e3c8a2

UOM rows are platform reference data required by catalog operations. They are
part of database provisioning, not tenant/demo seed data.
"""
from __future__ import annotations

from alembic import op


revision = "a5d7c2e4f901"
down_revision = "91d6f0e3c8a2"
branch_labels = None
depends_on = None


UOMS = (
    ("EACH", "حبة"),
    ("CARTON", "كرتونة"),
    ("CASE", "صندوق"),
    ("PACK", "باكيت"),
    ("BAG", "كيس"),
    ("SACK", "شوال"),
    ("TRAY", "صينية"),
    ("CRATE", "قفص"),
    ("BUNDLE", "حزمة"),
    ("KG", "كيلوغرام"),
    ("G", "غرام"),
    ("L", "لتر"),
    ("ML", "ملليلتر"),
    ("PALLET", "طبلية"),
)


def upgrade() -> None:
    values = ",\n".join(
        "(" + ", ".join("'" + value.replace("'", "''") + "'" for value in row) + ")"
        for row in UOMS
    )
    op.execute(
        f"""
        INSERT INTO public.uom (code, name)
        VALUES {values}
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Refusing to delete sovereign UOM reference data during rollback. "
        "Ship an explicit forward migration if the reference catalog must change."
    )
