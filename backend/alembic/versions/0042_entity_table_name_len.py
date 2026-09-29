"""Widen Business Entity table_name to the identifier limit.

Revision ID: 0042_entity_table_name_len
Revises: 0041_business_entities
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042_entity_table_name_len"
down_revision: Union[str, None] = "0041_business_entities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "business_entities",
        "table_name",
        existing_type=sa.String(48),
        type_=sa.String(63),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "business_entities",
        "table_name",
        existing_type=sa.String(63),
        type_=sa.String(48),
        existing_nullable=False,
    )
