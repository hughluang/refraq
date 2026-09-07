"""Catalog embeddings: JSONB to pgvector (ADR 0041 follow-through).

Revision ID: 0040_catalog_embeddings_vector
Revises: 0039_catalog_search_trgm

No vector index: current embeddings are 4096-d, above pgvector HNSW
limits (vector 2000, halfvec 4000). Exact ``<=>`` scan is the neighbor
path. ANN stays gated on ADR 0041 Decision 5.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0040_catalog_embeddings_vector"
down_revision: Union[str, None] = "0039_catalog_search_trgm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE catalog_embeddings ADD COLUMN embedding_vec vector")
    op.execute("ALTER TABLE catalog_embeddings ADD COLUMN embedding_dim integer")
    op.execute(
        """
        UPDATE catalog_embeddings
        SET
          embedding_vec = (embedding::text)::vector,
          embedding_dim = jsonb_array_length(embedding)
        WHERE jsonb_typeof(embedding) = 'array'
          AND jsonb_array_length(embedding) > 0
        """
    )
    leftover = op.get_bind().execute(
        text(
            "SELECT count(*) FROM catalog_embeddings "
            "WHERE embedding_vec IS NULL OR embedding_dim IS NULL"
        )
    ).scalar()
    if leftover:
        raise RuntimeError(
            f"catalog_embeddings: {leftover} rows could not convert JSONB "
            "embedding to vector"
        )
    op.execute("ALTER TABLE catalog_embeddings DROP COLUMN embedding")
    op.execute("ALTER TABLE catalog_embeddings RENAME COLUMN embedding_vec TO embedding")
    op.execute("ALTER TABLE catalog_embeddings ALTER COLUMN embedding SET NOT NULL")
    op.execute("ALTER TABLE catalog_embeddings ALTER COLUMN embedding_dim SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE catalog_embeddings ADD COLUMN embedding_json jsonb")
    op.execute(
        """
        UPDATE catalog_embeddings
        SET embedding_json = embedding::text::jsonb
        """
    )
    leftover = op.get_bind().execute(
        text(
            "SELECT count(*) FROM catalog_embeddings WHERE embedding_json IS NULL"
        )
    ).scalar()
    if leftover:
        raise RuntimeError(
            f"catalog_embeddings: {leftover} rows could not convert vector "
            "embedding to JSONB"
        )
    op.execute("ALTER TABLE catalog_embeddings DROP COLUMN embedding")
    op.execute("ALTER TABLE catalog_embeddings DROP COLUMN embedding_dim")
    op.execute(
        "ALTER TABLE catalog_embeddings RENAME COLUMN embedding_json TO embedding"
    )
    op.execute("ALTER TABLE catalog_embeddings ALTER COLUMN embedding SET NOT NULL")
