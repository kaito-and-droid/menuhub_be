"""item variants (JSONB) + order_items.variant_name

Revision ID: c1a2b3d4e5f6
Revises: 7bcea14ef7e2
Create Date: 2026-07-18 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '7bcea14ef7e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('menu_items', sa.Column('variants', JSONB, nullable=True))
    op.add_column('order_items', sa.Column('variant_name', sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column('order_items', 'variant_name')
    op.drop_column('menu_items', 'variants')
